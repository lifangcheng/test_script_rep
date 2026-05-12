from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

from utils.io import _read_text_smart, read_json_or_yaml

RULE_PATTERNS = ["rules.yaml", "rules.yml", "rules.json", "*.rules.yaml", "*.rules.yml", "*.rules.json"]
KNOWLEDGE_PATTERNS = ["knowledge.txt", "*.knowledge.txt", "*.md"]


def normalize_rule(raw: Dict[str, Any], *, source: str, index: int) -> Dict[str, Any]:
    rid = str(raw.get("id") or f"{Path(source).stem}_{index}")
    name = str(raw.get("name") or raw.get("skill_name") or rid)

    target_raw = raw.get("target")
    target: Dict[str, Any] = dict(target_raw) if isinstance(target_raw, dict) else {}

    signal = target.get("signal") or raw.get("signal") or raw.get("signal_name")
    if signal is not None:
        target["signal"] = str(signal)

    can_id = target.get("can_id") if "can_id" in target else raw.get("can_id")
    if can_id is not None:
        try:
            target["can_id"] = int(can_id)
        except Exception:
            target.pop("can_id", None)

    trig = raw.get("trigger")
    trigger: Dict[str, Any] = trig if isinstance(trig, dict) else {}

    if not target.get("signal"):
        raise ValueError(f"rule {rid} missing target.signal")

    out: Dict[str, Any] = {
        "id": rid,
        "name": name,
        "target": target,
        "trigger": trigger,
        "severity": raw.get("severity"),
        "context_signals": raw.get("context_signals") or [],
        "source": source,
        "raw": raw,
    }

    # Back-compat for downstream code paths
    out["signal"] = target["signal"]
    if "can_id" in target:
        out["can_id"] = target["can_id"]
    out["skill_name"] = name

    return out


def _iter_files(base: Path, patterns: List[str]):
    for pat in patterns:
        for p in base.rglob(pat):
            if p.is_file():
                yield p


def gather_skills(skills_dir: Path) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    rules: List[Dict[str, Any]] = []
    knowledge: Dict[str, str] = {}

    if not skills_dir.exists() or not skills_dir.is_dir():
        return rules, knowledge

    for rule_path in _iter_files(skills_dir, RULE_PATTERNS):
        obj = read_json_or_yaml(rule_path)
        src = str(rule_path)
        if isinstance(obj, list):
            for i, r in enumerate(obj):
                if isinstance(r, dict):
                    rules.append(normalize_rule(r, source=src, index=i))
        elif isinstance(obj, dict):
            rules.append(normalize_rule(obj, source=src, index=0))

    for know_path in _iter_files(skills_dir, KNOWLEDGE_PATTERNS):
        try:
            knowledge[str(know_path.parent)] = knowledge.get(str(know_path.parent), "") + "\n" + _read_text_smart(know_path)
        except Exception:
            continue

    return rules, knowledge


def resolve_skills_dir(config_path: str | None, skills_dir_override: str | None) -> Path:
    if skills_dir_override:
        return Path(skills_dir_override)
    if config_path:
        return Path(config_path).parent / "skills"
    return Path("skills")
