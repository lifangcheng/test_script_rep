#!/usr/bin/env python3
import os
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
try:
    from openai import OpenAI
    import openai
except Exception:
    OpenAI = None  # optional
    openai = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AppConfig:
    """应用程序配置"""
    # 基本参数
    DEFAULT_HEADERS = ["测试名称", "需求编号", "需求描述", "测试描述", "前置条件", "测试步骤", "预期结果"]
    DEFAULT_BASE_URL = "http://model.mify.ai.srv"  # 内部服务优先
    MAX_RETRY_ATTEMPTS = 3
    MIN_PARAGRAPH_LENGTH = 10
    API_KEY = "sk-HXFiS9bEeg95uypM96B6kJfKaxe3ze52FUeQEriGGaGIIefS"  # 固定硬编码

    # 模型配置
    MODEL_MAP = {
        "Qwen-235B-A22B": "Qwen-235B-A22B",
        "MiMo-7B-RL": "MiMo-7B-RL",
        "deepseek-v3.1": "deepseek-v3.1",
        "Qwen2.5-VL-72B-Instruct-AWQ": "Qwen2.5-VL-72B-Instruct-AWQ",
        "mock-model": "mock-model",
    }

    ALLOWED_MODELS = list(MODEL_MAP.keys())

    MODEL_PRICING_TAG = {
        "MiMo-7B-RL": "(免费)",
        "Qwen-235B-A22B": "(计费)",
        "deepseek-v3.1": "(计费)",
        "Qwen2.5-VL-72B-Instruct-AWQ": "(计费)"
    }

    # 服务路由配置
    MODEL_PROVIDER_HEADER = {
        "MiMo-7B-RL": "xiaomi",
        "Qwen-235B-A22B": "xiaomi",
        "deepseek-v3.1": "xiaomi",
        "Qwen2.5-VL-72B-Instruct-AWQ": "xiaomi"
    }



def handle_errors(func):
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except requests.exceptions.HTTPError as e:
            logger.exception(e)
            msg = str(e)
            if e.response is not None and e.response.status_code == 400:
                # 详细显示 400 错误的内容
                error_detail = e.response.text
                st.error(f"请求被拒绝 (400 Bad Request)。\n服务器返回详情: {error_detail}")
                return None

            low = msg.lower()
            # Detect common authentication failure patterns
            if '401' in msg or 'authentication' in low or 'invalid' in low and 'key' in low or 'invalid_request_error' in low:
                st.error("认证失败：API Key 无效或未授权。请在侧边栏重新输入正确的 API Key，或选择 'local-model' / 'mock-model' 进行本地测试。")
            else:
                st.error(f"操作失败: {msg}")
            return None
        except Exception as e:
            logger.exception(e)
            st.error(f"操作失败: {str(e)}")
            return None
    return wrapper


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


def compute_dynamic_case_counts(
    text: str,
    min_total: int = 3,
    max_total: int = 9,
    pos_w: float = 3.0,
    neg_w: float = 2.0,
    edge_w: float = 2.0
) -> Tuple[int, int, int]:
    """根据需求文本复杂度动态计算各类用例数量"""
    # 计算基础复杂度分数 (根据文本长度和句子数)
    sentences = len(re.split(r'[。！？.!?]+', text.strip()))
    words = len(text.strip())
    base_score = min(1.0, words / 1000) * 0.6 + min(1.0, sentences / 10) * 0.4

    # 风险关键词加权 (每个关键词提高10%的复杂度, 最高到2.0)
    risk_keywords = [
        "异常", "故障", "错误", "超时", "重试", "保护", "边界",
        "限制", "安全", "警告", "报警", "错误", "诊断", "丢帧"
    ]
    keyword_matches = sum(1 for k in risk_keywords if k in text)
    risk_score = min(2.0, 1.0 + keyword_matches * 0.1)

    # 最终复杂度分数 (基础分数和风险分数的加权平均)
    complexity = base_score * 0.7 + risk_score * 0.3

    # 根据复杂度计算用例总数 (在min_total和max_total之间线性插值)
    total_cases = round(min_total + (max_total - min_total) * complexity)

    # 按权重分配用例数
    total_weight = pos_w + neg_w + edge_w
    pos_ratio = pos_w / total_weight
    neg_ratio = neg_w / total_weight
    edge_ratio = edge_w / total_weight

    pos = round(total_cases * pos_ratio)
    neg = round(total_cases * neg_ratio)
    edge = round(total_cases * edge_ratio)

    # 确保每类至少1个用例
    pos = max(1, pos)
    neg = max(1, neg)
    edge = max(1, edge)

    return pos, neg, edge

