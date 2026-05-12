from __future__ import annotations

from graph.state import CANState
from utils.io import write_json


def summarize(state: CANState) -> CANState:
    stage = "summarize"
    state.add_stage_event({"stage": stage, "status": "running", "error": None})

    if state.diagnosis is None:
        return state.fail(
            stage,
            "diagnosis_missing",
            "diagnosis is missing after decode.",
            "Ensure decode_dbc computes diagnosis or switch pipeline mode.",
        )

    write_json(f"{state.output_dir}/diagnosis.json", state.diagnosis)

    state.add_stage_event({"stage": stage, "status": "success", "error": None})
    return state
