from __future__ import annotations

from core.report import generate_reports
from graph.state import CANState


def report_generate(state: CANState) -> CANState:
    stage = "report_generate"
    state.add_stage_event({"stage": stage, "status": "running", "error": None})

    if state.decoded_df is None:
        return state.fail(
            stage,
            "decoded_df_missing",
            "decoded_df is None; cannot generate report.",
            "Ensure decode_dbc/build_dataframe produce decoded_df.",
        )

    if state.anomalies is None:
        return state.fail(
            stage,
            "anomalies_missing",
            "anomalies is None; cannot generate report.",
            "Ensure anomaly_detect produces anomalies.",
        )

    if state.diagnosis is None:
        return state.fail(
            stage,
            "diagnosis_missing",
            "diagnosis is None; cannot generate report.",
            "Ensure summarize produces diagnosis.",
        )

    res = generate_reports(
        output_dir=state.output_dir,
        decoded_df=state.decoded_df,
        anomalies=state.anomalies,
        diagnosis=state.diagnosis,
        ai_report=state.ai_report,
        base_ts=state.base_ts,
        base_iso=state.base_iso,
    )
    if not res.ok:
        err = res.error or {"code": "unknown", "message": "unknown", "fix": ""}
        return state.fail(stage, err["code"], err["message"], err["fix"])

    state.report_path = res.value["report_path"]

    state.add_stage_event({"stage": stage, "status": "success", "error": None})
    return state
