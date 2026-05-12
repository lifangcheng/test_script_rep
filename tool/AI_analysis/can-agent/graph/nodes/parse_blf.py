from __future__ import annotations

from core.blf_reader import read_blf
from graph.state import CANState


def parse_blf(state: CANState) -> CANState:
    stage = "parse_blf"
    state.add_stage_event({"stage": stage, "status": "running", "error": None})

    # Keep a small sample of raw msgs for debugging/observability.
    max_msgs = int((state.config or {}).get("raw_sample_size", 2000))
    chunk_size = int((state.config or {}).get("chunk_size", 200_000))

    res = read_blf(
        state.blf_path,
        chunk_size=chunk_size,
        max_msgs=max_msgs,
        whitelist_can_ids=state.whitelist_can_ids,
    )
    if not res.ok:
        err = res.error or {"code": "unknown", "message": "unknown", "fix": ""}
        return state.fail(stage, err["code"], err["message"], err["fix"])

    # CanRawMsg is a dataclass; serialize to JSON-friendly dict.
    from core.types import to_jsonable_raw_msg

    state.raw_msgs = [to_jsonable_raw_msg(m) for m in res.value]

    state.add_stage_event({"stage": stage, "status": "success", "error": None})
    return state