def _generate_mock_csv(requirement: str, headers: List[str], pos_n: int, neg_n: int, edge_n: int, req_id: str = "") -> str:
    """Generate a deterministic mock CSV string for fast local testing."""
    rows = []
    idx = 1
    def make_row(req_num, req_desc, title, desc, pre, steps, expect, trace):
        # escape double quotes by doubling them for CSV
        cells = [req_num, req_desc, title, desc, pre or "无", steps, expect, trace]
        quoted = [f'"{c.replace("\"", "\"\"")}"' for c in cells]
        return ",".join(quoted)

    # Extract requirement ID from text if present
    req_match = re.search(r'REQ-[A-Z]+-\d+', requirement)
    final_req_id = req_match.group(0) if req_match else (req_id if req_id else "REQ-001")
    req_desc = requirement[:50] + "..." if len(requirement) > 50 else requirement

    for i in range(pos_n):
        title = f"{requirement[:30]} - 正向 {i+1}"
        desc = f"验证正常流程 {i+1}"
        steps = "步骤1：初始化；步骤2：执行；步骤3：验证"
        expect = "功能按预期；无错误"
        trace = f"验证 {final_req_id} 正向功能 {i+1}"
        rows.append(make_row(final_req_id, req_desc, title, desc, "无", steps, expect, trace))
        idx += 1
    for i in range(neg_n):
        title = f"{requirement[:30]} - 异常 {i+1}"
        desc = f"验证异常处理 {i+1}"
        steps = "步骤1：注入异常；步骤2：观察；步骤3：恢复"
        expect = "产生错误码；进入安全模式"
        trace = f"验证 {final_req_id} 异常处理 {i+1}"
        rows.append(make_row(final_req_id, req_desc, title, desc, "注入异常", steps, expect, trace))
        idx += 1
    for i in range(edge_n):
        title = f"{requirement[:30]} - 边界 {i+1}"
        desc = f"验证边界条件 {i+1}"
        steps = "步骤1：设置边界值；步骤2：执行；步骤3：验证"
        expect = "系统在临界值下稳定或按规格处理"
        trace = f"验证 {final_req_id} 边界条件 {i+1}"
        rows.append(make_row(final_req_id, req_desc, title, desc, "无", steps, expect, trace))
        idx += 1

    header = ",".join([f'"{h}"' for h in headers])
    return header + "\n" + "\n".join(rows)



