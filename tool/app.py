# app.py - 优化版本
import os
import re
from io import BytesIO, StringIO
from typing import List, Optional, Dict, Any
import logging

import pandas as pd
import streamlit as st
from docx import Document
from openai import OpenAI
from ai_requirement_processor import AIRequirementProcessor, estimate_requirement_complexity
import json

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =========================
# 常量配置
# =========================
DEFAULT_HEADERS = ["测试名称", "测试描述", "前置条件", "测试步骤", "预期结果"]
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"
MAX_RETRY_ATTEMPTS = 3
MIN_PARAGRAPH_LENGTH = 10

# =========================
# 异常处理装饰器
# =========================
def handle_errors(func):
    """错误处理装饰器"""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.error(f"函数 {func.__name__} 执行失败: {e}")
            st.error(f"操作失败: {str(e)}")
            return None
    return wrapper


# =========================
# Helpers: read requirements
# =========================

def identify_requirements_with_ai(full_text: str, filename: str) -> List[str]:
    """使用AI智能识别文档中的需求"""
    try:
        # 检查是否有API配置
        api_key = st.session_state.get('api_key') or os.getenv("DEEPSEEK_API_KEY", "")
        base_url = st.session_state.get('base_url', "https://api.deepseek.com")
        
        if not api_key:
            st.warning("未配置API Key，无法使用AI需求识别")
            return []
        
        # 创建AI客户端
        import uuid
        base = str(base_url or "").rstrip("/")
        if "model.mify.ai.srv" in base and not base.endswith("/v1"):
            base = base + "/v1"
        client = OpenAI(
            api_key=api_key,
            base_url=base,
            default_headers=(
                {
                    "X-Model-Provider-Id": "xiaomi",
                    "X-Model-Request-Id": str(uuid.uuid4()),
                }
                if "model.mify.ai.srv" in base
                else None
            ),
        )
        
        # 构建提示词
        prompt = f"""请从以下文档内容中识别出所有的软件需求。文档内容：
        
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
            model=st.session_state.get('model', 'deepseek-chat'),
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
        logger.error(f"AI需求识别失败 ({filename}): {e}")
        st.warning(f"AI需求识别失败: {str(e)}")
        return []
def read_word(file) -> str:
    """读取Word文档内容"""
    try:
        doc = Document(file)
        paras = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]
        content = "\n".join(paras)
        return content
    except Exception as e:
        logging.error(f"读取Word文档失败: {e}")
        raise ValueError(f"无法读取Word文档: {e}")

def split_word_requirements(content: str, mode: str = "by_blank_line") -> List[str]:
    """按指定模式分割需求文本"""
    if not content or not content.strip():
        return []

    if mode == "single":
        return [content.strip()]

    # 按连续空行分段
    blocks = re.split(r"\n\s*\n+", content.strip())
    # 过滤太短的段落（少于10个字符的段落可能无意义）
    return [b.strip() for b in blocks if len(b.strip()) > 10]

def read_excel(uploaded_file) -> dict:
    """读取Excel文件，返回所有sheet的数据"""
    try:
        xl = pd.ExcelFile(uploaded_file)
        sheets = {}
        for sheet in xl.sheet_names:
            df = xl.parse(sheet)
            sheets[sheet] = df
        return sheets
    except Exception as e:
        logging.error(f"读取Excel文件失败: {e}")
        raise ValueError(f"无法读取Excel文件: {e}")


# =========================
# DeepSeek client factory
# =========================
@st.cache_resource(show_spinner=False)
def make_client(api_key: str, base_url: str) -> OpenAI:
    """创建OpenAI客户端，带缓存"""
    if not api_key:
        raise ValueError("API Key 不能为空")

    import uuid

    base = str(base_url or "").rstrip("/")
    if "model.mify.ai.srv" in base and not base.endswith("/v1"):
        base = base + "/v1"

    return OpenAI(
        api_key=api_key,
        base_url=base,
        default_headers=(
            {
                "X-Model-Provider-Id": "xiaomi",
                "X-Model-Request-Id": str(uuid.uuid4()),
            }
            if "model.mify.ai.srv" in base
            else None
        ),
    )


# =========================
# Prompt builder
# =========================
def build_prompt(requirement: str, headers: list[str], pos_n: int, neg_n: int, edge_n: int):
    cols_line = ",".join(headers)
    guidance = f"""
