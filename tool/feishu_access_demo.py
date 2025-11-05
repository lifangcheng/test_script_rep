"""Feishu (Lark) Unified Access Demo

Implements the official access token acquisition flow (internal application) per:
  https://open.larkoffice.com/document/server-docs/api-call-guide/calling-process/get-access-token

Features:
  1. Obtain app_access_token (internal)
  2. Obtain tenant_access_token (internal)
  3. Fallback domain attempt: open.feishu.cn -> open.larksuite.com (in case of 500 in some regions)
  4. Example API calls:
       - Contact Department detail (/contact/v3/departments/<id>)
       - Docx document meta + blocks (simplified textual extraction)
  5. Retry with exponential backoff for token endpoints, log_id extraction on server errors
  6. CLI overrides for app_id / app_secret; environment variable support

Environment Variables (optional):
  FEISHU_APP_ID, FEISHU_APP_SECRET
  FEISHU_OPEN_BASE (override API base, typical values: https://open.feishu.cn or https://open.larksuite.com)

Usage Examples:
  python feishu_access_demo.py --dept-id od-64242a18099d3a31acd24d8fce8dXXXX --app-id cli_xxx --app-secret yyy --debug
  python feishu_access_demo.py --doc-id ZTJVdfHJvoQbxkxaw8Ic06dLn3g --app-id cli_xxx --app-secret yyy --fetch-doc --save doc.md

Security:
  Do NOT hardcode secrets into source control.

"""
from __future__ import annotations
import os
import sys
import re
import json
import time
import argparse
from typing import Optional, Dict, List, Tuple

import requests

DEFAULT_DOMAINS = [
    "https://open.feishu.cn",
    "https://open.larksuite.com",
]

TOKEN_PATH_APP = "/open-apis/auth/v3/app_access_token/internal"
TOKEN_PATH_TENANT = "/open-apis/auth/v3/tenant_access_token/internal"
CONTACT_DEPT_TMPL = "/open-apis/contact/v3/departments/{dept_id}"
DOC_META_TMPL = "/open-apis/docx/v1/documents/{doc_id}"
DOC_BLOCKS_TMPL = "/open-apis/docx/v1/documents/{doc_id}/blocks/{block_id}?page_size={ps}&page_token={pt}"

LOG_ID_PATTERN = re.compile(r'"log_id"\s*:\s*"([0-9A-Z]+)"')

