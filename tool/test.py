"""AI 测试用例生成器 (整洁重构版)

保留功能:
 - 单条/批量需求用例生成
 - 背景知识文档 (docx/txt/md)
 - CSV 解析与下载 (Excel/CSV)

模型与计费说明:
 - MiMo-7B-RL: 免费 (标注: 免费)
 - Qwen-235B-A22B / deepseek-v3.1 / Qwen2.5-VL-72B-Instruct-AWQ: 收费 (标注: 计费)

改动摘要 (本次重构):
 - 移除代理设置与相关参数 (精简 UI / 逻辑)
 - 精简模型调用逻辑, 统一异常与回退处理
 - 移除未使用的 mock 生成函数与无用 import
 - 增加模型标签 (免费 / 计费)
 - 代码块结构化: 常量区 / 工具函数 / 模型调用 / 解析 / UI
"""

import re
import logging
from io import BytesIO, StringIO
from typing import List, Dict, Optional, Any, Tuple
import csv
import json
import time
import uuid
import requests
import pandas as pd
import streamlit as st
from docx import Document
from urllib.parse import urlparse
try:
    from openai import OpenAI
    import openai  # noqa
except Exception:
    OpenAI = None
    openai = None  # noqa
import os
import sys
import argparse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DEFAULT_HEADERS = ["测试名称", "需求编号", "需求描述", "测试描述", "前置条件", "测试步骤", "预期结果", "需求追溯"]
DEFAULT_BASE_URL = "http://model.mify.ai.srv"  # 内部服务优先
MAX_RETRY_ATTEMPTS = 3
MIN_PARAGRAPH_LENGTH = 10

API_KEY = "sk-HXFiS9bEeg95uypM96B6kJfKaxe3ze52FUeQEriGGaGIIefS"  # 固定硬编码使用

# 模型集合 (MiMo 免费 / 其他计费)
MODEL_MAP = {
    "MiMo-7B-RL": "MiMo-7B-RL",
    "Qwen-235B-A22B": "Qwen-235B-A22B",
    "deepseek-v3.1": "deepseek-v3.1",
    "Qwen2.5-VL-72B-Instruct-AWQ": "Qwen2.5-VL-72B-Instruct-AWQ",
}
ALLOWED_MODELS = list(MODEL_MAP.keys())  # 顺序保持声明次序

MODEL_PRICING_TAG = {
    "MiMo-7B-RL": "(免费)",
    "Qwen-235B-A22B": "(计费)",
    "deepseek-v3.1": "(计费)",
    "Qwen2.5-VL-72B-Instruct-AWQ": "(计费)",
}

# 内部网关可能需要的路由头（之前版本使用过）
ROUTE_HEADER_VALUE = "xiaomi"  # 默认用于 MiMo
MODEL_PROVIDER_HEADER = {
    "MiMo-7B-RL": "xiaomi",
    "Qwen-235B-A22B": "openai_api_compatible",
    "deepseek-v3.1": "openai_api_compatible",
    "Qwen2.5-VL-72B-Instruct-AWQ": "openai_api_compatible",
}

# 飞书API相关常量
FEISHU_BASE_API = os.environ.get("FEISHU_OPEN_BASE", "https://open.feishu.cn")
FEISHU_TOKEN_ENDPOINT = f"{FEISHU_BASE_API}/open-apis/auth/v3/tenant_access_token/internal"
FEISHU_USER_TOKEN_ENDPOINT = f"{FEISHU_BASE_API}/open-apis/authen/v1/access_token"
FEISHU_OAUTH_AUTHORIZE_URL = f"{FEISHU_BASE_API}/open-apis/authen/v1/authorize"
FEISHU_OAUTH_TOKEN_URL = f"{FEISHU_BASE_API}/open-apis/authen/v1/refresh_access_token"
FEISHU_DOC_ENDPOINT_TMPL = f"{FEISHU_BASE_API}/open-apis/docx/v1/documents/{{doc_id}}"
FEISHU_BLOCKS_ENDPOINT_TMPL = f"{FEISHU_BASE_API}/open-apis/docx/v1/documents/{{doc_id}}/blocks/{{block_id}}?page_size={{page_size}}&page_token={{page_token}}"

# 飞书文档块类型抽取策略
FEISHU_INLINE_KEY_CANDIDATES = ["elements", "runs", "inlines", "text_run"]

def handle_errors(func):
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.exception(e)
            msg = str(e)
            low = msg.lower()
            if ('401' in msg) or ('authentication' in low) or ('invalid' in low and 'key' in low):
                st.error("认证失败：请确认后端已为当前硬编码密钥授权。")
            else:
                st.error(f"操作失败: {msg}")
            return None
    return wrapper

# ===== 飞书API辅助函数 =====
def get_feishu_user_access_token(app_id: str, app_secret: str, code: str, debug: bool = False) -> str:
    """通过授权码获取飞书用户访问令牌"""
    payload = {
        "grant_type": "authorization_code",
        "client_id": app_id,
        "client_secret": app_secret,
        "code": code
    }
    if debug:
        print(f"[DBG] Requesting user token with code: {code[:10]}...")
    
    try:
        resp = requests.post(FEISHU_OAUTH_TOKEN_URL, json=payload, timeout=10)
    except requests.RequestException as e:
        raise RuntimeError(f"User token request network error: {e}")
    
    if debug:
        print(f"[DBG] User token HTTP status: {resp.status_code}")
    
    if resp.status_code != 200:
        raise RuntimeError(f"User token HTTP {resp.status_code}: {resp.text[:300]}")
    
    try:
        data = resp.json()
    except ValueError:
        raise RuntimeError(f"User token response not JSON: {resp.text[:200]}")
    
    if debug:
        print(f"[DBG] User token raw JSON: {json.dumps(data, ensure_ascii=False)[:400]}")
    
    if data.get("code") != 0:
        raise RuntimeError(f"User token error code={data.get('code')} msg={data.get('msg')}")
    
    return data["data"]["access_token"]
def get_feishu_tenant_access_token(app_id: str, app_secret: str, debug: bool = False, retries: int = 3, base_delay: float = 0.8) -> str:
    payload = {"app_id": app_id, "app_secret": app_secret}
    last_err: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        if debug:
            print(f"[DBG] Requesting token attempt {attempt}/{retries} -> {FEISHU_TOKEN_ENDPOINT}")
        try:
            resp = requests.post(FEISHU_TOKEN_ENDPOINT, json=payload, timeout=10)
        except requests.RequestException as e:
            last_err = RuntimeError(f"Token request network error: {e}")
            if debug:
                print(f"[DBG] Network error: {e}")
        else:
            if debug:
                print(f"[DBG] Token HTTP status: {resp.status_code}")
            if resp.status_code == 500:
                snippet = resp.text[:300]
                print(f"[WARN] Server 500. Body snippet: {snippet}")
                last_err = RuntimeError(f"Server 500 internal error (log_id maybe in snippet)")
            elif resp.status_code != 200:
                last_err = RuntimeError(f"Token HTTP {resp.status_code}: {resp.text[:300]}")
            else:
                try:
                    data = resp.json()
                except ValueError:
                    last_err = RuntimeError(f"Token response not JSON: {resp.text[:200]}")
                else:
                    if debug:
                        print(f"[DBG] Token raw JSON: {json.dumps(data, ensure_ascii=False)[:400]}")
                    code = data.get("code")
                    if code == 0:
                        return data["tenant_access_token"]
                    else:
                        last_err = RuntimeError(f"Token error code={code} msg={data.get('msg')}")
        # backoff
        if attempt < retries:
            delay = base_delay * (2 ** (attempt - 1))
            if debug:
                print(f"[DBG] Retry in {delay:.2f}s ...")
            time.sleep(delay)
    raise last_err or RuntimeError("Token acquisition failed (unknown error)")

