from __future__ import annotations

from core.ai_analyzer import analyze_with_ai
from graph.state import CANState
from utils.io import write_json


def ai_analyze(state: CANState) -> CANState:
    stage = "ai_analyze"

    # AI node is optional and must not break main flow.
    if not state.enable_ai:
        state.add_stage_event({"stage": stage, "status": "success", "error": None})
        return state

    state.add_stage_event({"stage": stage, "status": "running", "error": None})

    if state.diagnosis is None or state.anomalies is None:
        state.add_stage_event(
            {
                "stage": stage,
                "status": "failed",
                "error": {
                    "code": "missing_inputs",
                    "message": "AI analysis requires diagnosis and anomalies.",
                    "fix": "Ensure summarize/anomaly_detect succeed before enabling AI.",
                },
            }
        )
        return state

    res = analyze_with_ai(
        config=state.config or {},
        anomalies=state.anomalies,
        anomaly_slices=state.anomaly_slices,
        skills_knowledge=state.skills_knowledge,
    )
    if not res.ok:
        err = res.error or {"code": "invalid_response", "message": "unknown", "fix": ""}
        state.add_stage_event({"stage": stage, "status": "failed", "error": err})
        return state

    state.ai_report = res.value
    write_json(f"{state.output_dir}/ai_report.json", state.ai_report)

    state.add_stage_event({"stage": stage, "status": "success", "error": None})
    return state
