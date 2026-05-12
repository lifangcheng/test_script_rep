from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from core.anomaly import detect_anomalies
from core.blf_reader import _iter_blf_python_can
from core.dataframe import normalize_decoded_df
from core.dbc_decoder import decode_with_dbc
from core.diagnosis import build_diagnosis
from core.types import CoreResult


def _parse_base_time_from_name(blf_path: str) -> Tuple[Optional[float], Optional[str]]:
    name = Path(blf_path).stem
    import re

    m = re.search(r"(20\d{2})[-_](\d{2})[-_](\d{2})[-_](\d{2})[-_](\d{2})[-_](\d{2})", name)
    if not m:
        return None, None
    try:
        dt = datetime(
            year=int(m.group(1)),
            month=int(m.group(2)),
            day=int(m.group(3)),
            hour=int(m.group(4)),
            minute=int(m.group(5)),
            second=int(m.group(6)),
        )
        iso = dt.isoformat() + "Z"
        return dt.timestamp(), iso
    except Exception:
        return None, None


def run_core_pipeline_streaming(
    *,
    blf_path: str,
    dbc_path: str,
    config: Dict[str, Any],
    max_msgs: Optional[int] = None,
    whitelist_can_ids: Optional[List[int]] = None,
    whitelist_signals: Optional[List[str]] = None,
) -> CoreResult:
    out_dir = Path((config or {}).get("out", "")) if (config or {}).get("out") else None

    if not Path(blf_path).exists():
        return CoreResult(
            ok=False,
            error={"code": "blf_not_found", "message": f"BLF not found: {blf_path}", "fix": "Check --blf"},
        )
    if not Path(dbc_path).exists():
        return CoreResult(
            ok=False,
            error={"code": "dbc_not_found", "message": f"DBC not found: {dbc_path}", "fix": "Check --dbc"},
        )

    chunk_size = int((config or {}).get("chunk_size", 200_000))

    decoded_parts: List[pd.DataFrame] = []
    seen = 0

    try:
        wl_set = set(whitelist_can_ids) if whitelist_can_ids else None
        chunk_idx = 0
        for chunk in _iter_blf_python_can(blf_path, chunk_size=chunk_size, whitelist_can_ids=wl_set):
            chunk_idx += 1
            if max_msgs is not None:
                remaining = max_msgs - seen
                if remaining <= 0:
                    break
                chunk = chunk[:remaining]

            seen += len(chunk)
            res_df = decode_with_dbc(dbc_path, chunk, whitelist_signals=whitelist_signals)
            if not res_df.ok:
                return res_df

            res_norm = normalize_decoded_df(res_df.value)
            if not res_norm.ok:
                return res_norm

            decoded_parts.append(res_norm.value)
            if out_dir:
                out_dir.mkdir(parents=True, exist_ok=True)
                res_norm.value.to_parquet(out_dir / f"chunk_{chunk_idx}.parquet", index=False)

        if not decoded_parts:
            return CoreResult(
                ok=False,
                error={
                    "code": "no_decoded_signals",
                    "message": "No decoded data produced.",
                    "fix": "Verify BLF contains frames and matches DBC.",
                },
            )

        decoded_df = pd.concat(decoded_parts, ignore_index=True)
        decoded_df = decoded_df.sort_values(["signal", "timestamp"], kind="mergesort").reset_index(drop=True)

        if out_dir:
            out_dir.mkdir(parents=True, exist_ok=True)
            decoded_df.to_parquet(out_dir / "decoded.parquet", index=False)

        # allow disabling anomaly/diagnosis via config
        if (config or {}).get("skip_anomaly"):
            res_anom = CoreResult(ok=True, value={"anomalies": [], "slices": None})
        else:
            res_anom = detect_anomalies(
                decoded_df,
                config=config or {},
                skills=(config or {}).get("skills_rules") or None,
            )
            if not res_anom.ok:
                return res_anom

        if (config or {}).get("skip_diagnosis"):
            res_diag = CoreResult(ok=True, value=[])
        else:
            res_diag = build_diagnosis(res_anom.value if isinstance(res_anom.value, list) else res_anom.value.get("anomalies", []))
            if not res_diag.ok:
                return res_diag

        base_ts, base_iso = _parse_base_time_from_name(blf_path)

        return CoreResult(
            ok=True,
            value={
                "decoded_df": decoded_df,
                "anomalies": res_anom.value.get("anomalies", res_anom.value) if isinstance(res_anom.value, dict) else res_anom.value,
                "slices": res_anom.value.get("slices") if isinstance(res_anom.value, dict) else None,
                "diagnosis": res_diag.value,
                "base_ts": base_ts,
                "base_iso": base_iso,
            },
        )
    except Exception as e:  # noqa: BLE001
        return CoreResult(
            ok=False,
            error={
                "code": "streaming_pipeline_failed",
                "message": f"Streaming pipeline failed: {e}",
                "fix": "Check BLF/DBC validity and dependencies (python-can, cantools).",
            },
        )