def feishu_api_get(url: str, token: str, debug: bool = False) -> Dict:
    """飞书API GET请求"""
    headers = {"Authorization": f"Bearer {token}"}
    if debug:
        print(f"[DBG] GET {url}")
    try:
        resp = requests.get(url, headers=headers, timeout=10)
    except requests.RequestException as e:
        raise RuntimeError(f"GET {url} network error: {e}")
    if debug:
        print(f"[DBG] Response status: {resp.status_code}")
    if resp.status_code != 200:
        raise RuntimeError(f"GET {url} -> {resp.status_code}: {resp.text[:300]}")
    try:
        data = resp.json()
    except ValueError:
        raise RuntimeError(f"Response not JSON for {url}: {resp.text[:200]}")
    if debug:
        snippet = json.dumps(data, ensure_ascii=False)[:400]
        print(f"[DBG] JSON snippet: {snippet}")
    if data.get("code") not in (0, None):
        raise RuntimeError(f"API logical error code={data.get('code')} msg={data.get('msg')}")
    return data

def fetch_feishu_blocks_recursive(doc_id: str, block_id: str, token: str, depth: int = 0, max_depth: int = 8, debug: bool = False) -> List[Dict]:
    """递归获取飞书文档块内容"""
    results: List[Dict] = []
    page_token = ""
    while True:
        url = FEISHU_BLOCKS_ENDPOINT_TMPL.format(doc_id=doc_id, block_id=block_id, page_size=200, page_token=page_token)
        data = feishu_api_get(url, token, debug=debug)
        
        # 处理API响应结构
        if block_id == doc_id:
            # 根块：返回的是单个block对象
            block_data = data.get("data", {}).get("block")
            if block_data:
                results.append(block_data)
                # 处理根块的子块
                children = block_data.get("children", [])
                for child_id in children:
                    if child_id:
                        try:
                            child_blocks = fetch_feishu_blocks_recursive(doc_id, child_id, token, depth + 1, max_depth, debug=debug)
                            results.extend(child_blocks)
                        except Exception as e:
                            print(f"[WARN] fetch child {child_id} failed: {e}")
            break  # 根块没有分页
        else:
            # 子块：也返回单个block对象
            block_data = data.get("data", {}).get("block")
            if block_data:
                results.append(block_data)
                # 处理子块的子块
                children = block_data.get("children", [])
                for child_id in children:
                    if child_id:
                        try:
                            child_blocks = fetch_feishu_blocks_recursive(doc_id, child_id, token, depth + 1, max_depth, debug=debug)
                            results.extend(child_blocks)
                        except Exception as e:
                            print(f"[WARN] fetch child {child_id} failed: {e}")
            break  # 子块也没有分页（至少在这个API中）
    
    return results

def extract_text_from_feishu_block(block: Dict) -> str:
    """从飞书文档块中提取文本"""
    text_parts: List[str] = []
    
    # 处理不同类型的块
    block_type = block.get("block_type")
    
    # 页面块（根块）
    if block_type == 1:
        page_data = block.get("page", {})
        elements = page_data.get("elements", [])
        for elem in elements:
            if isinstance(elem, dict):
                text_run = elem.get("text_run", {})
                content = text_run.get("content", "")
                if content:
                    text_parts.append(content.replace("\n", " ").strip())
    
    # 文本块
    elif block_type == 2:
        text_data = block.get("text", {})
        elements = text_data.get("elements", [])
        for elem in elements:
            if isinstance(elem, dict):
                text_run = elem.get("text_run", {})
                content = text_run.get("content", "")
                if content:
                    text_parts.append(content.replace("\n", " ").strip())
    
    # 其他块类型保持原有逻辑作为后备
    else:
        block_content = block.get("block") or {}
        def iter_dict(d: Dict):
            for k, v in d.items():
                yield k, v
                if isinstance(v, dict):
                    for k2, v2 in iter_dict(v):
                        yield k2, v2
                elif isinstance(v, list):
                    for elem in v:
                        if isinstance(elem, dict):
                            for k3, v3 in iter_dict(elem):
                                yield k3, v3

        for k, v in iter_dict(block_content):
            if k == "text_run" and isinstance(v, dict):
                c = v.get("content")
                if c:
                    text_parts.append(c.replace("\n", " ").strip())
    
    text = " ".join([t for t in text_parts if t])
    return text.strip()

def feishu_blocks_to_markdown(blocks: List[Dict]) -> str:
    """将飞书文档块转换为markdown"""
    lines: List[str] = []
    for b in blocks:
        t = extract_text_from_feishu_block(b)
        if not t:
            continue
        bt = str(b.get("block_type", "")).lower()
        if bt.startswith("heading") or bt == "3":  # 标题块
            level = bt[-1] if bt[-1].isdigit() else "2"
            lines.append(f"{'#'*int(level)} {t}")
        elif bt in ["bullet", "ordered", "list", "4", "5", "6"]:  # 列表块
            lines.append(f"- {t}")
        else:
            lines.append(t)
    # 去重连续空行
    cleaned: List[str] = []
    prev_blank = False
    for l in lines:
        blank = (not l.strip())
        if blank and prev_blank:
            continue
        cleaned.append(l)
        prev_blank = blank
    return "\n".join(cleaned)

def fetch_feishu_document(url_or_id: str, app_id: Optional[str] = None, app_secret: Optional[str] = None, debug: bool = False) -> str:
    """获取飞书文档内容并转换为markdown
    
    Args:
        url_or_id: 文档URL或ID
        app_id: 飞书应用ID，如果为None则从环境变量读取
        app_secret: 飞书应用密钥，如果为None则从环境变量读取
        debug: 是否启用调试模式
    
    Returns:
        文档内容的markdown字符串
    """
    try:
        # 获取凭证 (硬编码)
        if app_id is None:
            app_id = "cli_a85ffa34d3fad00c"
        if app_secret is None:
            app_secret = "MxD6ukGa9ZMJeGl5KicVSgNQLhnE1tcN"
        
        if not app_id or not app_secret:
            return f"【飞书API错误】缺少FEISHU_APP_ID或FEISHU_APP_SECRET环境变量"
        
        # 提取文档ID
        doc_input = url_or_id.strip()
        m = re.search(r"/(?:docx|wiki|docs)/([A-Za-z0-9]+)", doc_input)
        if m:
            doc_id = m.group(1)
        else:
            doc_id = doc_input
        
        # 获取token
        token = get_feishu_tenant_access_token(app_id, app_secret, debug=debug)
        
        # 检查是否是wiki文档
        is_wiki = "/wiki/" in doc_input
        
        if is_wiki:
            # 对于wiki文档，直接使用提取的token作为文档token
            # 不再需要额外的API调用来获取节点信息
            if debug:
                print(f"[DEBUG] Wiki文档检测到，使用token作为文档ID: {doc_id}")
            # doc_id已经是提取的wiki token，直接使用
        
        # 获取文档块
        blocks = fetch_feishu_blocks_recursive(doc_id, doc_id, token, depth=0, max_depth=6, debug=debug)
        
        if debug:
            print(f"[DEBUG] 获取到 {len(blocks)} 个文档块")
            if blocks:
                print(f"[DEBUG] 第一个块: {json.dumps(blocks[0], ensure_ascii=False, indent=2)}")
        
        # 转换为markdown
        md = feishu_blocks_to_markdown(blocks)
        
        if debug:
            print(f"[DEBUG] 转换后的markdown长度: {len(md)}")
            print(f"[DEBUG] markdown预览: {md[:200]}...")
        
        return md
    
    except Exception as e:
        return f"【飞书API错误】{str(e)}"

def _is_valid_url(u: str) -> bool:
    try:
        p = urlparse(u.strip())
        return p.scheme in ("http", "https") and bool(p.netloc)
    except Exception:
        return False