class FeishuClient:
    def __init__(self, app_id: str, app_secret: str, base_domains: Optional[List[str]] = None, debug: bool = False):
        self.app_id = app_id
        self.app_secret = app_secret
        self.base_domains = base_domains or DEFAULT_DOMAINS
        self.debug = debug
        self.app_access_token: Optional[str] = None
        self.tenant_access_token: Optional[str] = None
        self.active_base: Optional[str] = None

    # ---------------- Token Retrieval ----------------
    def _post_json(self, base: str, path: str, payload: Dict, timeout: int = 10) -> Tuple[int, str, Dict]:
        url = base + path
        if self.debug:
            # Escape braces to show a literal dict shape without evaluating formatting
            print(f"[DBG] POST {url} payload={{'app_id': '***', 'app_secret': '***'}}")
        try:
            resp = requests.post(url, json=payload, timeout=timeout)
        except requests.RequestException as e:
            return 0, f"network error: {e}", {}
        text = resp.text
        try:
            data = resp.json()
        except ValueError:
            data = {}
        return resp.status_code, text, data

    def _retry_token(self, path: str, retries: int = 3) -> Dict:
        payload = {"app_id": self.app_id, "app_secret": self.app_secret}
        last_err: Optional[str] = None
        for attempt in range(1, retries + 1):
            for base in self.base_domains:
                status, text, data = self._post_json(base, path, payload)
                if status == 200 and data.get("code") == 0:
                    self.active_base = base
                    if self.debug:
                        print(f"[DBG] Token success via {base} path={path}")
                    return data
                # Compose diagnostic
                snippet = text[:400]
                log_id = None
                m = LOG_ID_PATTERN.search(text)
                if m:
                    log_id = m.group(1)
                if self.debug:
                    print(f"[DBG] Token attempt {attempt} base={base} status={status} code={data.get('code')} log_id={log_id} snippet={snippet}")
                last_err = f"status={status} code={data.get('code')} log_id={log_id} snippet={snippet}" if status else text
            if attempt < retries:
                delay = 0.6 * (2 ** (attempt - 1))
                if self.debug:
                    print(f"[DBG] Retry all domains in {delay:.2f}s ...")
                time.sleep(delay)
        raise RuntimeError(f"Token retrieval failed after {retries} attempts: {last_err}")

    def get_app_access_token(self) -> str:
        if self.app_access_token:
            return self.app_access_token
        data = self._retry_token(TOKEN_PATH_APP)
        self.app_access_token = data.get("app_access_token")
        if not self.app_access_token:
            raise RuntimeError("app_access_token missing in response")
        return self.app_access_token

    def get_tenant_access_token(self) -> str:
        if self.tenant_access_token:
            return self.tenant_access_token
        data = self._retry_token(TOKEN_PATH_TENANT)
        self.tenant_access_token = data.get("tenant_access_token")
        if not self.tenant_access_token:
            raise RuntimeError("tenant_access_token missing in response")
        return self.tenant_access_token

    # ---------------- Generic GET ----------------
    def _get(self, path: str, token: str, timeout: int = 10) -> Dict:
        if not self.active_base:
            # fallback to first domain
            self.active_base = self.base_domains[0]
        url = self.active_base + path
        if self.debug:
            print(f"[DBG] GET {url}")
        try:
            resp = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=timeout)
        except requests.RequestException as e:
            raise RuntimeError(f"GET {url} network error: {e}")
        if self.debug:
            print(f"[DBG] GET status={resp.status_code}")
        text = resp.text
        try:
            data = resp.json()
        except ValueError:
            raise RuntimeError(f"Response not JSON: {text[:300]}")
        if data.get("code") not in (0, None):
            log_id = data.get("log_id")
            raise RuntimeError(f"API logical error code={data.get('code')} msg={data.get('msg')} log_id={log_id}")
        return data

    # ---------------- Contact Department Example ----------------
    def get_department(self, dept_id: str) -> Dict:
        token = self.get_tenant_access_token()
        path = CONTACT_DEPT_TMPL.format(dept_id=dept_id)
        return self._get(path, token)

    # ---------------- Docx Fetch (Meta + Blocks) ----------------
    def get_doc_meta(self, doc_id: str) -> Dict:
        token = self.get_tenant_access_token()
        path = DOC_META_TMPL.format(doc_id=doc_id)
        return self._get(path, token)

    def get_doc_blocks(self, doc_id: str, max_depth: int = 6) -> List[Dict]:
        token = self.get_tenant_access_token()
        collected: List[Dict] = []
        def recurse(block_id: str, depth: int = 0, page_token: str = ""):
            if depth > max_depth:
                return
            while True:
                path = DOC_BLOCKS_TMPL.format(doc_id=doc_id, block_id=block_id, ps=200, pt=page_token)
                data = self._get(path, token)
                items = data.get("data", {}).get("items", [])
                for it in items:
                    collected.append(it)
                    has_child = it.get("has_child") or (it.get("children") not in (None, []))
                    if has_child:
                        cid = it.get("block_id") or it.get("id")
                        if cid:
                            try:
                                recurse(cid, depth + 1, "")
                            except Exception as e:
                                print(f"[WARN] child {cid} failed: {e}")
                page_token_next = data.get("data", {}).get("page_token")
                if not page_token_next:
                    break
                page_token = page_token_next
                time.sleep(0.04)
        recurse(doc_id, 0, "")
        return collected

    # ---------------- Simple Block -> Text Extraction ----------------
    def blocks_to_markdown(self, blocks: List[Dict]) -> str:
        lines: List[str] = []
        for b in blocks:
            bt = (b.get("block_type") or b.get("type") or "").lower()
            block_content = b.get("block") or {}
            texts: List[str] = []
            def walk(v):
                if isinstance(v, dict):
                    if "text_run" in v and isinstance(v["text_run"], dict):
                        c = v["text_run"].get("content")
                        if c:
                            texts.append(c.replace('\n', ' ').strip())
                    for vv in v.values():
                        walk(vv)
                elif isinstance(v, list):
                    for i in v:
                        walk(i)
            walk(block_content)
            merged = " ".join([t for t in texts if t])
            merged = merged.strip()
            if not merged:
                continue
            if bt.startswith("heading"):
                level = bt[-1] if bt[-1].isdigit() else "2"
                lines.append(f"{'#'*int(level)} {merged}")
            elif bt.startswith("bullet") or bt.startswith("ordered") or bt.startswith("list"):
                lines.append(f"- {merged}")
            else:
                lines.append(merged)
        # collapse blank lines
        cleaned: List[str] = []
        prev_blank = False
        for l in lines:
            blank = not l.strip()
            if blank and prev_blank:
                continue
            cleaned.append(l)
            prev_blank = blank
        return "\n".join(cleaned)

