from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pandas as pd


def _normalize_stage_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    # Enforce node event schema:
    # {
    #   "stage": "string",
    #   "status": "running|success|failed",
    #   "error": {"code": "...", "message": "...", "fix": "..."} | None
    # }
    stage = str(payload.get("stage", ""))
    status = str(payload.get("status", ""))

    err = payload.get("error", None)
    if err is None:
        error: Optional[Dict[str, Any]] = None
    else:
        error = {
            "code": str(err.get("code", "unknown")),
            "message": str(err.get("message", "unknown")),
            "fix": str(err.get("fix", "")),
        }

    return {"stage": stage, "status": status, "error": error}


@dataclass
class CANState:
    blf_path: str
    dbc_path: str
    config: Dict[str, Any]
    enable_ai: bool
    output_dir: str

    raw_msgs: Optional[List[Dict[str, Any]]] = None
    decoded_df: Optional[pd.DataFrame] = None
    anomalies: Optional[List[Dict[str, Any]]] = None
    diagnosis: Optional[Dict[str, Any]] = None

    # skills / whitelist
    skills_rules: Optional[List[Dict[str, Any]]] = None
    skills_knowledge: Optional[Dict[str, str]] = None
    whitelist_can_ids: Optional[List[int]] = None
    whitelist_signals: Optional[List[str]] = None

    # slice outputs
    anomaly_slices: Optional[Dict[str, Any]] = None

    report_path: Optional[str] = None
    signals_index: Optional[Dict[str, Any]] = None
    ai_report: Optional[Dict[str, Any]] = None

    # time base
    base_ts: Optional[float] = None
    base_iso: Optional[str] = None

    status: str = "created"  # created|running|success|failed
    error: Optional[Dict[str, Any]] = None
    logs: List[Dict[str, Any]] = field(default_factory=list)

    def add_stage_event(self, payload: Dict[str, Any]) -> None:
        self.logs.append(_normalize_stage_payload(payload))

    def fail(self, stage: str, code: str, message: str, fix: str) -> "CANState":
        self.status = "failed"
        self.error = {
            "stage": stage,
            "code": code,
            "message": message,
            "fix": fix,
        }
        self.add_stage_event(
            {
                "stage": stage,
                "status": "failed",
                "error": {"code": code, "message": message, "fix": fix},
            }
        )
        return self
