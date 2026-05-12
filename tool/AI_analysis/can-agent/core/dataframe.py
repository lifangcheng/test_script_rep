from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from core.types import CoreResult


UNIFIED_COLUMNS = ["timestamp", "channel", "can_id", "message", "signal", "value", "unit"]


def normalize_decoded_df(df: pd.DataFrame) -> CoreResult:
    missing = set(UNIFIED_COLUMNS) - set(df.columns)
    if missing:
        return CoreResult(
            ok=False,
            error={
                "code": "schema_mismatch",
                "message": f"decoded_df missing required columns: {sorted(missing)}",
                "fix": "Ensure DBC decode outputs unified columns.",
            },
        )

    out = df.copy()

    out["timestamp"] = pd.to_numeric(out["timestamp"], errors="coerce").astype(float)
    out["channel"] = pd.to_numeric(out["channel"], errors="coerce").fillna(0).astype(int)
    out["can_id"] = pd.to_numeric(out["can_id"], errors="coerce").fillna(0).astype(int)

    out["message"] = out["message"].astype(str)
    out["signal"] = out["signal"].astype(str)
    out["unit"] = out["unit"].fillna("").astype(str)

    # value can be numeric or string; keep as-is but normalize numpy scalars
    def _norm_value(v: Any) -> Any:
        try:
            if hasattr(v, "item"):
                return v.item()
        except Exception:
            pass
        return v

    out["value"] = out["value"].map(_norm_value)

    out = out.sort_values(["signal", "timestamp"], kind="mergesort").reset_index(drop=True)

    if out["timestamp"].isna().any():
        return CoreResult(
            ok=False,
            error={
                "code": "timestamp_invalid",
                "message": "Some rows have invalid timestamp after normalization.",
                "fix": "Ensure BLF parser provides valid timestamps and decoder passes them through.",
            },
        )

    return CoreResult(ok=True, value=out[UNIFIED_COLUMNS])
