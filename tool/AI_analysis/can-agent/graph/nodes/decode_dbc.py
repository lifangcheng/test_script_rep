from __future__ import annotations

from core.pipeline import run_core_pipeline_streaming
from graph.state import CANState


def decode_dbc(state: CANState) -> CANState:
    stage = "decode_dbc"
    state.add_stage_event({"stage": stage, "status": "running", "error": None})

    cfg = state.config or {}
    if state.output_dir:
        cfg = dict(cfg)
        cfg["out"] = state.output_dir
        cfg["skills_rules"] = state.skills_rules
        # 允许通过 config 控制 skip_anomaly/skip_diagnosis，但默认不跳过

    res = run_core_pipeline_streaming(
        blf_path=state.blf_path,
        dbc_path=state.dbc_path,
        config=cfg,
        whitelist_can_ids=state.whitelist_can_ids,
        whitelist_signals=state.whitelist_signals,
    )
    if not res.ok:
        err = res.error or {"code": "unknown", "message": "unknown", "fix": ""}
        return state.fail(stage, err["code"], err["message"], err["fix"])

    payload = res.value
    state.decoded_df = payload.get("decoded_df")
    state.anomalies = payload.get("anomalies")
    state.anomaly_slices = payload.get("slices")
    state.diagnosis = payload.get("diagnosis")

    state.add_stage_event({"stage": stage, "status": "success", "error": None})
    return state
