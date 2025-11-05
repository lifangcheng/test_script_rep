"""处理批量导入和预览的函数"""

import streamlit as st
from typing import Dict, Any, List
import pandas as pd
from docx import Document
import PyPDF2
from io import BytesIO, StringIO
import re
from test_batch import BatchProcessor

def handle_batch_input() -> None:
    """处理批量导入需求的输入部分"""
    try:
        st.markdown("### 需求输入")
        
        # 清空按钮
        if st.button("🗑️ 清空所有需求"):
            st.session_state.collected_requirements = []
            st.session_state.source_counts = []
            st.success("已清空所有需求")
        
        # 1. 飞书文档输入
        feishu_doc = st.text_input(
            "飞书文档链接或ID", 
            placeholder="输入飞书文档链接或ID"
        )
        if feishu_doc:
            with st.spinner("正在读取飞书文档..."):
                doc_content = fetch_feishu_document(feishu_doc)
                if doc_content:
                    parts = re.split(r"\n\s*\n+", doc_content.strip())
                    feishu_reqs = [p for p in parts 
                                if len(p.strip()) > MIN_PARAGRAPH_LENGTH]
                    if feishu_reqs:
                        add_requirements_batch(feishu_reqs, "飞书文档")
                        st.success(f"已导入 {len(feishu_reqs)} 条需求")
        
        # 2. 文件上传
        uploaded_files = st.file_uploader(
            "上传需求文件",
            type=["xlsx", "docx", "pdf", "txt", "csv"],
            accept_multiple_files=True
        )
        
        if uploaded_files:
            for file in uploaded_files:
                with st.spinner(f"正在处理 {file.name}..."):
                    process_uploaded_file(file)
        
        # 3. 手动输入
        manual_reqs = st.text_area(
            "直接输入需求（每行一条）",
            placeholder="需求1\n需求2\n需求3...",
            height=150
        )
        
        if st.button("添加手工输入"):
            if manual_reqs:
                lines = [l.strip() for l in manual_reqs.splitlines() 
                        if len(l.strip()) > MIN_PARAGRAPH_LENGTH]
                if lines:
                    add_requirements_batch(lines, "手工输入")
                    st.success(f"已添加 {len(lines)} 条需求")
            else:
                st.warning("请输入需求内容")
                
    except Exception as e:
        st.error(f"需求输入处理错误: {str(e)}")
        if st.session_state.get("debug_mode"):
            st.exception(e)

