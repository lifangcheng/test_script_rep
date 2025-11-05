"""飞书API集成客户端

提供飞书API的统一访问接口，包括：
- 文档访问和处理
- 认证令牌管理
- 数据解析和转换
"""

import os
import re
import json
import time
import logging
from typing import Dict, List, Optional
import requests
from functools import wraps

# 配置日志记录
logger = logging.getLogger(__name__)

class APIError(Exception):
    """API调用相关错误的基类"""
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code

class AuthenticationError(APIError):
    """认证相关错误"""
    pass

class NetworkError(APIError):
    """网络请求错误"""
    pass

class ResponseError(APIError):
    """响应解析错误"""
    pass

class FeishuConfig:
    """飞书API配置"""
    BASE_API = os.environ.get("FEISHU_OPEN_BASE", "https://open.feishu.cn")
    TOKEN_ENDPOINT = f"{BASE_API}/open-apis/auth/v3/tenant_access_token/internal"
    USER_TOKEN_ENDPOINT = f"{BASE_API}/open-apis/authen/v1/access_token"
    OAUTH_AUTHORIZE_URL = f"{BASE_API}/open-apis/authen/v1/authorize"
    OAUTH_TOKEN_URL = f"{BASE_API}/open-apis/authen/v1/refresh_access_token"
    DOC_ENDPOINT_TMPL = f"{BASE_API}/open-apis/docx/v1/documents/{{doc_id}}"
    BLOCKS_ENDPOINT_TMPL = (
        f"{BASE_API}/open-apis/docx/v1/documents/{{doc_id}}"
        f"/blocks/{{block_id}}?page_size={{page_size}}&page_token={{page_token}}"
    )

