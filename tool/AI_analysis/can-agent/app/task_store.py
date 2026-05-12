from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class TaskRecord:
    task_id: str
    created_at: float
    status: str = "pending"  # pending|running|success|failed
    output_dir: str = ""
    error: Optional[Dict[str, Any]] = None
    logs: list[Dict[str, Any]] = field(default_factory=list)


class InMemoryTaskStore:
    def __init__(self, persist_path: str):
        self._lock = threading.Lock()
        self._tasks: Dict[str, TaskRecord] = {}
        self._persist_path = Path(persist_path)
        self._persist_path.parent.mkdir(parents=True, exist_ok=True)
        self._load()

    def _load(self) -> None:
        if not self._persist_path.exists():
            return
        try:
            raw = json.loads(self._persist_path.read_text(encoding="utf-8"))
            for task_id, rec in (raw or {}).items():
                self._tasks[task_id] = TaskRecord(
                    task_id=task_id,
                    created_at=float(rec.get("created_at", time.time())),
                    status=str(rec.get("status", "pending")),
                    output_dir=str(rec.get("output_dir", "")),
                    error=rec.get("error"),
                    logs=list(rec.get("logs", [])),
                )
        except Exception:
            # ignore corrupt cache
            return

    def _save(self) -> None:
        payload = {k: asdict(v) for k, v in self._tasks.items()}
        self._persist_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def create(self, output_dir: str) -> TaskRecord:
        task_id = str(uuid.uuid4())
        rec = TaskRecord(task_id=task_id, created_at=time.time(), output_dir=output_dir)
        with self._lock:
            self._tasks[task_id] = rec
            self._save()
        return rec

    def get(self, task_id: str) -> Optional[TaskRecord]:
        with self._lock:
            return self._tasks.get(task_id)

    def update(self, task_id: str, **fields: Any) -> None:
        with self._lock:
            rec = self._tasks.get(task_id)
            if not rec:
                return
            for k, v in fields.items():
                setattr(rec, k, v)
            self._save()


store = InMemoryTaskStore(persist_path=str(Path(__file__).resolve().parent / "tasks.json"))
