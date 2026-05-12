"""Utility helpers for CAN agent file IO."""

from pathlib import Path
from typing import Union, Any
import json

PathLike = Union[str, Path]


def ensure_dir(path: PathLike) -> Path:
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    return target


def read_text(path: PathLike, encoding: str = "utf-8") -> str:
    return Path(path).read_text(encoding=encoding)


def write_text(path: PathLike, content: str, encoding: str = "utf-8") -> None:
    Path(path).write_text(content, encoding=encoding)


def write_json(path: PathLike, data: Any, encoding: str = "utf-8", **kwargs) -> None:
    path = Path(path)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, **kwargs), encoding=encoding)


def _read_text_smart(path: PathLike, encoding: str = "utf-8") -> str:
    return read_text(path, encoding=encoding)


def read_json_or_yaml(path: PathLike, encoding: str = "utf-8") -> Any:
    text = read_text(path, encoding=encoding)
    try:
        import yaml

        if path.endswith((".yaml", ".yml")):
            return yaml.safe_load(text)
    except ImportError:
        pass
    return json.loads(text)
