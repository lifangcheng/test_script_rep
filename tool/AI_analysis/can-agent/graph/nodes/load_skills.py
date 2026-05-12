from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

from config.skills_loader import gather_skills, resolve_skills_dir
from graph.state import CANState


def load_skills(state: CANState) -> CANState:
    state.add_stage_event({"stage": "load_skills", "status": "running", "error": None})

    skills_cfg = (state.config or {}).get("skills", {})
    skills_dir = skills_cfg.get("dir", "")
    allow_missing = bool(skills_cfg.get("allow_missing", True))

    skills_path = resolve_skills_dir(state.config.get("config_path"), skills_dir)

    try:
        rules, knowledge = gather_skills(skills_path)
    except Exception as e:
        return state.fail(
            "load_skills",
            "skills_invalid",
            f"Failed to load skills under {skills_path}: {e}",
            "Fix invalid rules.yaml schema (see skills/SCHEMA.md)",
        )

    if not rules and not knowledge:
        if not allow_missing:
            return state.fail(
                "load_skills",
                "skills_not_found",
                f"No skills found under {skills_path}",
                "Provide --skills-dir or set skills.allow_missing=true",
            )
        # warn-only
        state.add_stage_event(
            {
                "stage": "load_skills",
                "status": "success",
                "error": None,
                "message": f"No skills found under {skills_path}, continue without skills",
            }
        )
        state.skills_rules = []
        state.skills_knowledge = {}
        state.whitelist_can_ids = []
        state.whitelist_signals = []
        return state

    # build whitelist from rules if present
    whitelist_can_ids: List[int] = []
    whitelist_signals: List[str] = []
    for r in rules:
        can_id = r.get("can_id")
        if can_id is not None:
            try:
                whitelist_can_ids.append(int(can_id))
            except Exception:
                pass
        sig = r.get("signal") or r.get("signal_name")
        if sig:
            whitelist_signals.append(str(sig))

    # merge with explicit whitelist from config
    wl_cfg = (state.config or {}).get("whitelist", {})
    for cid in wl_cfg.get("can_ids", []) or []:
        try:
            whitelist_can_ids.append(int(cid))
        except Exception:
            pass
    for sig in wl_cfg.get("signals", []) or []:
        whitelist_signals.append(str(sig))

    state.skills_rules = rules
    state.skills_knowledge = knowledge
    state.whitelist_can_ids = sorted(list({int(c) for c in whitelist_can_ids}))
    state.whitelist_signals = sorted(list({s for s in whitelist_signals}))

    state.add_stage_event({"stage": "load_skills", "status": "success", "error": None})
    return state
