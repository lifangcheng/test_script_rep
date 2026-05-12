import time
from typing import Any, Dict

import httpx

from core.types import CoreResult

# 与 tool/app_main.py 对齐的模型调用配置
DEFAULT_BASE_URL = "http://model.mify.ai.srv"
API_KEY = "sk-HXFiS9bEeg95uypM96B6kJfKaxe3ze52FUeQEriGGaGIIefS"
MAX_RETRY_ATTEMPTS = 5  # 增加重试次数

MODEL_PROVIDER_HEADER = {
    "Qwen-235B-A22B": "openai_api_compatible",
    "deepseek-v3.1": "openai_api_compatible",
    "Qwen2.5-VL-72B-Instruct-AWQ": "openai_api_compatible",
}
FALLBACK_ALLOWED = set(MODEL_PROVIDER_HEADER.keys())


def _classify_http_error(status_code: int) -> str:
    if status_code in (401, 403):
        return "auth_failed"
    if status_code == 429:
        return "rate_limited"
    if status_code in (502, 503, 504):
        return "gateway_error"
    return "invalid_response"


def _mk_url(base_url: str, path: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        return f"{base}{path}"
    return f"{base}/v1{path}"


def _success(data: Any) -> CoreResult:
    return CoreResult(ok=True, value=data)


def _failure(code: str, message: str, fix: str) -> CoreResult:
    return CoreResult(ok=False, error={"code": code, "message": message, "fix": fix})


def call_chat_completions(
    *,
    base_url: str,
    api_key: str,
    model: str,
    payload: Dict[str, Any],
    timeout_s: float,
) -> CoreResult:
    """与 tool/app_main.py 的 call_model 保持一致：chat 优先，必要时回退 completions。"""

    api_key = api_key or API_KEY
    if not api_key:
        return _failure("ai_key_missing", "AI api_key is empty.", "Set config.ai.api_key (e.g. via config/ai_strict.yaml) and rerun with --ai.")
    provider = MODEL_PROVIDER_HEADER.get(model, "openai_api_compatible")

    chat_url = _mk_url(base_url or DEFAULT_BASE_URL, "/chat/completions")
    comp_url = _mk_url(base_url or DEFAULT_BASE_URL, "/completions")

    headers = {"Content-Type": "application/json", "X-Model-Provider-Id": provider}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    def _do(client: httpx.Client, url: str) -> CoreResult:
        try:
            resp = client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException as e:
            return _failure("timeout", f"AI request timeout: {e}", "Increase timeout_s or check network connectivity.")
        except Exception as e:  # noqa: BLE001
            return _failure("gateway_error", f"AI request failed: {e}", "Check base_url and network connectivity.")

        if resp.status_code >= 400:
            return _failure(
                _classify_http_error(resp.status_code),
                f"AI HTTP {resp.status_code}: {resp.text}",
                "Verify API key, quota, and base_url.",
            )

        try:
            data = resp.json()
        except Exception as e:  # noqa: BLE001
            return _failure(
                "invalid_response",
                f"AI response is not JSON: {e}",
                "Check the gateway/proxy and model endpoint compatibility.",
            )
        return _success(data)

    # chat.completions 优先
    with httpx.Client(timeout=timeout_s) as client:
        for attempt in range(MAX_RETRY_ATTEMPTS):
            res = _do(client, chat_url)
            if res.ok:
                return res

            code = (res.error or {}).get("code")
            # 对 5xx/429 退避重试
            if code in ("gateway_error", "rate_limited") and attempt < MAX_RETRY_ATTEMPTS - 1:
                time.sleep(1.5 * (attempt + 1))
                continue

            if code == "auth_failed":
                return res

            # 400 系列且允许回退时，跳出进入 completions
            if code == "invalid_response" and model in FALLBACK_ALLOWED:
                break

            return res

    # completions 回退
    if model in FALLBACK_ALLOWED:
        with httpx.Client(timeout=timeout_s) as client:
            for attempt in range(MAX_RETRY_ATTEMPTS):
                res = _do(client, comp_url)
                if res.ok:
                    return res

                code = (res.error or {}).get("code")
                if code in ("gateway_error", "rate_limited") and attempt < MAX_RETRY_ATTEMPTS - 1:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                return res

    return _failure("invalid_response", "AI call failed (chat+completions)", "Check model availability and network.")


def extract_text_from_chat_completions(resp: Dict[str, Any]) -> CoreResult:
    try:
        choices = resp.get("choices") or []
        if not choices:
            raise ValueError("missing choices")
        c0 = choices[0]
        # chat.completions
        msg = c0.get("message") or {}
        content = msg.get("content") if isinstance(msg, dict) else None
        if isinstance(content, str) and content.strip():
            return _success(content)
        # completions 回退
        text = c0.get("text") if isinstance(c0, dict) else None
        if isinstance(text, str) and text.strip():
            return _success(text)
        raise ValueError("missing content/text")
    except Exception as e:  # noqa: BLE001
        return _failure(
            "invalid_response",
            f"Unexpected AI response shape: {e}",
            "Ensure /v1/chat/completions returns OpenAI-compatible schema.",
        )
