"""Feishu (Lark) Docx Fetch Demo

安全说明:
  * 不要在代码里硬编码 APP_ID / APP_SECRET / 访问 Token。
  * 使用环境变量: FEISHU_APP_ID / FEISHU_APP_SECRET
  * 若需在 CI 中使用, 建议通过密钥管理注入。

功能:
  1. 获取 tenant_access_token (内部应用)
  2. 拉取指定 docx 文档基础信息
  3. 递归 / 分页获取文档块 (blocks) 内容并抽取纯文本
  4. 输出到终端或保存为 Markdown

参考文档 (需登录飞书开放平台查看):
  - https://open.feishu.cn/document/server-docs/docs/docs-overview
  - 获取租户访问令牌: POST /open-apis/auth/v3/tenant_access_token/internal
  - 获取文档:       GET  /open-apis/docx/v1/documents/:document_id
  - 获取文档块:     GET  /open-apis/docx/v1/documents/:document_id/blocks/:block_id (根块一般为 document_id)

用法示例:
  python feishu_doc_demo.py --doc ZTJVdfHJvoQbxkxaw8Ic06dLn3g --save output.md
  export FEISHU_APP_ID=cli_xxx
  export FEISHU_APP_SECRET=xxx

限制:
  - 本示例不包含 token 缓存 / 重试策略的生产级封装。
  - 未对所有 block 类型做完全解析 (只抽取常见段落文字 / 标题 / 列表)。
"""
from __future__ import annotations
import os
import sys
import json
import time
import argparse
from typing import Dict, List, Optional
import re

import requests

BASE_API = os.environ.get("FEISHU_OPEN_BASE", "https://open.feishu.cn")
TOKEN_ENDPOINT = f"{BASE_API}/open-apis/auth/v3/tenant_access_token/internal"
DOC_ENDPOINT_TMPL = f"{BASE_API}/open-apis/docx/v1/documents/{{doc_id}}"
BLOCKS_ENDPOINT_TMPL = f"{BASE_API}/open-apis/docx/v1/documents/{{doc_id}}/blocks/{{block_id}}?page_size={{page_size}}&page_token={{page_token}}"

# 简单的块类型 -> 纯文本抽取策略
INLINE_KEY_CANDIDATES = ["elements", "runs", "inlines", "text_run"]


