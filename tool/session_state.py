"""会话状态管理

管理Streamlit应用的会话状态，包括：
- 初始化
- 状态变量访问
- 状态更新和检查 
- 请求限制追踪
- 速率控制
"""

import streamlit as st
import time
from typing import Any, Dict, List, Optional

class SessionState:
    """会话状态管理器"""
    
    def __init__(self):
        """初始化会话状态变量"""
        self._initialize_state()
        
    def _initialize_state(self):
        """初始化所有状态变量的默认值"""
        defaults = {
            # 需求管理
            'requirements_initialized': True,
            'collected_requirements': [],
            'source_counts': [],
            'last_batch_result': None,
            
            # 背景知识
            'background_knowledge': None,
            'background_file': None,
            'background_urls': [],
            'background_urls_content': [],
            
            # 飞书设置
            'feishu_app_id': None,
            'feishu_app_secret': None,
            
            # 调试设置
            'debug_mode': False,
            
            # 用户输入
            'direct_background_text': "",
            'last_background_doc_name': None,
            
            # 请求限制
            'request_counter': 0,
            'last_reset_time': time.time(),
            'rate_limit_duration': 3600,  # 1小时周期
            'rate_limit_max': 100,  # 每小时最大请求数
        }
        
        # 设置默认值
        for key, value in defaults.items():
            if key not in st.session_state:
                st.session_state[key] = value
                
    def get(self, key: str, default: Any = None) -> Any:
        """获取状态值
        
        Args:
            key: 状态键名
            default: 默认值
            
        Returns:
            状态值
        """
        return st.session_state.get(key, default)
        
    def set(self, key: str, value: Any):
        """设置状态值
        
        Args:
            key: 状态键名
            value: 状态值
        """
        st.session_state[key] = value
        
    def clear(self, key: str):
        """清除状态值
        
        Args:
            key: 状态键名
        """
        if key in st.session_state:
            del st.session_state[key]
            
    def has(self, key: str) -> bool:
        """检查状态是否存在
        
        Args:
            key: 状态键名
            
        Returns:
            是否存在
        """
        return key in st.session_state
        
    def update(self, updates: Dict[str, Any]):
        """批量更新状态值
        
        Args:
            updates: 状态更新字典
        """
        st.session_state.update(updates)
        
    def get_requirements(self) -> List[Dict[str, str]]:
        """获取已收集的需求列表
        
        Returns:
            需求列表
        """
        return self.get('collected_requirements', [])
        
    def add_requirements(self, reqs: List[Dict[str, str]], source: str):
        """添加需求列表
        
        Args:
            reqs: 需求列表
            source: 需求来源
        """
        current = self.get_requirements()
        current.extend(reqs)
        self.set('collected_requirements', current)
        
        counts = self.get('source_counts', [])
        counts.append(f"{source}:{len(reqs)}")
        self.set('source_counts', counts)
        
    def clear_requirements(self):
        """清除所有需求"""
        self.set('collected_requirements', [])
        self.set('source_counts', [])
        self.set('last_batch_result', None)
        
    def set_background(self, content: Optional[str], source: Optional[str] = None):
        """设置背景知识内容
        
        Args:
            content: 背景知识内容
            source: 内容来源
        """
        if content:
            self.set('background_knowledge', content)
            if source:
                self.set('last_background_doc_name', source)
        else:
            self.clear('background_knowledge')
            self.clear('last_background_doc_name')
            
    def get_background(self) -> Optional[str]:
        """获取背景知识内容
        
        Returns:
            背景知识内容
        """
        return self.get('background_knowledge')
        
    def get_debug_mode(self) -> bool:
        """获取调试模式状态
        
        Returns:
            是否启用调试模式
        """
        return self.get('debug_mode', False)
        
    def set_debug_mode(self, enabled: bool):
        """设置调试模式状态
        
        Args:
            enabled: 是否启用
        """
        self.set('debug_mode', enabled)
        
    def get_feishu_credentials(self) -> tuple[Optional[str], Optional[str]]:
        """获取飞书API凭证
        
        Returns:
            (app_id, app_secret) 元组
        """
        app_id = self.get('feishu_app_id')
        app_secret = self.get('feishu_app_secret')
        return app_id, app_secret
        
    def set_feishu_credentials(self, app_id: str, app_secret: str):
        """设置飞书API凭证
        
        Args:
            app_id: 应用ID
            app_secret: 应用密钥
        """
        self.set('feishu_app_id', app_id)
        self.set('feishu_app_secret', app_secret)
        
    def check_rate_limit(self) -> bool:
        """检查请求频率是否在限制范围内
        
        根据当前状态判断是否允许新的请求。如果已达到限制，
        返回False；否则增加计数并返回True。
        
        Returns:
            bool: 是否允许继续请求
        """
        now = time.time()
        last_reset = self.get('last_reset_time', 0)
        duration = self.get('rate_limit_duration', 3600)
        
        # 检查是否需要重置计数器
        if now - last_reset >= duration:
            self.set('request_counter', 0)
            self.set('last_reset_time', now)
            
        current_count = self.get('request_counter', 0)
        max_requests = self.get('rate_limit_max', 100)
        
        # 检查是否超出限制
        if current_count >= max_requests:
            return False
            
        # 增加计数并允许请求
        self.set('request_counter', current_count + 1)
        return True
        
    def get_rate_limit_status(self) -> Dict[str, Any]:
        """获取当前请求限制状态
        
        Returns:
            包含当前计数、重置时间等信息的字典
        """
        now = time.time()
        last_reset = self.get('last_reset_time', 0)
        duration = self.get('rate_limit_duration', 3600)
        current_count = self.get('request_counter', 0)
        max_requests = self.get('rate_limit_max', 100)
        
        time_until_reset = max(0, duration - (now - last_reset))
        requests_remaining = max(0, max_requests - current_count)
        
        return {
            'current_count': current_count,
            'max_requests': max_requests,
            'requests_remaining': requests_remaining,
            'reset_in_seconds': time_until_reset,
            'rate_limit_duration': duration
        }
        
    def set_rate_limit(self, max_requests: int, duration: int):
        """更新请求限制配置
        
        Args:
            max_requests: 周期内最大请求数
            duration: 限制周期(秒)
        """
        self.set('rate_limit_max', max_requests)
        self.set('rate_limit_duration', duration)
        # 重置计数器
        self.set('request_counter', 0)
        self.set('last_reset_time', time.time())