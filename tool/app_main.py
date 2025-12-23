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
import subprocess
import argparse

# --- Hardcoded Feishu Credentials ---
# This is the single source of truth for Feishu API access.
FEISHU_APP_ID = "cli_a85ffa34d3fad00c"
FEISHU_APP_SECRET = "MxD6ukGa9ZMJeGl5KicVSgNQLhnE1tcN"

# Ensure helper utilities (which rely on environment variables) can read the
# credentials even when they are only configured here.
os.environ.setdefault("FEISHU_APP_ID", FEISHU_APP_ID)
os.environ.setdefault("FEISHU_APP_SECRET", FEISHU_APP_SECRET)
# --- End of Hardcoded Credentials ---

from ai_requirement_processor import AIRequirementProcessor, estimate_requirement_complexity
from helper_functions import fetch_feishu_document, process_requirements_from_text

# 加载环境变量配置
try:
    from dotenv import load_dotenv
    # 从项目根目录加载.env文件
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
    if os.path.exists(env_path):
        load_dotenv(env_path)
        logging.info(f"已加载环境配置文件: {env_path}")
    else:
        logging.info("未找到.env文件，使用系统环境变量")
except ImportError:
    logging.warning("未安装python-dotenv，无法加载.env文件")
except Exception as e:
    logging.warning(f"加载.env文件失败: {e}")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DEFAULT_HEADERS = ["测试名称", "需求编号", "需求描述", "测试描述", "前置条件", "测试步骤", "预期结果", "需求追溯"]
DEFAULT_BASE_URL = "http://model.mify.ai.srv"  # 内部服务优先
MAX_RETRY_ATTEMPTS = 3
MIN_PARAGRAPH_LENGTH = 10

API_KEY = "sk-HXFiS9bEeg95uypM96B6kJfKaxe3ze52FUeQEriGGaGIIefS"  # 固定硬编码使用