你是一名资深测试工程师。请基于以下功能需求，生成高质量测试用例，覆盖正向（{pos_n} 条）、异常（{neg_n} 条）、边界（{edge_n} 条）。
输出必须是严格的 CSV，第一行是表头，表头列名严格为：
{cols_line}

约束：
- 仅输出 CSV 数据，不要包含多余说明、代码块标记或空行。
- “测试步骤”用“；”在同一单元格内串联步骤，避免换行。
- 无可用前置条件时填“无”。
- 用词简洁、可执行、可复现，避免含糊描述。
- 不要使用英文逗号以外的分隔符；中文内容可以包含逗号，但整体仍以英文逗号分列。
"""
    return f"{guidance}\n功能需求：\n{requirement}\n"


# =========================
# Call DeepSeek chat
# =========================
def call_deepseek(client: OpenAI, model: str, prompt: str, temperature: float = 0.2):
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "你是专业的软件测试用例生成助手，只输出干净的CSV数据。"},
            {"role": "user", "content": prompt},
        ],
        temperature=temperature,
    )
    return resp.choices[0].message.content


# =========================
# Parse CSV safely
# =========================
def parse_csv_to_df(csv_text: str, expected_headers: list[str]) -> pd.DataFrame:
    # 去除可能的代码块围栏和 BOM
    cleaned = csv_text.strip()
    cleaned = re.sub(r"^```.*?\n", "", cleaned)
    cleaned = re.sub(r"\n```$", "", cleaned)
    cleaned = cleaned.replace("\ufeff", "")

    # 直接尝试解析
    try:
        df = pd.read_csv(StringIO(cleaned))
        # 如果模型未输出表头，尝试补齐
        if list(df.columns) != expected_headers and df.shape[1] == len(expected_headers):
            df.columns = expected_headers
        return df
    except Exception:
        # 退化解析：按行切分，再按逗号切分
        lines = [ln for ln in cleaned.splitlines() if ln.strip()]
        # 若首行不是指定表头，则插入期望表头
        if lines and ",".join(expected_headers) not in lines[0]:
            lines.insert(0, ",".join(expected_headers))
        try:
            df = pd.read_csv(StringIO("\n".join(lines)))
            return df
        except Exception as e:
            raise ValueError(f"CSV 解析失败：{e}\n原始输出：\n{csv_text}")


# =========================
# Export helpers
# =========================
def make_excel_download(df: pd.DataFrame, filename="测试用例.xlsx"):
    buf = BytesIO()
    df.to_excel(buf, index=False)
    buf.seek(0)
    st.download_button(
        "💾 下载 Excel",
        data=buf,
        file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

def make_csv_download(df: pd.DataFrame, filename="测试用例.csv"):
    csv = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "💾 下载 CSV",
        data=csv,
        file_name=filename,
        mime="text/csv",
    )


# =========================
# UI
# =========================
st.set_page_config(page_title="AI 测试用例生成器（DeepSeek）", layout="wide")
st.title("🤖 AI 自动生成测试用例（DeepSeek 版）")

with st.sidebar:
    st.header("连接设置")
    # API Key 优先级：侧边栏输入 > secrets > 环境变量
    api_key_input = st.text_input("DeepSeek API Key", type="password", help="建议使用环境变量或 Streamlit Secrets，更安全")
    # api_key = api_key_input or st.secrets.get("DEEPSEEK_API_KEY", "") or os.getenv("DEEPSEEK_API_KEY", "")
    api_key = api_key_input or os.getenv("DEEPSEEK_API_KEY", "")

    base_url = st.text_input("API Base URL", value="https://api.deepseek.com")
    model = st.selectbox("模型", ["deepseek-chat", "deepseek-reasoner"], index=0)
    temperature = st.slider("Temperature", 0.0, 1.0, 0.2, 0.05)

    st.divider()
    st.header("网络代理（可选）")
    proxy = st.text_input("HTTP/HTTPS 代理，例如 http://127.0.0.1:7890", value="")
    if proxy:
        os.environ["http_proxy"] = proxy
        os.environ["https_proxy"] = proxy
        st.caption("已设置代理环境变量 http_proxy / https_proxy")

    st.divider()
    st.header("用例列设置")
    default_headers = ["测试名称", "测试描述", "前置条件", "测试步骤", "预期结果"]
    headers_text = st.text_input("逗号分隔的列名", value=",".join(default_headers))
    headers = [h.strip() for h in headers_text.split(",") if h.strip()]
    if not headers:
        st.warning("列名不能为空，将回退为默认列")
        headers = default_headers

    st.divider()
    st.header("每类用例数量")
    pos_n = st.number_input("正向用例数", min_value=1, max_value=20, value=2, step=1)
    neg_n = st.number_input("异常用例数", min_value=1, max_value=20, value=2, step=1)
    edge_n = st.number_input("边界用例数", min_value=1, max_value=20, value=2, step=1)

tab_single, tab_batch = st.tabs(["单条需求", "批量（Excel/Word）"])

# ============ 单条需求 ============
with tab_single:
    st.subheader("单条需求输入")
    requirement_text = st.text_area("请输入功能需求（支持多行）", height=200, placeholder="例如：ccu-dsp 唤醒流程测试……")

    if st.button("🚀 生成测试用例（单条）", type="primary", use_container_width=True):
        if not api_key:
            st.error("请在侧边栏配置 DeepSeek API Key")
        elif not requirement_text.strip():
            st.warning("请输入需求内容")
        else:
            client = make_client(api_key, base_url)
            prompt = build_prompt(requirement_text.strip(), headers, pos_n, neg_n, edge_n)
            with st.spinner("正在生成测试用例……"):
                try:
                    csv_text = call_deepseek(client, model, prompt, temperature)
                    df = parse_csv_to_df(csv_text, headers)
                    st.success(f"生成完成，共 {len(df)} 条。")
                    st.dataframe(df, use_container_width=True, height=360)
                    make_excel_download(df, filename="测试用例_单条.xlsx")
                    make_csv_download(df, filename="测试用例_单条.csv")
                except Exception as e:
                    st.error(f"生成失败：{e}")

# ============ 批量需求 ============
with tab_batch:
    st.subheader("批量需求导入")
    
    # AI需求处理配置
    st.markdown("#### AI需求智能处理")
    col1, col2 = st.columns(2)
    with col1:
        enable_ai_analysis = st.checkbox("启用AI需求分析", value=True, 
                                       help="使用AI自动识别需求类型、优先级和复杂度")
    with col2:
        enable_ai_decomposition = st.checkbox("启用AI需求分解", value=True,
                                            help="自动将复杂需求分解为可测试的子需求")
    
    uploaded = st.file_uploader("上传 Excel（.xlsx）或 Word（.docx）", type=["xlsx", "docx"])

    if uploaded:
        if uploaded.name.lower().endswith(".xlsx"):
            sheets = read_excel(uploaded)
            sheet_name = st.selectbox("选择工作表", list(sheets.keys()))
            df_sheet = sheets[sheet_name]
            st.write("预览（前 10 行）")
            st.dataframe(df_sheet.head(10), use_container_width=True)

            col = st.selectbox("选择需求列", list(df_sheet.columns))
            batch_rows = df_sheet[col].dropna().astype(str).str.strip()
            st.caption(f"已收集有效需求 {batch_rows.shape[0]} 条")

            # AI需求分析按钮
            if enable_ai_analysis and api_key and not batch_rows.empty:
                if st.button("🔍 执行AI需求分析", type="secondary"):
                    with st.spinner("正在执行AI需求分析..."):
                        try:
                            # 创建AI处理器
                            ai_processor = AIRequirementProcessor(
                                client=make_client(api_key, base_url),
                                model=model,
                                temperature=temperature
                            )
                            
                            # 执行AI分析
                            req_texts = batch_rows.tolist()
                            processed_reqs = ai_processor.process_batch_requirements(req_texts)
                            
                            # 显示分析结果
                            analysis_df = pd.DataFrame([{
                                "原始需求": req["original_requirement"],
                                "处理需求": req["sub_requirement"],
                                "类型": req["type"],
                                "优先级": req["priority"],
                                "复杂度": req["complexity"],
                                "是否分解": "是" if req["is_decomposed"] else "否"
                            } for req in processed_reqs])
                            
                            st.success(f"AI分析完成！共分析 {len(processed_reqs)} 条需求")
                            st.dataframe(analysis_df, use_container_width=True)
                            
                            # 更新需求列表为处理后的需求
                            processed_req_texts = [req["sub_requirement"] for req in processed_reqs]
                            batch_rows = pd.Series(processed_req_texts)
                            
                        except Exception as e:
                            st.error(f"AI需求分析失败: {str(e)}")
            
            if st.button("🚀 生成测试用例（批量）", type="primary", use_container_width=True):
                if not api_key:
                    st.error("请在侧边栏配置 DeepSeek API Key")
                elif batch_rows.empty:
                    st.warning("未检索到需求文本")
                else:
                    client = make_client(api_key, base_url)
                    all_cases = []
                    with st.spinner("批量生成中，请稍候……"):
                        
                        # 如果启用了AI分解，对复杂需求进行分解
                        req_list = batch_rows.tolist()
                        if enable_ai_decomposition:
                            try:
                                ai_processor = AIRequirementProcessor(
                                    client=client,
                                    model=model,
                                    temperature=temperature
                                )
                                
                                decomposed_reqs = []
                                for req_text in req_list:
                                    complexity = estimate_requirement_complexity(req_text)
                                    if complexity == "高":
                                        sub_reqs = ai_processor.decompose_requirement(req_text)
                                        for sub_req in sub_reqs:
                                            decomposed_reqs.append(sub_req["sub_requirement"])
                                    else:
                                        decomposed_reqs.append(req_text)
                                
                                req_list = decomposed_reqs
                                st.info(f"AI分解后共 {len(req_list)} 条可测试需求")
                                
                            except Exception as e:
                                st.warning(f"AI需求分解失败，使用原始需求: {str(e)}")
                        
                        for idx, req in enumerate(req_list, start=1):
                            prompt = build_prompt(req, headers, pos_n, neg_n, edge_n)
                            try:
                                csv_text = call_deepseek(client, model, prompt, temperature)
                                df_one = parse_csv_to_df(csv_text, headers)
                                df_one.insert(0, "需求", req)
                                all_cases.append(df_one)
                            except Exception as e:
                                st.warning(f"第 {idx} 条需求生成失败：{e}")
                        if all_cases:
                            df_all = pd.concat(all_cases, ignore_index=True)
                            st.success(f"批量完成，共 {len(df_all)} 条用例（{len(all_cases)} 条需求成功生成）")
                            st.dataframe(df_all.head(200), use_container_width=True, height=360)
                            make_excel_download(df_all, filename="测试用例_批量.xlsx")
                            make_csv_download(df_all, filename="测试用例_批量.csv")
                        else:
                            st.error("未生成任何用例，请检查需求或重试。")

        elif uploaded.name.lower().endswith(".docx"):
            content = read_word(uploaded)
            
            if enable_ai_analysis:
                st.info("使用AI智能识别Word文档中的需求...")
                # 使用AI智能识别需求
                ai_reqs = identify_requirements_with_ai(content, uploaded.name)
                if ai_reqs:
                    reqs = ai_reqs
                    st.success(f"AI智能识别出 {len(reqs)} 条需求")
                else:
                    # AI识别失败，使用传统方法
                    split_mode = st.radio("Word 分段方式", ["按空行分段", "整篇作为一条需求"], horizontal=True)
                    reqs = split_word_requirements(content, mode="by_blank_line" if split_mode == "按空行分段" else "single")
                    st.info(f"传统方法识别出 {len(reqs)} 条需求")
            else:
                # 不使用AI，使用传统方法
                split_mode = st.radio("Word 分段方式", ["按空行分段", "整篇作为一条需求"], horizontal=True)
                reqs = split_word_requirements(content, mode="by_blank_line" if split_mode == "按空行分段" else "single")
                st.info(f"识别出 {len(reqs)} 条需求")
            
            st.caption(f"已识别需求段落 {len(reqs)} 条")
            if len(reqs) > 0:
                st.text_area("段落预览", value="\n\n".join(reqs[:5]), height=200)

            # AI需求分析按钮
            if enable_ai_analysis and api_key and reqs:
                if st.button("🔍 执行AI需求分析", type="secondary"):
                    with st.spinner("正在执行AI需求分析..."):
                        try:
                            # 创建AI处理器
                            ai_processor = AIRequirementProcessor(
                                client=make_client(api_key, base_url),
                                model=model,
                                temperature=temperature
                            )
                            
                            # 执行AI分析
                            processed_reqs = ai_processor.process_batch_requirements(reqs)
                            
                            # 显示分析结果
                            analysis_df = pd.DataFrame([{
                                "原始需求": req["original_requirement"],
                                "处理需求": req["sub_requirement"],
                                "类型": req["type"],
                                "优先级": req["priority"],
                                "复杂度": req["complexity"],
                                "是否分解": "是" if req["is_decomposed"] else "否"
                            } for req in processed_reqs])
                            
                            st.success(f"AI分析完成！共分析 {len(processed_reqs)} 条需求")
                            st.dataframe(analysis_df, use_container_width=True)
                            
                            # 更新需求列表为处理后的需求
                            reqs = [req["sub_requirement"] for req in processed_reqs]
                            
                        except Exception as e:
                            st.error(f"AI需求分析失败: {str(e)}")
            
            if st.button("🚀 生成测试用例（批量）", type="primary", use_container_width=True):
                if not api_key:
                    st.error("请在侧边栏配置 DeepSeek API Key")
                elif not reqs:
                    st.warning("未识别到有效需求内容")
                else:
                    client = make_client(api_key, base_url)
                    all_cases = []
                    with st.spinner("批量生成中，请稍候……"):
                        
                        # 如果启用了AI分解，对复杂需求进行分解
                        req_list = reqs
                        if enable_ai_decomposition:
                            try:
                                ai_processor = AIRequirementProcessor(
                                    client=client,
                                    model=model,
                                    temperature=temperature
                                )
                                
                                decomposed_reqs = []
                                for req_text in req_list:
                                    complexity = estimate_requirement_complexity(req_text)
                                    if complexity == "高":
                                        sub_reqs = ai_processor.decompose_requirement(req_text)
                                        for sub_req in sub_reqs:
                                            decomposed_reqs.append(sub_req["sub_requirement"])
                                    else:
                                        decomposed_reqs.append(req_text)
                                
                                req_list = decomposed_reqs
                                st.info(f"AI分解后共 {len(req_list)} 条可测试需求")
                                
                            except Exception as e:
                                st.warning(f"AI需求分解失败，使用原始需求: {str(e)}")
                        
                        for idx, req in enumerate(req_list, start=1):
                            prompt = build_prompt(req, headers, pos_n, neg_n, edge_n)
                            try:
                                csv_text = call_deepseek(client, model, prompt, temperature)
                                df_one = parse_csv_to_df(csv_text, headers)
                                df_one.insert(0, "需求", req)
                                all_cases.append(df_one)
                            except Exception as e:
                                st.warning(f"第 {idx} 条需求生成失败：{e}")
                        if all_cases:
                            df_all = pd.concat(all_cases, ignore_index=True)
                            st.success(f"批量完成，共 {len(df_all)} 条用例（{len(all_cases)} 段需求成功生成）")
                            st.dataframe(df_all.head(200), use_container_width=True, height=360)
                            make_excel_download(df_all, filename="测试用例_批量.xlsx")
                            make_csv_download(df_all, filename="测试用例_批量.csv")
                        else:
                            st.error("未生成任何用例，请检查文档或重试。")
    else:
        st.info("请上传 Excel 或 Word 文件以开始批量生成。")


# =========================
# Footer tips
# =========================
st.divider()
st.caption("提示：若遇到网络/连接问题，可在侧边栏设置代理；建议把 API Key 配置为环境变量或 Streamlit Secrets，避免泄露。")
