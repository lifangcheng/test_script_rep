from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class CanRawMsg:
    timestamp: float
    channel: int
    can_id: int
    data: bytes
    is_extended_id: bool = False


def to_jsonable_raw_msg(m: CanRawMsg) -> Dict[str, Any]:
    return {
        "timestamp": m.timestamp,
        "channel": m.channel,
        "can_id": m.can_id,
        "data": m.data.hex(),
        "is_extended_id": m.is_extended_id,
    }


def from_jsonable_raw_msg(d: Dict[str, Any]) -> CanRawMsg:
    return CanRawMsg(
        timestamp=float(d["timestamp"]),
        channel=int(d.get("channel", 0)),
        can_id=int(d["can_id"]),
        data=bytes.fromhex(d.get("data", "")),
        is_extended_id=bool(d.get("is_extended_id", False)),
    )


@dataclass(frozen=True)
class Anomaly:
    kind: str
    severity: str
    signal: str
    can_id: int
    start: float
    end: float
    count: int
    evidence: Dict[str, Any]
    rule_source: Optional[str] = None
    rule_id: Optional[str] = None
    rule_name: Optional[str] = None
    rule_condition: Optional[str] = None


@dataclass
class CoreResult:
    ok: bool
    value: Optional[Any] = None
    error: Optional[Dict[str, str]] = None
