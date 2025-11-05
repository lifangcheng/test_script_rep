"""UI辅助函数模块"""

import pandas as pd
import streamlit as st
from docx import Document
from io import BytesIO, StringIO
from typing import Dict, List, Optional, Any
import re
import PyPDF2
import requests
from urllib.parse import urlparse
import time
import json
import os

# Constants
MIN_PARAGRAPH_LENGTH = 10  # 最小段落长度
MAX_CHARS = 12000  # URL抓取最大字符数

def _is_valid_url(u: str) -> bool:
    """Check if a string is a valid URL."""
    try:
        p = urlparse(u.strip())
        return p.scheme in ("http", "https") and bool(p.netloc)
    except Exception:
        return False

def fetch_url_content(url: str, timeout: int = 10, max_chars: int = MAX_CHARS) -> str:
    """Fetch webpage text content with special handling for Feishu docs."""
    try:
        # Special handling for Feishu/Lark docs
        if 'feishu.cn' in url or 'larksuite' in url:
            if re.search(r"/(?:docx|wiki|docs)/[A-Za-z0-9]+", url):
                try:
                    content = fetch_feishu_document(url, debug=st.session_state.get("debug_mode", False))
                    if content and not content.startswith("【飞书API错误】"):
                        if len(content) > max_chars:
                            content = content[:max_chars] + "...【截断】"
                        return content
                except Exception as e:
                    if st.session_state.get("debug_mode"):
                        print(f"[DEBUG] Feishu API failed, fallback to web: {e}")
                    st.warning(f"飞书API访问失败: {str(e)}，尝试网页抓取方式")

        # Regular webpage handling 
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "TestCaseGenBot/1.0"})
        if r.status_code != 200:
            return f"【失败 {r.status_code}】{url}"
        text = r.text
        # Simple tag removal
        text = re.sub(r"<script[\s\S]*?</script>", "", text, flags=re.IGNORECASE)
        text = re.sub(r"<style[\s\S]*?</style>", "", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "\n", text)
        text = re.sub(r"\n{2,}", "\n", text)
        text = text.strip()
        if len(text) > max_chars:
            text = text[:max_chars] + "...【截断】"
        # Special handling for short content from Feishu
        if len(text) < 120 and ('feishu.cn' in url or 'larksuite' in url):
            return ("【飞书文档需登录或未开放，建议：1) 在飞书中导出为 docx 后上传；" \
                    "2) 或提供开放接口 Token 后走 API 抓取】" + url)
        if len(text) < 50:
            return f"【内容过短或无法提取】{url}"
        return text
    except Exception as e:
        return f"【异常: {e.__class__.__name__}】{url}"

def read_word(file: BytesIO) -> str:
    """Read content from a Word document."""
    doc = Document(file)
    paras = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]
    content = "\n".join(paras)
    if not content.strip():
        raise ValueError("Word 文档为空")
    return content

def read_excel(uploaded_file: BytesIO) -> Dict[str, pd.DataFrame]:
    """Read content from an Excel file."""
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

def read_pdf(file: BytesIO) -> str:
    """Read content from a PDF file."""
    pdf_reader = PyPDF2.PdfReader(file)
    text_parts = []
    for page in pdf_reader.pages:
        text = page.extract_text()
        if text.strip():
            text_parts.append(text.strip())
    return "\n\n".join(text_parts)

def read_background_doc(file: Optional[BytesIO]) -> Optional[str]:
    """Read content from various document formats."""
    if file is None:
        return None
    name = file.name.lower()
    if name.endswith('.docx'):
        return read_word(file)
    if name.endswith(('.txt', '.md')):
        return StringIO(file.getvalue().decode("utf-8")).read()
    if name.endswith('.pdf'):
        try:
            return read_pdf(BytesIO(file.getvalue()))
        except Exception as e:
            st.error(f"PDF读取失败: {e}")
            return None
    st.warning("不支持的文件类型，请使用 .docx, .txt, .md 或 .pdf")
    return None

