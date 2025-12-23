"""UI辅助函数模块"""

import logging
from collections import deque
from typing import Any, Dict, List, Optional, Set

import pandas as pd
import streamlit as st
from docx import Document
from io import BytesIO, StringIO
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
            if re.search(r"/(?:docx|wiki|docs|sheets)/[A-Za-z0-9]+", url):
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
        r = requests.get(url, timeout=min(timeout, 15), headers={"User-Agent": "TestCaseGenBot/1.0"})
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
    # 优先尝试使用独立的 feishu_fetcher.py 脚本，因为它经过验证更稳定
    try:
        import subprocess
        import sys

        fetcher_path = os.path.join(os.path.dirname(__file__), "feishu_fetcher.py")
        if os.path.exists(fetcher_path):
            if debug:
                print(f"[DEBUG] Invoking subprocess: {fetcher_path} {url_or_id}")

            # 确保环境变量传递给子进程，并强制使用 UTF-8
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"

            command = [sys.executable, fetcher_path, url_or_id]
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='ignore',
                env=env
            )
            stdout, stderr = process.communicate(timeout=300)

            if debug and stderr:
                print(f"[DEBUG] Subprocess stderr: {stderr}")

            if process.returncode == 0:
                content = stdout.strip()
                if content:
                    return content
                else:
                    return "【飞书API错误】获取到的文档内容为空"
            else:
                error_msg = stderr.strip() if stderr else "未知错误"
                return f"【飞书API错误】子进程执行失败 (Code {process.returncode}): {error_msg}"

    except Exception as e:
        return f"【飞书API错误】子进程调用异常: {str(e)}"

    # 如果代码执行到这里，说明 fetcher_path 不存在
    return "【飞书API错误】找不到 feishu_fetcher.py 脚本"

def process_requirements_from_text(text: str, min_length: int = 5) -> List[str]:
    """Extract requirements from text content."""
    if not text or not text.strip():
        return []

    # 0. 优先策略：基于层级结构的逐行扫描
    # 这种方法能准确识别模块（大标题）和需求（带ID的标题），并将模块信息关联到需求中
    # 同时能有效剔除不属于当前需求的大标题（作为分割点）

    lines = text.split('\n')
    reqs = []
    current_module = ""
    current_req_lines = []

    req_id_pattern = re.compile(r"(?:SR\d+|REQ-[\w-]+)", re.IGNORECASE)
    # 匹配 Markdown 标题 (# ...)
    header_pattern = re.compile(r"^#{1,6}\s+(.*)")

    has_structured_content = False

    for line in lines:
        stripped = line.strip()
        header_match = header_pattern.match(stripped)

        if header_match:
            has_structured_content = True
            title_content = header_match.group(1)
            has_id = req_id_pattern.search(title_content)

            if has_id:
                # 是需求标题 -> 新需求开始
                # 1. 保存上一个需求
                if current_req_lines:
                    reqs.append("\n".join(current_req_lines))
                    current_req_lines = []

                # 2. 开始新需求
                # 将当前模块名作为前缀加入，满足“放到对应的子目录下”的需求
                if current_module:
                    # 使用特殊格式标记模块，方便后续处理或阅读
                    current_req_lines.append(f"【模块：{current_module}】 {stripped}")
                else:
                    current_req_lines.append(stripped)
            else:
                # 是目录标题 -> 模块切换，且是上一个需求的结束
                # 1. 保存上一个需求
                if current_req_lines:
                    reqs.append("\n".join(current_req_lines))
                    current_req_lines = []

                # 2. 更新当前模块
                current_module = title_content.strip()
        else:
            # 普通行，归属于当前需求（如果有的话）
            if current_req_lines:
                current_req_lines.append(line)

    # 保存最后一个需求
    if current_req_lines:
        reqs.append("\n".join(current_req_lines))

    # 如果成功提取到了需求，直接返回
    if reqs and has_structured_content:
        # 再次过滤过短的条目
        valid_reqs = [r for r in reqs if len(r.strip()) > min_length]
        if valid_reqs:
            return valid_reqs

    # 2. 回退到按双换行符分割 (标准段落)
    parts = re.split(r"\n\s*\n+", text.strip())
    reqs = [p.strip() for p in parts if len(p.strip()) > min_length]
    if len(reqs) > 0:
        return reqs

    # 3. 最后尝试按单换行符分割 (针对紧凑格式)
    parts = text.strip().split("\n")
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

    def _parse_req(source, content):
        # 尝试提取需求编号 (SRxxxx, REQ-xxx)
        req_id = ""
        match = re.search(r"(SR\d+|REQ-[\w-]+)", content, re.IGNORECASE)
        if match:
            req_id = match.group(1)

        # 尝试提取标题 (第一行，去除 #)
        lines = content.strip().split('\n')
        title = lines[0].strip().lstrip('#').strip()
        if len(title) > 50:
            title = title[:50] + "..."

        return {
            '来源': source,
            '需求编号': req_id,
            '需求标题': title,
            '需求详情': content  # 保留完整内容
        }

    # From Feishu
    if 'feishu_reqs' in st.session_state:
        all_reqs.extend([_parse_req('飞书文档', r)
                        for r in st.session_state['feishu_reqs']])

    # From files
    for k in st.session_state:
        if k.startswith('file_reqs_'):
            source = k.replace('file_reqs_', '')
            all_reqs.extend([_parse_req(source, r)
                           for r in st.session_state[k]])

    # From manual input
    if 'manual_reqs' in st.session_state:
        all_reqs.extend([_parse_req('手动输入', r)
                        for r in st.session_state['manual_reqs']])

    if all_reqs:
        df = pd.DataFrame(all_reqs)
        # 调整列顺序
        cols = ['来源', '需求编号', '需求标题', '需求详情']
        # 确保所有列都存在
        for c in cols:
            if c not in df.columns:
                df[c] = ""
        df = df[cols]

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