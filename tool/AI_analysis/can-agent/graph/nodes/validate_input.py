from __future__ import annotations

from pathlib import Path

from config.loader import load_yaml_config
from graph.state import CANState


def validate_input(state: CANState) -> CANState:
    stage = "validate_input"
    state.status = "running"
    state.add_stage_event({"stage": stage, "status": "running", "error": None})

    blf = Path(state.blf_path)
    dbc = Path(state.dbc_path)

    if not blf.exists():
        return state.fail(
            stage,
            "blf_not_found",
            f"BLF file not found: {blf}",
            "Check the --blf path and file permissions.",
        )

    if not dbc.exists():
        return state.fail(
            stage,
            "dbc_not_found",
            f"DBC file not found: {dbc}",
            "Check the --dbc path and file permissions.",
        )

    cfg_path = state.config.get("config_path") if isinstance(state.config, dict) else None
    cfg_res = load_yaml_config(cfg_path)
    if cfg_res.error:
        return state.fail(stage, cfg_res.error["code"], cfg_res.error["message"], cfg_res.error["fix"])

    state.config = cfg_res.config.model_dump() if cfg_res.config else {}

    state.add_stage_event({"stage": stage, "status": "success"})
    return state
