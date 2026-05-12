from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class StageEvent:
    stage: str
    status: str  # running|success|failed
    error: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"stage": self.stage, "status": self.status}
        if self.error is not None:
            payload["error"] = self.error
        return payload


class JsonLogger:
    def __init__(self, stream=None):
        self._stream = stream or sys.stdout

    def log(self, level: str, message: str, **fields: Any) -> None:
        payload = {
            "ts": time.time(),
            "level": level,
            "message": message,
            **fields,
        }
        self._stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self._stream.flush()


logger = JsonLogger()
