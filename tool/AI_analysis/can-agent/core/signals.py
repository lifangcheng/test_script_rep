from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd

from core.types import CoreResult
from utils.io import write_json


def _sanitize_filename(name: str) -> str:
    safe = "".join(c if (c.isalnum() or c in "-_ .") else "_" for c in name)
    safe = safe.replace(" ", "_")
    return safe[:180] if len(safe) > 180 else safe


def _anomaly_spans_for_signal(anomalies: List[Dict[str, Any]], signal: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for a in anomalies:
        if str(a.get("signal")) != str(signal):
            continue
        out.append(
            {
                "kind": a.get("kind"),
                "severity": a.get("severity"),
                "start": a.get("start"),
                "end": a.get("end"),
                "count": a.get("count"),
                "evidence": a.get("evidence", {}),
            }
        )
    return out


def export_signals(
    *,
    output_dir: str,
    decoded_df: pd.DataFrame,
    anomalies: List[Dict[str, Any]],
) -> CoreResult:
    try:
        sig_dir = Path(output_dir) / "signals"
        data_dir = sig_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        idx: List[Dict[str, Any]] = []

        for signal, g in decoded_df.sort_values("timestamp").groupby("signal", dropna=False):
            sig_name = str(signal)
            file_name = _sanitize_filename(sig_name) + ".json"
            rel_path = f"signals/data/{file_name}"

            times = g["timestamp"].astype(float).tolist()
            values = g["value"].tolist()
            units = g["unit"].fillna("").astype(str)
            unit = units.iloc[0] if len(units) else ""
            can_ids = g["can_id"].astype(int).unique().tolist()

            spans = _anomaly_spans_for_signal(anomalies, sig_name)

            payload = {
                "signal": sig_name,
                "unit": unit,
                "can_ids": can_ids,
                "series": {"timestamp": times, "value": values},
                "anomalies": spans,
            }
            write_json(str(data_dir / file_name), payload)

            idx.append(
                {
                    "signal": sig_name,
                    "unit": unit,
                    "can_ids": can_ids,
                    "count": int(len(g)),
                    "data_path": rel_path,
                    "anomaly_count": int(len(spans)),
                }
            )

        index_payload = {
            "generated_at": "1970-01-01T00:00:00Z",
            "total_signals": int(len(idx)),
            "signals": sorted(idx, key=lambda x: (-x["anomaly_count"], -x["count"], x["signal"])) ,
        }
        write_json(str(sig_dir / "index.json"), index_payload)

        return CoreResult(ok=True, value=index_payload)
    except Exception as e:  # noqa: BLE001
        return CoreResult(
            ok=False,
            error={
                "code": "signals_export_failed",
                "message": f"Failed to export signals: {e}",
                "fix": "Check output directory permissions and decoded_df schema.",
            },
        )