@handle_errors
def call_model(model: str, prompt: str, api_key: str, base_url: str, temperature: float = 0.2, local_model_url: Optional[str] = None, http_proxy: Optional[str] = None, https_proxy: Optional[str] = None, timeout: int = 60) -> str:
    """
    Calls the specified model via HTTP POST request.
    This function handles remote (OpenAI-like & Gemini) and local models.
    """
    # Validate inputs
    if not model:
        raise ValueError("必须指定模型名称")

    if model not in AppConfig.MODEL_MAP and model not in ["local-model", "mock-model", "gemini"]:
        raise ValueError(f"不支持的模型: {model}")

    proxies = {}
    if http_proxy and http_proxy.strip():
        proxies["http"] = http_proxy.strip()
    if https_proxy and https_proxy.strip():
        proxies["https"] = https_proxy.strip()
    elif http_proxy and http_proxy.strip(): # Fallback for https
        proxies["https"] = http_proxy.strip()

    # --- Handle Gemini API ---
    if model == "gemini":
        if not api_key: raise ValueError("Gemini 模型需要 API Key")
        if not base_url: raise ValueError("Gemini 模型需要 API Base URL")

        actual_model = MODEL_MAP.get(model, model)
        url = f"{base_url.rstrip('/')}/v1beta/models/{actual_model}:generateContent?key={api_key}"
        headers = {"Content-Type": "application/json"}
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": temperature}
        }

        for attempt in range(MAX_RETRY_ATTEMPTS):
            try:
                r = requests.post(url, headers=headers, json=payload, timeout=timeout, proxies=proxies if proxies else None)
                r.raise_for_status()
                j = r.json()
                return j['candidates'][0]['content']['parts'][0]['text']
            except requests.exceptions.HTTPError as e:
                # Handle 429 Rate Limit Exceeded with exponential backoff
                if e.response.status_code == 429:
                    if attempt < MAX_RETRY_ATTEMPTS - 1:
                        wait_time = 2 ** (attempt + 1)  # Exponential backoff: 2, 4, 8 seconds
                        logger.warning(f"Gemini API 速率限制。将在 {wait_time} 秒后重试... (尝试 {attempt + 1}/{MAX_RETRY_ATTEMPTS})")
                        st.toast(f"Gemini API 速率限制。将在 {wait_time} 秒后重试...")
                        time.sleep(wait_time)
                        continue  # Continue to the next attempt
                    else:
                        st.error("Gemini API 速率限制过于频繁，请稍后再试或检查您的账户配额。")
                        raise e # Raise on the last attempt
                elif e.response.status_code == 404:
                    error_message = (
                        "Gemini API 返回 404 Not Found 错误。\n"
                        "这通常意味着以下问题之一：\n"
                        "1. **API Base URL 不正确**: 请确保侧边栏中的 URL 是 `https://generativelanguage.googleapis.com`。\n"
                        "2. **API Key 无效或未授权**: 请检查您的 API Key 是否正确，并确保它所属的 Google Cloud 项目已经启用了 'Generative Language API' 或 'Gemini API'。\n"
                        "3. **模型名称不正确**: 确认模型名称 `gemini-1.5-pro-latest` 是否适用于您的 API Key。"
                    )
                    raise ValueError(error_message) from e
                # Re-raise other HTTP errors
                raise e
            except (requests.exceptions.RequestException, KeyError, IndexError) as e:
                logger.warning(f"Gemini 模型调用 (URL: {url}) 第 {attempt+1} 次失败: {e}")
                if attempt == MAX_RETRY_ATTEMPTS - 1:
                    raise e
        raise Exception("Gemini 模型调用失败，已达到最大重试次数")

    # --- Handle local & OpenAI-compatible APIs ---
    if model == "local-model":
        if not local_model_url: raise ValueError("使用 local-model 时需提供 local_model_url")
        url = local_model_url
        headers = {"Content-Type": "application/json"}
        payload = {"prompt": prompt, "temperature": temperature}
    else: # OpenAI-compatible remote models
        if not api_key: raise ValueError("远端模型需要 API Key")
        if not base_url: raise ValueError("远端模型需要 API Base URL")
        url = f"{base_url.rstrip('/')}/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "Connection": "keep-alive"
        }

        # 从AppConfig获取路由头（Mify 网关使用 X-Model-Provider-Id；避免使用 X-Provider 造成路由不一致）
        provider = AppConfig.MODEL_PROVIDER_HEADER.get(model)
        # 兼容旧配置：若 MODEL_PROVIDER_HEADER 仍返回 openai_api_compatible，则映射到 xiaomi
        if provider == "openai_api_compatible":
            provider = "xiaomi"

        actual_model = AppConfig.MODEL_MAP.get(model, model)

        # Add debug logging
        logger.info(f"Calling API endpoint: {url}")
        logger.info(f"Model: {model} (actual: {actual_model})")
        logger.info(f"Headers: {headers}")
        if st.session_state.get("debug_mode"):
            st.write(f"Debug - API Endpoint: {url}")
            st.write(f"Debug - Model: {model} (actual: {actual_model})")
            st.write(f"Debug - Headers: {headers}")
            st.write(f"Debug - Provider: {provider}")
            payload_debug = {
                "model": actual_model,
                "messages": [
                    {"role": "system", "content": "你是测试用例生成助手，严格输出 CSV"},
                    {"role": "user", "content": prompt[:100] + "..." if len(prompt) > 100 else prompt}
                ],
                "temperature": temperature,
            }
            st.write(f"Debug - Payload: {json.dumps(payload_debug, ensure_ascii=False, indent=2)}")
        payload = {
            "model": actual_model,
            "messages": [{"role": "system", "content": "你是测试用例生成助手，严格输出 CSV"}, {"role": "user", "content": prompt}],
            "temperature": temperature,
        }
        # 从MODEL_PROVIDER_HEADER获取路由头
        if provider:
            headers["X-Model-Provider-Id"] = provider
            headers.setdefault("X-Model-Request-Id", str(uuid.uuid4()))

    # Make the request with retries for non-Gemini models
    for attempt in range(AppConfig.MAX_RETRY_ATTEMPTS):
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=120, proxies=proxies if proxies else None)
            r.raise_for_status()
            j = r.json()
            if model == "local-model":
                 return j.get("text") or j.get("output") or j.get("result") or r.text
            else:
                return j['choices'][0]['message']['content']
        except requests.exceptions.HTTPError as e:
            # Handle 429 Rate Limit Exceeded with exponential backoff
            if e.response.status_code == 429:
                if attempt < AppConfig.MAX_RETRY_ATTEMPTS - 1:
                    wait_time = 2 ** (attempt + 1)  # Exponential backoff: 2, 4, 8 seconds
                    logger.warning(f"API 速率限制。将在 {wait_time} 秒后重试... (尝试 {attempt + 1}/{AppConfig.MAX_RETRY_ATTEMPTS})")
                    st.toast(f"API 速率限制。将在 {wait_time} 秒后重试...")
                    time.sleep(wait_time)
                    continue  # Continue to the next attempt
                else:
                    st.error("API 速率限制过于频繁，请稍后再试或检查您的账户配额。")
                    raise e # Raise on the last attempt
            elif e.response.status_code == 400:
                logger.error(f"400 Bad Request. URL: {url}")
                logger.error(f"Payload: {json.dumps(payload, ensure_ascii=False)}")
                logger.error(f"Response: {e.response.text}")
                if st.session_state.get("debug_mode"):
                    st.error(f"400 Bad Request. Response: {e.response.text}")
                    st.json(payload)
                raise e
            # For other HTTP errors, re-raise immediately
            raise e
        except (requests.exceptions.RequestException, KeyError, IndexError) as e:
            logger.warning(f"模型调用 (URL: {url}) 第 {attempt+1} 次失败: {e}")
            if attempt == AppConfig.MAX_RETRY_ATTEMPTS - 1:
                raise e
    raise Exception("模型调用失败，已达到最大重试次数")