# 模型集合 (MiMo 免费 / 其他计费)
MODEL_MAP = {
    "Qwen-235B-A22B": "Qwen-235B-A22B",
    "MiMo-7B-RL": "MiMo-7B-RL",
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
def get_feishu_tenant_access_token(debug: bool = False, retries: int = 3, base_delay: float = 0.8) -> str:
    payload = {"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET}
    last_err: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        if debug:
            print(f"[DBG] Requesting token attempt {attempt}/{retries} -> {FEISHU_TOKEN_ENDPOINT}")
        try:
            resp = requests.post(FEISHU_TOKEN_ENDPOINT, json=payload, timeout=30)
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
    """优化版飞书API GET请求 - 减少超时和调试输出"""
    headers = {"Authorization": f"Bearer {token}"}
    
    # 简化调试输出
    if debug:
        print(f"[DBG] GET {url[:100]}...")
    
    try:
        # 更宽松的超时设置以避免网络问题
        resp = requests.get(url, headers=headers, timeout=(30, 60))
    except requests.RequestException as e:
        if debug:
            print(f"[DBG] 网络错误: {e}")
        raise RuntimeError(f"GET {url} network error: {e}")
    
    if resp.status_code != 200:
        if debug:
            print(f"[DBG] HTTP {resp.status_code}")
        # 简化错误信息
        raise RuntimeError(f"API HTTP {resp.status_code}")
    
    try:
        data = resp.json()
    except ValueError:
        if debug:
            print(f"[DBG] JSON解析失败")
        raise RuntimeError(f"Response not JSON")
    
    if data.get("code") not in (0, None):
        if debug:
            print(f"[DBG] API错误: {data.get('code')}")
        raise RuntimeError(f"API error code={data.get('code')}")
    
    return data

def _fetch_blocks_recursive_helper(doc_id: str, block_id: str, token: str, all_blocks: List[Dict], visited: set, debug: bool, depth: int = 0):
    """Recursive helper to fetch all blocks in a document tree."""
    MAX_DEPTH = 15
    MAX_BLOCKS = 800
    if depth > MAX_DEPTH or block_id in visited or len(all_blocks) > MAX_BLOCKS:
        return

    if debug and depth <= 2:
        print(f"[DBG] Fetching block '{block_id[:10]}...' at depth {depth}")

    visited.add(block_id)
    # Fetch all children of a block in one go
    page_token = ""
    while True:
        url = FEISHU_BLOCKS_ENDPOINT_TMPL.format(doc_id=doc_id, block_id=block_id, page_size=500, page_token=page_token)
        try:
            data = feishu_api_get(url, token, debug=(debug and depth <= 1))
            
            items = data.get("data", {}).get("items", [])
            if not items:
                # Fallback for older API or single block fetch
                block = data.get("data", {}).get("block")
                if block:
                    items = [block]
                else:
                    break

            for block in items:
                block_id_current = block.get("block_id")
                if block_id_current and block_id_current not in visited:
                    all_blocks.append(block)
                    visited.add(block_id_current)
                    if 'children' in block and block['children']:
                        for child_id in block['children']:
                            _fetch_blocks_recursive_helper(doc_id, child_id, token, all_blocks, visited, debug, depth + 1)
            
            page_token = data.get("data", {}).get("page_token", "")
            has_more = data.get("data", {}).get("has_more", False)
            if not page_token or not has_more:
                break
        except Exception as e:
            if debug:
                print(f"[WARN] Failed to fetch blocks for parent '{block_id}': {e}")
            break

def extract_raw_text_from_elements(elements: List[Dict]) -> str:
    """Extracts raw text content from a list of 'elements'."""
    text_parts = []
    if not elements:
        return ""
    for elem in elements:
        if "text_run" in elem:
            text_parts.append(elem.get("text_run", {}).get("content", ""))
    return "".join(text_parts)

def feishu_blocks_to_markdown(blocks: List[Dict]) -> str:
    """Converts a list of Feishu blocks to a markdown string."""
    lines = []
    blocks_map = {b["block_id"]: b for b in blocks}

    # Since fetching is now recursive and flat, we need to reconstruct the hierarchy to render lists correctly.
    # For simplicity in this pass, we will render each block independently.
    for block in blocks:
        block_type = block.get("block_type")
        text = ""
        
        # Extract raw text based on block type
        if block_type == 1: # Page
            text = extract_raw_text_from_elements(block.get("page", {}).get("elements"))
            if text: lines.append(f"# {text}")
        elif block_type == 2: # Text
            text = extract_raw_text_from_elements(block.get("text", {}).get("elements"))
            if text: lines.append(text)
        elif 3 <= block_type <= 11: # Headings
            level = block_type - 2
            h_key = f"heading{level}"
            text = extract_raw_text_from_elements(block.get(h_key, {}).get("elements"))
            if text: lines.append(f"{'#' * level} {text}")
        elif block_type == 12: # Bullet List
            text = extract_raw_text_from_elements(block.get("bullet", {}).get("elements"))
            if text: lines.append(f"- {text}")
        elif block_type == 13: # Ordered List
            text = extract_raw_text_from_elements(block.get("ordered", {}).get("elements"))
            # Note: The actual number in the sequence is not available in the block, so we just use '1.'
            if text: lines.append(f"1. {text}")
        elif block_type == 15: # Todo List
            text = extract_raw_text_from_elements(block.get("todo", {}).get("elements"))
            is_done = block.get("todo", {}).get("done", False)
            if text: lines.append(f"- [{'x' if is_done else ' '}] {text}")

        elif block_type == 17: # Table
            table_data = block.get("table", {})
            cells = table_data.get("cells", [])
            md_table = []
            
            for i, row_cell_ids in enumerate(cells):
                md_row = []
                for cell_container_id in row_cell_ids:
                    cell_container_block = blocks_map.get(cell_container_id)
                    cell_text_parts = []
                    if cell_container_block and 'children' in cell_container_block:
                        for child_id in cell_container_block['children']:
                            child_block = blocks_map.get(child_id)
                            if child_block:
                                # This is a simplified text extraction for cells
                                child_text = feishu_blocks_to_markdown([child_block])
                                cell_text_parts.append(child_text)
                    
                    # Join parts and escape pipe characters for markdown table
                    cell_text = " ".join(cell_text_parts).replace("\n", " ").replace("|", "\\|")
                    md_row.append(cell_text)
                md_table.append("| " + " | ".join(md_row) + " |")

            # Add header separator for tables with a header row
            if md_table and table_data.get("property", {}).get("header_row"):
                header_separator = "| " + " | ".join(["---"] * len(cells[0])) + " |"
                md_table.insert(1, header_separator)
            
            lines.append("\n".join(md_table))

        elif block_type == 27: # Image
            token = block.get("image", {}).get("token")
            lines.append(f"![Image]({token})")
            
        elif block_type == 31: # Bitable
            token = block.get("bitable", {}).get("token")
            lines.append(f"\n[Embedded Bitable: {token}]\n")

    # Final cleanup
    # Remove excessive blank lines
    final_text = []
    prev_line_blank = False
    for line in lines:
        is_blank = not line.strip()
        if is_blank and prev_line_blank:
            continue
        final_text.append(line)
        prev_line_blank = is_blank

    return "\n".join(final_text)

def fetch_feishu_document_via_subprocess(url: str, debug: bool = False) -> str:
    """Invokes the standalone feishu_fetcher.py script to fetch content."""
    fetcher_path = os.path.join(os.path.dirname(__file__), "feishu_fetcher.py")
    command = [sys.executable, fetcher_path, url]
    
    if debug:
        print(f"[DBG] Invoking subprocess: {' '.join(command)}")

    try:
        # Start the subprocess
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='ignore'
        )
        
        # Wait for the process to complete and get the output
        stdout, stderr = process.communicate(timeout=180) # 180-second timeout
        
        if debug and stderr:
            print(f"[FETCHER_STDERR]\n{stderr}")

        if process.returncode == 0:
            return stdout.strip()
        else:
            # If the fetcher script fails, return its specific error message
            error_message = stderr.strip()
            if not error_message:
                error_message = f"Fetcher script exited with code {process.returncode}."
            return f"【飞书API错误】{error_message}"

    except subprocess.TimeoutExpired:
        if debug:
            print("[DBG] Subprocess timed out.")
        return "【飞书API错误】获取文档超时。"
    except FileNotFoundError:
        return f"【飞书API错误】无法找到 fetcher 脚本: {fetcher_path}"
    except Exception as e:
        if debug:
            print(f"[DBG] Subprocess execution failed: {e}")
        return f"【飞书API错误】调用 fetcher 脚本时发生未知异常: {e}"

def _is_valid_url(u: str) -> bool:
    try:
        p = urlparse(u.strip())
        return p.scheme in ("http", "https") and bool(p.netloc)
    except Exception:
        return False

def fetch_url_content(url: str, timeout: int = 8, max_chars: int = 8000, progress_callback=None, has_creds: bool = True, debug_mode: bool = False) -> str:
    """优化版网页内容抓取函数 - 解决卡顿和性能问题"""
    import time
    start_time = time.time()

    def update_progress(step, status=""):
        """更新进度回调"""
        if progress_callback:
            # 简化和标准化状态显示
            clean_status = status.replace("飞书", "").replace("API", "").replace("网页", "")
            if "超时" in status:
                clean_status = "超时"
            elif "错误" in status:
                clean_status = "错误"
            elif "成功" in status:
                clean_status = "成功"

            elapsed = time.time() - start_time
            try:
                progress_callback(url, step, clean_status, elapsed)
            except Exception:
                pass

    try:
        from urllib.parse import urlparse

        update_progress("start", "开始处理URL")

        # 验证URL格式
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            update_progress("error", "无效URL")
            return f"【无效URL】{url}"

        # 特殊处理飞书文档链接 - 智能判断是否使用API
        if 'feishu.cn' in url or 'larksuite' in url:
            # 检查是否是文档链接 (支持docx和wiki)
            if re.search(r"/(?:docx|wiki|docs)/[A-Za-z0-9]+", url):
                # 检查是否有API凭证
                if has_creds:
                    update_progress("feishu_api", "尝试飞书API")
                    try:
                        content = fetch_feishu_document(url, debug=debug_mode)
                        if content and not content.startswith("【飞书API错误】"):
                            if len(content) > max_chars:
                                content = content[:max_chars] + "...【截断】"
                            update_progress("success", f"飞书API成功 ({len(content)}字符)")
                            return content
                        else:
                            # API调用失败，直接返回错误信息，不再回退到网页抓取
                            # 因为网页抓取飞书文档通常需要登录，回退只会掩盖真实的API权限错误
                            update_progress("error", "飞书API调用失败")
                            return content
                    except Exception as e:
                        update_progress("error", f"飞书API异常: {e}")
                        return f"【飞书API异常】{str(e)}"
                else:
                    # 没有API凭证，直接使用网页抓取
                    update_progress("web_scrape", "无API凭证，使用网页抓取")
                    
                    # 继续执行到网页抓取
            else:
                # 不是文档链接，使用网页抓取
                update_progress("web_scrape", "非文档链接，使用网页抓取")
                
                # 继续执行到网页抓取
        else:
            # 不是飞书链接，使用网页抓取
            update_progress("web_scrape", "非飞书链接，使用网页抓取")
            
            # 继续执行到网页抓取
        
        # 优化网页抓取 - 更严格的超时控制
        update_progress("web_scrape", "开始网页抓取")
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.8,en;q=0.6",
            "Connection": "close"  # 避免连接池问题
        }
        
        # 使用更严格的超时设置
        session = requests.Session()
        session.trust_env = False  # 避免代理问题
        
        try:
            update_progress("connecting", "建立连接")
            # 进一步优化超时设置
            response = session.get(url, timeout=(2, 4), headers=headers, stream=True)
            
            # 检查状态码
            if response.status_code != 200:
                update_progress("error", f"HTTP {response.status_code}")
                return f"【失败 {response.status_code}】{url}"
            
            # 检查内容类型
            content_type = response.headers.get('content-type', '').lower()
            
            # 如果不是文本内容，直接返回
            if not any(t in content_type for t in ['text/html', 'text/plain', 'application/json']):
                update_progress("error", "非文本内容")
                return f"【非文本内容】{url}"
            
            update_progress("reading", "读取内容")
            
            # 限制读取大小，防止大文件卡顿
            max_bytes = max_chars * 4  # 为UTF-8预留空间
            text = ""
            bytes_read = 0
            
            for chunk in response.iter_content(chunk_size=1024, decode_unicode=True):
                if bytes_read > max_bytes:
                    text += "...【内容过大截断】"
                    break
                if chunk:
                    text += chunk.decode('utf-8', errors='ignore') if isinstance(chunk, bytes) else chunk
                    bytes_read += len(chunk)
            
            update_progress("processing", "处理HTML")
            
            # 智能HTML内容提取
            if 'text/html' in content_type:
                # 特殊处理飞书文档 - 检测是否为登录页面
                if 'feishu.cn' in url or 'larksuite' in url:
                    # 检查是否是登录页面（包含登录相关关键词）
                    login_indicators = ['login', 'signin', '登录', '飞书', 'lark', 'pre-loading', 'global-loading']
                    is_login_page = any(indicator in text.lower() for indicator in login_indicators)
                    
                    if is_login_page:
                        # 如果是登录页面，提供更详细的错误信息
                        update_progress("warning", "飞书文档需登录")
                        return ("【飞书文档需登录访问，API调用可能因环境问题失败。建议：" \
                                "1) 检查API配置是否有效；" \
                                "2) 在飞书中导出为 docx 文件后上传；" \
                                "3) 或复制文档内容直接粘贴到文本框中】")
                
                # 通用HTML内容提取
                # 1. 移除脚本和样式
                text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
                text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
                text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)
                
                # 2. 提取正文内容（优先提取article、main、content等区域）
                content_patterns = [
                    r'<article[^>]*>(.*?)</article>',
                    r'<main[^>]*>(.*?)</main>',
                    r'<div[^>]*class="[^"]*(?:content|main|article|text)[^"]*"[^>]*>(.*?)</div>',
                    r'<div[^>]*id="[^"]*(?:content|main|article|text)[^"]*"[^>]*>(.*?)</div>',
                    r'<body[^>]*>(.*?)</body>'
                ]
                
                extracted_text = ""
                for pattern in content_patterns:
                    match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
                    if match:
                        extracted_text = match.group(1)
                        break
                
                if extracted_text:
                    text = extracted_text
                
                # 3. 保留段落结构
                text = re.sub(r'</(p|div|h[1-6]|section|article)>', '\n\n', text, flags=re.IGNORECASE)
                
                # 4. 移除所有标签，保留文本内容
                text = re.sub(r'<[^>]+>', ' ', text)
                
                # 5. 移除多余的空白字符
                text = re.sub(r'\s+', ' ', text)
                text = re.sub(r'\n{3,}', '\n\n', text)
                text = text.strip()
            
            # 进一步截断
            if len(text) > max_chars:
                text = text[:max_chars] + "...【截断】"
            
            # 针对飞书在线文档的特殊处理
            if ('feishu.cn' in url or 'larksuite' in url):
                # 检测是否为有效文档内容
                has_meaningful_content = len(text) > 200 and not re.search(r'css|style|loading|login', text.lower())
                
                if not has_meaningful_content:
                    update_progress("warning", "飞书文档需登录")
                    
                    # 提供更详细的建议
                    suggestions = [
                        "在飞书客户端中打开文档，然后导出为 docx 文件上传到本系统",
                        "直接复制文档内容粘贴到下方的文本输入框中",
                        "如果文档已公开分享，检查分享权限设置",
                        "联系文档所有者获取文档内容"
                    ]
                    
                    suggestion_text = "\n".join([f"{i+1}. {suggestion}" for i, suggestion in enumerate(suggestions)])
                    
                    return (f"【飞书文档访问限制】\n\n"
                            f"检测到该飞书文档需要登录才能访问实际内容。\n"
                            f"当前获取到的是登录页面样式代码，不是文档正文。\n\n"
                            f"解决方案：\n"
                            f"{suggestion_text}")
                else:
                    # 如果是有效内容，进一步清理
                    update_progress("success", "飞书文档内容有效")
                    return text
            
            # 过滤无效内容
            if len(text) < 30 or 'javascript' in text.lower() or 'function' in text.lower():
                update_progress("error", "内容无效")
                return f"【内容无效】{url}"
            
            # 性能统计
            elapsed = time.time() - start_time
            update_progress("success", f"完成 ({len(text)}字符, {elapsed:.1f}s)")
            
            return text
            
        finally:
            session.close()
        
    except requests.exceptions.Timeout:
        update_progress("timeout", "连接超时")
        return f"【超时】{url}"
    except requests.exceptions.ConnectionError:
        update_progress("error", "连接错误")
        return f"【连接错误】{url}"
    except Exception as e:
        update_progress("error", f"异常: {e}")
        if debug_mode:
            print(f"[DEBUG] 网页抓取异常: {e}")
        return f"【异常: {e.__class__.__name__}】{url}"