def fetch_feishu_document(url_or_id: str, debug: bool = False) -> str:
    """Get Feishu document content via API and convert to markdown.

    Args:
        url_or_id: Document URL or ID
        debug: Enable debug mode for more verbose output

    Returns:
        Document content as markdown string
    """
    try:
        # Hardcoded credentials for testing
        app_id = "cli_a85ffa34d3fad00c"
        app_secret = "MxD6ukGa9ZMJeGl5KicVSgNQLhnE1tcN"

        if not app_id or not app_secret:
            return "【飞书API错误】缺少FEISHU_APP_ID或FEISHU_APP_SECRET环境变量"

        # Extract doc ID from URL
        doc_input = url_or_id.strip()
        m = re.search(r"/(?:docx|wiki|docs)/([A-Za-z0-9]+)", doc_input)
        doc_id = m.group(1) if m else doc_input

        # Get access token
        FEISHU_BASE_API = os.environ.get("FEISHU_OPEN_BASE", "https://open.feishu.cn")
        token_endpoint = f"{FEISHU_BASE_API}/open-apis/auth/v3/tenant_access_token/internal"
        payload = {"app_id": app_id, "app_secret": app_secret}
        resp = requests.post(token_endpoint, json=payload, timeout=10)
        if resp.status_code != 200:
            return f"【飞书API错误】获取token失败: HTTP {resp.status_code}"
        token_data = resp.json()
        if token_data.get("code") != 0:
            return f"【飞书API错误】获取token失败: {token_data.get('msg')}"
        token = token_data["tenant_access_token"]

        # Check if wiki document
        is_wiki = "/wiki/" in doc_input
        if is_wiki and debug:
            print(f"[DEBUG] Wiki document detected, using token as doc ID: {doc_id}")

        # Get document content
        doc_endpoint = f"{FEISHU_BASE_API}/open-apis/docx/v1/documents/{doc_id}"
        blocks_endpoint = f"{FEISHU_BASE_API}/open-apis/docx/v1/documents/{doc_id}/blocks"
        headers = {"Authorization": f"Bearer {token}"}

        # Get root block
        resp = requests.get(doc_endpoint, headers=headers, timeout=10)
        if resp.status_code != 200:
            return f"【飞书API错误】获取文档失败: HTTP {resp.status_code}"
        doc_data = resp.json()
        if doc_data.get("code") != 0:
            return f"【飞书API错误】获取文档失败: {doc_data.get('msg')}"

        # Get all blocks
        all_text = []
        page_token = ""
        while True:
            url = f"{blocks_endpoint}?page_size=50&page_token={page_token}"
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code != 200:
                return f"【飞书API错误】获取文档块失败: HTTP {resp.status_code}"
            blocks_data = resp.json()
            if blocks_data.get("code") != 0:
                return f"【飞书API错误】获取文档块失败: {blocks_data.get('msg')}"

            for block in blocks_data.get("data", {}).get("items", []):
                text = ""
                if "page" in block:
                    # Page block - title and body
                    text = block["page"].get("title", "")
                    if text:
                        all_text.append(f"# {text}")
                    for para in block["page"].get("body", {}).get("blocks", []):
                        if "text" in para:
                            text = para["text"].get("content", "").strip()
                            if text:
                                all_text.append(text)
                elif "text" in block:
                    # Text block
                    text = block["text"].get("content", "").strip()
                    if text:
                        all_text.append(text)

            page_token = blocks_data.get("data", {}).get("page_token")
            if not page_token:
                break

        content = "\n\n".join(all_text)
        if not content.strip():
            return "【飞书API错误】未获取到有效内容"
        return content

    except Exception as e:
        return f"【飞书API错误】{str(e)}"

def process_requirements_from_text(text: str, min_length: int = MIN_PARAGRAPH_LENGTH) -> List[str]:
    """Extract requirements from text content."""
    if not text or not text.strip():
        return []
    parts = re.split(r"\n\s*\n+", text.strip())
    return [p.strip() for p in parts if len(p.strip()) > min_length]

