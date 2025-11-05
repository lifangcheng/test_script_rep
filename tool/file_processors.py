"""File processing utilities for batch requirement handling"""

import streamlit as st
import pandas as pd
import re
from io import StringIO, BytesIO
from typing import List, Dict, Optional

MIN_PARAGRAPH_LENGTH = 10

def _process_excel_file(file) -> None:
    """Process Excel file for requirements
    
    Args:
        file: Uploaded Excel file
    """
    sheets = pd.read_excel(file, sheet_name=None)
    if sheets:
        df_reqs = []
        for sheet_name, df in sheets.items():
            for col in df.columns:
                rows = df[col].dropna().astype(str).str.strip()
                df_reqs.extend([r for r in rows if len(r.strip()) > MIN_PARAGRAPH_LENGTH])
                
        if df_reqs:
            for req in df_reqs:
                st.session_state.collected_requirements.append({
                    "需求编号": "",
                    "需求描述": req,
                    "来源": f"Excel-{file.name}"
                })
            st.session_state.source_counts.append(f"Excel:{len(df_reqs)}")
            st.success(f"{file.name}: 已导入 {len(df_reqs)} 条需求")

def _process_word_file(file) -> None:
    """Process Word file for requirements
    
    Args:
        file: Uploaded Word file
    """
    from docx import Document
    doc = Document(file)
    reqs = []
    for para in doc.paragraphs:
        text = para.text.strip()
        if len(text) > MIN_PARAGRAPH_LENGTH:
            reqs.append(text)
    
    if reqs:
        for req in reqs:
            st.session_state.collected_requirements.append({
                "需求编号": "",
                "需求描述": req,
                "来源": f"Word-{file.name}"
            })
        st.session_state.source_counts.append(f"Word:{len(reqs)}")
        st.success(f"{file.name}: 已导入 {len(reqs)} 条需求")

def _process_pdf_file(file) -> None:
    """Process PDF file for requirements
    
    Args:
        file: Uploaded PDF file
    """
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(BytesIO(file.getvalue()))
        reqs = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                parts = re.split(r"\n\s*\n+", text.strip())
                reqs.extend([p.strip() for p in parts 
                           if len(p.strip()) > MIN_PARAGRAPH_LENGTH])
        
        if reqs:
            for req in reqs:
                st.session_state.collected_requirements.append({
                    "需求编号": "",
                    "需求描述": req,
                    "来源": f"PDF-{file.name}"
                })
            st.session_state.source_counts.append(f"PDF:{len(reqs)}")
            st.success(f"{file.name}: 已导入 {len(reqs)} 条需求")
            
    except ImportError:
        st.error("处理PDF需要安装PyPDF2库")
        
def _process_text_file(file) -> None:
    """Process text file for requirements
    
    Args:
        file: Uploaded text file
    """
    text = file.getvalue().decode('utf-8')
    lines = [l.strip() for l in text.splitlines() 
             if len(l.strip()) > MIN_PARAGRAPH_LENGTH]
    
    if lines:
        for line in lines:
            st.session_state.collected_requirements.append({
                "需求编号": "",
                "需求描述": line,
                "来源": f"Text-{file.name}"
            })
        st.session_state.source_counts.append(f"Text:{len(lines)}")
        st.success(f"{file.name}: 已导入 {len(lines)} 条需求")