def process_urls_batch(urls: List[str], timeout: int = 60, max_chars: int = 8000, progress_callback=None) -> Dict[str, str]:
    """优化版批量处理URL抓取 - 解决卡顿和超时问题"""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import time

    results = {}

    # 限制URL数量，防止过多请求导致卡死
    urls = urls[:10]  # 最多处理10个URL

    # 在主线程捕获 session_state，避免在子线程中访问导致上下文丢失
    try:
        has_creds = st.session_state.get('feishu_credentials_available', False)
        debug_mode = st.session_state.get("debug_mode", False)
    except Exception:
        has_creds = True
        debug_mode = False

    def wrapped_fetch_url(url: str) -> str:
        """包装器，将进度回调适配到 batch 处理器中。"""
        def progress_adapter(cb_url, step, status, elapsed):
            if progress_callback:
                try:
                    progress_callback(cb_url, step, status, elapsed, len(results), len(urls))
                except Exception:
                    # 忽略线程中的UI更新错误
                    pass
        # 传递捕获的配置
        return fetch_url_content(url, timeout=timeout, max_chars=max_chars, progress_callback=progress_adapter, has_creds=has_creds, debug_mode=debug_mode)

    # 使用线程池并行处理，限制并发数
    max_workers = min(2, len(urls))  # 最多同时处理2个URL

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 提交所有任务
        future_to_url = {
            executor.submit(wrapped_fetch_url, url): url
            for url in urls
        }

        # 显示进度
        total = len(urls)
        processed = 0
        start_time = time.time()

        # 设置总体超时时间 - 增加等待时间以适应飞书API
        # 基础超时 * 数量，但至少给 60 秒，最多 180 秒
        overall_timeout = min(max(timeout * len(urls), 60), 180)

        # 处理完成的任务
        try:
            for future in as_completed(future_to_url, timeout=overall_timeout):
                url = future_to_url[future]
                try:
                    # 使用较短的单个任务超时，但也需要足够长
                    result = future.result(timeout=timeout + 10)
                    results[url] = result
                    processed += 1

                    # 显示进度
                    elapsed = time.time() - start_time
                    avg_time = elapsed / processed if processed > 0 else 0

                    if debug_mode:
                        status = "成功" if not result.startswith("【") else "失败"
                        print(f"[DEBUG] 进度: {processed}/{total} - {url} -> {status} ({len(result)}字符)")

                except Exception as e:
                    results[url] = f"【处理异常】{url}: {e}"
                    processed += 1
                    if debug_mode:
                        print(f"[DEBUG] 错误: {url} -> {e}")

        except TimeoutError:
            # 处理总体超时
            pending_urls = set(future_to_url.values()) - set(results.keys())
            for url in pending_urls:
                results[url] = f"【处理超时】{url}"

            if debug_mode:
                print(f"[DEBUG] 总体超时，完成 {len(results)}/{total} 个任务")

        finally:
            # 清理未完成的任务
            for future in list(future_to_url.keys()):
                url = future_to_url[future]
                if url not in results:
                    results[url] = f"【未完成】{url}"
                    if not future.done():
                        future.cancel()

    # 性能统计
    elapsed = time.time() - start_time
    if debug_mode:
        success_count = sum(1 for r in results.values() if not r.startswith("【"))
        print(f"[DEBUG] 批量处理完成: {success_count}/{total} 成功，耗时: {elapsed:.2f}s")

    return results

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
# Context
[可选背景知识]
请参考以下检索到的上下文（如果为空，请根据通用行业标准处理）：
{background_knowledge.strip()}
"""

    guidance = f"""
# Role
你是一位追求极致覆盖率的 OBC (On-Board Charger) / CCU (Combined Charging Unit) / BMU (电池管理)测试开发专家与自动化架构师。
你深知自动化脚本编写的痛点：**一个测试函数只应验证一个特定的逻辑分支。**
因此，在设计用例时，你遵循“原子化原则”——严禁将正向、逆向或边界测试混合在同一个用例中。
你精通电力电子特性、ISO 15118/GB 27930 充电协议、CAN/CAN-FD 通信矩阵、UDS 诊断 (ISO 14229) 以及 HIL (Hardware-in-the-Loop) 测试系统。
你的核心能力是将自然语言的需求描述转化为**包含具体信号交互、逻辑严密、可直接用于编写自动化脚本**的工程级测试用例。

{background_section}

# Extraction Rules (关键步骤)
在设计用例前，请先深入分析需求文档，提取以下要素（无需单独输出，但必须融入用例中）：
1.  **信号实体**：识别需求中涉及的物理信号（如：AC_Voltage, CC_Resistor）和总线信号（如：CAN ID, 信号名, Enum值）。若文档未明确信号名，请使用符合行业规范的英文占位符（如 `OBC_Sts_ChgMode`）。
2.  **逻辑阈值**：提取具体数值、公差（±5%）、时间参数（timeout=500ms, debounce=100ms）。
3.  **状态机**：明确前置状态（如 Standby）和目标状态（如 Charging）。
4. **Happy Path (正向)**：标称值输入，验证最理想的成功路径。
5. **Boundary (边界)**：刚好达到触发阈值（如 >260V）、刚好未达到阈值（如 259V）。
6. **Failure Mode (故障)**：注入错误信号、校验失败、物理连接断开。
7. **Timeout (超时)**：前置条件满足但响应超时。

# Task Instructions
针对提供的“需求描述”，请遵循以下原则设计测试用例：

1.  **信号级精确性**：
    * 禁止使用模糊描述（如“检查电压是否正常”）。
    * 必须使用**具体数值和信号逻辑**（如“检查 `OBC_DC_Out_Volt` 在 2s 内达到 400V ±5V”）。
2.  **脚本可转换性 (Script-Ready)**：
    * **测试步骤**必须是原子化的动作序列，格式建议为：`[动作] [对象/信号] 为 [数值/状态]`。
    * **前置条件**必须量化（如 `KL15 = ON`, `BMS_SOC = 20%`）。
3.  **覆盖率要求**：
    * **正向场景**：标称值测试。
    * **边界值**：最大值、最小值、最大值+1、最小值-1。
    * **异常/注入**：信号丢失(Lost Communication)、校验错误(CRC Error)、超出范围值、超时未响应。
    * **交互场景**：充电过程中发生诊断请求、高低温降额等。
* 如果一条需求 `REQ-001` 包含“支持过压保护和欠压保护”，**必须**输出至少两条用例：一条测过压，一条测欠压。 * **禁止**在“预期结果”中出现“或者”、“如果不满足则...”这类分支逻辑。每条用例的结果必须是单一且确定的。
*每一条需求，至少包含一条可验证的用例

 4. **交互/场景化用例 (Scenario Cases)**
    * **核心优化点** **当发现需求间存在关联时，必须增加此类用例：** * **名称格式**：使用 `_Scenario_` 或 `_Interaction_` 后缀。
    * **覆盖逻辑**： * **顺序执行**：将多个需求的逻辑串联成一个长流程（如：插枪 -> 握手成功 -> 充电 -> 满充停止 -> 拔枪）。
    * **冲突仲裁**：在满足需求 A (正常工作) 时，强制触发需求 B (故障条件)，验证高优先级逻辑是否生效。
    * **状态转换**：验证从需求 A 的状态跳转到需求 B 的状态是否符合时序要求。

# Output Format
请严格遵守 CSV 格式输出，**不要**使用 Markdown 表格，**不要**包含表头以外的解释性文字。
字段顺序与要求如下：

1.  **测试名称**：简练明确，包含场景特征（如：`CASE_OBC_Chg_OverVolt_Protection`），必须带后缀以区分场景 (e.g., `_Norm`, `_Max`, `_Timeout`)。
2.  **需求编号**：同一需求编号会在多行中重复出现。 如果是交互用例，需列出所有相关的ID，用分号分隔 (e.g., `REQ-001;REQ-003`)。
3.  **需求描述**：简要概括。
4.  **测试描述**：测试目的（侧重于验证单一逻辑还是交互逻辑）。
5.  **前置条件**：初始化环境变量与信号状态（用分号分隔）。
6.  **测试步骤**：原子化步骤，**每一步带上序号**，包含具体的信号操作（Set/Wait/Check）。
7.  **预期结果**：具体的信号响应、标志位翻转或物理现象，包含时间约束。
8.  **用例类型**：`Positive`, `Negative`, `Boundary`, `Robustness`, `Integration`。

# Input Requirement
请根据以上规则，为以下需求生成 {total_cases} 条测试用例（正向 {pos_n}, 异常 {neg_n}, 边界 {edge_n}）：

需求ID: {req_id if req_id else "REQ-001"}
需求描述:
{requirement.strip()}

请开始生成测试用例（CSV格式）：
{cols_line}
"""
    return guidance

def get_standard_prompt_template() -> str:
    """返回在生成用例时使用的标准 Prompt 模板（占位符形式展示）。"""
    return (
        "# Role\n"
        "你是一位追求极致覆盖率的 OBC/CCU/BMU 测试开发专家与自动化架构师。\n"
        "你遵循“原子化原则”——严禁将正向、逆向或边界测试混合在同一个用例中。\n\n"
        "# Context\n"
        "[可选背景知识]\n{背景知识}\n\n"
        "# Extraction Rules (关键步骤)\n"
        "1. 信号实体：识别物理信号和总线信号。\n"
        "2. 逻辑阈值：提取具体数值、公差、时间参数。\n"
        "3. 状态机：明确前置状态和目标状态。\n"
        "4. Happy Path (正向)\n"
        "5. Boundary (边界)\n"
        "6. Failure Mode (故障)\n"
        "7. Timeout (超时)\n\n"
        "# Task Instructions\n"
        "1. 信号级精确性：禁止模糊描述，必须使用具体数值和信号逻辑。\n"
        "2. 脚本可转换性：测试步骤必须是原子化的动作序列，前置条件必须量化。\n"
        "3. 覆盖率要求：正向、边界、异常、交互场景。\n"
        "4. 交互/场景化用例：顺序执行、冲突仲裁、状态转换。\n\n"
        "# Output Format\n"
        "请严格遵守 CSV 格式输出，不要使用 Markdown 表格。\n"
        "字段：测试名称, 需求编号, 需求描述, 测试描述, 前置条件, 测试步骤, 预期结果, 用例类型\n\n"
        "# Input Requirement\n"
        "需求ID: {需求编号}\n"
        "需求描述:\n{需求全文}\n\n"
        "请开始生成测试用例（CSV格式）：\n{列名逗号分隔}"
    )

def get_output_format_template(headers: List[str] = None) -> str:
    """返回标准的输出格式模板（CSV格式，第一行为表头，第二行为占位符示例）。"""
    if headers is None:
        headers = DEFAULT_HEADERS
    header_line = ",".join(f'"{h}"' for h in headers)
    example_line = ",".join(f'"{h}示例"' for h in headers)
    return f"{header_line}\n{example_line}"

# 匹配 REQ-xxx 或 SRxxxx 格式的需求编号
REQ_ID_PATTERN = re.compile(r"\b((?:REQ-[A-Za-z0-9]+-\d{2,4})|(?:SR\d+))\b", re.IGNORECASE)

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

# ===== AI大模型需求分析功能 =====
@handle_errors
def analyze_requirements_with_ai(full_text: str, base_url: str, model: str, temperature: float = 0.2, 
                                max_tokens: int = 4000) -> List[Dict[str, str]]:
    """使用AI大模型对整个文档进行智能需求分析和分解
    
    Args:
        full_text: 完整的文档文本内容
        base_url: API基础URL
        model: 模型名称
        temperature: 温度参数
        max_tokens: 最大token数
    
    Returns:
        分析后的需求列表，每个需求包含编号、标题、描述等信息
    """
    
    # 智能文本截断，保留重要部分
    if len(full_text) > 12000:
        # 保留开头和结尾的重要部分，中间截断
        first_part = full_text[:6000]
        last_part = full_text[-6000:]
        truncated_text = f"{first_part}\n... [文档中间部分已截断] ...\n{last_part}"
    else:
        truncated_text = full_text
    
    # 构建智能分析提示词
    analysis_prompt = f"""你是一名专业的软件需求分析师，擅长从技术文档中智能提取和分解需求。