def fetch_url_content(url: str, timeout: int = 10, max_chars: int = 12000) -> str:
    """Fetch webpage text content (very lightweight heuristic)."""
    try:
        # 特殊处理飞书文档链接
        if 'feishu.cn' in url or 'larksuite' in url:
            # 检查是否是文档链接 (支持docx和wiki)
            if re.search(r"/(?:docx|wiki|docs)/[A-Za-z0-9]+", url):
                try:
                    # 尝试使用飞书API获取内容
                    content = fetch_feishu_document(url, debug=st.session_state.get("debug_mode", False))
                    if content and not content.startswith("【飞书API错误】"):
                        if len(content) > max_chars:
                            content = content[:max_chars] + "...【截断】"
                        return content
                    # 如果API失败，回退到网页抓取
                except Exception as e:
                    if st.session_state.get("debug_mode"):
                        print(f"[DEBUG] 飞书API失败，回退网页抓取: {e}")
                    st.warning(f"飞书API访问失败: {str(e)}，尝试网页抓取方式")
            
            # 回退到普通网页抓取
            r = requests.get(url, timeout=timeout, headers={"User-Agent": "TestCaseGenBot/1.0"})
            if r.status_code != 200:
                return f"【失败 {r.status_code}】{url}"
            text = r.text
            # 简单去标签
            text = re.sub(r"<script[\s\S]*?</script>", "", text, flags=re.IGNORECASE)
            text = re.sub(r"<style[\s\S]*?</style>", "", text, flags=re.IGNORECASE)
            text = re.sub(r"<[^>]+>", "\n", text)
            text = re.sub(r"\n{2,}", "\n", text)
            text = text.strip()
            if len(text) > max_chars:
                text = text[:max_chars] + "...【截断】"
            # 针对飞书在线文档的特殊处理
            if len(text) < 120:  # 仍然过短，提示用户使用导出
                return ("【飞书文档需登录或未开放，建议：1) 在飞书中导出为 docx 后上传；" \
                        "2) 或提供开放接口 Token 后走 API 抓取】" + url)
            return text
        
        # 普通网页处理
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "TestCaseGenBot/1.0"})
        if r.status_code != 200:
            return f"【失败 {r.status_code}】{url}"
        text = r.text
        # 简单去标签
        text = re.sub(r"<script[\s\S]*?</script>", "", text, flags=re.IGNORECASE)
        text = re.sub(r"<style[\s\S]*?</style>", "", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "\n", text)
        text = re.sub(r"\n{2,}", "\n", text)
        text = text.strip()
        if len(text) > max_chars:
            text = text[:max_chars] + "...【截断】"
        # 其他站点过滤非常短内容
        if len(text) < 50:
            return f"【内容过短或无法提取】{url}"
        return text
    except Exception as e:
        return f"【异常: {e.__class__.__name__}】{url}"

@handle_errors
def read_word(file) -> str:
    doc = Document(file)
    paras = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]
    content = "\n".join(paras)
    if not content.strip():
        raise ValueError("Word 文档为空")
    return content

@handle_errors
def read_excel(uploaded_file) -> Dict[str, pd.DataFrame]:
    xl = pd.ExcelFile(uploaded_file)
    sheets = {}
    for sheet in xl.sheet_names:
        df = xl.parse(sheet)
        if df.empty:
            continue
        sheets[sheet] = df
    if not sheets:
        raise ValueError("Excel 没有有效工作表")
    return sheets

def build_prompt(requirement: str, headers: List[str], pos_n: int, neg_n: int, edge_n: int, req_id: str = "", background_knowledge: Optional[str] = None) -> str:
    if not requirement.strip():
        raise ValueError("需求不能为空")
    cols_line = ",".join(headers)
    total_cases = pos_n + neg_n + edge_n
    background_section = ""
    if background_knowledge and background_knowledge.strip():
        background_section = f"""
请参考以下背景知识来生成用例：
---
{background_knowledge.strip()}
---
"""
    guidance = f"""
{background_section}
你是一名具备电力电子与车载系统经验的高级测试工程师，熟悉 OBC/CCU/BMS/EVCC、CAN/CAN-FD、充电流程与功率约束。
请基于下列需求生成 {total_cases} 条高质量、可执行的测试用例（CSV 格式，第一行为表头）：
{cols_line}

分配：正向 {pos_n} 条，异常 {neg_n} 条，边界 {edge_n} 条。

规则：
- 仅输出 CSV 内容，不要附加解释或代码块。
- 测试步骤用分号（；）分隔并放在同一单元格内。
- 前置条件为空填写 "无"。
- 输入数据要具体（例如：VIN=1234, CAN_ID=0x18FF50E5, 电压=400V, 电流=50A）。
- 预期结果应包含可观测的阈值或时间条件（例如：电流稳定在 50A ±5% 持续 10s）。
- 需求编号列填写: {req_id if req_id else "REQ-001"}
- 需求描述列简要概括需求内容（不超过50字）
- 需求追溯列填写该测试用例验证的具体需求点

电力电子注意事项：明确采样时序、SOC/温度/电力边界、故障注入（丢帧/延迟/短路）、EVCC通信协议和安全互锁。
"""
    return f"{guidance}\n\n需求ID: {req_id}\n需求描述:\n{requirement.strip()}\n\n请开始生成测试用例："

def get_standard_prompt_template() -> str:
    """返回在生成用例时使用的标准 Prompt 模板（占位符形式展示）。"""
    return (
        "[系统角色]\n"
        "你是资深的OBC/CCU测试开发专家，精通电力电子、车载充电、CAN/CAN-FD协议、硬件交互、诊断与安全。\n\n"
        "[可选背景知识]\n"
        "如有背景知识，请充分结合理解。\n---\n{背景知识}\n---\n\n"
        "[任务]\n"
        "针对‘需求描述’，生成 {正向数} 条正向、{异常数} 条异常、{边界数} 条边界测试用例（共 {总用例数} 条），要求如下：\n\n"
        "[CSV 列顺序]\n{列名逗号分隔}\n\n"
        "[生成规则]\n"
        "1. 仅输出原始 CSV 内容，不输出任何解释、代码块或多余文本。\n"
        "2. 测试步骤应细致、可复现，单元格内用全角分号（；）分隔。\n"
        "3. 前置条件为空填‘无’，如需特定硬件/线束/环境请明确。\n"
        "4. 输入/参数需具体可执行（如VIN=1234, CAN_ID=0x18FF50E5, 电压=400V, 电流=50A），涉及信号/报文/物理操作要写明。\n"
        "5. 预期结果应包含可观测阈值、时序、诊断码、功率/安全/互锁等判据（如：电流稳定在50A±5%持续10s，或下发BMS故障码0x1234）。\n"
        "6. ‘需求编号’列填{需求编号}（或自动生成REQ-001/002…）。\n"
        "7. ‘需求描述’列≤50字，精准概括需求关键点。\n"
        "8. ‘需求追溯’列写明该用例验证的具体需求点、协议条款或场景。\n"
        "9. 用例应覆盖典型流程、异常场景（如通信丢帧/超时/非法报文/硬件断开）、边界条件（如极限电压/温度/功率/时序）。\n"
        "10. OBC/CCU关注：\n"
        "    - 充电流程（插枪、授权、启动、完成、拔枪、异常中断）\n"
        "    - CAN/CAN-FD报文交互、信号采集、诊断帧\n"
        "    - 功率/温度/电流/电压边界、SOC阈值\n"
        "    - 故障注入（丢帧、延迟、短路、信号异常）\n"
        "    - 安全互锁、硬件状态检测、诊断码上报\n"
        "    - 时序要求（如xx ms内响应/动作）\n"
        "    - 物理操作与人机交互（如插拔枪、急停、授权流程）\n\n"
        "[需求输入]\n"
        "需求ID: {需求编号}\n"
        "需求描述:\n{需求全文}\n\n"
        "[输出]\n仅输出 CSV，无其他文字。"
    )

def get_output_format_template(headers: List[str] = None) -> str:
    """返回标准的输出格式模板（CSV格式，第一行为表头，第二行为占位符示例）。"""
    if headers is None:
        headers = DEFAULT_HEADERS
    header_line = ",".join(f'"{h}"' for h in headers)
    example_line = ",".join(f'"{h}示例"' for h in headers)
    return f"{header_line}\n{example_line}"