def handle_batch_preview_and_generate(
    base_url: str,
    model: str,
    temperature: float,
    headers: List[str],
    pos_n: int,
    neg_n: int,
    edge_n: int,
    auto_mode: bool,
    dyn_params: Dict[str, Any]
) -> None:
    """处理批量需求的预览和生成部分"""
    try:
        st.markdown("### 需求预览与生成")
        
        # 获取已收集的需求
        requirements = st.session_state.get("collected_requirements", [])
        
        if not requirements:
            st.warning("请先添加需求")
            return
        
        # 显示统计信息
        source_counts = st.session_state.get("source_counts", [])
        if source_counts:
            st.info("数据来源: " + " | ".join(source_counts))
        st.info(f"总计: {len(requirements)} 条需求")
        
        # 预览表格
        preview_df = pd.DataFrame(requirements)
        st.dataframe(preview_df, use_container_width=True)
        
        st.divider()
        st.markdown("### 生成设置")
        
        parallel = st.number_input("并行处理数", 1, 8, 4)
        progress_ph = st.empty()
        result_ph = st.empty()
        
        if st.button("开始批量生成", type="primary"):
            try:
                progress_bar = progress_ph.progress(0)
                result_ph.info("正在生成...")
                
                # 创建处理器
                processor = BatchProcessor(
                    model=model,
                    base_url=base_url,
                    headers=headers,
                    pos_n=pos_n,
                    neg_n=neg_n,
                    edge_n=edge_n,
                    temperature=temperature,
                    max_workers=parallel,
                    background_knowledge=st.session_state.get('background_knowledge'),
                    dynamic_mode=auto_mode,
                    dynamic_params=dyn_params
                )
                
                # 准备需求列表
                req_list = get_requirements_for_batch(requirements)
                
                # 执行生成
                df_result = processor.process_batch(req_list)
                progress_bar.progress(100)
                
                if df_result is not None and not df_result.empty:
                    result_ph.success(f"已生成 {len(df_result)} 条测试用例")
                    st.dataframe(df_result, use_container_width=True)
                    
                    # 准备下载
                    excel_data = BytesIO()
                    with pd.ExcelWriter(excel_data, engine='openpyxl') as writer:
                        df_result.to_excel(writer, index=False)
                    excel_data.seek(0)
                    
                    # 下载按钮
                    st.download_button(
                        "📥 下载 Excel",
                        data=excel_data,
                        file_name="测试用例_批量.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                    
                    st.download_button(
                        "📥 下载 CSV",
                        data=df_result.to_csv(index=False).encode('utf-8-sig'),
                        file_name="测试用例_批量.csv",
                        mime="text/csv"
                    )
                    
                    # 错误信息
                    errors = processor.get_errors()
                    if errors:
                        with st.expander(f"处理过程中的错误 ({len(errors)})"):
                            for req_id, error in errors:
                                st.error(f"{req_id}: {error}")
                else:
                    result_ph.error("生成失败，未获得有效结果")
                    
            except Exception as e:
                progress_ph.empty()
                result_ph.error(f"批量生成失败: {str(e)}")
                if st.session_state.get("debug_mode"):
                    st.exception(e)
                    
    except Exception as e:
        st.error(f"预览和生成错误: {str(e)}")
        if st.session_state.get("debug_mode"):
            st.exception(e)

def process_uploaded_file(file) -> None:
    """处理上传的文件"""
    try:
        name = file.name.lower()
        if name.endswith('.xlsx'):
            df = pd.read_excel(file)
            df_reqs = df['需求描述'].dropna().tolist()
            if df_reqs:
                add_requirements_batch(df_reqs, f"Excel-{file.name}")
                st.success(f"已导入 {len(df_reqs)} 条需求")
        
        elif name.endswith('.docx'):
            doc = Document(file)
            word_reqs = [p.text.strip() for p in doc.paragraphs 
                        if len(p.text.strip()) > MIN_PARAGRAPH_LENGTH]
            if word_reqs:
                add_requirements_batch(word_reqs, f"Word-{file.name}")
                st.success(f"已导入 {len(word_reqs)} 条需求")
        
        elif name.endswith('.pdf'):
            pdf_reader = PyPDF2.PdfReader(BytesIO(file.getvalue()))
            pdf_reqs = []
            for page in pdf_reader.pages:
                text = page.extract_text()
                parts = re.split(r"\n\s*\n+", text.strip())
                pdf_reqs.extend([p for p in parts 
                            if len(p.strip()) > MIN_PARAGRAPH_LENGTH])
            if pdf_reqs:
                add_requirements_batch(pdf_reqs, f"PDF-{file.name}")
                st.success(f"已导入 {len(pdf_reqs)} 条需求")
        
        elif name.endswith(('.txt', '.csv')):
            stringio = StringIO(file.getvalue().decode("utf-8"))
            lines = [l.strip() for l in stringio.readlines() 
                    if len(l.strip()) > MIN_PARAGRAPH_LENGTH]
            if lines:
                add_requirements_batch(lines, f"Text-{file.name}")
                st.success(f"已导入 {len(lines)} 条需求")
                
    except Exception as e:
        st.error(f"处理文件 {file.name} 失败: {str(e)}")
        if st.session_state.get("debug_mode"):
            st.exception(e)

def add_requirements_batch(requirements: List[str], source: str) -> None:
    """添加一批需求到会话状态"""
    if not hasattr(st.session_state, "collected_requirements"):
        st.session_state.collected_requirements = []
    if not hasattr(st.session_state, "source_counts"):
        st.session_state.source_counts = []
        
    for req in requirements:
        st.session_state.collected_requirements.append({
            "需求编号": "",
            "需求描述": req.strip(),
            "来源": source
        })
    st.session_state.source_counts.append(f"{source}:{len(requirements)}")

def get_requirements_for_batch(requirements: List[Dict[str, str]]) -> List[str]:
    """将需求列表转换为批处理格式"""
    return [r["需求描述"] for r in requirements if r["需求描述"].strip()]