请分析以下技术文档，识别并智能分解其中的所有需求。文档内容：

---
{truncated_text}
---

请按照以下结构化格式输出分析结果（JSON格式）：
{{
  "requirements": [
    {{
      "id": "需求编号（格式：REQ-类别-序号，如：REQ-FUNC-001）",
      "title": "需求标题（简洁描述核心功能）",
      "description": "详细需求描述（清晰、具体、可验证）",
      "category": "需求类别（功能需求/性能需求/安全需求/接口需求/可靠性需求/可用性需求）",
      "priority": "优先级（高/中/低）",
      "testable": "是否可测试（是/否）",
      "complexity": "复杂度（简单/中等/复杂）",
      "dependencies": "依赖关系（相关需求编号列表）",
      "test_scenarios": ["主要测试场景1", "主要测试场景2"],
      "acceptance_criteria": ["验收标准1", "验收标准2"]
    }}
  ]
}}

智能分析要求：
1. **需求识别**：识别文档中的所有类型需求，包括功能、性能、安全等
2. **智能分解**：将复杂需求分解为可独立测试的子需求
3. **语义理解**：基于上下文理解需求之间的关联和依赖
4. **优先级评估**：根据业务重要性和技术复杂度评估优先级
5. **可测试性分析**：评估每个需求的可测试性和测试复杂度
6. **场景识别**：识别主要的测试场景和验收标准
7. **编号规范**：使用标准编号格式，确保唯一性和可追溯性

请确保：
- 需求描述具体、可验证、无歧义
- 复杂需求被合理分解为原子需求
- 识别需求之间的依赖关系
- 评估测试复杂度和资源需求

请直接输出JSON格式的结果，不要包含其他解释性文字。"""

    try:
        # 调用AI模型进行分析
        response = call_model(model, analysis_prompt, base_url, temperature)
        
        # 解析JSON响应
        import json
        
        # 清理响应文本，提取JSON部分
        json_start = response.find('{')
        json_end = response.rfind('}') + 1
        if json_start >= 0 and json_end > json_start:
            json_text = response[json_start:json_end]
            result = json.loads(json_text)
            
            requirements = result.get('requirements', [])
            
            # 验证和标准化需求数据
            validated_reqs = []
            for req in requirements:
                # 确保必需字段存在
                req_id = req.get('id', '').strip()
                title = req.get('title', '').strip()
                description = req.get('description', '').strip()
                
                if req_id and title and description:
                    # 标准化需求编号
                    if not req_id.startswith('REQ-'):
                        # 根据类别生成标准编号
                        category_map = {
                            '功能需求': 'FUNC', '性能需求': 'PERF', '安全需求': 'SEC',
                            '接口需求': 'INTF', '可靠性需求': 'RELY', '可用性需求': 'USAB'
                        }
                        category = req.get('category', '功能需求')
                        category_code = category_map.get(category, 'FUNC')
                        req_id = f"REQ-{category_code}-{len(validated_reqs) + 1:03d}"
                    
                    # 标准化优先级
                    priority = req.get('priority', '中').lower()
                    if priority in ['high', '高', 'critical']:
                        priority = '高'
                    elif priority in ['medium', '中', 'normal']:
                        priority = '中'
                    else:
                        priority = '低'
                    
                    validated_reqs.append({
                        'id': req_id,
                        'title': title,
                        'description': description,
                        'category': req.get('category', '功能需求'),
                        'priority': priority,
                        'testable': req.get('testable', '是'),
                        'complexity': req.get('complexity', '中等'),
                        'dependencies': req.get('dependencies', []),
                        'test_scenarios': req.get('test_scenarios', []),
                        'acceptance_criteria': req.get('acceptance_criteria', [])
                    })
            
            return validated_reqs
        else:
            st.warning("AI分析结果格式异常，回退到传统识别方法")
            return []
            
    except Exception as e:
        st.error(f"AI需求分析失败: {e}")
        return []

@handle_errors
def intelligent_requirement_decomposition(requirement_text: str, base_url: str, model: str, 
                                        temperature: float = 0.2) -> List[Dict[str, str]]:
    """智能需求分解 - 将复杂需求分解为可测试的子需求
    
    Args:
        requirement_text: 单个需求文本
        base_url: API基础URL
        model: 模型名称
        temperature: 温度参数
    
    Returns:
        分解后的子需求列表
    """
    
    decomposition_prompt = f"""你是一名专业的测试工程师，擅长将复杂需求分解为可测试的子需求。

请将以下复杂需求分解为可独立测试的原子需求：

---
{requirement_text}
---

请按照以下格式输出分解结果（JSON格式）：
{{
  "sub_requirements": [
    {{
      "id": "子需求编号（格式：SUB-父需求编号-序号）",
      "title": "子需求标题",
      "description": "详细子需求描述",
      "test_focus": "测试重点",
      "complexity": "测试复杂度（简单/中等/复杂）",
      "dependencies": "依赖关系"
    }}
  ]
}}

分解原则：
1. **原子性**：每个子需求应该是可独立测试的最小单元
2. **可验证性**：每个子需求应该有明确的验证标准
3. **完整性**：所有子需求组合应覆盖原始需求的全部功能
4. **独立性**：尽量减少子需求之间的依赖关系
5. **可追溯性**：保持与原始需求的关联关系

请直接输出JSON格式的结果。"""

    try:
        response = call_model(model, decomposition_prompt, base_url, temperature)
        
        import json
        json_start = response.find('{')
        json_end = response.rfind('}') + 1
        if json_start >= 0 and json_end > json_start:
            json_text = response[json_start:json_end]
            result = json.loads(json_text)
            
            sub_requirements = result.get('sub_requirements', [])
            return sub_requirements
        else:
            return []
            
    except Exception as e:
        st.error(f"智能需求分解失败: {e}")
        return []

@handle_errors
def batch_requirement_analysis(documents: List[str], base_url: str, model: str, 
                             temperature: float = 0.2, batch_size: int = 5) -> Dict[str, Any]:
    """批量需求分析 - 对多个文档进行智能分析
    
    Args:
        documents: 文档文本列表
        base_url: API基础URL
        model: 模型名称
        temperature: 温度参数
        batch_size: 批量处理大小
    
    Returns:
        分析结果统计和需求列表
    """
    
    all_requirements = []
    analysis_stats = {
        'total_documents': len(documents),
        'total_requirements': 0,
        'by_category': {},
        'by_priority': {'高': 0, '中': 0, '低': 0},
        'by_testability': {'是': 0, '否': 0},
        'processing_time': 0
    }
    
    start_time = time.time()
    
    # 分批处理文档
    for i in range(0, len(documents), batch_size):
        batch_docs = documents[i:i + batch_size]
        
        for doc in batch_docs:
            try:
                requirements = analyze_requirements_with_ai(doc, base_url, model, temperature)
                all_requirements.extend(requirements)
                
                # 更新统计信息
                for req in requirements:
                    analysis_stats['total_requirements'] += 1
                    
                    # 按类别统计
                    category = req.get('category', '其他')
                    analysis_stats['by_category'][category] = analysis_stats['by_category'].get(category, 0) + 1
                    
                    # 按优先级统计
                    priority = req.get('priority', '中')
                    analysis_stats['by_priority'][priority] = analysis_stats['by_priority'].get(priority, 0) + 1
                    
                    # 按可测试性统计
                    testable = req.get('testable', '是')
                    analysis_stats['by_testability'][testable] = analysis_stats['by_testability'].get(testable, 0) + 1
                    
            except Exception as e:
                st.warning(f"文档分析失败: {e}")
                continue
        
        # 批量处理间隔
        if i + batch_size < len(documents):
            time.sleep(0.1)
    
    analysis_stats['processing_time'] = time.time() - start_time
    
    return {
        'requirements': all_requirements,
        'statistics': analysis_stats
    }

def extract_text_from_file(uploaded_file) -> str:
    """从上传的文件中提取文本内容"""
    if uploaded_file is None:
        return ""
    
    name = uploaded_file.name.lower()
    
    if name.endswith('.pdf'):
        try:
            from PyPDF2 import PdfReader
            pdf = PdfReader(BytesIO(uploaded_file.getvalue()))
            text = ""
            for page in pdf.pages:
                text += page.extract_text() + "\n"
            return text
        except Exception as e:
            st.error(f"PDF文本提取失败: {e}")
            return ""
    
    elif name.endswith('.docx'):
        try:
            return read_word(uploaded_file)
        except Exception as e:
            st.error(f"Word文本提取失败: {e}")
            return ""
    
    elif name.endswith(('.txt', '.md')):
        try:
            return StringIO(uploaded_file.getvalue().decode("utf-8")).read()
        except Exception as e:
            st.error(f"文本文件读取失败: {e}")
            return ""
    
    elif name.endswith('.xlsx'):
        try:
            sheets = read_excel(uploaded_file)
            text_parts = []
            for sheet_name, df in sheets.items():
                text_parts.append(f"工作表: {sheet_name}")
                for _, row in df.iterrows():
                    row_text = " | ".join([str(cell) for cell in row if pd.notna(cell)])
                    text_parts.append(row_text)
            return "\n".join(text_parts)
        except Exception as e:
            st.error(f"Excel文本提取失败: {e}")
            return ""
    
    else:
        st.warning("不支持的文件类型")
        return ""

def identify_requirements_with_ai(full_text: str, source_name: str) -> List[str]:
    """使用AI智能识别文档中的需求"""
    try:
        # 检查是否有API配置
        api_key = API_KEY  # 使用硬编码的API Key
        base_url = DEFAULT_BASE_URL
        
        if not api_key:
            st.warning("未配置API Key，无法使用AI需求识别")
            return []
        
        # 创建AI客户端
        client = OpenAI(api_key=api_key, base_url=base_url)
        
        # 构建提示词
        prompt = f"""请从以下文档内容中识别出所有的软件需求。文档来源：{source_name}
        