REQ_ID_PATTERN = re.compile(r"\b(REQ-[A-Za-z0-9]+-\d{2,4})\b")

def extract_req_id(text: str) -> Optional[str]:
    """尝试从需求文本中抽取需求编号 (格式示例: REQ-OBC-001)。

    若找到多个, 返回第一个。返回统一大写。未找到返回 None。
    """
    if not text:
        return None
    match = REQ_ID_PATTERN.search(text.upper())
    if match:
        return match.group(1).upper().rstrip(':')
    return None

# ===== 动态用例数量分配 =====
KEYWORD_WEIGHTS = {
    "异常": 1.0,
    "错误": 1.0,
    "故障": 1.1,
    "超时": 0.9,
    "边界": 0.8,
    "限制": 0.6,
    "保护": 0.7,
    "降级": 0.9,
    "重试": 0.8,
    "安全": 0.7,
    "加密": 0.6,
}

def _complexity_score(text: str) -> float:
    if not text:
        return 0.0
    t = text.strip()
    length = len(t)
    sentences = len(re.findall(r"[。.!?]", t)) or 1
    kw_score = 0.0
    for k, w in KEYWORD_WEIGHTS.items():
        cnt = t.count(k)
        if cnt:
            kw_score += cnt * w
    # 归一化: 设计经验参数
    base = (length / 300.0) + (sentences / 6.0) + (kw_score / 4.0)
    return min(base / 3.0, 1.0)  # 限制 0~1

def compute_dynamic_case_counts(text: str, min_total: int, max_total: int, pos_w: float, neg_w: float, edge_w: float) -> Tuple[int, int, int]:
    score = _complexity_score(text)
    total = int(round(min_total + (max_total - min_total) * score))
    total = max(min_total, min(total, max_total))
    weights = [max(pos_w, 0.01), max(neg_w, 0.01), max(edge_w, 0.01)]
    w_sum = sum(weights)
    raw_counts = [w / w_sum * total for w in weights]
    # 初步四舍五入
    counts = [max(1, int(round(c))) for c in raw_counts]
    # 调整使得和=total
    diff = sum(counts) - total
    if diff != 0:
        # 根据误差大小调整, 优先调整最大或最小的分类
        for _ in range(abs(diff)):
            if diff > 0:
                # 需要减
                idx = counts.index(max(counts))
                if counts[idx] > 1:
                    counts[idx] -= 1
            else:
                # 需要加
                idx = counts.index(min(counts))
                counts[idx] += 1
    return counts[0], counts[1], counts[2]

# ===== 单条需求 -> 多分支解析 =====
BRANCH_BULLET_PATTERN = re.compile(r"^\s*(?:- |\* |\d+[).、]\s*|[（(]\d+[)）]\s*)")

def split_requirement_into_branches(text: str, max_branches: int = 15) -> List[Dict[str, str]]:
    """将单条原始需求拆分为多个可测试的『分支子需求』。

    解析策略 (启发式):
    1. 优先按换行中的项目符号/编号拆分 (数字. / （数字） / - / * )
    2. 若未检测到明显条目, 尝试按句号/分号切成句子 (长度>15) 作为候选
    3. 对过短 (<8) 行自动与后续合并
    4. 限制最大分支数, 超过时截断并在最后追加一条『其余合并』
    返回: [{'branch_index':1,'branch_id':'B01','title':'...','content':'...'}]
    """
    if not text or len(text.strip()) < 8:
        return []
    raw_lines = [l.rstrip() for l in text.strip().splitlines() if l.strip()]
    candidates: List[str] = []
    buffer = []
    def flush_buffer():
        if buffer:
            merged = " ".join(buffer).strip()
            if merged:
                candidates.append(merged)
            buffer.clear()

    bullet_mode = any(BRANCH_BULLET_PATTERN.search(l) for l in raw_lines)
    if bullet_mode:
        for line in raw_lines:
            if BRANCH_BULLET_PATTERN.search(line):
                flush_buffer()
                # 去掉前缀符号
                cleaned = BRANCH_BULLET_PATTERN.sub("", line, count=1).strip()
                buffer.append(cleaned)
            else:
                # 继续累积到当前分支
                buffer.append(line.strip())
        flush_buffer()
    else:
        # 句子切分 (中文句号/分号/英文标点)
        sentences = re.split(r"(?<=[。；;.!?])\s+", text.strip())
        for s in sentences:
            s_clean = s.strip()
            if len(s_clean) >= 15:
                candidates.append(s_clean)
        # 如果还没有, 整体作为一个
        if not candidates:
            candidates = [text.strip()]

    # 合并过短片段 (<8) 到前一个
    merged: List[str] = []
    for seg in candidates:
        if merged and len(seg) < 8:
            merged[-1] = merged[-1] + " " + seg
        else:
            merged.append(seg)

    # 截断与溢出处理
    overflow = []
    if len(merged) > max_branches:
        overflow = merged[max_branches-1:]
        merged = merged[:max_branches-1]
        merged.append("其余合并: " + " | ".join(overflow[:5]) + (" ..." if len(overflow) > 5 else ""))

    branches: List[Dict[str, str]] = []
    for idx, seg in enumerate(merged, 1):
        title = seg[:40].replace('\n', ' ').strip()
        branches.append({
            "branch_index": idx,
            "branch_id": f"B{idx:02d}",
            "title": title,
            "content": seg.strip(),
        })
    return branches

def get_requirement_templates() -> Dict[str, str]:
    return {
        "OBC 充电流程": """
REQ-OBC-001: 【功能】车载充电机 (OBC)：插枪握手->授权->充电->停止
场景包括：接地检测、互锁、限流、充电完成检测与故障处理
验证点：握手时序、授权流程、充电参数协商、异常断开处理
""",
        "CCU 与 BMS 交互": """
REQ-CCU-001: 【功能】CCU 请求 BMS 状态（SOC/温度/电压/故障码），处理超时与重试
验证点：CAN通信时序、数据完整性、超时重试机制、故障码解析
""",
        "BMS SOC 与充放电策略": """
REQ-BMS-001: 【功能】SOC 估算、温度相关充放电限制、低电量保护
验证点：SOC精度、温度保护阈值、功率限制算法、保护策略触发
""",
        "EVCC 通信控制": """
REQ-EVCC-001: 【功能】EVCC与充电桩通信：ISO15118协议、数字证书验证、充电参数协商
验证点：协议握手、证书链验证、参数协商、通信安全性
""",
        "充电连接与断开流程": """
REQ-CHG-001: 【功能】人机与硬件交互：插枪、授权、开始、完成、拔枪与强制中断场景
验证点：物理连接检测、用户授权、充电启停、紧急断开
""",
    }

def get_requirement_examples() -> List[str]:
    return [
        "OBC: 插枪后 5s 内未授权应取消请求",
        "BMS: 温度>60°C 时限制充电电流至 0.2C",
        "CCU: BMS 请求超时 100ms 后重试 3 次并记录故障",
    ]

