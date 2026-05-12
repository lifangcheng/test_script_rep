from __future__ import annotations

from pathlib import Path
from typing import Iterator, List, Optional, Set

from core.types import CanRawMsg, CoreResult


# Prefer asammdf BLF reader (handles CAN FD, Vector BLF), fallback to python-can.
def _iter_blf_asammdf(blf_path: str, chunk_size: int, whitelist_can_ids: Optional[Set[int]]) -> Iterator[List[CanRawMsg]]:
    try:
        from asammdf.blf import BLF  # type: ignore
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"asammdf.blf not available: {e}")

    blf = BLF(blf_path)
    buf: List[CanRawMsg] = []
    for msg in blf:
        can_id_val = int(getattr(msg, "ArbID", msg.ID if hasattr(msg, "ID") else 0))
        if whitelist_can_ids and can_id_val not in whitelist_can_ids:
            continue
        data_bytes = getattr(msg, "DataBytes", getattr(msg, "Data", b"")) or b""
        timestamp = float(getattr(msg, "Timestamp", getattr(msg, "TimeStamp", 0.0)))
        channel = int(getattr(msg, "Channel", getattr(msg, "BusChannel", 0)) or 0)
        is_ext = bool(getattr(msg, "EDL", False) or getattr(msg, "ExtendedFrame", False))
        buf.append(
            CanRawMsg(
                timestamp=timestamp,
                channel=channel,
                can_id=can_id_val,
                data=bytes(data_bytes),
                is_extended_id=is_ext,
            )
        )
        if len(buf) >= chunk_size:
            yield buf
            buf = []
    if buf:
        yield buf


def _iter_blf_python_can(blf_path: str, chunk_size: int, whitelist_can_ids: Optional[Set[int]]) -> Iterator[List[CanRawMsg]]:
    try:
        import can  # type: ignore
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"python-can not available: {e}")

    reader = can.BLFReader(blf_path)
    buf: List[CanRawMsg] = []
    for msg in reader:
        can_id_val = int(getattr(msg, "arbitration_id", 0))
        if whitelist_can_ids and can_id_val not in whitelist_can_ids:
            continue
        buf.append(
            CanRawMsg(
                timestamp=float(getattr(msg, "timestamp", 0.0)),
                channel=int(getattr(msg, "channel", 0) or 0),
                can_id=can_id_val,
                data=bytes(getattr(msg, "data", b"")),
                is_extended_id=bool(getattr(msg, "is_extended_id", False)),
            )
        )
        if len(buf) >= chunk_size:
            yield buf
            buf = []

    if buf:
        yield buf


def read_blf(
    blf_path: str,
    chunk_size: int = 200_000,
    max_msgs: Optional[int] = None,
    whitelist_can_ids: Optional[List[int]] = None,
) -> CoreResult:
    p = Path(blf_path)
    if not p.exists():
        return CoreResult(
            ok=False,
            error={
                "code": "blf_not_found",
                "message": f"BLF not found: {p}",
                "fix": "Check the BLF path.",
            },
        )

    try:
        raw: List[CanRawMsg] = []
        wl_set: Optional[Set[int]] = set(whitelist_can_ids) if whitelist_can_ids else None

        # Try asammdf first
        try:
            for chunk in _iter_blf_asammdf(str(p), chunk_size=chunk_size, whitelist_can_ids=wl_set):
                raw.extend(chunk)
                if max_msgs is not None and len(raw) >= max_msgs:
                    raw = raw[:max_msgs]
                    break
        except Exception:
            # Fallback to python-can
            for chunk in _iter_blf_python_can(str(p), chunk_size=chunk_size, whitelist_can_ids=wl_set):
                raw.extend(chunk)
                if max_msgs is not None and len(raw) >= max_msgs:
                    raw = raw[:max_msgs]
                    break

        return CoreResult(ok=True, value=raw)
    except Exception as e:  # noqa: BLE001
        return CoreResult(
            ok=False,
            error={
                "code": "blf_read_failed",
                "message": f"Failed to read BLF: {e}",
                "fix": "Install python-can/asammdf and ensure the BLF is valid.",
            },
        )
