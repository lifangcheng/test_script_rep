from __future__ import annotations

from core.anomaly import detect_anomalies
from graph.state import CANState


def anomaly_detect(state: CANState) -> CANState:
    stage = "anomaly_detect"
    state.add_stage_event({"stage": stage, "status": "running", "error": None})

    if state.decoded_df is None:
        return state.fail(
            stage,
            "decoded_df_missing",
            "decoded_df is None; cannot detect anomalies.",
            "Ensure decode_dbc/build_dataframe produce decoded_df.",
        )

    # compute anomalies if not already present
    if state.anomalies is None:
        res = detect_anomalies(state.decoded_df, config=state.config or {}, skills=state.skills_rules)
        if not res.ok:
            err = res.error or {"code": "unknown", "message": "unknown", "fix": ""}
            return state.fail(stage, err["code"], err["message"], err["fix"])
        payload = res.value
        state.anomalies = payload.get("anomalies", payload)
        state.anomaly_slices = payload.get("slices")

    state.add_stage_event({"stage": stage, "status": "success", "error": None})
    return state