@handle_errors
def call_model(model: str, prompt: str, base_url: str, temperature: float = 0.2) -> str:
    """调用模型: 优先 chat.completions, 需要时回退 completions.

    回退条件: fallback 集合模型出现 400 且返回内容包含 prompt/field required/missing.
    """
    provider = MODEL_PROVIDER_HEADER.get(model, ROUTE_HEADER_VALUE)
    debug = st.session_state.get("debug_mode", False)
    actual_model = MODEL_MAP.get(model, model)

    def _chat_payload() -> dict:
        return {
            "model": actual_model,
            "messages": [
                {"role": "system", "content": "你是测试用例生成助手，严格输出 CSV"},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "max_tokens": 2000,
        }

    def _completions_payload() -> dict:
        return {
            "model": actual_model,
            "prompt": "你是测试用例生成助手，严格输出 CSV。\n" + prompt,
            "temperature": temperature,
            "max_tokens": 2000,
        }

    def _do_request(url: str, payload: dict) -> requests.Response:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
            "X-Model-Provider-Id": provider,
        }
        return requests.post(url, headers=headers, json=payload, timeout=60)

    chat_url = f"{base_url.rstrip('/')}/v1/chat/completions"
    comp_url = f"{base_url.rstrip('/')}/v1/completions"
    fallback_allowed = {"Qwen-235B-A22B", "deepseek-v3.1", "Qwen2.5-VL-72B-Instruct-AWQ"}

    # Chat 调用
    for attempt in range(MAX_RETRY_ATTEMPTS):
        try:
            resp = _do_request(chat_url, _chat_payload())
            if resp.status_code >= 500:
                if debug:
                    st.warning(f"[调试-chat] {attempt+1} 次 -> {resp.status_code}: {resp.text[:200]}")
                if attempt < MAX_RETRY_ATTEMPTS - 1:
                    time.sleep(1.2 * (attempt + 1))
                    continue
            if resp.status_code == 400:
                low = resp.text.lower()
                if model in fallback_allowed and any(k in low for k in ["prompt", "field required", "missing"]):
                    if debug:
                        st.info("[调试] Chat 400 缺字段, 回退 completions")
                    break
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except requests.exceptions.HTTPError as e:
            code = e.response.status_code if e.response else None
            if code in (502, 503, 504, 429) and attempt < MAX_RETRY_ATTEMPTS - 1:
                time.sleep(1.2 * (attempt + 1))
                continue
            if code == 400:
                if model not in fallback_allowed:
                    raise e
                break
            raise e
        except (requests.exceptions.RequestException, KeyError, IndexError) as e:
            if attempt == MAX_RETRY_ATTEMPTS - 1:
                raise e
            if debug:
                st.warning(f"[调试-chat] 异常重试 {attempt+1}: {e}")
            time.sleep(1.0 * (attempt + 1))
    else:
        if model not in fallback_allowed:
            raise Exception("chat.completions 重试耗尽")

    # 回退 completions
    if model in fallback_allowed:
        if debug:
            st.info(f"[调试] 回退 completions 调用 {model}")
        for attempt in range(MAX_RETRY_ATTEMPTS):
            try:
                resp = _do_request(comp_url, _completions_payload())
                if resp.status_code >= 500:
                    if debug:
                        st.warning(f"[调试-comp] {attempt+1} 次 -> {resp.status_code}: {resp.text[:200]}")
                    if attempt < MAX_RETRY_ATTEMPTS - 1:
                        time.sleep(1.2 * (attempt + 1))
                        continue
                resp.raise_for_status()
                data = resp.json()
                if "choices" in data and data["choices"]:
                    c0 = data["choices"][0]
                    if isinstance(c0, dict):
                        if "message" in c0 and "content" in c0["message"]:
                            return c0["message"]["content"]
                        if "text" in c0:
                            return c0["text"]
                return json.dumps(data, ensure_ascii=False)[:4000]
            except requests.exceptions.HTTPError as e:
                code = e.response.status_code if e.response else None
                if code in (502, 503, 504, 429) and attempt < MAX_RETRY_ATTEMPTS - 1:
                    time.sleep(1.2 * (attempt + 1))
                    continue
                raise e
            except (requests.exceptions.RequestException, KeyError, IndexError) as e:
                if attempt == MAX_RETRY_ATTEMPTS - 1:
                    raise e
                if debug:
                    st.warning(f"[调试-comp] 异常重试 {attempt+1}: {e}")
                time.sleep(1.0 * (attempt + 1))
        raise Exception("completions 回退也失败")

    raise Exception("模型调用失败 (未命中成功路径)")

