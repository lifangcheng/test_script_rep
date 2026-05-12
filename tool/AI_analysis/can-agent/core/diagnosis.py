from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, List

from core.types import CoreResult


def build_diagnosis(anomalies: List[Dict[str, Any]]) -> CoreResult:
    try:
        by_kind = Counter([a.get("kind", "unknown") for a in anomalies])
        by_signal: Dict[str, int] = Counter([a.get("signal", "") for a in anomalies])

        hot_signals = [
            {"signal": s, "count": int(c)}
            for s, c in sorted(by_signal.items(), key=lambda x: (-x[1], x[0]))
            if s
        ][:50]

        severity_count = Counter([a.get("severity", "unknown") for a in anomalies])

        diagnosis: Dict[str, Any] = {
            "summary": {
                "total_anomalies": int(len(anomalies)),
                "by_kind": dict(by_kind),
                "by_severity": dict(severity_count),
                "top_signals": hot_signals,
            },
            "notes": [
                "This diagnosis is rule-based. Validate against vehicle context and DBC definitions.",
            ],
        }
        return CoreResult(ok=True, value=diagnosis)
    except Exception as e:  # noqa: BLE001
        return CoreResult(
            ok=False,
            error={
                "code": "diagnosis_failed",
                "message": f"Failed to build diagnosis: {e}",
                "fix": "Check anomalies format and retry.",
            },
        )
