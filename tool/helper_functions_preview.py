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