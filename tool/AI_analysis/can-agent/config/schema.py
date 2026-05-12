from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

# 与 tool/app_main.py 保持一致的默认模型/网关配置
DEFAULT_BASE_URL = "http://model.mify.ai.srv"
DEFAULT_MODEL = "deepseek-v3.1"
DEFAULT_TIMEOUT = 60  # 提高超时，配合上游 5xx 重试


class InputConfig(BaseModel):
    chunk_size: int = Field(default=200_000, ge=1)
    timezone: str = Field(default="UTC")

    anomaly: Dict[str, Any] = Field(default_factory=lambda: {
        "period_tol": 0.2,
        "spike_z": 6.0,
        "freeze_min_points": 10,
        "freeze_enabled": False,
    })

    # skills / whitelist
    skills: Dict[str, Any] = Field(
        default_factory=lambda: {
            "dir": "",
            "allow_missing": True,
        }
    )
    whitelist: Dict[str, Any] = Field(
        default_factory=lambda: {
            "can_ids": [],
            "signals": [],
            "enforce": False,
        }
    )

    # anomaly window slicing
    slice: Dict[str, Any] = Field(
        default_factory=lambda: {
            "window_sec": 2.0,
            "format": "csv",  # csv|json
            "max_rows": 500,
            "min_points": 5,
        }
    )

    # fallback anomaly rules
    fallback: Dict[str, Any] = Field(
        default_factory=lambda: {
            "variance_z": 6.0,
            "timeout_multiplier": 3.0,
            "uds_service_ids": [0x19],
            "keyword_signals": ["flt", "warn", "status"],
        }
    )

    ai: Dict[str, Any] = Field(
        default_factory=lambda: {
            "base_url": DEFAULT_BASE_URL,
            "api_key": "",
            "model": DEFAULT_MODEL,
            "timeout_s": DEFAULT_TIMEOUT,
            "system_prompt": "",
            "user_prompt": "",
        }
    )


class ConfigLoadResult(BaseModel):
    config: Optional[InputConfig] = None
    error: Optional[Dict[str, str]] = None