def handle_api_errors(func):
    """API错误处理装饰器"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except requests.exceptions.RequestException as e:
            raise NetworkError(f"网络请求失败: {e}")
        except (ValueError, json.JSONDecodeError) as e:
            raise ResponseError(f"响应格式错误: {e}")
        except Exception as e:
            if isinstance(e, APIError):
                raise
            raise APIError(f"API调用异常: {e}")
    return wrapper

class FeishuClient:
    """飞书API客户端
    
    提供飞书API的统一访问接口，支持:
    - 认证和令牌管理
    - 文档访问和解析
    - 文档块处理和转换
    """
    
    def __init__(
        self, 
        app_id: str, 
        app_secret: str, 
        debug: bool = False
    ):
        """初始化飞书客户端
        
        Args:
            app_id: 飞书应用ID
            app_secret: 飞书应用密钥
            debug: 是否启用调试模式
        """
        self.app_id = app_id
        self.app_secret = app_secret
        self.debug = debug
        self._token_cache: Optional[str] = None
        self._token_expire: Optional[float] = None
    
    @handle_api_errors
    def get_user_access_token(self, code: str) -> str:
        """通过授权码获取飞书用户访问令牌
        
        Args:
            code: 用户授权码
            
        Returns:
            用户访问令牌
            
        Raises:
            AuthenticationError: 获取令牌失败
            NetworkError: 网络请求失败
            ResponseError: 响应解析失败
        """
        payload = {
            "grant_type": "authorization_code",
            "client_id": self.app_id,
            "client_secret": self.app_secret,
            "code": code
        }
        
        if self.debug:
            logger.debug(f"Requesting user token with code: {code[:10]}...")
            
        resp = requests.post(
            FeishuConfig.OAUTH_TOKEN_URL,
            json=payload,
            timeout=10
        )
        
        if self.debug:
            logger.debug(f"User token HTTP status: {resp.status_code}")
            
        if resp.status_code != 200:
            raise AuthenticationError(
                f"获取用户令牌失败: {resp.text[:300]}", 
                resp.status_code
            )
            
        data = resp.json()
        
        if self.debug:
            logger.debug(
                f"User token response: {json.dumps(data, ensure_ascii=False)[:400]}"
            )
            
        if data.get("code") != 0:
            raise AuthenticationError(
                f"获取用户令牌失败: code={data.get('code')} msg={data.get('msg')}"
            )
            
        return data["data"]["access_token"]
    
    @handle_api_errors    
    def get_tenant_access_token(
        self, 
        retries: int = 3,
        base_delay: float = 0.8,
        force_refresh: bool = False
    ) -> str:
        """获取租户访问令牌
        
        Args:
            retries: 重试次数
            base_delay: 基础重试延迟时间
            force_refresh: 是否强制刷新缓存的令牌
            
        Returns:
            租户访问令牌
            
        Raises:
            AuthenticationError: 获取令牌失败
            NetworkError: 网络请求失败
            ResponseError: 响应解析失败
        """
        # 检查缓存
        now = time.time()
        if not force_refresh and self._token_cache and self._token_expire:
            if now < self._token_expire:
                return self._token_cache
        
        payload = {
            "app_id": self.app_id,
            "app_secret": self.app_secret
        }
        
        last_error: Optional[Exception] = None
        
        for attempt in range(1, retries + 1):
            if self.debug:
                logger.debug(f"Token request attempt {attempt}/{retries}")
                
            try:
                resp = requests.post(
                    FeishuConfig.TOKEN_ENDPOINT,
                    json=payload,
                    timeout=10
                )
                
                if self.debug:
                    logger.debug(f"Token response status: {resp.status_code}")
                
                if resp.status_code == 500:
                    snippet = resp.text[:300]
                    logger.warning(f"Server 500 error. Response: {snippet}")
                    last_error = APIError("服务器内部错误", 500)
                    
                elif resp.status_code != 200:
                    last_error = APIError(
                        f"获取令牌失败: {resp.text[:300]}", 
                        resp.status_code
                    )
                    
                else:
                    data = resp.json()
                    
                    if self.debug:
                        logger.debug(
                            f"Token response: {json.dumps(data, ensure_ascii=False)[:400]}"
                        )
                    
                    if data.get("code") == 0:
                        token = data["tenant_access_token"]
                        # 缓存令牌 (有效期设为获取到的过期时间的80%)
                        expire_seconds = int(data.get("expire", 7200))
                        self._token_cache = token
                        self._token_expire = now + (expire_seconds * 0.8)
                        return token
                    
                    last_error = APIError(
                        f"获取令牌失败: code={data.get('code')} msg={data.get('msg')}"
                    )
                    
            except requests.RequestException as e:
                last_error = NetworkError(f"网络请求失败: {e}")
                if self.debug:
                    logger.debug(f"Network error: {e}")
            
            # 指数退避重试
            if attempt < retries:
                delay = base_delay * (2 ** (attempt - 1))
                if self.debug:
                    logger.debug(f"Retrying in {delay:.2f}s")
                time.sleep(delay)
                
        raise last_error or APIError("获取令牌失败(未知错误)")
    
    @handle_api_errors
    def api_get(self, url: str, token: str) -> Dict:
        """通用飞书API GET请求方法
        
        Args:
            url: 请求URL
            token: 访问令牌
            
        Returns:
            响应数据
            
        Raises:
            APIError: API调用失败
            NetworkError: 网络请求失败
            ResponseError: 响应解析失败
        """
        headers = {"Authorization": f"Bearer {token}"}
        
        if self.debug:
            logger.debug(f"GET {url}")
            
        resp = requests.get(url, headers=headers, timeout=10)
        
        if self.debug:
            logger.debug(f"Response status: {resp.status_code}")
            
        if resp.status_code != 200:
            raise APIError(
                f"请求失败: {resp.text[:300]}", 
                resp.status_code
            )
            
        data = resp.json()
        
        if self.debug:
            logger.debug(
                f"Response data: {json.dumps(data, ensure_ascii=False)[:400]}"
            )
            
        if data.get("code") not in (0, None):
            raise APIError(
                f"请求失败: code={data.get('code')} msg={data.get('msg')}"
            )
            
        return data
    
    @handle_api_errors
    def fetch_document_blocks(
        self, 
        doc_id: str,
        block_id: str,
        token: str,
        depth: int = 0,
        max_depth: int = 8
    ) -> List[Dict]:
        """递归获取飞书文档块内容
        
        Args:
            doc_id: 文档ID
            block_id: 当前块ID
            token: 访问令牌
            depth: 当前递归深度
            max_depth: 最大递归深度
            
        Returns:
            文档块列表
            
        Raises:
            APIError: API调用失败
            NetworkError: 网络请求失败
            ResponseError: 响应解析失败
        """
        # 防止过深递归
        if depth > max_depth:
            logger.warning(f"达到最大递归深度 {max_depth}")
            return []
            
        results: List[Dict] = []
        
        # 构建API请求URL
        url = FeishuConfig.BLOCKS_ENDPOINT_TMPL.format(
            doc_id=doc_id,
            block_id=block_id,
            page_size=200,
            page_token=""
        )
        
        # 获取块数据
        data = self.api_get(url, token)
        block_data = data.get("data", {}).get("block")
        
        if not block_data:
            return results
            
        results.append(block_data)
        
        # 处理子块
        children = block_data.get("children", [])
        for child_id in children:
            if not child_id:
                continue
                
            try:
                child_blocks = self.fetch_document_blocks(
                    doc_id=doc_id,
                    block_id=child_id,
                    token=token,
                    depth=depth + 1,
                    max_depth=max_depth
                )
                results.extend(child_blocks)
            except Exception as e:
                logger.warning(f"获取子块 {child_id} 失败: {e}")
                
        return results
        
    def extract_block_text(self, block: Dict) -> str:
        """从文档块中提取文本内容
        
        支持的块类型:
        - 1: 页面块（根块）
        - 2: 文本块
        - 其他: 通用处理
        
        Args:
            block: 文档块数据
            
        Returns:
            提取的文本内容
        """
        text_parts: List[str] = []
        block_type = block.get("block_type")
        
        # 页面块处理
        if block_type == 1:
            text_parts.extend(
                self._extract_elements_text(
                    block.get("page", {}).get("elements", [])
                )
            )
            
        # 文本块处理
        elif block_type == 2:
            text_parts.extend(
                self._extract_elements_text(
                    block.get("text", {}).get("elements", [])
                )
            )
            
        # 其他块类型通用处理
        else:
            block_content = block.get("block") or {}
            text_parts.extend(
                self._extract_nested_text(block_content)
            )
            
        return " ".join(text_parts).strip()
    
    def _extract_elements_text(self, elements: List[Dict]) -> List[str]:
        """从元素列表中提取文本
        
        Args:
            elements: 元素列表
            
        Returns:
            文本片段列表
        """
        texts: List[str] = []
        for elem in elements:
            if not isinstance(elem, dict):
                continue
                
            text_run = elem.get("text_run", {})
            content = text_run.get("content", "")
            if content:
                texts.append(
                    content.replace("\n", " ").strip()
                )
        return texts
        
    def _extract_nested_text(self, data: Dict) -> List[str]:
        """递归提取嵌套数据中的文本
        
        Args:
            data: 嵌套的数据结构
            
        Returns:
            文本片段列表
        """
        texts: List[str] = []
        
        def _iter_dict(d: Dict) -> None:
            for key, value in d.items():
                if key == "text_run" and isinstance(value, dict):
                    content = value.get("content")
                    if content:
                        texts.append(
                            content.replace("\n", " ").strip()
                        )
                elif isinstance(value, dict):
                    _iter_dict(value)
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict):
                            _iter_dict(item)
                            
        _iter_dict(data)
        return texts
        
    def blocks_to_markdown(self, blocks: List[Dict]) -> str:
        """将飞书文档块转换为Markdown格式
        
        Args:
            blocks: 文档块列表
            
        Returns:
            Markdown格式的文档内容
        """
        lines: List[str] = []
        
        for block in blocks:
            # 提取文本
            text = self.extract_block_text(block)
            if not text:
                continue
                
            # 根据块类型格式化
            block_type = str(block.get("block_type", "")).lower()
            
            # 标题块处理
            if block_type.startswith("heading") or block_type == "3":
                level = block_type[-1] if block_type[-1].isdigit() else "2"
                lines.append(f"{'#' * int(level)} {text}")
                
            # 列表块处理
            elif block_type in ("bullet", "ordered", "list", "4", "5", "6"):
                lines.append(f"- {text}")
                
            # 普通文本块
            else:
                lines.append(text)
                
        # 清理连续空行
        return self._clean_empty_lines(lines)
        
    def _clean_empty_lines(self, lines: List[str]) -> str:
        """清理文本中的连续空行
        
        Args:
            lines: 文本行列表
            
        Returns:
            清理后的文本
        """
        cleaned: List[str] = []
        prev_blank = False
        
        for line in lines:
            is_blank = not line.strip()
            if is_blank and prev_blank:
                continue
            cleaned.append(line)
            prev_blank = is_blank
            
        return "\n".join(cleaned)
        
    def fetch_document(self, url_or_id: str) -> str:
        """获取并处理飞书文档内容
        
        Args:
            url_or_id: 文档URL或ID
            
        Returns:
            Markdown格式的文档内容
        """
        try:
            # 提取文档ID
            doc_id = self._extract_document_id(url_or_id)
            if not doc_id:
                raise ValueError("无法从URL提取文档ID")
                
            # 获取访问令牌
            token = self.get_tenant_access_token()
                
            # 获取文档块
            blocks = self.fetch_document_blocks(
                doc_id=doc_id,
                block_id=doc_id,
                token=token,
                depth=0,
                max_depth=6
            )
                
            if self.debug:
                logger.debug(f"获取到 {len(blocks)} 个文档块")
                if blocks:
                    logger.debug(
                        f"第一个块示例: {json.dumps(blocks[0], ensure_ascii=False)[:200]}..."
                    )
                
            # 转换为Markdown
            markdown = self.blocks_to_markdown(blocks)
                
            if self.debug:
                logger.debug(f"生成Markdown长度: {len(markdown)}")
                logger.debug(f"Markdown预览: {markdown[:200]}...")
                
            return markdown
            
        except Exception as e:
            logger.exception("处理飞书文档失败")
            return f"【飞书API错误】{str(e)}"
            
    def _extract_document_id(self, url_or_id: str) -> Optional[str]:
        """从URL或ID字符串中提取文档ID
        
        Args:
            url_or_id: URL或ID字符串
            
        Returns:
            文档ID，如果无法提取则返回None
        """
        doc_input = url_or_id.strip()
        match = re.search(r"/(?:docx|wiki|docs)/([A-Za-z0-9]+)", doc_input)
        
        if match:
            return match.group(1)
            
        # 如果不是URL格式，假定整个输入就是ID
        if re.match(r"^[A-Za-z0-9]+$", doc_input):
            return doc_input
            
        return None