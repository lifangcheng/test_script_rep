from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from config.schema import ConfigLoadResult, InputConfig


def load_yaml_config(path: Optional[str]) -> ConfigLoadResult:
    if not path:
        return ConfigLoadResult(config=InputConfig())

    p = Path(path)
    if not p.exists():
        return ConfigLoadResult(
            error={
                "code": "config_not_found",
                "message": f"Config file not found: {p}",
                "fix": "Provide a valid --config YAML path or omit it.",
            }
        )

    try:
        raw: Dict[str, Any] = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception as e:  # noqa: BLE001
        return ConfigLoadResult(
            error={
                "code": "config_parse_failed",
                "message": f"Failed to parse YAML: {e}",
                "fix": "Ensure the YAML syntax is valid.",
            }
        )

    try:
        return ConfigLoadResult(config=InputConfig.model_validate(raw))
    except Exception as e:  # noqa: BLE001
        return ConfigLoadResult(
            error={
                "code": "config_schema_invalid",
                "message": f"Config schema validation failed: {e}",
                "fix": "Update the YAML to match InputConfig schema.",
            }
        )