{full_text[:4000]}  # 限制文本长度避免token超限

请按照以下要求识别需求：
1. 识别独立的功能需求、性能需求、安全需求等
2. 每个需求应该是完整、可测试的独立单元
3. 忽略文档的格式标记、标题、页眉页脚等非需求内容
4. 将识别出的需求按JSON数组格式返回

返回格式：
{{
    "requirements": [
        "需求1描述",
        "需求2描述",
        ...
    ]
}}

请只返回JSON格式，不要有其他内容。"""
        
        response = client.chat.completions.create(
            model="MiMo-7B-RL",  # 使用免费模型
            messages=[
                {"role": "system", "content": "你是一个专业的软件需求分析师，能够准确识别文档中的软件需求。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        )
        
        result_text = response.choices[0].message.content
        
        # 解析结果
        json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
            requirements = result.get("requirements", [])
            
            # 过滤空需求和过短需求
            filtered_reqs = [req.strip() for req in requirements 
                           if req.strip() and len(req.strip()) > MIN_PARAGRAPH_LENGTH]
            
            return filtered_reqs
        else:
            st.warning("AI需求识别返回格式不正确")
            return []
            
    except Exception as e:
        logger.error(f"AI需求识别失败 ({source_name}): {e}")
        st.warning(f"AI需求识别失败: {str(e)}")
        return []

# ===== 进度显示工具 =====
def display_url_progress(url, step, status, elapsed, current=None, total=None):
    """显示URL处理进度"""
    if st.session_state.get("debug_mode"):
        progress_info = f"[{step}] {status} ({elapsed:.1f}s)"
        if current is not None and total is not None:
            progress_info = f"[{current}/{total}] {progress_info}"
        print(f"[PROGRESS] {url[:50]}... -> {progress_info}")

def process_single_document_with_progress(url, progress_bar=None, status_text=None):
    """处理单个文档并显示进度 - 优先使用飞书API"""
    def progress_callback(step, status="", elapsed=0.0):
        """单个文档进度回调"""
        if progress_bar and status_text:
            # 进度映射
            progress_map = {
                "start": 10,
                "feishu_api": 40,
                "fallback": 60,
                "web_scrape": 80,
                "processing": 95,
                "success": 100,
                "timeout": 100,
                "error": 100
            }
            progress = progress_map.get(step, 0)
            progress_bar.progress(progress)
            
            # 状态显示
            status_map = {
                "start": "开始处理文档",
                "feishu_api": "使用飞书API",
                "fallback": "备用方案",
                "web_scrape": "网页抓取",
                "processing": "处理内容",
                "success": "完成",
                "timeout": "超时",
                "error": "错误"
            }
            display_status = status_map.get(step, step)
            status_text.text(f"{display_status}... ({elapsed:.1f}s)")
    
    import time
    start_time = time.time()
    
    # 如果是飞书文档，优先使用API
    if 'feishu.cn' in url or 'larksuite' in url:
        progress_callback("feishu_api", "使用飞书API", time.time() - start_time)
        try:
            content = fetch_feishu_document(url, debug=st.session_state.get("debug_mode", False))
            
            # 检查API调用是否成功
            if content and not content.startswith("【飞书API错误】"):
                progress_callback("success", "完成", time.time() - start_time)
                return content  # API成功，立即返回
            else:
                # API调用失败，回退到网页抓取
                progress_callback("fallback", "备用方案", time.time() - start_time)
                # 继续执行到网页抓取
        except Exception as e:
            progress_callback("fallback", "备用方案", time.time() - start_time)
            # 继续执行到网页抓取
    
    # 使用网页抓取作为备选方案
    progress_callback("web_scrape", "网页抓取", time.time() - start_time)
    
    def web_progress_callback(url, step, status, elapsed):
        """网页抓取进度回调包装器"""
        progress_callback(step if step != "start" else "web_scrape", status, elapsed)
    
    return fetch_url_content(url, progress_callback=web_progress_callback)

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
    fallback_allowed = {"Qwen-235B-A22B", "deepseek-v3.1", "Qwen2.5-VL-72B-Instruct-AWQ", "MiMo-7B-RL"}

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
                # 宽松的回退条件：只要是 400 且模型支持回退，就尝试 completions
                if model in fallback_allowed:
                    if debug:
                        st.info(f"[调试] Chat 400 ({resp.text[:50]}...), 回退 completions")
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
        try:
            text = call_model(model, prompt, base_url, temperature)
        except Exception as e:
            if "400" in str(e) and background_knowledge:
                # 如果是 400 错误且包含背景知识，尝试移除背景知识重试
                if st.session_state.get("debug_mode"):
                    st.warning(f"需求 {req_id} 生成失败 (400)，尝试移除背景知识重试...")
                prompt_simple = build_prompt(req, headers, local_pos, local_neg, local_edge, req_id, None)
                try:
                    text = call_model(model, prompt_simple, base_url, temperature)
                except Exception as e2:
                    st.error(f"需求 {req_id} 生成失败: {e2}")
                    text = None
            else:
                st.error(f"需求 {req_id} 生成失败: {e}")
                text = None

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
            time.sleep(0.1)
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
            
            if valid_urls:
                # 创建进度显示区域 - 简化显示
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                def progress_callback(url, step, status, elapsed, current=None, total=None):
                    """优化进度回调函数"""
                    if total:
                        progress = (current / total) * 100
                        progress_bar.progress(int(progress))
                        # 简化状态显示
                        simple_status = {
                            "start": "开始处理",
                            "feishu_api": "飞书API",
                            "web_scrape": "网页抓取",
                            "connecting": "连接中",
                            "reading": "读取内容",
                            "processing": "处理中",
                            "success": "完成",
                            "timeout": "超时",
                            "error": "错误"
                        }
                        display_step = simple_status.get(step, step)
                        status_text.text(f"[{current}/{total}] {display_step}: {status} ({elapsed:.1f}s)")
                    else:
                        status_text.text(f"处理中: {status} ({elapsed:.1f}s)")
                
                # 使用批量处理
                with st.spinner(f"正在抓取 {len(valid_urls[:8])} 个链接..."):
                    # 增加超时时间到 100 秒，以适应大型飞书文档
                    batch_results = process_urls_batch(valid_urls[:8], timeout=100, progress_callback=progress_callback)
                    fetched = [(url, content) for url, content in batch_results.items()]
                
                # 显示结果统计
                success_count = sum(1 for _, content in fetched if not content.startswith("【"))
                
                # 清理进度显示
                progress_bar.empty()
                status_text.empty()
                
                st.session_state['background_urls'] = valid_urls
                st.session_state['background_urls_content'] = fetched
                if bad_urls:
                    st.warning(f"无效链接已忽略: {len(bad_urls)}")
                if success_count > 0:
                    st.success(f"成功获取 {success_count}/{len(fetched)} 个链接")
                else:
                    st.error("所有链接处理失败，请检查链接有效性或权限")

                # 显示详细结果（包括错误）
                with st.expander("查看处理详情"):
                    for url, content in fetched:
                        if content.startswith("【"):
                            st.error(f"{url}\n{content}")
                        else:
                            st.success(f"{url}\n成功获取 {len(content)} 字符")
            else:
                st.warning("请输入有效的URL链接")

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
        st.subheader("飞书API配置")
        st.caption("凭证已在 `tool/feishu_config.py` 中硬编码，无需在此配置。")
        # Display status based on the hardcoded credentials
        if FEISHU_APP_ID and FEISHU_APP_SECRET:
            st.success(f"✅ 已加载飞书API凭证 (应用ID: {FEISHU_APP_ID[:10]}...)")
            st.info("系统将优先使用API方式访问飞书文档。")
        else:
            st.error("❌ 飞书凭证未在 feishu_config.py 中配置！")

        return base_url, model, temperature, headers, pos_n, neg_n, edge_n, auto_mode, dyn_params

def get_enhanced_background_knowledge() -> str:
    """获取增强的背景知识，包含左侧背景和批量需求上下文"""
    bg_knowledge = st.session_state.get('background_knowledge', '') or ""

    # 获取批量需求（如果有）
    batch_reqs = st.session_state.get('batch_requirements', [])
    selected_indices = st.session_state.get('selected_requirements', [])

    final_batch_reqs = []
    if batch_reqs:
        if selected_indices:
            final_batch_reqs = [batch_reqs[i] for i in selected_indices if i < len(batch_reqs)]
        else:
            # 如果没有选中记录（可能还没进过 tab2），则使用全部
            final_batch_reqs = batch_reqs

    if final_batch_reqs:
        batch_context_list = []
        for i, r in enumerate(final_batch_reqs):
            # 简单的清理和截断单条需求，避免单条过长
            clean_r = r.strip().replace('\n', ' ')
            if len(clean_r) > 200:
                clean_r = clean_r[:200] + "..."
            batch_context_list.append(f"关联需求#{i+1}: {clean_r}")

        batch_context_str = "\n".join(batch_context_list)

        # 总长度限制
        if len(batch_context_str) > 15000:
            batch_context_str = batch_context_str[:15000] + "\n... (部分需求因长度限制已省略)"

        bg_knowledge = f"{bg_knowledge}\n\n【项目全量需求参考 (上下文)】\n{batch_context_str}"

    return bg_knowledge

def main():
    st.set_page_config(page_title="AI 测试用例生成器 (完整)", layout="wide")
    
    # Set a flag to indicate credentials are available
    st.session_state['feishu_credentials_available'] = True

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
                    prompt = build_prompt(req_text, headers, local_pos, local_neg, local_edge, auto_req_id, get_enhanced_background_knowledge())
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
                            branch_prompt = build_prompt(b['content'], headers, lp, ln, le, sub_req_id, get_enhanced_background_knowledge())
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
                        time.sleep(0.1)
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
        uploaded = st.file_uploader("上传文件", type=["xlsx", "docx", "pdf", "html"])
        collected: List[str] = []
        source_counts = []

        # 1. 处理文件来源
        # 重置PDF处理状态（如果上传了新文件）
        if uploaded:
            current_file_name = uploaded.name
            if 'current_pdf_file' not in st.session_state or st.session_state.current_pdf_file != current_file_name:
                st.session_state.pdf_processed = False
                st.session_state.pdf_requirements = []
                st.session_state.current_pdf_file = current_file_name
            
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
            elif uploaded.name.lower().endswith('.pdf'):
                # 处理PDF文件
                try:
                    from PyPDF2 import PdfReader
                    pdf = PdfReader(BytesIO(uploaded.getvalue()))
                    text = ""
                    for page in pdf.pages:
                        text += page.extract_text() + "\n"
                    
                    if text.strip():
                        # 初始化PDF处理状态
                        if 'pdf_processed' not in st.session_state:
                            st.session_state.pdf_processed = False
                        if 'pdf_requirements' not in st.session_state:
                            st.session_state.pdf_requirements = []
                        
                        # PDF文档AI分解选项
                        st.markdown("#### PDF文档AI智能分解")
                        col_pdf1, col_pdf2 = st.columns(2)
                        with col_pdf1:
                            enable_pdf_ai = st.checkbox("启用PDF AI分解", value=True, 
                                                      help="使用AI智能分解PDF文档中的需求",
                                                      key="enable_pdf_ai")
                        with col_pdf2:
                            # 分解条件配置
                            decomposition_condition = st.text_input("分解条件（可选）", 
                                                                   placeholder="例如：按功能模块、按优先级、按复杂度等",
                                                                   key="decomposition_condition")
                        
                        # 默认使用传统方法提取需求
                        parts = re.split(r"\n\s*\n+", text.strip())
                        pdf_reqs = [p for p in parts if len(p.strip()) > MIN_PARAGRAPH_LENGTH]
                        
                        # 如果还没有处理过PDF，或者用户重新上传了文件，使用传统方法
                        if not st.session_state.pdf_processed:
                            st.session_state.pdf_requirements = pdf_reqs
                            st.session_state.pdf_processed = True
                        
                        if enable_pdf_ai:
                            # 显示AI分解选项
                            if st.button("🔍 AI分解PDF需求"):
                                with st.spinner("AI正在分解PDF文档需求..."):
                                    try:
                                        # 使用AI进行PDF文档需求分解
                                        client = OpenAI(api_key=API_KEY, base_url=DEFAULT_BASE_URL)
                                        ai_processor = AIRequirementProcessor(client)
                                        
                                        # 根据用户输入的分解条件构建提示词
                                        condition_prompt = ""
                                        if decomposition_condition.strip():
                                            condition_prompt = f"请按照以下条件进行需求分解：{decomposition_condition}"
                                        
                                        # 分析PDF文档
                                        analyzed_reqs = ai_processor.process_pdf_requirements(text, uploaded.name, condition_prompt)
                                        
                                        if analyzed_reqs:
                                            st.success(f"✅ AI智能分解出 {len(analyzed_reqs)} 条高质量需求")
                                            
                                            # 显示分解统计
                                            with st.expander("📊 PDF分解统计"):
                                                categories = {}
                                                priorities = {}
                                                complexities = {}
                                                
                                                for req in analyzed_reqs:
                                                    cat = req.get('type', '未知')
                                                    pri = req.get('priority', '中')
                                                    comp = req.get('complexity', '中等')
                                                    
                                                    categories[cat] = categories.get(cat, 0) + 1
                                                    priorities[pri] = priorities.get(pri, 0) + 1
                                                    complexities[comp] = complexities.get(comp, 0) + 1
                                                
                                                col1, col2 = st.columns(2)
                                                with col1:
                                                    st.write("**需求类别**")
                                                    for cat, count in categories.items():
                                                        st.write(f"- {cat}: {count}")
                                                    st.write("**优先级**")
                                                    for pri, count in priorities.items():
                                                        st.write(f"- {pri}: {count}")
                                                with col2:
                                                    st.write("**复杂度**")
                                                    for comp, count in complexities.items():
                                                        st.write(f"- {comp}: {count}")
                                            
                                            # 显示AI分解的需求预览
                                            with st.expander("🔍 AI分解需求预览"):
                                                for i, req in enumerate(analyzed_reqs[:15]):  # 显示前15条
                                                    st.write(f"**{i+1}. {req.get('type', '未知类型')}**")
                                                    st.write(f"   优先级: {req.get('priority', '中')} | 复杂度: {req.get('complexity', '中等')}")
                                                    st.write(f"   描述: {req.get('sub_requirement', req.get('original_requirement', ''))[:200]}...")
                                                    st.divider()
                                            
                                            # 使用AI分解的需求更新session状态
                                            ai_pdf_reqs = [req.get('sub_requirement', req.get('original_requirement', '')) for req in analyzed_reqs]
                                            st.session_state.pdf_requirements = ai_pdf_reqs
                                            st.session_state.pdf_ai_analysis_completed = True
                                            st.rerun()
                                        else:
                                            # AI分解失败，保持传统方法
                                            st.warning("AI分解失败，使用传统方法处理")
                                        
                                    except Exception as e:
                                        st.warning(f"PDF AI分解失败，使用传统方法: {e}")
                            
                        # 使用session状态中的需求
                        collected.extend(st.session_state.pdf_requirements)
                        source_counts.append(f"PDF:{len(st.session_state.pdf_requirements)}")
                        
                        # 显示PDF AI分析结果（如果已完成）
                        if st.session_state.get('pdf_ai_analysis_completed', False):
                            st.success("✅ PDF AI分解已完成")
                            
                            # 显示PDF内容预览
                            with st.expander("PDF内容预览"):
                                st.text(text[:500] + ("..." if len(text) > 500 else ""))
                        else:
                            # 显示PDF内容预览
                            with st.expander("PDF内容预览"):
                                st.text(text[:500] + ("..." if len(text) > 500 else ""))
                    else:
                        st.warning("PDF文件内容为空或无法提取文本")
                        
                except ImportError:
                    st.error("PDF处理需要安装 PyPDF2 库。请运行: pip install PyPDF2")
                except Exception as e:
                    st.error(f"PDF读取失败: {e}")
            elif uploaded.name.lower().endswith('.docx'):
                content = read_word(uploaded)
                if content:
                    parts = re.split(r"\n\s*\n+", content.strip())
                    word_reqs = [p for p in parts if len(p.strip()) > MIN_PARAGRAPH_LENGTH]
                    collected.extend(word_reqs)
                    source_counts.append(f"Word:{len(word_reqs)}")
            
            # 处理HTML文件
            elif uploaded.name.lower().endswith('.html'):
                try:
                    html_content = uploaded.getvalue().decode('utf-8')
                    # 提取HTML文本内容
                    text_content = re.sub(r'<[^>]+>', ' ', html_content)
                    text_content = re.sub(r'\\s+', ' ', text_content)
                    
                    if text_content.strip():
                        parts = re.split(r"\n\s*\n+", text_content.strip())
                        html_reqs = [p for p in parts if len(p.strip()) > MIN_PARAGRAPH_LENGTH]
                        collected.extend(html_reqs)
                        source_counts.append(f"HTML:{len(html_reqs)}")
                        
                        # 显示HTML内容预览
                        with st.expander("HTML内容预览"):
                            st.text(text_content[:500] + ("..." if len(text_content) > 500 else ""))
                except Exception as e:
                    st.error(f"HTML文件处理失败: {e}")

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
        st.markdown("**网页链接 (需求来源)**")
        
        # 单个文档处理
        col1, col2 = st.columns([2, 1])
        with col1:
            single_url = st.text_input("单个文档链接", placeholder="https://mi.feishu.cn/docx/...", key="single_url_box")
            # 添加飞书文档提示
            if single_url and ('feishu.cn' in single_url or 'larksuite' in single_url):
                st.info("💡 **飞书文档提示**: 已配置API自动获取，如遇问题可导出为docx文件或复制内容直接粘贴。")
        with col2:
            process_single = st.button("🔍 处理单个文档", type="primary")
        
        st.markdown("**批量链接处理 (每行一个 URL)**")
        url_require_text = st.text_area("需求链接列表", placeholder="https://example.com/page1\nhttps://example.com/page2", height=110, key="req_url_box")
        
        # 单个文档处理
        if process_single and single_url:
            if _is_valid_url(single_url):
                # 创建进度显示
                progress_bar = st.progress(0)
                status_text = st.empty()
                result_text = st.empty()
                
                # 使用单个文档处理函数
                with st.spinner("正在处理单个文档..."):
                    content = process_single_document_with_progress(single_url, progress_bar, status_text)
                
                # 清理进度显示
                progress_bar.empty()
                status_text.empty()
                
                if content and not content.startswith("【"):
                    # 使用统一的需求提取函数
                    seg_clean = process_requirements_from_text(content)

                    if seg_clean:
                        # 存入session
                        st.session_state['single_doc_requirements'] = seg_clean
                        st.session_state['force_refresh_requirements'] = True
                        result_text.success(f"✅ 成功处理文档，提取 {len(seg_clean)} 条候选需求")

                        # 显示内容预览
                        with st.expander("📄 文档内容预览"):
                            st.text(content[:500] + ("..." if len(content) > 500 else ""))
                    else:
                        result_text.warning("⚠️ 文档内容为空或格式异常")
                else:
                    # 改进错误信息显示
                    if content.startswith("【飞书文档需登录访问"):
                        result_text.error(f"❌ 飞书文档处理失败: API调用异常，已回退到网页抓取但需要登录。请检查API配置或使用其他方式上传文档。")
                    elif content.startswith("【"):
                        result_text.error(f"❌ 文档处理失败: {content}")
                    else:
                        result_text.error(f"❌ 文档处理失败: 未知错误")
            else:
                st.warning("请输入有效的URL链接")
        
        # 批量链接处理
        fetch_req_urls = st.button("批量抓取链接需求")
        if fetch_req_urls:
            raw_urls = [u.strip() for u in url_require_text.splitlines() if u.strip()]
            valid_urls = [u for u in raw_urls if _is_valid_url(u)]
            fetched_req = []
            
            if valid_urls:
                # 创建进度显示区域 - 简化显示
                progress_bar = st.progress(0)
                status_text = st.empty()
                result_text = st.empty()
                
                def progress_callback(url, step, status, elapsed, current=None, total=None):
                    """优化进度回调函数"""
                    if total:
                        progress = (current / total) * 100
                        progress_bar.progress(int(progress))
                        # 简化状态显示
                        simple_status = {
                            "start": "开始",
                            "feishu_api": "飞书API",
                            "web_scrape": "抓取",
                            "connecting": "连接",
                            "reading": "读取",
                            "processing": "处理",
                            "success": "完成",
                            "timeout": "超时",
                            "error": "错误"
                        }
                        display_step = simple_status.get(step, step)
                        status_text.text(f"需求抓取 [{current}/{total}]: {display_step} ({elapsed:.1f}s)")
                    else:
                        status_text.text(f"需求抓取: {status} ({elapsed:.1f}s)")
                
                # 使用批量处理
                with st.spinner(f"正在抓取 {len(valid_urls[:6])} 个需求链接..."):
                    # 增加超时时间到 100 秒
                    batch_results = process_urls_batch(valid_urls[:6], timeout=100, max_chars=16000, progress_callback=progress_callback)

                    # 提取需求段落
                    success_count = 0
                    failed_urls = []
                    for url, txt in batch_results.items():
                        if not txt.startswith("【"):  # 成功的抓取
                            success_count += 1
                            # 使用统一的需求提取函数
                            seg_clean = process_requirements_from_text(txt)
                            if seg_clean:
                                fetched_req.extend(seg_clean)
                        else:
                            failed_urls.append((url, txt))

                # 清理进度显示
                progress_bar.empty()
                status_text.empty()

                if fetched_req:
                    # 存入 session
                    st.session_state['batch_url_requirements'] = fetched_req
                    st.session_state['force_refresh_requirements'] = True
                    result_text.success(f"✅ 成功抓取 {success_count}/{len(valid_urls)} 个链接，提取 {len(fetched_req)} 条候选需求")
                else:
                    result_text.warning("⚠️ 未从链接中提取到有效需求")

                # 显示失败详情
                if failed_urls:
                    with st.expander("⚠️ 查看失败链接详情"):
                        for url, error in failed_urls:
                            st.error(f"**{url}**\n{error}")
            else:
                st.warning("请输入有效的URL链接")

        # 单个文档需求
        if st.session_state.get('single_doc_requirements'):
            single_count = len(st.session_state['single_doc_requirements'])
            source_counts.append(f"单个文档:{single_count}")
            with st.expander(f"查看单个文档需求 ({single_count})"):
                for i, rtxt in enumerate(st.session_state['single_doc_requirements'][:20]):
                    st.write(f"{i+1}. {rtxt[:160]}{'...' if len(rtxt)>160 else ''}")
            collected.extend(st.session_state['single_doc_requirements'])
        
        # 批量链接需求
        if st.session_state.get('batch_url_requirements'):
            url_count = len(st.session_state['batch_url_requirements'])
            source_counts.append(f"网页:{url_count}")
            with st.expander(f"查看链接提取需求 ({url_count})"):
                for i, rtxt in enumerate(st.session_state['batch_url_requirements'][:50]):
                    st.write(f"{i+1}. {rtxt[:160]}{'...' if len(rtxt)>160 else ''}")
            collected.extend(st.session_state['batch_url_requirements'])

        # 阶段1：用户交互编辑（先进行需求编辑）
        st.divider()
        st.subheader("✏️ 需求编辑和筛选")

        # 初始化session状态
        if 'batch_requirements' not in st.session_state or st.session_state.get('force_refresh_requirements'):
            st.session_state.batch_requirements = collected.copy()
            # 重置选中状态为全选
            st.session_state.selected_requirements = list(range(len(collected)))
            # 清除强制刷新标志
            st.session_state.force_refresh_requirements = False

        # 如果PDF AI分解已完成，确保需求被包含
        if st.session_state.get('pdf_ai_analysis_completed', False) and st.session_state.get('pdf_requirements'):
            # 检查是否已经包含了PDF需求
            pdf_reqs = st.session_state.pdf_requirements
            if not any(req in st.session_state.batch_requirements for req in pdf_reqs):
                st.session_state.batch_requirements.extend(pdf_reqs)
        
        if 'selected_requirements' not in st.session_state:
            st.session_state.selected_requirements = list(range(len(st.session_state.batch_requirements)))
        if 'user_commands' not in st.session_state:
            st.session_state.user_commands = ""
        
        # 需求筛选和编辑功能
        col1, col2 = st.columns([3, 1])
        
        with col1:
            # 搜索框
            search_term = st.text_input("🔍 搜索需求", placeholder="输入关键词筛选需求...", key="search_requirements_batch")
            
            # 需求列表展示
            # 使用带索引的列表以处理重复需求内容的情况
            all_reqs_with_idx = list(enumerate(st.session_state.batch_requirements))

            if search_term:
                filtered_reqs_with_idx = [(i, req) for i, req in all_reqs_with_idx
                                        if search_term.lower() in req.lower()]
            else:
                filtered_reqs_with_idx = all_reqs_with_idx

            st.write(f"**显示 {len(filtered_reqs_with_idx)} 条需求**")

            # 需求选择器
            selected_indices = []
            # 收集当前页面上被选中的索引（注意：这会覆盖之前的选择，如果逻辑不当）
            # 但这里的逻辑是：如果 checkbox 被选中，就加入 selected_indices。
            # 实际上，Streamlit 的 checkbox 状态在 rerun 之间保持。
            # 我们需要维护 st.session_state.selected_requirements。

            # 先复制一份当前选中的，避免丢失未显示的需求的选中状态
            current_selected = set(st.session_state.selected_requirements)

            for original_idx, req in filtered_reqs_with_idx:
                col_a, col_b = st.columns([1, 4])
                with col_a:
                    # 使用 original_idx 作为 key 的一部分，确保唯一性
                    is_selected = st.checkbox(f"需求 {original_idx+1}",
                                         value=original_idx in st.session_state.selected_requirements,
                                         key=f"req_{original_idx}")

                    if is_selected:
                        current_selected.add(original_idx)
                    elif original_idx in current_selected:
                        current_selected.remove(original_idx)

                with col_b:
                    st.text_area(f"需求内容 {original_idx+1}", value=req, height=60,
                               key=f"content_{original_idx}",
                               on_change=lambda idx=original_idx: _update_requirement(idx))

            # 更新选中的需求索引
            st.session_state.selected_requirements = list(current_selected)
        
        with col2:
            st.write("**批量操作**")
            
            # 选择操作
            if st.button("✅ 全选"):
                st.session_state.selected_requirements = list(range(len(st.session_state.batch_requirements)))
                st.rerun()
            
            if st.button("❌ 清空选择"):
                st.session_state.selected_requirements = []
                st.rerun()
            
            # 删除选中
            if st.button("🗑️ 删除选中"):
                if st.session_state.selected_requirements:
                    # 按索引从大到小删除，避免索引变化
                    for idx in sorted(st.session_state.selected_requirements, reverse=True):
                        if idx < len(st.session_state.batch_requirements):
                            st.session_state.batch_requirements.pop(idx)
                    st.session_state.selected_requirements = []
                    st.rerun()
            
            # 添加新需求
            new_req = st.text_area("➕ 添加新需求", height=80, placeholder="输入新的需求描述...")
            if st.button("添加") and new_req.strip():
                st.session_state.batch_requirements.append(new_req.strip())
                st.rerun()
        
        # 用户命令交互区域
        st.divider()
        st.subheader("💬 用户命令交互")
        
        col_cmd1, col_cmd2 = st.columns([3, 1])
        with col_cmd1:
            user_cmd = st.text_area("输入命令", value=st.session_state.user_commands, 
                                  placeholder="例如：删除包含'测试'的需求，合并相似需求，添加编号前缀等...",
                                  height=100)
        with col_cmd2:
            st.write("**可用命令**")
            st.write("• `删除 关键词`")
            st.write("• `保留 关键词`")
            st.write("• `添加前缀 前缀`")
            st.write("• `合并相似`")
            st.write("• `清理重复`")
            
            if st.button("执行命令"):
                if user_cmd.strip():
                    st.session_state.user_commands = user_cmd
                    _process_user_commands(user_cmd)
                    st.rerun()
        
        # 阶段2：AI智能分析（在用户编辑之后）
        st.divider()
        st.subheader("🤖 AI需求智能分析（可选）")
        
        col_ai1, col_ai2 = st.columns(2)
        with col_ai1:
            enable_ai_analysis = st.checkbox("启用AI需求分析", value=True, 
                                           help="使用AI自动识别需求类型、优先级和复杂度",
                                           key="enable_ai_analysis_batch")
        with col_ai2:
            enable_ai_decomposition = st.checkbox("启用AI需求分解", value=True,
                                                help="自动将复杂需求分解为可测试的子需求",
                                                key="enable_ai_decomposition_batch")
        
        processed_reqs = st.session_state.batch_requirements.copy()
        ai_analysis_results = None
        
        if enable_ai_analysis and st.session_state.batch_requirements:
            if st.button("🔍 开始AI分析"):
                with st.spinner("AI正在分析需求..."):
                    try:
                        # 直接使用 batch_requirements 进行分析，避免合并后再拆分导致需求碎片化
                        paragraphs = [req for req in st.session_state.batch_requirements
                                    if req.strip() and len(req.strip()) > MIN_PARAGRAPH_LENGTH]

                        # 使用AI进行需求识别和分解
                        client = OpenAI(api_key=API_KEY, base_url=DEFAULT_BASE_URL)
                        ai_processor = AIRequirementProcessor(client)

                        # 分析需求
                        analyzed_reqs = ai_processor.process_batch_requirements(paragraphs, enable_decomposition=enable_ai_decomposition)

                        if analyzed_reqs:
                            # 保存AI分析结果到session状态
                            st.session_state.ai_analysis_results = analyzed_reqs
                            st.session_state.ai_analysis_completed = True
                            
                            # 替换为AI识别的需求
                            processed_reqs = [req.get('sub_requirement', req.get('original_requirement', '')) for req in analyzed_reqs]
                            st.session_state.batch_requirements = processed_reqs
                            
                            # 重置选择状态，选择所有新需求
                            st.session_state.selected_requirements = list(range(len(processed_reqs)))
                            
                            st.success(f"✅ AI智能识别出 {len(analyzed_reqs)} 条高质量需求")
                            st.rerun()
                        
                    except Exception as e:
                        st.warning(f"AI需求分析失败，使用传统方法: {e}")
        
        # 显示AI分析结果（如果已完成）
        if st.session_state.get('ai_analysis_completed', False) and st.session_state.get('ai_analysis_results'):
            analyzed_reqs = st.session_state.ai_analysis_results
            
            # 显示分析统计
            with st.expander("📊 AI分析统计"):
                categories = {}
                priorities = {}
                complexities = {}
                decomposition_stats = {'已分解': 0, '未分解': 0}
                
                for req in analyzed_reqs:
                    cat = req.get('type', '未知')
                    pri = req.get('priority', '中')
                    comp = req.get('complexity', '中等')
                    is_decomposed = req.get('is_decomposed', False)
                    
                    categories[cat] = categories.get(cat, 0) + 1
                    priorities[pri] = priorities.get(pri, 0) + 1
                    complexities[comp] = complexities.get(comp, 0) + 1
                    if is_decomposed:
                        decomposition_stats['已分解'] += 1
                    else:
                        decomposition_stats['未分解'] += 1
                
                col1, col2 = st.columns(2)
                with col1:
                    st.write("**需求类别**")
                    for cat, count in categories.items():
                        st.write(f"- {cat}: {count}")
                    st.write("**优先级**")
                    for pri, count in priorities.items():
                        st.write(f"- {pri}: {count}")
                with col2:
                    st.write("**复杂度**")
                    for comp, count in complexities.items():
                        st.write(f"- {comp}: {count}")
                    st.write("**分解状态**")
                    for stat, count in decomposition_stats.items():
                        st.write(f"- {stat}: {count}")
            
            # 显示AI识别的需求详情与筛选
            st.markdown("### 🧬 AI分析结果详情与筛选")

            # 筛选工具栏
            col_filter1, col_filter2, col_filter3 = st.columns(3)
            with col_filter1:
                filter_type = st.multiselect("按类型筛选", options=list(categories.keys()))
            with col_filter2:
                filter_priority = st.multiselect("按优先级筛选", options=list(priorities.keys()))
            with col_filter3:
                filter_complexity = st.multiselect("按复杂度筛选", options=list(complexities.keys()))

            # 过滤逻辑
            filtered_ai_reqs = []
            for i, req in enumerate(analyzed_reqs):
                if filter_type and req.get('type', '未知') not in filter_type:
                    continue
                if filter_priority and req.get('priority', '中') not in filter_priority:
                    continue
                if filter_complexity and req.get('complexity', '中等') not in filter_complexity:
                    continue
                filtered_ai_reqs.append((i, req))

            st.write(f"显示 {len(filtered_ai_reqs)} / {len(analyzed_reqs)} 条需求")

            # 全选/反选
            col_act1, col_act2 = st.columns([1, 5])
            with col_act1:
                if st.button("全选当前", key="ai_select_all"):
                    # 更新 selected_requirements
                    current_indices = [i for i, _ in filtered_ai_reqs]
                    st.session_state.selected_requirements = list(set(st.session_state.selected_requirements) | set(current_indices))
                    st.rerun()
            with col_act2:
                if st.button("取消全选当前", key="ai_deselect_all"):
                    current_indices = set([i for i, _ in filtered_ai_reqs])
                    st.session_state.selected_requirements = [i for i in st.session_state.selected_requirements if i not in current_indices]
                    st.rerun()

            # 列表展示
            display_limit = 50
            for idx, (i, req) in enumerate(filtered_ai_reqs):
                if idx >= display_limit:
                    st.info(f"还有 {len(filtered_ai_reqs) - display_limit} 条需求未显示，请使用筛选器缩小范围。")
                    break

                col_c, col_d = st.columns([0.5, 10])
                with col_c:
                    # 这里的 i 是原始索引，对应 batch_requirements 和 selected_requirements
                    # 注意：我们需要手动处理 checkbox 的状态更新，因为 Streamlit 的 checkbox 在 rerun 时才会更新 session_state
                    # 但在这里我们直接操作 session_state.selected_requirements

                    is_sel = st.checkbox("", value=i in st.session_state.selected_requirements, key=f"ai_req_sel_{i}")

                    # 实时更新选中状态 (虽然 Streamlit 的 checkbox 返回值已经是当前状态，但我们需要同步到 selected_requirements)
                    if is_sel:
                        if i not in st.session_state.selected_requirements:
                            st.session_state.selected_requirements.append(i)
                    else:
                        if i in st.session_state.selected_requirements:
                            st.session_state.selected_requirements.remove(i)

                with col_d:
                    content = req.get('sub_requirement', req.get('original_requirement', ''))
                    meta = f"**[{req.get('type')}]** 优先级:`{req.get('priority')}` 复杂度:`{req.get('complexity')}`"
                    if req.get('is_decomposed'):
                        meta += " (已分解)"
                    st.markdown(f"{meta}\n\n{content}")
                    st.divider()
        
        # 阶段3：最终确认和生成
        st.divider()
        st.subheader("🚀 最终确认和生成")
        
        # 显示当前需求统计
        st.info(f"当前需求数量: {len(st.session_state.batch_requirements)} 条")
        
        # 最终需求统计
        final_reqs = st.session_state.batch_requirements
        if st.session_state.selected_requirements:
            final_reqs = [st.session_state.batch_requirements[i] 
                        for i in st.session_state.selected_requirements 
                        if i < len(st.session_state.batch_requirements)]
        
        st.success(f"✅ 准备生成测试用例的需求数量: {len(final_reqs)} 条")
        
        # 显示最终需求预览
        with st.expander("📋 最终需求预览"):
            for i, req in enumerate(final_reqs[:20]):  # 显示前20条
                st.write(f"**{i+1}.** {req[:150]}{'...' if len(req) > 150 else ''}")
        
        # 批量生成按钮
        if final_reqs:
            if st.button("🚀 批量生成测试用例"):
                with st.spinner("正在生成测试用例..."):
                    df_all = process_batch_requirements(
                        base_url,
                        final_reqs,
                        headers,
                        model,
                        pos_n,
                        neg_n,
                        edge_n,
                        temperature,
                        get_enhanced_background_knowledge(),
                        dynamic=auto_mode,
                        dyn_params=dyn_params,
                    )
                st.dataframe(df_all)
                make_excel_download(df_all, "测试用例_批量.xlsx")
                make_csv_download(df_all, "测试用例_批量.csv")
        else:
            st.warning("请先上传文件或输入需求内容")
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

def _update_requirement(index: int):
    """更新需求内容"""
    if f"content_{index}" in st.session_state:
        new_content = st.session_state[f"content_{index}"]
        if index < len(st.session_state.batch_requirements):
            st.session_state.batch_requirements[index] = new_content

def _process_user_commands(command: str):
    """处理用户命令"""
    if not command.strip():
        return
    
    original_reqs = st.session_state.batch_requirements.copy()
    
    # 删除命令
    if command.startswith("删除"):
        keyword = command.replace("删除", "").strip()
        if keyword:
            st.session_state.batch_requirements = [
                req for req in original_reqs 
                if keyword.lower() not in req.lower()
            ]
            st.success(f"已删除包含 '{keyword}' 的需求，剩余 {len(st.session_state.batch_requirements)} 条")
    
    # 保留命令
    elif command.startswith("保留"):
        keyword = command.replace("保留", "").strip()
        if keyword:
            st.session_state.batch_requirements = [
                req for req in original_reqs 
                if keyword.lower() in req.lower()
            ]
            st.success(f"已保留包含 '{keyword}' 的需求，剩余 {len(st.session_state.batch_requirements)} 条")
    
    # 添加前缀
    elif command.startswith("添加前缀"):
        prefix = command.replace("添加前缀", "").strip()
        if prefix:
            st.session_state.batch_requirements = [
                f"{prefix} {req}" for req in original_reqs
            ]
            st.success(f"已为所有需求添加前缀 '{prefix}'")
    
    # 合并相似需求（简单实现）
    elif command == "合并相似":
        # 简单的相似度合并（基于关键词）
        merged = []
        for req in original_reqs:
            is_similar = False
            for existing in merged:
                # 简单的相似度判断：共享关键词
                req_words = set(req.lower().split())
                existing_words = set(existing.lower().split())
                if len(req_words & existing_words) >= 2:  # 至少共享2个词
                    is_similar = True
                    break
            if not is_similar:
                merged.append(req)
        
        if len(merged) < len(original_reqs):
            st.session_state.batch_requirements = merged
            st.success(f"已合并相似需求，从 {len(original_reqs)} 条减少到 {len(merged)} 条")
    
    # 清理重复
    elif command == "清理重复":
        unique_reqs = []
        seen = set()
        for req in original_reqs:
            if req not in seen:
                seen.add(req)
                unique_reqs.append(req)
        
        if len(unique_reqs) < len(original_reqs):
            st.session_state.batch_requirements = unique_reqs
            st.success(f"已清理重复需求，从 {len(original_reqs)} 条减少到 {len(unique_reqs)} 条")
    
    else:
        st.warning("未知命令，请使用：删除/保留/添加前缀/合并相似/清理重复")

if __name__ == '__main__':
    main()