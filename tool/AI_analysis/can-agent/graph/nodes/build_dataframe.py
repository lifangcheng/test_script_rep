from __future__ import annotations

from core.dataframe import normalize_decoded_df
from graph.state import CANState


def build_dataframe(state: CANState) -> CANState:
    stage = "build_dataframe"
    state.add_stage_event({"stage": stage, "status": "running", "error": None})

    if state.decoded_df is None:
        return state.fail(
            stage,
            "decoded_df_missing",
            "decoded_df is None; cannot build dataframe.",
            "Ensure decode_dbc outputs a DataFrame with required columns.",
        )

    res = normalize_decoded_df(state.decoded_df)
    if not res.ok:
        err = res.error or {"code": "unknown", "message": "unknown", "fix": ""}
        return state.fail(stage, err["code"], err["message"], err["fix"])

    state.decoded_df = res.value

    state.add_stage_event({"stage": stage, "status": "success", "error": None})
    return state
