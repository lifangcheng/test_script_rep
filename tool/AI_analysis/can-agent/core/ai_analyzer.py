import json
from collections import Counter, defaultdict
from typing import Any, Dict, List

from core.ai_client import call_chat_completions, extract_text_from_chat_completions
from core.types import CoreResult


SYSTEM_PROMPT = """You are an expert automotive CAN log analyst.
Return ONLY valid JSON with keys:
summary, root_cause, confidence, highlights, suspicious_signals, suggestions
"""

PRIORITY_PREFIXES = ("flt", "warn", "dtc")
MAX_ANOMALIES = 200  # per run cap


def _aggregate(anomalies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # Already per-anomaly; just trim by severity/time
    sev_rank = {"critical": 3, "high": 2, "medium": 1, "low": 0}
    ordered = sorted(
        anomalies,
        key=lambda a: (
            -sev_rank.get(a.get("severity", ""), 0),
            a.get("signal", ""),
            a.get("start", 0.0),
        ),
    )
    return ordered[:MAX_ANOMALIES]


def _build_per_anomaly_payload(
    *,
    model: str,
    system_prompt: str,
    knowledge: str,
    anomaly: Dict[str, Any],
    slice_ctx: Any,
    user_prompt: str,
) -> Dict[str, Any]:
    user = {
        "anomaly": anomaly,
        "context_data": slice_ctx,
        "knowledge": knowledge,
        "instruction": user_prompt,
    }
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt or SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ],
        "temperature": 0.1,
    }


def analyze_with_ai(
    *,
    config: Dict[str, Any],
    anomalies: List[Dict[str, Any]],
    anomaly_slices: Dict[str, Any] | None,
    skills_knowledge: Dict[str, str] | None,
) -> CoreResult:
    ai_cfg = (config or {}).get("ai", {})
    base_url = str(ai_cfg.get("base_url", "http://localhost:8000/v1"))
    api_key = str(ai_cfg.get("api_key", ""))
    model = str(ai_cfg.get("model", "gpt-4.1-mini"))
    timeout_s = float(ai_cfg.get("timeout_s", 30))
    system_prompt = str(ai_cfg.get("system_prompt", SYSTEM_PROMPT))
    user_prompt = str(ai_cfg.get("user_prompt", ""))

    results: List[Dict[str, Any]] = []
    for a in _aggregate(anomalies):
        slice_ctx = None
        if anomaly_slices and a.get("slice_id") in anomaly_slices:
            slice_ctx = anomaly_slices[a["slice_id"]]

        knowledge = ""
        if skills_knowledge:
            # pick knowledge by source if available
            src = a.get("source") or a.get("rule_source") or ""
            for key, txt in skills_knowledge.items():
                if src and key in src:
                    knowledge = txt
                    break
            if not knowledge and len(skills_knowledge) == 1:
                knowledge = next(iter(skills_knowledge.values()))

        a = dict(a)
        try:
            from datetime import datetime, timezone

            if isinstance(a.get("start"), (int, float)) and float(a["start"]) > 1_000_000_000:
                a["start_iso"] = datetime.fromtimestamp(float(a["start"]), tz=timezone.utc).isoformat().replace("+00:00", "Z")
            if isinstance(a.get("end"), (int, float)) and float(a["end"]) > 1_000_000_000:
                a["end_iso"] = datetime.fromtimestamp(float(a["end"]), tz=timezone.utc).isoformat().replace("+00:00", "Z")
        except Exception:
            pass

        payload = _build_per_anomaly_payload(
            model=model,
            system_prompt=system_prompt,
            knowledge=knowledge,
            anomaly=a,
            slice_ctx=slice_ctx,
            user_prompt=user_prompt,
        )
        res = call_chat_completions(base_url=base_url, api_key=api_key, model=model, payload=payload, timeout_s=timeout_s)
        if not res.ok:
            return res

        res_text = extract_text_from_chat_completions(res.value)
        if not res_text.ok:
            return res_text

        # Debug: persist raw AI text for inspection
        try:
            out_dir = ai_cfg.get("out_dir")  # optional override for tests
            if not out_dir:
                out_dir = "outputs"
            raw_path = f"{out_dir}/ai_raw.txt"
            with open(raw_path, "a", encoding="utf-8") as f:
                f.write("==== ai response ===\n")
                f.write(res_text.value or "<empty>")
                f.write("\n\n")
        except Exception:
            # Do not fail pipeline on logging errors
            pass

        raw_text = res_text.value or ""
        raw_text = raw_text.strip()

        # Best-effort cleanup: drop code fences / prefixes and extract the first JSON object
        candidate = raw_text
        if "==== ai response" in candidate:
            parts = candidate.split("==== ai response ===")
            for part in parts:
                part = part.strip()
                if part:
                    candidate = part
                    break
        if candidate.startswith("```"):
            # remove leading/backtick fences and optional language tag
            candidate = candidate.strip("`").lstrip()
            if candidate.lower().startswith("json"):
                candidate = candidate[4:].lstrip()
        # If still not pure JSON, try to slice the first {...}
        if "{" in candidate and "}" in candidate:
            start = candidate.find("{")
            end = candidate.find("}", start)
            # take first balanced block heuristically by matching braces count
            brace = 0
            end_idx = None
            for idx, ch in enumerate(candidate[start:], start):
                if ch == "{":
                    brace += 1
                elif ch == "}":
                    brace -= 1
                    if brace == 0:
                        end_idx = idx
                        break
            if end_idx is not None:
                candidate = candidate[start : end_idx + 1]

        try:
            obj = json.loads(candidate)
        except Exception as e:  # noqa: BLE001
            return CoreResult(
                ok=False,
                error={
                    "code": "invalid_response",
                    "message": f"AI content is not valid JSON: {e}",
                    "fix": "Ensure the model returns JSON only (no markdown, no prose).",
                },
            )

        if not isinstance(obj, dict):
            return CoreResult(
                ok=False,
                error={
                    "code": "invalid_response",
                    "message": "AI response is not an object",
                    "fix": "Ensure the model returns JSON object.",
                },
            )

        if isinstance(a.get("can_id"), int):
            a["can_id_hex"] = hex(a["can_id"])
            del a["can_id"]

        results.append({"anomaly": a, "analysis": obj, "rule": {"id": a.get("rule_id"), "name": a.get("rule_name"), "condition": a.get("rule_condition"), "source": a.get("rule_source")}})

    return CoreResult(ok=True, value={"per_anomaly": results})
