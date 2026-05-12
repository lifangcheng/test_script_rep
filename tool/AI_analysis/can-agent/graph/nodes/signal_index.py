from __future__ import annotations

from core.signals import export_signals
from graph.state import CANState


def signal_index(state: CANState) -> CANState:
    stage = "signal_index"
    state.add_stage_event({"stage": stage, "status": "running", "error": None})

    if state.decoded_df is None:
        return state.fail(
            stage,
            "decoded_df_missing",
            "decoded_df is None; cannot build signal index.",
            "Ensure build_dataframe outputs decoded_df.",
        )

    if state.anomalies is None:
        return state.fail(
            stage,
            "anomalies_missing",
            "anomalies is None; cannot build signal index.",
            "Ensure anomaly_detect outputs anomalies.",
        )

    res = export_signals(output_dir=state.output_dir, decoded_df=state.decoded_df, anomalies=state.anomalies)
    if not res.ok:
        err = res.error or {"code": "unknown", "message": "unknown", "fix": ""}
        return state.fail(stage, err["code"], err["message"], err["fix"])

    state.signals_index = res.value

    state.add_stage_event({"stage": stage, "status": "success", "error": None})
    return state
