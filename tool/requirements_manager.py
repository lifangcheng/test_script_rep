"""Requirements management utilities for test case generation"""

import streamlit as st
from typing import List, Dict, Optional, Any
import re

MIN_PARAGRAPH_LENGTH = 10

def add_requirement(req_text: str, source: str, req_id: str = "") -> None:
    """Add a single requirement to the session state
    
    Args:
        req_text: The requirement text
        source: Source identifier
        req_id: Optional requirement ID
    """
    if not hasattr(st.session_state, 'collected_requirements'):
        st.session_state.collected_requirements = []
    if not hasattr(st.session_state, 'source_counts'):
        st.session_state.source_counts = []
        
    if req_text and len(req_text.strip()) > MIN_PARAGRAPH_LENGTH:
        st.session_state.collected_requirements.append({
            "需求编号": req_id,
            "需求描述": req_text.strip(),
            "来源": source
        })

def add_requirements_batch(reqs: List[str], source: str, base_id: str = "") -> None:
    """Add a batch of requirements to the session state
    
    Args:
        reqs: List of requirement texts
        source: Source identifier
        base_id: Base requirement ID to use (will be suffixed with numbers)
    """
    count = 0
    for req in reqs:
        if req and len(req.strip()) > MIN_PARAGRAPH_LENGTH:
            req_id = f"{base_id}{count+1:03d}" if base_id else ""
            add_requirement(req.strip(), source, req_id)
            count += 1
            
    if count > 0:
        if not hasattr(st.session_state, 'source_counts'):
            st.session_state.source_counts = []
        st.session_state.source_counts.append(f"{source}:{count}")
        
def clear_requirements() -> None:
    """Clear all collected requirements"""
    st.session_state.collected_requirements = []
    st.session_state.source_counts = []
    
def get_unique_requirements() -> List[Dict[str, str]]:
    """Get deduplicated list of requirements
    
    Returns:
        List of requirement dictionaries with auto-generated IDs
    """
    if not hasattr(st.session_state, 'collected_requirements'):
        return []
        
    unique_reqs = []
    seen = set()
    
    for req in st.session_state.collected_requirements:
        key = req["需求描述"].strip()
        if key and key not in seen:
            seen.add(key)
            # Add auto ID if missing
            if not req["需求编号"]:
                req["需求编号"] = f"REQ-{len(unique_reqs)+1:03d}"
            unique_reqs.append(req)
            
    return unique_reqs
    
def get_source_summary() -> str:
    """Get summary of requirement sources
    
    Returns:
        String summarizing the sources and counts
    """
    if not hasattr(st.session_state, 'source_counts'):
        return "无数据来源"
        
    return " | ".join(st.session_state.source_counts)
    
def get_requirements_for_batch() -> List[tuple[str, str]]:
    """Get requirements formatted for batch processing
    
    Returns:
        List of (requirement_text, requirement_id) tuples
    """
    reqs = get_unique_requirements()
    return [(r["需求描述"], r["需求编号"]) for r in reqs]