# ---------------- Utility ----------------

def extract_doc_id(maybe_url: str) -> str:
    maybe_url = maybe_url.strip()
    m = re.search(r"/docx/([A-Za-z0-9]+)", maybe_url)
    return m.group(1) if m else maybe_url


def main():
    ap = argparse.ArgumentParser(description="Feishu Unified Access Demo")
    ap.add_argument("--app-id", help="Override FEISHU_APP_ID env")
    ap.add_argument("--app-secret", help="Override FEISHU_APP_SECRET env")
    ap.add_argument("--dept-id", help="Department ID for contact API test")
    ap.add_argument("--doc-id", help="Docx ID or full URL")
    ap.add_argument("--fetch-doc", action="store_true", help="Fetch doc meta + blocks (requires --doc-id)")
    ap.add_argument("--save", help="Save extracted markdown")
    ap.add_argument("--debug", action="store_true", help="Verbose debug")
    args = ap.parse_args()

    app_id = args.app_id or os.environ.get("FEISHU_APP_ID")
    app_secret = args.app_secret or os.environ.get("FEISHU_APP_SECRET")
    if not app_id or not app_secret:
        print("[ERR] app_id/app_secret missing (use --app-id/--app-secret or env vars)")
        sys.exit(2)

    if args.doc_id:
        args.doc_id = extract_doc_id(args.doc_id)

    client = FeishuClient(app_id, app_secret, debug=args.debug)

    # Acquire tokens early to surface errors
    try:
        client.get_app_access_token()
        if args.debug:
            print("[DBG] app_access_token obtained")
        client.get_tenant_access_token()
        if args.debug:
            print("[DBG] tenant_access_token obtained")
    except Exception as e:
        print(f"[ERROR] Token flow failed: {e}")
        sys.exit(3)

    if args.dept_id:
        try:
            dept = client.get_department(args.dept_id)
            print("[DEPT]", json.dumps(dept, ensure_ascii=False)[:800])
        except Exception as e:
            print(f"[ERROR] Department fetch failed: {e}")

    if args.fetch_doc and args.doc_id:
        try:
            meta = client.get_doc_meta(args.doc_id)
            print("[DOC_META]", json.dumps(meta, ensure_ascii=False)[:800])
        except Exception as e:
            print(f"[ERROR] Doc meta fetch failed: {e}")
        try:
            blocks = client.get_doc_blocks(args.doc_id)
            print(f"[INFO] Blocks fetched: {len(blocks)}")
            md = client.blocks_to_markdown(blocks)
            preview = md[:1500] + ("..." if len(md) > 1500 else "")
            print("===== Markdown Preview =====\n" + preview)
            if args.save:
                with open(args.save, "w", encoding="utf-8") as f:
                    f.write(md)
                print(f"[INFO] Saved markdown -> {args.save}")
        except Exception as e:
            print(f"[ERROR] Doc blocks fetch failed: {e}")

    if not (args.dept_id or (args.fetch_doc and args.doc_id)):
        print("[INFO] No action specified. Use --dept-id or --fetch-doc with --doc-id")

if __name__ == "__main__":
    main()