def process_uploaded_files(files: List[BytesIO], min_length: int = MIN_PARAGRAPH_LENGTH) -> Dict[str, List[str]]:
    """Process uploaded files and extract requirements."""
    requirements = {}
    for file in files:
        try:
            lname = file.name.lower()
            with st.spinner(f"正在处理 {file.name}..."):
                if lname.endswith('.xlsx'):
                    sheets = read_excel(file)
                    if 'Sheet1' in sheets:  # Assuming requirements are in Sheet1
                        df = sheets['Sheet1']
                        if '需求描述' in df.columns:
                            reqs = df['需求描述'].dropna().tolist()
                            if reqs:
                                requirements[f"Excel-{file.name}"] = [r for r in reqs if len(str(r).strip()) > min_length]
                elif lname.endswith('.docx'):
                    content = read_word(file)
                    if content:
                        reqs = process_requirements_from_text(content, min_length)
                        if reqs:
                            requirements[f"Word-{file.name}"] = reqs
                elif lname.endswith('.pdf'):
                    content = read_pdf(BytesIO(file.getvalue()))
                    if content:
                        reqs = process_requirements_from_text(content, min_length)
                        if reqs:
                            requirements[f"PDF-{file.name}"] = reqs
                elif lname.endswith(('.txt', '.csv')):
                    content = StringIO(file.getvalue().decode("utf-8")).read()
                    if content:
                        reqs = process_requirements_from_text(content, min_length)
                        if reqs:
                            requirements[f"Text-{file.name}"] = reqs
        except Exception as e:
            st.error(f"处理文件 {file.name} 失败: {e}")
            continue
    return requirements

def render_batch_input() -> None:
    """Render batch input interface."""
    st.markdown("### 需求输入方式")
    
    # 1. Feishu document
    st.subheader("方式1: 飞书文档")
    feishu_doc = st.text_input("输入飞书文档链接或ID")
    if feishu_doc and st.button("读取飞书文档"):
        try:
            with st.spinner("正在读取文档..."):
                content = fetch_feishu_document(feishu_doc)
                if content and not content.startswith("【飞书API错误】"):
                    reqs = process_requirements_from_text(content)
                    if reqs:
                        st.session_state['feishu_reqs'] = reqs
                        st.success(f"已读取 {len(reqs)} 条需求")
                        st.session_state['source_counts'].append(f"飞书文档:{len(reqs)}")
                    else:
                        st.warning("未找到有效需求")
                else:
                    st.error(content)
        except Exception as e:
            st.error(f"读取失败: {e}")
    
    # 2. File upload
    st.subheader("方式2: 文件上传")
    files = st.file_uploader("支持 Excel, Word, PDF, TXT", 
                            type=['xlsx', 'docx', 'pdf', 'txt'],
                            accept_multiple_files=True)
    if files:
        reqs_dict = process_uploaded_files(files)
        for source, reqs in reqs_dict.items():
            st.session_state[f'file_reqs_{source}'] = reqs
            st.success(f"从 {source} 读取了 {len(reqs)} 条需求")
            st.session_state['source_counts'].append(f"{source}:{len(reqs)}")
    
    # 3. Manual input
    st.subheader("方式3: 手动输入")
    manual_text = st.text_area("每行一条需求", height=150)
    if manual_text and st.button("添加手动输入"):
        reqs = process_requirements_from_text(manual_text)
        if reqs:
            st.session_state['manual_reqs'] = reqs
            st.success(f"已添加 {len(reqs)} 条需求")
            st.session_state['source_counts'].append(f"手工输入:{len(reqs)}")
        else:
            st.warning("未找到有效需求")

def render_batch_preview() -> None:
    """Render preview of collected requirements."""
    st.markdown("### 需求预览")
    
    # Collect all requirements
    all_reqs = []
    
    # From Feishu
    if 'feishu_reqs' in st.session_state:
        all_reqs.extend([{'来源': '飞书文档', '需求': r} 
                        for r in st.session_state['feishu_reqs']])
    
    # From files
    for k in st.session_state:
        if k.startswith('file_reqs_'):
            source = k.replace('file_reqs_', '')
            all_reqs.extend([{'来源': source, '需求': r} 
                           for r in st.session_state[k]])
    
    # From manual input
    if 'manual_reqs' in st.session_state:
        all_reqs.extend([{'来源': '手动输入', '需求': r} 
                        for r in st.session_state['manual_reqs']])
    
    if all_reqs:
        df = pd.DataFrame(all_reqs)
        st.write(f"总计: {len(df)} 条需求")
        st.dataframe(df, use_container_width=True)
        
        if st.button("清空所有需求"):
            # Clear all requirements
            for k in list(st.session_state.keys()):
                if k in ['feishu_reqs', 'manual_reqs'] or k.startswith('file_reqs_'):
                    del st.session_state[k]
            st.session_state['source_counts'] = []
            st.success("已清空所有需求")
        
        # Show source summary
        if 'source_counts' in st.session_state and st.session_state['source_counts']:
            st.info("来源分布:\n" + "\n".join(st.session_state['source_counts']))
    else:
        st.info("还没有导入任何需求")