def getenv_or_exit(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        print(f"[ERR] Missing environment variable: {name}", file=sys.stderr)
        sys.exit(2)
    return val


def get_tenant_access_token(app_id: str, app_secret: str, debug: bool = False, retries: int = 3, base_delay: float = 0.8) -> str:
    payload = {"app_id": app_id, "app_secret": app_secret}
    last_err: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        if debug:
            print(f"[DBG] Requesting token attempt {attempt}/{retries} -> {TOKEN_ENDPOINT}")
        try:
            resp = requests.post(TOKEN_ENDPOINT, json=payload, timeout=10)
        except requests.RequestException as e:
            last_err = RuntimeError(f"Token request network error: {e}")
            if debug:
                print(f"[DBG] Network error: {e}")
        else:
            if debug:
                print(f"[DBG] Token HTTP status: {resp.status_code}")
            if resp.status_code == 500:
                snippet = resp.text[:300]
                print(f"[WARN] Server 500. Body snippet: {snippet}")
                last_err = RuntimeError(f"Server 500 internal error (log_id maybe in snippet)")
            elif resp.status_code != 200:
                last_err = RuntimeError(f"Token HTTP {resp.status_code}: {resp.text[:300]}")
            else:
                try:
                    data = resp.json()
                except ValueError:
                    last_err = RuntimeError(f"Token response not JSON: {resp.text[:200]}")
                else:
                    if debug:
                        print(f"[DBG] Token raw JSON: {json.dumps(data, ensure_ascii=False)[:400]}")
                    code = data.get("code")
                    if code == 0:
                        return data["tenant_access_token"]
                    else:
                        last_err = RuntimeError(f"Token error code={code} msg={data.get('msg')}")
        # backoff
        if attempt < retries:
            delay = base_delay * (2 ** (attempt - 1))
            if debug:
                print(f"[DBG] Retry in {delay:.2f}s ...")
            time.sleep(delay)
    raise last_err or RuntimeError("Token acquisition failed (unknown error)")


def api_get(url: str, token: str, debug: bool = False) -> Dict:
    headers = {"Authorization": f"Bearer {token}"}
    if debug:
        print(f"[DBG] GET {url}")
    try:
        resp = requests.get(url, headers=headers, timeout=(10, 30))
    except requests.RequestException as e:
        raise RuntimeError(f"GET {url} network error: {e}")
    if debug:
        print(f"[DBG] Response status: {resp.status_code}")
    if resp.status_code != 200:
        raise RuntimeError(f"GET {url} -> {resp.status_code}: {resp.text[:300]}")
    try:
        data = resp.json()
    except ValueError:
        raise RuntimeError(f"Response not JSON for {url}: {resp.text[:200]}")
    if debug:
        snippet = json.dumps(data, ensure_ascii=False)[:400]
        print(f"[DBG] JSON snippet: {snippet}")
    if data.get("code") not in (0, None):
        raise RuntimeError(f"API logical error code={data.get('code')} msg={data.get('msg')}")
    return data


def get_document_meta(doc_id: str, token: str, debug: bool = False) -> Dict:
    url = DOC_ENDPOINT_TMPL.format(doc_id=doc_id)
    return api_get(url, token, debug=debug)


def fetch_blocks_recursive(doc_id: str, block_id: str, token: str, depth: int = 0, max_depth: int = 8, debug: bool = False) -> List[Dict]:
    results: List[Dict] = []
    page_token = ""
    while True:
        url = BLOCKS_ENDPOINT_TMPL.format(doc_id=doc_id, block_id=block_id, page_size=200, page_token=page_token)
        data = api_get(url, token, debug=debug)
        items = data.get("data", {}).get("items", [])
        for it in items:
            results.append(it)
            # 递归子块 (若有 children)
            has_children = it.get("has_child") or (it.get("children") not in (None, []))
            if has_children and depth < max_depth:
                child_id = it.get("block_id") or it.get("id")
                if child_id:
                    try:
                        child_blocks = fetch_blocks_recursive(doc_id, child_id, token, depth + 1, max_depth, debug=debug)
                        results.extend(child_blocks)
                    except Exception as e:
                        print(f"[WARN] fetch child {child_id} failed: {e}")
        page_token = data.get("data", {}).get("page_token")
        if not page_token:
            break
        time.sleep(0.05)
    return results


def extract_text_from_block(block: Dict) -> str:
    btype = block.get("block_type") or block.get("type")
    # 常见: paragraph / heading / list 等
    text_parts: List[str] = []
    # 飞书 docx blocks 中 often: block['block'] -> { 'paragraph': { 'elements': [ { 'text_run': { 'content': 'xxx' } } ] } }
    block_content = block.get("block") or {}
    # Flatten nested dicts
    def iter_dict(d: Dict):
        for k, v in d.items():
            yield k, v
            if isinstance(v, dict):
                for k2, v2 in iter_dict(v):
                    yield k2, v2
            elif isinstance(v, list):
                for elem in v:
                    if isinstance(elem, dict):
                        for k3, v3 in iter_dict(elem):
                            yield k3, v3

    for k, v in iter_dict(block_content):
        if k == "text_run" and isinstance(v, dict):
            c = v.get("content")
            if c:
                text_parts.append(c.replace("\n", " ").strip())
    text = " ".join([t for t in text_parts if t])
    # 简单清理
    return text.strip()


def blocks_to_markdown(blocks: List[Dict]) -> str:
    lines: List[str] = []
    for b in blocks:
        t = extract_text_from_block(b)
        if not t:
            continue
        bt = (b.get("block_type") or b.get("type") or "").lower()
        if bt.startswith("heading"):
            level = bt[-1] if bt[-1].isdigit() else "2"
            lines.append(f"{'#'*int(level)} {t}")
        elif bt.startswith("bullet") or bt.startswith("ordered") or bt.startswith("list"):
            lines.append(f"- {t}")
        else:
            lines.append(t)
    # 去重连续空
    cleaned: List[str] = []
    prev_blank = False
    for l in lines:
        blank = (not l.strip())
        if blank and prev_blank:
            continue
        cleaned.append(l)
        prev_blank = blank
    return "\n".join(cleaned)


def check_connectivity(debug: bool = False) -> None:
    test_url = BASE_API
    try:
        r = requests.get(test_url, timeout=5)
        if debug:
            print(f"[DBG] Connectivity to {test_url} -> {r.status_code}")
    except Exception as e:
        raise RuntimeError(f"Cannot reach {test_url}: {e}")


def main():
    ap = argparse.ArgumentParser(description="Feishu Docx Fetch Demo")
    ap.add_argument("--doc", required=True, help="Document ID or full URL (e.g. https://xxx/docx/ABCDEFGHIjkLmno)")
    ap.add_argument("--save", help="Save extracted markdown to file")
    ap.add_argument("--json", action="store_true", help="Dump raw blocks JSON")
    ap.add_argument("--meta", action="store_true", help="Print document meta JSON")
    ap.add_argument("--max-depth", type=int, default=6, help="Max recursive depth")
    ap.add_argument("--debug", action="store_true", help="Enable verbose debug output")
    ap.add_argument("--app-id", help="Override FEISHU_APP_ID env")
    ap.add_argument("--app-secret", help="Override FEISHU_APP_SECRET env")
    args = ap.parse_args()

    # 优先使用命令行参数，其次环境变量
    if args.app_id:
        app_id = args.app_id
    else:
        app_id = getenv_or_exit("FEISHU_APP_ID")
    if args.app_secret:
        app_secret = args.app_secret
    else:
        app_secret = getenv_or_exit("FEISHU_APP_SECRET")

    if args.debug:
        print(f"[DBG] BASE_API={BASE_API}")
        masked_id = app_id[:6] + "***" if len(app_id) > 6 else "***"
        print(f"[DBG] APP_ID={masked_id}")
    print("[INFO] Checking connectivity ...")
    try:
        check_connectivity(debug=args.debug)
    except Exception as e:
        print(f"[ERROR] Connectivity check failed: {e}")
        sys.exit(3)

    print("[INFO] Getting tenant access token ...")
    try:
        token = get_tenant_access_token(app_id, app_secret, debug=args.debug)
    except Exception as e:
        print(f"[ERROR] Token acquisition failed: {e}")
        sys.exit(4)
    print("[INFO] Token acquired (value hidden)")

    # 兼容直接传入完整 URL -> 提取 /docx/<ID> 或 /wiki/<ID>
    doc_input = args.doc.strip()
    m = re.search(r"/(?:docx|wiki)/([A-Za-z0-9]+)", doc_input)
    if m:
        if args.debug:
            print(f"[DBG] Extracted doc id from URL: {m.group(1)}")
        args.doc = m.group(1)

    if args.meta:
        try:
            meta = get_document_meta(args.doc, token, debug=args.debug)
            print("[META]", json.dumps(meta, ensure_ascii=False)[:800])
        except Exception as e:
            print(f"[ERROR] Fetch meta failed: {e}")
            # 不直接退出, 继续尝试 blocks

    print("[INFO] Fetching blocks ...")
    try:
        blocks = fetch_blocks_recursive(args.doc, args.doc, token, depth=0, max_depth=args.max_depth, debug=args.debug)
    except Exception as e:
        print(f"[ERROR] Fetch blocks failed: {e}")
        sys.exit(5)
    print(f"[INFO] Total blocks fetched: {len(blocks)}")

    if args.json:
        print(json.dumps(blocks, ensure_ascii=False, indent=2)[:5000])

    md = blocks_to_markdown(blocks)
    print("\n===== Extracted Markdown (preview) =====\n")
    print(md[:2000] + ("..." if len(md) > 2000 else ""))

    if args.save:
        with open(args.save, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"[INFO] Saved markdown to {args.save}")

if __name__ == "__main__":
    main()
