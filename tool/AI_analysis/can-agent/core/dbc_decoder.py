from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from core.types import CanRawMsg, CoreResult


def _load_dbc(dbc_path: str):
    try:
        import cantools  # type: ignore
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"cantools not available: {e}")

    return cantools.database.load_file(dbc_path)


def decode_with_dbc(
    dbc_path: str,
    raw_msgs: List[CanRawMsg],
    *,
    allow_unknown_ids: bool = True,
    whitelist_signals: Optional[List[str]] = None,
) -> CoreResult:
    p = Path(dbc_path)
    if not p.exists():
        return CoreResult(
            ok=False,
            error={
                "code": "dbc_not_found",
                "message": f"DBC not found: {p}",
                "fix": "Check the DBC path.",
            },
        )

    try:
        db = _load_dbc(str(p))
    except Exception as e:  # noqa: BLE001
        return CoreResult(
            ok=False,
            error={
                "code": "dbc_load_failed",
                "message": f"Failed to load DBC: {e}",
                "fix": "Ensure cantools is installed and DBC is valid.",
            },
        )

    rows: List[Dict[str, Any]] = []
    unknown = 0

    whitelist_sig_set = set(whitelist_signals) if whitelist_signals else None

    for m in raw_msgs:
        try:
            msg = db.get_message_by_frame_id(m.can_id)
            decoded = msg.decode(m.data, decode_choices=False)
            for sig_name, val in decoded.items():
                if whitelist_sig_set and sig_name not in whitelist_sig_set:
                    continue
                sig = msg.get_signal_by_name(sig_name)
                rows.append(
                    {
                        "timestamp": m.timestamp,
                        "channel": m.channel,
                        "can_id": m.can_id,
                        "message": msg.name,
                        "signal": sig_name,
                        "value": float(val) if isinstance(val, (int, float)) else val,
                        "unit": getattr(sig, "unit", "") or "",
                    }
                )
        except Exception:
            unknown += 1
            if not allow_unknown_ids:
                return CoreResult(
                    ok=False,
                    error={
                        "code": "dbc_decode_failed",
                        "message": f"Failed decoding can_id={m.can_id}",
                        "fix": "Ensure the DBC contains this frame_id or enable allow_unknown_ids.",
                    },
                )
            continue

    if not rows:
        return CoreResult(
            ok=False,
            error={
                "code": "no_decoded_signals",
                "message": "No signals decoded (DBC mismatch or empty BLF).",
                "fix": "Verify BLF/DBC pairing and that BLF contains CAN traffic.",
            },
        )

    df = pd.DataFrame.from_records(rows)
    df.attrs["unknown_frames"] = unknown
    return CoreResult(ok=True, value=df)