@handle_errors
def parse_csv_to_df(csv_text: str, expected_headers: List[str]) -> pd.DataFrame:
    if not csv_text or not csv_text.strip(): raise ValueError("CSV 内容为空")
    cleaned = csv_text.strip()
    cleaned = re.sub(r"^```.*?\n", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\n```$", "", cleaned)
    cleaned = cleaned.replace("\ufeff", "")
    lines = [l for l in cleaned.splitlines() if l.strip()]
    if not lines: raise ValueError("CSV 内容为空（清理后）")
    text = "\n".join(lines)
    try:
        sniffer = csv.Sniffer(); dialect = sniffer.sniff(text[:4096], delimiters=",;\t|")
        delimiter = dialect.delimiter
    except Exception:
        delimiter = ','
    reader = csv.reader(StringIO(text), delimiter=delimiter, quotechar='"')
    rows = [r for r in reader if any(cell.strip() for cell in r)]
    if not rows: raise ValueError("CSV 内容无法解析为行")
    def _normalize_rows(rows_list, n_cols, delim):
        normalized = []
        for r in rows_list:
            r = [c.strip().strip('"') for c in r]
            if len(r) <= n_cols: normalized.append(r + [""] * (n_cols - len(r)))
            else:
                merged_last = delim.join(r[n_cols - 1:]); normalized.append(r[:n_cols - 1] + [merged_last])
        return normalized
    header = [c.strip().strip('"') for c in rows[0]]
    matches = sum(1 for h in header if any(exp in h or h in exp for exp in expected_headers))
    if matches >= max(1, len(expected_headers)//2):
        data_rows = rows[1:]
        if not all(len(r)==len(header) for r in data_rows): data_rows = _normalize_rows(data_rows, len(header), delimiter)
        df = pd.DataFrame(data_rows, columns=header)
    else:
        if all(len(r)==len(expected_headers) for r in rows):
            df = pd.DataFrame(rows, columns=expected_headers)
        else:
            normalized = _normalize_rows(rows, len(expected_headers), delimiter)
            df = pd.DataFrame(normalized, columns=expected_headers)
    return df.fillna("").astype(str)

def make_excel_download(df: pd.DataFrame, filename: str = "测试用例.xlsx") -> None:
    if df is None or (hasattr(df, "empty") and df.empty): st.warning("没有数据可导出"); return
    buf = BytesIO();
    with pd.ExcelWriter(buf, engine='openpyxl') as w: df.to_excel(w, index=False, sheet_name='测试用例')
    buf.seek(0)
    st.download_button("💾 下载 Excel", data=buf, file_name=filename, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key=f"dxl_{uuid.uuid4().hex}")

def make_csv_download(df: pd.DataFrame, filename: str = "测试用例.csv") -> None:
    if df is None or (hasattr(df, "empty") and df.empty): st.warning("没有数据可导出"); return
    csv_bytes = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button("💾 下载 CSV", data=csv_bytes, file_name=filename, mime="text/csv", key=f"dcsv_{uuid.uuid4().hex}")

def process_batch_requirements(base_url: str, requirements: List[str], headers: List[str], model: str, pos_n: int, neg_n: int, edge_n: int, temperature: float, background_knowledge: Optional[str] = None, *, dynamic: bool = False, dyn_params: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
    all_cases = []
    pb = st.progress(0)
    status = st.empty()
    total = len(requirements)
    used_ids = set()
    for i, req in enumerate(requirements):
        pb.progress((i + 1) / total)
        status.text(f"处理中 {i+1}/{total}")
        extracted = extract_req_id(req)
        if extracted:
            req_id = extracted
            if req_id in used_ids:  # 简单重复处理
                suffix = 2
                new_id = f"{req_id}-DUP{suffix}"
                while new_id in used_ids:
                    suffix += 1
                    new_id = f"{req_id}-DUP{suffix}"
                req_id = new_id
        else:
            req_id = f"REQ-{i+1:03d}"
        used_ids.add(req_id)
        local_pos, local_neg, local_edge = pos_n, neg_n, edge_n
        if dynamic:
            p = dyn_params or {}
            local_pos, local_neg, local_edge = compute_dynamic_case_counts(
                req,
                p.get("min_total", 3),
                p.get("max_total", 9),
                p.get("pos_w", 3.0),
                p.get("neg_w", 2.0),
                p.get("edge_w", 2.0),
            )
            if st.session_state.get("debug_mode"):
                st.write(f"{req_id} 动态分配 -> 正向:{local_pos} 异常:{local_neg} 边界:{local_edge}")
        prompt = build_prompt(req, headers, local_pos, local_neg, local_edge, req_id, background_knowledge)
        text = call_model(model, prompt, base_url, temperature)
        if text:
            df = parse_csv_to_df(text, headers)
            if df is not None and not df.empty:
                if "需求编号" not in df.columns:
                    df.insert(0, "需求编号", req_id)
                else:
                    # 填充空值 / 纠正首行缺失
                    df['需求编号'] = df['需求编号'].astype(str)
                    df['需求编号'] = df['需求编号'].where(df['需求编号'].str.strip() != "", req_id)
                if "需求描述" not in df.columns:
                    df.insert(1, "需求描述", req[:100])
                all_cases.append(df)
        if i < total - 1:
            time.sleep(2)
    pb.empty(); status.empty()
    if all_cases:
        return pd.concat(all_cases, ignore_index=True)
    raise ValueError("未生成任何用例")

@handle_errors
def read_background_doc(file: Optional[Any]) -> Optional[str]:
    if file is None: return None
    name = file.name.lower()
    if name.endswith('.docx'): return read_word(file)
    if name.endswith(('.txt', '.md')): return StringIO(file.getvalue().decode("utf-8")).read()
    if name.endswith('.pdf'):
        try:
            # 尝试导入PDF处理库
            from PyPDF2 import PdfReader
            pdf = PdfReader(BytesIO(file.getvalue()))
            text = ""
            for page in pdf.pages:
                text += page.extract_text() + "\n"
            return text.strip()
        except ImportError:
            st.error("PDF处理需要安装 PyPDF2 库。请运行: pip install PyPDF2")
            return None
        except Exception as e:
            st.error(f"PDF读取失败: {e}")
            return None
    st.warning("不支持的文件类型，请使用 .docx, .txt, .md 或 .pdf")
    return None

def setup_sidebar() -> Tuple[str, str, float, List[str], int, int, int, bool, Dict[str, Any]]:
    with st.sidebar:
        st.header("连接设置")
        st.caption("当前使用硬编码 API Key (界面不再提供修改)。")
        # 模型标签展示 (免费 / 计费)
        model_display = {m: f"{m} {MODEL_PRICING_TAG.get(m,'')}" for m in ALLOWED_MODELS}
        model_choice = st.selectbox("模型 (MiMo免费 / 其他计费)", list(model_display.keys()), format_func=lambda k: model_display[k])
        model = model_choice
        base_url = st.text_input("API Base URL", value=DEFAULT_BASE_URL)
        st.checkbox("调试模式", value=False, key="debug_mode", help="显示重试 / 原始错误片段，协助排查 502 等问题")
        temperature = st.slider("Temperature", 0.0, 1.0, 0.2, 0.05)
        st.divider(); st.header("背景知识 (可选)")
        background_doc = st.file_uploader("上传背景文档", type=["docx", "txt", "md", "pdf"])
        if background_doc:
            if st.session_state.get('last_background_doc_name') != background_doc.name:
                content = read_background_doc(background_doc)
                st.session_state['background_knowledge'] = content
                st.session_state['last_background_doc_name'] = background_doc.name
                if content:
                    st.success("已加载背景")
        else:
            st.session_state.pop('background_knowledge_file', None)
            st.session_state.pop('last_background_doc_name', None)

        # 直接文本输入背景知识
        st.markdown("**直接输入背景知识 (粘贴文档内容)**")
        direct_text = st.text_area("背景知识文本", placeholder="粘贴文档内容、需求规格说明等...", height=150, key="direct_background_text")
        if direct_text and direct_text.strip():
            st.session_state['background_knowledge'] = direct_text.strip()
            st.success("已设置背景知识文本")
        elif not background_doc and not st.session_state.get('background_urls_content'):
            st.session_state.pop('background_knowledge', None)

        # 多个 URL 输入
        st.markdown("**网页链接 (每行一个 URL，可与文档混合)**")
        url_text = st.text_area("背景链接列表", placeholder="https://example.com/doc1\nhttps://example.com/spec", height=110)
        load_urls = st.button("加载链接内容")
        if load_urls:
            raw_urls = [u.strip() for u in url_text.splitlines() if u.strip()]
            valid_urls = [u for u in raw_urls if _is_valid_url(u)]
            bad_urls = [u for u in raw_urls if u and u not in valid_urls]
            fetched = []
            for u in valid_urls[:8]:  # 限制最多 8 个，避免过慢
                with st.spinner(f"抓取 {u} ..."):
                    txt = fetch_url_content(u)
                fetched.append((u, txt))
            st.session_state['background_urls'] = valid_urls
            st.session_state['background_urls_content'] = fetched
            if bad_urls:
                st.warning(f"无效链接已忽略: {len(bad_urls)}")
            st.success(f"已获取 {len(fetched)} 个链接")

        # 组合背景 (文档 + 直接文本 + URL)
        combined_parts = []
        if st.session_state.get('background_knowledge') and not st.session_state.get('direct_background_text'):
            # 如果有上传的文档内容且没有直接输入，则使用文档内容
            combined_parts.append("【文档内容】\n" + st.session_state['background_knowledge'])
        if st.session_state.get('direct_background_text') and st.session_state.get('direct_background_text').strip():
            combined_parts.append("【直接输入】\n" + st.session_state['direct_background_text'].strip())
        if st.session_state.get('background_urls_content'):
            for u, txt in st.session_state['background_urls_content']:
                combined_parts.append(f"【网页摘录】{u}\n{txt}")
        combined_text = "\n\n".join(combined_parts) if combined_parts else None
        st.session_state['background_knowledge'] = combined_text

        if combined_text:
            with st.expander("查看合并背景 (前500字符)"):
                st.text(combined_text[:500] + ("..." if len(combined_text) > 500 else ""))
        st.divider(); st.header("用例配置")
        headers_text = st.text_input("列名", value=",".join(DEFAULT_HEADERS))
        headers = [h.strip() for h in headers_text.split(",") if h.strip()]
        auto_mode = st.checkbox("按需求自动分配用例数量", value=False, help="基于需求长度/关键词动态确定正向/异常/边界数量")
        dyn_params: Dict[str, Any] = {}
        if auto_mode:
            c1, c2 = st.columns(2)
            with c1:
                min_total = st.number_input("最小总数", 3, 30, 3)
                pos_w = st.number_input("正向权重", 0.5, 10.0, 3.0, 0.5)
            with c2:
                max_total = st.number_input("最大总数", 3, 50, 9)
                neg_w = st.number_input("异常权重", 0.5, 10.0, 2.0, 0.5)
            edge_w = st.number_input("边界权重", 0.5, 10.0, 2.0, 0.5)
            dyn_params = {"min_total": min_total, "max_total": max_total, "pos_w": pos_w, "neg_w": neg_w, "edge_w": edge_w}
            st.caption("根据需求复杂度 (长度/句子数/风险关键词) 在线计算用例数量")
            # 占位固定值 (不会被使用)
            pos_n = neg_n = edge_n = 0
        else:
            pos_n = st.number_input("正向", 1, 20, 2)
            neg_n = st.number_input("异常", 1, 20, 2)
            edge_n = st.number_input("边界", 1, 20, 2)
        st.divider()
        st.subheader("飞书API配置 (可选)")
        st.caption("用于访问飞书文档作为背景知识。需要先在飞书开发者后台配置应用并获取凭证。")
        st.info("💡 **飞书文档访问提示**: 如果遇到权限问题，可以：1) 在飞书中导出文档为Word/PDF后上传；2) 复制文档内容直接粘贴到上方文本框；3) 分享文档为公开链接")
        feishu_app_id = st.text_input("飞书应用ID", placeholder="cli_xxx", help="从飞书开发者后台获取")
        feishu_app_secret = st.text_input("飞书应用密钥", type="password", placeholder="xxx", help="从飞书开发者后台获取")
        if feishu_app_id and feishu_app_secret:
            # 存储到环境变量或session
            os.environ["FEISHU_APP_ID"] = feishu_app_id
            os.environ["FEISHU_APP_SECRET"] = feishu_app_secret
            st.success("飞书API凭证已配置")
        elif feishu_app_id or feishu_app_secret:
            st.warning("请同时提供飞书应用ID和应用密钥")
        else:
            st.info("未配置飞书API凭证，将使用网页抓取方式访问飞书文档")
        return base_url, model, temperature, headers, pos_n, neg_n, edge_n, auto_mode, dyn_params

def main():
    st.set_page_config(page_title="AI 测试用例生成器 (完整)", layout="wide")
    st.title("AI 测试用例生成器 - 电力电子")
    base_url, model, temperature, headers, pos_n, neg_n, edge_n, auto_mode, dyn_params = setup_sidebar()
    tab1, tab2, tab3 = st.tabs(["单条需求", "批量处理", "帮助"])
    with tab1:
        st.subheader("单条需求生成")
        templates = get_requirement_templates(); opts = ["自定义"] + list(templates.keys())
        sel = st.selectbox("模板", opts)
        default = templates.get(sel, "") if sel != "自定义" else ""
        req_text = st.text_area("需求描述", value=default, height=220)
        req_id = st.text_input("需求编号", placeholder="例如: REQ-OBC-001")
        st.checkbox("启用分支解析 (对单条需求内部多点拆分)", value=False, key="enable_branch_split")
        st.number_input("单需求分支最大数", 2, 30, 10, key="branch_max")
        st.selectbox("分支用例分配策略", ["均分", "复杂度动态", "手动固定"], key="branch_strategy", help="对每个分支分配的用例数量策略")
        st.text_input("手动固定分配(正,异,边) 例如: 2,1,1", key="branch_manual_counts")
        st.caption("提示: 若原需求含多条规则/步骤/条件, 勾选 '启用分支解析' 自动拆成子需求并分别生成用例, 支持动态复杂度再分配。")
        if st.button("生成"):
            auto_req_id = req_id.strip() or extract_req_id(req_text) or ""
            if not req_id.strip() and auto_req_id:
                st.info(f"自动识别需求编号: {auto_req_id}")
            enable_branch = st.session_state.get("enable_branch_split", False)
            branch_strategy = st.session_state.get("branch_strategy", "均分")
            manual_counts_text = st.session_state.get("branch_manual_counts", "").strip()
            max_branches = st.session_state.get("branch_max", 10)

            placeholder = st.empty(); progress = st.progress(0)
            try:
                if not enable_branch:
                    local_pos, local_neg, local_edge = pos_n, neg_n, edge_n
                    if auto_mode:
                        local_pos, local_neg, local_edge = compute_dynamic_case_counts(
                            req_text,
                            dyn_params.get("min_total", 3),
                            dyn_params.get("max_total", 9),
                            dyn_params.get("pos_w", 3.0),
                            dyn_params.get("neg_w", 2.0),
                            dyn_params.get("edge_w", 2.0),
                        )
                        st.info(f"动态分配 -> 正向:{local_pos} 异常:{local_neg} 边界:{local_edge} (总计:{local_pos+local_neg+local_edge})")
                    prompt = build_prompt(req_text, headers, local_pos, local_neg, local_edge, auto_req_id, st.session_state.get('background_knowledge'))
                    placeholder.info("生成中..."); progress.progress(10)
                    text = call_model(model, prompt, base_url, temperature); progress.progress(80)
                    if text:
                        df = parse_csv_to_df(text, headers); progress.progress(95)
                        if df is None or (hasattr(df, "empty") and df.empty): placeholder.error("解析失败")
                        else:
                            if "需求编号" in df.columns and auto_req_id:
                                df['需求编号'] = df['需求编号'].astype(str)
                                df['需求编号'] = df['需求编号'].where(df['需求编号'].str.strip() != "", auto_req_id)
                            elif auto_req_id and "需求编号" not in df.columns:
                                df.insert(0, "需求编号", auto_req_id)
                            st.dataframe(df, use_container_width=True)
                            make_excel_download(df)
                            make_csv_download(df)
                            progress.progress(100); placeholder.success("完成")
                else:
                    # 分支解析
                    branches = split_requirement_into_branches(req_text, max_branches=max_branches)
                    if not branches:
                        st.warning("未解析出有效分支，回退为整体生成")
                        branches = [{"branch_index":1, "branch_id":"B01", "title":"整体", "content":req_text}]
                    st.info(f"解析得到 {len(branches)} 个分支")
                    # 分支用例分配策略
                    branch_cases: List[Tuple[Dict[str,str], Tuple[int,int,int]]] = []
                    # 手动固定
                    manual_tuple = None
                    if branch_strategy == "手动固定" and manual_counts_text:
                        try:
                            parts = [int(x) for x in re.split(r"[，,]\s*", manual_counts_text) if x.strip()][:3]
                            if len(parts)==3 and all(p>0 for p in parts):
                                manual_tuple = tuple(parts)  # type: ignore
                        except Exception:
                            pass
                        if not manual_tuple:
                            st.warning("手动固定格式不正确，将回退为均分")
                    # 预计算复杂度用于动态策略
                    scores = [ _complexity_score(b['content']) for b in branches ]
                    min_total = dyn_params.get("min_total", 3)
                    max_total = dyn_params.get("max_total", 9)
                    for b, sc in zip(branches, scores):
                        if branch_strategy == "手动固定" and manual_tuple:
                            branch_cases.append((b, manual_tuple))
                        elif branch_strategy == "复杂度动态":
                            # 以分支内容作为输入进行动态
                            lp, ln, le = compute_dynamic_case_counts(
                                b['content'],
                                min_total,
                                max_total,
                                dyn_params.get("pos_w", 3.0),
                                dyn_params.get("neg_w", 2.0),
                                dyn_params.get("edge_w", 2.0),
                            )
                            branch_cases.append((b, (lp, ln, le)))
                        else:
                            # 均分: 复用主面板配置或默认 2/2/1
                            if auto_mode:
                                lp, ln, le = compute_dynamic_case_counts(
                                    b['content'],
                                    min_total,
                                    max_total,
                                    dyn_params.get("pos_w", 3.0),
                                    dyn_params.get("neg_w", 2.0),
                                    dyn_params.get("edge_w", 2.0),
                                )
                            else:
                                lp, ln, le = pos_n, neg_n, edge_n
                            branch_cases.append((b, (lp, ln, le)))

                    combined_df = []
                    for idx, (b, (lp, ln, le)) in enumerate(branch_cases, 1):
                        sub_req_id = f"{auto_req_id or 'REQ-000'}-{b['branch_id']}"
                        with st.expander(f"分支 {idx}: {b['title']}  (正:{lp}/异:{ln}/边:{le})"):
                            branch_prompt = build_prompt(b['content'], headers, lp, ln, le, sub_req_id, st.session_state.get('background_knowledge'))
                            st.write(b['content'])
                            try:
                                text = call_model(model, branch_prompt, base_url, temperature)
                                if text:
                                    dfb = parse_csv_to_df(text, headers)
                                    if dfb is not None and not dfb.empty:
                                        if '需求编号' in dfb.columns:
                                            dfb['需求编号'] = dfb['需求编号'].where(dfb['需求编号'].str.strip() != "", sub_req_id)
                                        else:
                                            dfb.insert(0, '需求编号', sub_req_id)
                                        dfb['需求描述'] = dfb['需求描述'].astype(str).where(dfb['需求描述'].str.strip() != "", b['title'][:50]) if '需求描述' in dfb.columns else b['title'][:50]
                                        st.dataframe(dfb, use_container_width=True)
                                        combined_df.append(dfb)
                            except Exception as e:
                                st.error(f"分支 {b['branch_id']} 生成失败: {e}")
                        progress.progress(int(idx/len(branch_cases)*100))
                        time.sleep(1)
                    if combined_df:
                        final_df = pd.concat(combined_df, ignore_index=True)
                        # 统一列名去重: 常见重复/变体合并
                        rename_map = {
                            '测试 描述': '测试描述', '测试说明': '测试描述', '描述': '测试描述',
                            '前置': '前置条件', '前提条件': '前置条件', '前置 条件': '前置条件',
                        }
                        final_df.columns = [rename_map.get(c.strip(), c.strip()) for c in final_df.columns]
                        # 移除全空列
                        empty_cols = [c for c in final_df.columns if final_df[c].astype(str).str.strip().eq('').all()]
                        if empty_cols:
                            final_df = final_df.drop(columns=empty_cols)
                        # 若出现重复列名 (例如多次解析出的“测试描述_1”), 合并优先非空
                        deduped = {}
                        for c in final_df.columns:
                            base = c
                            if base in deduped:
                                # 合并列
                                existing = deduped[base]
                                new_series = final_df[c].astype(str)
                                deduped[base] = existing.astype(str).where(existing.astype(str).str.strip()!='', new_series)
                            else:
                                deduped[base] = final_df[c]
                        final_df = pd.DataFrame(deduped)
                        # 强制列顺序 (若存在)
                        desired = ["测试名称","需求编号","需求描述","测试描述","前置条件","测试步骤","预期结果","需求追溯"]
                        ordered = [c for c in desired if c in final_df.columns]
                        tail = [c for c in final_df.columns if c not in ordered]
                        final_df = final_df[ordered + tail]
                        st.subheader("合并结果")
                        st.dataframe(final_df, use_container_width=True)
                        make_excel_download(final_df, "测试用例_分支合并.xlsx")
                        make_csv_download(final_df, "测试用例_分支合并.csv")
                        placeholder.success("全部分支完成")
                    else:
                        placeholder.error("未生成任何分支用例")
            finally:
                progress.empty(); placeholder.empty()
    with tab2:
        st.subheader("批量导入 (Excel / Word)")
        uploaded = st.file_uploader("上传文件", type=["xlsx", "docx"])
        collected: List[str] = []
        source_counts = []

        # 1. 处理文件来源
        if uploaded:
            if uploaded.name.lower().endswith('.xlsx'):
                sheets = read_excel(uploaded)
                if sheets:
                    sheet = st.selectbox("选择工作表", list(sheets.keys()))
                    df_sheet = sheets[sheet]; st.dataframe(df_sheet.head(10))
                    col = st.selectbox("需求列", list(df_sheet.columns))
                    rows = df_sheet[col].dropna().astype(str).str.strip()
                    excel_reqs = [r for r in rows if len(r) > MIN_PARAGRAPH_LENGTH]
                    collected.extend(excel_reqs)
                    source_counts.append(f"Excel:{len(excel_reqs)}")
            else:
                content = read_word(uploaded)
                if content:
                    parts = re.split(r"\n\s*\n+", content.strip())
                    word_reqs = [p for p in parts if len(p.strip()) > MIN_PARAGRAPH_LENGTH]
                    collected.extend(word_reqs)
                    source_counts.append(f"Word:{len(word_reqs)}")

        st.divider()
        # 2. 手工文本 (一行一个需求)
        st.markdown("**手工输入需求 (每行一个)**")
        manual_text = st.text_area("手工需求列表", placeholder="需求1...\n需求2...", height=150)
        if manual_text:
            manual_list = [l.strip() for l in manual_text.splitlines() if len(l.strip()) > MIN_PARAGRAPH_LENGTH]
            if manual_list:
                collected.extend(manual_list)
                source_counts.append(f"手工:{len(manual_list)}")

        st.divider()
        # 3. 网页链接 -> 需求提取 (简单按段落拆分)
        st.markdown("**网页链接 (需求来源) 每行一个 URL**")
        url_require_text = st.text_area("需求链接列表", placeholder="https://example.com/page1\nhttps://example.com/page2", height=110, key="req_url_box")
        fetch_req_urls = st.button("抓取链接需求")
        if fetch_req_urls:
            raw_urls = [u.strip() for u in url_require_text.splitlines() if u.strip()]
            valid_urls = [u for u in raw_urls if _is_valid_url(u)]
            fetched_req = []
            for u in valid_urls[:6]:  # 限制 6 个避免超时
                with st.spinner(f"抓取 {u} ..."):
                    txt = fetch_url_content(u, max_chars=16000)
                # 粗分段
                segments = re.split(r"\n\s*\n+", txt)
                seg_clean = [s.strip() for s in segments if len(s.strip()) > MIN_PARAGRAPH_LENGTH]
                # 限制每个链接最大段数 25
                seg_clean = seg_clean[:25]
                if seg_clean:
                    fetched_req.extend(seg_clean)
            if fetched_req:
                # 存入 session，允许重复点击覆盖
                st.session_state['batch_url_requirements'] = fetched_req
                st.success(f"链接共提取 {len(fetched_req)} 条候选需求")
            else:
                st.warning("未从链接中提取到有效需求")

        if st.session_state.get('batch_url_requirements'):
            url_count = len(st.session_state['batch_url_requirements'])
            source_counts.append(f"网页:{url_count}")
            with st.expander(f"查看链接提取需求 ({url_count})"):
                for i, rtxt in enumerate(st.session_state['batch_url_requirements'][:50]):
                    st.write(f"{i+1}. {rtxt[:160]}{'...' if len(rtxt)>160 else ''}")
            collected.extend(st.session_state['batch_url_requirements'])

        # 去重 & 清理
        unique_reqs = []
        seen = set()
        for r in collected:
            key = r.strip()
            if key not in seen:
                seen.add(key)
                unique_reqs.append(key)

        st.info(f"来源统计: {' | '.join(source_counts) if source_counts else '无'} | 合并后去重: {len(unique_reqs)} 条")

        # 批量生成按钮
        if st.button("批量生成 (混合来源)"):
            if not unique_reqs:
                st.error("没有可用需求")
            else:
                df_all = process_batch_requirements(
                    base_url,
                    unique_reqs,
                    headers,
                    model,
                    pos_n,
                    neg_n,
                    edge_n,
                    temperature,
                    st.session_state.get('background_knowledge'),
                    dynamic=auto_mode,
                    dyn_params=dyn_params,
                )
                st.dataframe(df_all)
                make_excel_download(df_all, "测试用例_批量.xlsx")
                make_csv_download(df_all, "测试用例_批量.csv")
    with tab3:
        st.subheader("示例与最佳实践")
        for ex in get_requirement_examples(): st.write(f"- {ex}")
        st.markdown("---")
        st.subheader("背景知识输入方式")
        st.markdown("""
        **支持的输入方式：**
        - 📄 **上传文件**: 支持 .docx, .txt, .md, .pdf 格式
        - 📝 **直接粘贴**: 复制文档内容直接粘贴到文本框
        - 🌐 **网页链接**: 输入文档URL，自动抓取内容
        - 🪶 **飞书文档**: 通过API访问或导出后上传
        
        **飞书文档访问问题解决：**
        - **权限不足**: 使用 tenant_access_token 只能访问公开文档
        - **替代方案**: 
          1. 在飞书中导出为 Word/PDF → 上传文件
          2. 复制文档内容 → 直接粘贴到文本框
          3. 设置文档为公开分享 → 使用网页链接输入
        """)
        st.markdown("---")
        st.subheader("标准输出格式模板")
        output_tpl = get_output_format_template()
        st.code(output_tpl, language="csv")
        st.caption("这是生成的测试用例CSV的标准格式，第一行为表头，第二行为占位符示例。")
    st.markdown("---")
    st.subheader("标准 Prompt 模板")
    tpl = get_standard_prompt_template()
    st.code(tpl, language="text")
    st.caption("占位符示例: {背景知识} / {列名逗号分隔} / {需求编号} / {需求全文} / {正向数} / {异常数} / {边界数} / {总用例数}")
    st.caption("模型计费: MiMo-7B-RL 免费; 其余 (Qwen / Deepseek / Qwen2.5-VL) 计费 | 使用固定内部 API Key")

if __name__ == '__main__':
    main()