@handle_errors
def parse_csv_to_df(csv_text: str, expected_headers: List[str]) -> pd.DataFrame:
    if not csv_text or not csv_text.strip():
        raise ValueError("CSV 内容为空")
    cleaned = csv_text.strip()
    cleaned = re.sub(r"^```.*?\n", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\n```$", "", cleaned)
    cleaned = cleaned.replace("\ufeff", "")
    lines = [l for l in cleaned.splitlines() if l.strip()]
    if not lines:
        raise ValueError("CSV 内容为空（清理后）")

    text = "\n".join(lines)

    # Try to detect delimiter (comma, semicolon, tab, pipe)
    try:
        sniffer = csv.Sniffer()
        dialect = sniffer.sniff(text[:4096], delimiters=",;\t|")
        delimiter = dialect.delimiter
    except Exception:
        delimiter = ','

    # Parse using csv.reader to respect quotes robustly
    reader = csv.reader(StringIO(text), delimiter=delimiter, quotechar='"')
    rows = [r for r in reader if any(cell.strip() for cell in r)]
    if not rows:
        raise ValueError("CSV 内容无法解析为行")

    # helper to normalize rows to a target column count
    def _normalize_rows(rows_list, n_cols, delim):
        normalized = []
        for r in rows_list:
            # strip each cell
            r = [c.strip().strip('"') for c in r]
            if len(r) <= n_cols:
                normalized.append(r + [""] * (n_cols - len(r)))
            else:
                # merge extra columns into the last column to avoid misalignment
                merged_last = delim.join(r[n_cols - 1:])
                normalized.append(r[:n_cols - 1] + [merged_last])
        return normalized

    # Heuristics to determine header row
    header_row = 0
    header = [c.strip().strip('"') for c in rows[0]]
    # if header looks like expected (contains some expected header names), use it
    matches = sum(1 for h in header if any(exp in h or h in exp for exp in expected_headers))
    if matches >= max(1, len(expected_headers) // 2):
        # ensure all data rows match header length
        data_rows = rows[1:]
        if not all(len(r) == len(header) for r in data_rows):
            data_rows = _normalize_rows(data_rows, len(header), delimiter)
        df = pd.DataFrame(data_rows, columns=header)
    else:
        # try to find a header in the first 3 rows
        found = False
        for i in range(0, min(3, len(rows))):
            r = [c.strip().strip('"') for c in rows[i]]
            matches = sum(1 for h in r if any(exp in h or h in exp for exp in expected_headers))
            if matches >= max(1, len(expected_headers) // 2) and len(r) >= 2:
                header_row = i
                data_rows = rows[i+1:]
                if not all(len(rr) == len(r) for rr in data_rows):
                    data_rows = _normalize_rows(data_rows, len(r), delimiter)
                df = pd.DataFrame(data_rows, columns=r)
                found = True
                break
        if not found:
            # If all rows have the same column count as expected, map directly
            if all(len(r) == len(expected_headers) for r in rows):
                df = pd.DataFrame(rows, columns=expected_headers)
            else:
                # Normalize rows to expected column count by merging extra columns into last column
                normalized = _normalize_rows(rows, len(expected_headers), delimiter)
                df = pd.DataFrame(normalized, columns=expected_headers)

    df = df.fillna("").astype(str)
    return df


def make_excel_download(df: pd.DataFrame, filename: str = "测试用例.xlsx") -> None:
    # tolerate None
    if df is None or (hasattr(df, "empty") and df.empty):
        st.warning("没有数据可导出")
        return
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as w:
        df.to_excel(w, index=False, sheet_name='测试用例')
    buf.seek(0)
    st.download_button("💾 下载 Excel", data=buf, file_name=filename, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key=f"dxl_{uuid.uuid4().hex}")


def make_csv_download(df: pd.DataFrame, filename: str = "测试用例.csv") -> None:
    # tolerate None
    if df is None or (hasattr(df, "empty") and df.empty):
        st.warning("没有数据可导出")
        return
    csv = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button("💾 下载 CSV", data=csv, file_name=filename, mime="text/csv", key=f"dcsv_{uuid.uuid4().hex}")


def process_batch_requirements(api_key: str, base_url: str, requirements: List[str], headers: List[str], model: str, pos_n: int, neg_n: int, edge_n: int, temperature: float, local_model_url: Optional[str], http_proxy: Optional[str], https_proxy: Optional[str], background_knowledge: Optional[str] = None) -> pd.DataFrame:
    all_cases = []
    pb = st.progress(0)
    status = st.empty()
    total = len(requirements)
    for i, req in enumerate(requirements):
        pb.progress((i+1)/total)
        status.text(f"处理中 {i+1}/{total}")
        req_id = f"REQ-{i+1:03d}"
        prompt = build_prompt(req, headers, pos_n, neg_n, edge_n, req_id, background_knowledge)
        text = call_model(model, prompt, api_key, base_url, temperature, local_model_url, http_proxy, https_proxy)
        if text:
            df = parse_csv_to_df(text, headers)
            if df is not None and not df.empty:
                # 如果生成的数据中没有需求编号列，则添加
                if "需求编号" not in df.columns:
                    df.insert(0, "需求编号", req_id)
                if "需求描述" not in df.columns:
                    df.insert(1, "需求描述", req[:100])
                all_cases.append(df)

        # Add a delay to avoid hitting rate limits, especially for batch jobs.
        # This helps respect policies like "requests per minute".
        if i < total - 1: # No need to wait after the last item
            time.sleep(0.1) # Wait for 0.1 seconds before the next request

    pb.empty(); status.empty()
    if all_cases:
        return pd.concat(all_cases, ignore_index=True)
    raise ValueError("未生成任何用例")


def setup_sidebar() -> tuple:
    with st.sidebar:
        st.header("连接设置")
        api_key = st.text_input("API Key（可选）", type="password", key="api_key_input")
        model = st.selectbox("模型", AppConfig.ALLOWED_MODELS, key="model_select")

        # auto-select sensible base_url based on model
        if model == "gemini":
            suggested_base = "https://generativelanguage.googleapis.com"
            st.info(f"已为 gemini 建议将 API Base URL 设置为 {suggested_base}（可修改）")
        else:
            suggested_base = AppConfig.DEFAULT_BASE_URL

        base_url = st.text_input("API Base URL", value=suggested_base, key="base_url_input")
        local_model_url = st.text_input("本地模型 URL (http)", placeholder="http://127.0.0.1:8000/v1/generate", key="local_model_url")

        st.divider()
        st.subheader("代理设置 (可选)")
        proxy_mode = st.radio("网络连接方式", ["使用系统代理", "自定义代理", "直接连接（绕过代理）"], key="proxy_mode")

        http_proxy = None
        https_proxy = None

        if proxy_mode == "使用系统代理":
            http_proxy = "http://127.0.0.1:7897"
            https_proxy = "http://127.0.0.1:7897"
            st.info("将使用检测到的系统代理: 127.0.0.1:7897")
        elif proxy_mode == "自定义代理":
            http_proxy = st.text_input("HTTP Proxy", placeholder="http://user:pass@host:port", key="http_proxy_input")
            https_proxy = st.text_input("HTTPS Proxy", placeholder="http://user:pass@host:port", key="https_proxy_input")
        else:  # 直接连接
            st.info("将绕过代理直接连接到 API 服务器")

        temperature = st.slider("Temperature", 0.0, 1.0, 0.2, 0.05, key="temperature_slider")

        st.divider()
        st.header("背景知识 (可选)")
        background_doc = st.file_uploader("上传需求、规格或背景知识文档", type=["docx", "txt", "md"], key="background_doc_uploader")

        # Use a key to avoid re-reading the file on every rerun
        if background_doc:
            if st.session_state.get('last_background_doc_name') != background_doc.name:
                content = read_background_doc(background_doc)
                if content:
                    st.session_state['background_knowledge'] = content
                    st.session_state['last_background_doc_name'] = background_doc.name
                    st.success(f"已加载背景文档: {background_doc.name}")
                else:
                    st.session_state['background_knowledge'] = None
                    st.session_state['last_background_doc_name'] = None
        else:
            # Clear if the file is removed by the user
            if 'background_knowledge' in st.session_state:
                st.session_state['background_knowledge'] = None
            if 'last_background_doc_name' in st.session_state:
                st.session_state['last_background_doc_name'] = None

        if st.session_state.get('background_knowledge'):
            with st.expander("查看已加载的背景知识 (前500字符)"):
                st.text(st.session_state['background_knowledge'][:500] + "...")

        st.divider()

        # initialize session_state for validation tracking
        if 'api_valid' not in st.session_state:
            st.session_state['api_valid'] = False
            st.session_state['api_error'] = ''
            st.session_state['api_key_cached'] = ''

        # reset cached validation when the API key text changes
        if api_key and api_key != st.session_state.get('api_key_cached', ''):
            st.session_state['api_valid'] = False
            st.session_state['api_error'] = ''
            st.session_state['api_key_cached'] = api_key

        # validate API Key button
        if st.button("验证 API Key", key="validate_api_key"):
            if model in ("local-model", "mock-model"):
                st.info("所选为本地模型，无需验证远端 API Key。")
            else:
                if not api_key:
                    st.error("请先在上方输入 API Key 再点击验证")
                else:
                    try:
                        proxies = {}
                        if http_proxy: proxies['http'] = http_proxy
                        if https_proxy: proxies['https'] = https_proxy

                        # Gemini has a different API structure for validation
                        if model == "gemini":
                            actual_model = MODEL_MAP.get(model, model)
                            ping_url = f"{base_url.rstrip('/')}/v1beta/models/{actual_model}?key={api_key}"
                            ping_headers = {"Content-Type": "application/json"}
                            resp = requests.get(ping_url, headers=ping_headers, proxies=proxies if proxies else None, timeout=20)
                        else: # OpenAI-compatible
                            ping_url = f"{base_url.rstrip('/')}/v1/chat/completions"
                            ping_headers = {
                                "Content-Type": "application/json",
                                "Authorization": f"Bearer {api_key}"
                            }
                            actual_model = AppConfig.MODEL_MAP.get(model, model)
                            ping_payload = {
                                "model": actual_model,
                                "messages": [{"role": "user", "content": "ping"}],
                                "max_tokens": 1,
                            }
                            resp = requests.post(
                                ping_url,
                                headers=ping_headers,
                                json=ping_payload,
                                proxies=proxies if proxies else None,
                                timeout=20
                            )

                        resp.raise_for_status() # Will raise an exception for 4xx/5xx status

                        st.success("验证通过：API Key 和网络连接可用")
                        st.session_state['api_valid'] = True
                        st.session_state['api_error'] = ''
                        st.session_state['api_key_cached'] = api_key
                    except requests.exceptions.RequestException as e:
                        logger.warning(f"API Key 验证失败: {e}")
                        error_details = f"请求错误: {e}"
                        if e.response is not None:
                            error_details += f"\n状态码: {e.response.status_code}\n响应: {e.response.text}"

                        st.error(f"认证或连接失败：{error_details}")
                        st.session_state['api_valid'] = False
                        st.session_state['api_error'] = str(e)
                    except Exception as e:
                        logger.warning(f"验证过程中出现意外错误: {e}")
                        st.error(f"验证失败: {e}")
                        st.session_state['api_valid'] = False
                        st.session_state['api_error'] = str(e)

        # clear cached validation and rerun
        if st.button("清除缓存并重置", key="clear_cache"):
            st.session_state['api_valid'] = False
            st.session_state['api_error'] = ''
            st.session_state['api_key_cached'] = ''
            st.experimental_rerun()

        st.divider()
        st.header("用例配置")
        headers_text = st.text_input("列名（逗号分隔）", value=",".join(AppConfig.DEFAULT_HEADERS), key="headers_input")
        headers = [h.strip() for h in headers_text.split(",") if h.strip()]
        pos_n = st.number_input("正向", min_value=1, max_value=20, value=2, key="pos_n_input")
        neg_n = st.number_input("异常", min_value=1, max_value=20, value=2, key="neg_n_input")
        edge_n = st.number_input("边界", min_value=1, max_value=20, value=2, key="edge_n_input")
    return api_key, base_url, model, temperature, headers, pos_n, neg_n, edge_n, local_model_url, http_proxy, https_proxy


def main():
    st.set_page_config(page_title="AI 测试用例生成器 - 电力电子", layout="wide")
    st.title("AI 测试用例生成器（电力电子方向）")
    api_key, base_url, model, temperature, headers, pos_n, neg_n, edge_n, local_model_url, http_proxy, https_proxy = setup_sidebar()
    tab1, tab2, tab3 = st.tabs(["单条需求", "批量处理", "帮助"])

    with tab1:
        st.subheader("单条需求生成")
        templates = get_requirement_templates()
        opts = ["自定义"] + list(templates.keys())
        sel = st.selectbox("模板", opts, key="template_select")
        default = templates.get(sel, "") if sel != "自定义" else ""
        req_text = st.text_area("需求描述", value=default, height=220, key="requirement_text_area")

        # 添加需求编号输入
        req_id = st.text_input("需求编号（可选）", placeholder="例如: REQ-OBC-001", key="req_id_input")

        if st.button("生成", key="gen_single"):
            if model != "local-model" and model != "mock-model" and not api_key:
                st.error("请输入 API Key 或选择 local-model 或 mock-model")
            else:
                prompt = build_prompt(req_text, headers, pos_n, neg_n, edge_n, req_id)
                placeholder = st.empty()
                progress = st.progress(0)
                try:
                    placeholder.info("开始生成，用时取决于所选模型...")
                    progress.progress(10)
                    if model == "mock-model":
                        text = _generate_mock_csv(req_text, headers, pos_n, neg_n, edge_n, req_id)
                        progress.progress(80)
                    else:
                        text = call_model(model, prompt, api_key, base_url, temperature, local_model_url, http_proxy, https_proxy)
                        progress.progress(80)
                    if text:
                        df = parse_csv_to_df(text, headers)
                        progress.progress(95)
                        if df is None or (hasattr(df, "empty") and df.empty):
                            placeholder.error("未能解析为有效的测试用例表格")
                        else:
                            st.dataframe(df, use_container_width=True)
                            make_excel_download(df)
                            make_csv_download(df)
                            progress.progress(100)
                            placeholder.success("生成完成")
                finally:
                    progress.empty()
                    placeholder.empty()

    with tab2:
        st.subheader("批量导入（Excel/Word）")
        uploaded = st.file_uploader("上传文件", type=["xlsx", "docx"], key="file_uploader")
        if uploaded:
            if uploaded.name.lower().endswith('.xlsx'):
                sheets = read_excel(uploaded)
                sheet = st.selectbox("选择表", list(sheets.keys()), key="sheet_select")
                df_sheet = sheets[sheet]
                st.dataframe(df_sheet.head(10))
                col = st.selectbox("需求列", list(df_sheet.columns), key="column_select")
                rows = df_sheet[col].dropna().astype(str).str.strip()
                valid = [r for r in rows if len(r) > AppConfig.MIN_PARAGRAPH_LENGTH]
                st.info(f"找到 {len(valid)} 条有效需求")
                if st.button("批量生成", key="batch_gen") and valid:
                    if model == "mock-model":
                        # generate all locally without remote calls
                        all_dfs = []
                        for i, req in enumerate(valid):
                            req_id = f"REQ-{i+1:03d}"
                            txt = _generate_mock_csv(req, headers, pos_n, neg_n, edge_n, req_id)
                            df = parse_csv_to_df(txt, headers)
                            # mock model已经包含了需求编号和描述列，不需要再添加
                            all_dfs.append(df)
                        df_all = pd.concat(all_dfs, ignore_index=True) if all_dfs else pd.DataFrame()
                    else:
                        df_all = process_batch_requirements(api_key, base_url, valid, headers, model, pos_n, neg_n, edge_n, temperature, local_model_url, http_proxy, https_proxy)
                    st.dataframe(df_all)
                    make_excel_download(df_all, "测试用例_批量.xlsx")
                    make_csv_download(df_all, "测试用例_批量.csv")
            else:
                content = read_word(uploaded)
                parts = re.split(r"\n\s*\n+", content.strip())
                parts = [p for p in parts if len(p.strip()) > AppConfig.MIN_PARAGRAPH_LENGTH]
                st.info(f"识别到 {len(parts)} 段需求")
                if st.button("批量生成(文档)", key="batch_doc") and parts:
                    if model == "mock-model":
                        all_dfs = []
                        for i, req in enumerate(parts):
                            req_id = f"REQ-DOC-{i+1:03d}"
                            txt = _generate_mock_csv(req, headers, pos_n, neg_n, edge_n, req_id)
                            df = parse_csv_to_df(txt, headers)
                            # mock model已经包含了需求编号和描述列，不需要再添加
                            all_dfs.append(df)
                        df_all = pd.concat(all_dfs, ignore_index=True) if all_dfs else pd.DataFrame()
                    else:
                        df_all = process_batch_requirements(api_key, base_url, parts, headers, model, pos_n, neg_n, edge_n, temperature, local_model_url, http_proxy, https_proxy)
                    st.dataframe(df_all)

    with tab3:
        st.subheader("示例与最佳实践")
        st.write("常见示例：")
        for ex in get_requirement_examples():
            st.write(f"- {ex}")


def make_client(api_key: str, base_url: str, http_proxy: Optional[str] = None, https_proxy: Optional[str] = None) -> Any:
    if OpenAI is None:
        raise ImportError("OpenAI package not installed. Please install it with: pip install openai")

    proxies = {}
    if http_proxy:
        proxies["http"] = http_proxy
    if https_proxy:
        proxies["https"] = https_proxy
    elif http_proxy:  # Fallback for https if only http is provided
        proxies["https"] = http_proxy

    import uuid

    base = base_url.rstrip("/")
    if not base.endswith("/v1"):
        base = base + "/v1"

    return OpenAI(
        api_key=api_key,
        base_url=base,
        default_headers={
            "X-Model-Provider-Id": "xiaomi",
            "X-Model-Request-Id": str(uuid.uuid4()),
        },
        http_client=requests.Session(),
        timeout=60.0,
        max_retries=3,
        proxies=proxies if proxies else None,
    )

@handle_errors
def read_background_doc(file: Optional[Any]) -> Optional[str]:
    """Reads content from an uploaded file (docx, txt, md)."""
    if file is None:
        return None

    file_name = file.name.lower()
    if file_name.endswith('.docx'):
        return read_word(file)
    elif file_name.endswith(('.txt', '.md')):
        # For txt, md, read as plain text
        return StringIO(file.getvalue().decode("utf-8")).read()
    else:
        st.warning(f"不支持的文件类型: {file_name}，请上传 .docx, .txt, 或 .md 文件。")
        return None
def get_output_format_template() -> str:
    """返回标准的 CSV 输出格式模板"""
    headers = ["测试名称", "需求编号", "需求描述", "测试描述", "前置条件", "测试步骤", "预期结果", "需求追溯"]
    header_line = ",".join([f'"{h}"' for h in headers])
    example_line = ",".join([f'"{h}示例"' for h in headers])
    return f"{header_line}\n{example_line}"

def get_standard_prompt_template() -> str:
    """返回标准的提示词模板"""
    return (
        "[系统角色]\n"
        "你是资深的OBC/CCU测试开发专家，精通电力电子、车载充电、CAN/CAN-FD协议、硬件交互、诊断与安全。\n\n"
        "[可选背景知识]\n"
        "如有背景知识，请充分结合理解。\n---\n{背景知识}\n---\n\n"
        "[任务]\n"
        "针对'需求描述'，生成 {正向数} 条正向、{异常数} 条异常、{边界数} 条边界测试用例（共 {总用例数} 条），要求如下：\n\n"
        "[CSV 列顺序]\n{列名逗号分隔}\n\n"
        "[生成规则]\n"
        "1. 仅输出原始 CSV 内容，不输出任何解释、代码块或多余文本。\n"
        "2. 测试步骤应细致、可复现，单元格内用全角分号（；）分隔。\n"
        "3. 前置条件为空填'无'，如需特定硬件/线束/环境请明确。\n"
        "4. 输入/参数需具体可执行（如VIN=1234, CAN_ID=0x18FF50E5, 电压=400V, 电流=50A），涉及信号/报文/物理操作要写明。\n"
        "5. 预期结果应包含可观测阈值、时序、诊断码、功率/安全/互锁等判据（如：电流稳定在50A±5%持续10s，或下发BMS故障码0x1234）。\n"
        "6. '需求编号'列填{需求编号}（或自动生成REQ-001/002…）。\n"
        "7. '需求描述'列≤50字，精准概括需求关键点。\n"
        "8. '需求追溯'列写明该用例验证的具体需求点、协议条款或场景。\n"
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

def process_single_requirement(
    req_text: str = "",
    req_id: str = "",
    base_url: str = "",
    model: str = "",
    temperature: float = 0.2,
    headers: List[str] = None,
    pos_n: int = 2,
    neg_n: int = 2,
    edge_n: int = 2,
    auto_mode: bool = False,
    dyn_params: Dict[str, Any] = None,
    api_key: Optional[str] = None,
    local_model_url: Optional[str] = None,
    http_proxy: Optional[str] = None,
    https_proxy: Optional[str] = None,
    background_knowledge: Optional[str] = None
) -> None:
    """处理单条需求生成测试用例"""
    if not req_text.strip():
        st.warning("请输入需求描述")
        return

    try:
        if auto_mode:
            local_pos, local_neg, local_edge = compute_dynamic_case_counts(
                req_text,
                dyn_params.get("min_total", 3),
                dyn_params.get("max_total", 9),
                dyn_params.get("pos_w", 3.0),
                dyn_params.get("neg_w", 2.0),
                dyn_params.get("edge_w", 2.0),
            )
            st.info(f"动态分配 -> 正向:{local_pos} 异常:{local_neg} 边界:{local_edge}")
        else:
            local_pos, local_neg, local_edge = pos_n, neg_n, edge_n

        prompt = build_prompt(
            req_text,
            headers,
            local_pos,
            local_neg,
            local_edge,
            req_id,
            background_knowledge
        )

        text = call_model(
            model=model,
            prompt=prompt,
            api_key=api_key,
            base_url=base_url,
            temperature=temperature,
            local_model_url=local_model_url,
            http_proxy=http_proxy,
            https_proxy=https_proxy
        )

        if text:
            df = parse_csv_to_df(text, headers)
            if df is None or df.empty:
                st.error("解析失败")
            else:
                st.dataframe(df, use_container_width=True)
                make_excel_download(df)
                make_csv_download(df)

    except Exception as e:
        st.error(f"生成失败: {e}")
        if st.session_state.get("debug_mode"):
            st.exception(e)

if __name__ == '__main__':
    main()
