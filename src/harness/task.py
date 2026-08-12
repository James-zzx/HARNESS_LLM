import json
import os
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Optional

import yaml


class TaskError(Exception):
    pass


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


@dataclass
class Task:
    id: str
    prompt: str
    eval_command: Optional[str] = None
    max_iterations: int = 10
    timeout: int | float = 120
    status: TaskStatus = TaskStatus.PENDING
    llm_mode: Optional[str] = None


def _require_str(data: Mapping[str, Any], name: str) -> str:
    if name not in data:
        raise TaskError(f"Task definition missing required field: {name}")
    value = data[name]
    if not isinstance(value, str):
        raise TaskError(f"Task field {name} must be a string, got {value!r}")
    return value


def _require_int(data: Mapping[str, Any], name: str, minimum: int, default: int) -> int:
    if name not in data:
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise TaskError(f"Task field {name} must be an integer, got {value!r}")
    if value < minimum:
        raise TaskError(f"Task field {name} must be >= {minimum}, got {value!r}")
    return value


def _require_number(data: Mapping[str, Any], name: str, default: int | float) -> int | float:
    if name not in data:
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TaskError(f"Task field {name} must be a number, got {value!r}")
    if value <= 0:
        raise TaskError(f"Task field {name} must be > 0, got {value!r}")
    return value


class TaskParser:
    @classmethod
    def load_yaml(cls, path: str) -> Task:
        if os.path.splitext(path)[1].lower() not in {".yaml", ".yml"}:
            raise TaskError(f"Expected a .yaml/.yml task file, got: {path}")
        if not os.path.exists(path):
            raise TaskError(f"Task file not found: {path}")
        try:
            with open(path, encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
        except (yaml.YAMLError, OSError) as exc:
            raise TaskError(f"Failed to load task file {path}: {exc}") from exc
        if data is None:
            data = {}
        if not isinstance(data, Mapping):
            raise TaskError(f"Task file {path} must contain a mapping")
        return cls.from_dict(data)

    @classmethod
    def load_json(cls, path: str) -> Task:
        if os.path.splitext(path)[1].lower() != ".json":
            raise TaskError(f"Expected a .json task file, got: {path}")
        if not os.path.exists(path):
            raise TaskError(f"Task file not found: {path}")
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            raise TaskError(f"Failed to load task file {path}: {exc}") from exc
        if not isinstance(data, Mapping):
            raise TaskError(f"Task file {path} must contain a mapping")
        return cls.from_dict(data)

    @classmethod
    def load(cls, path: str) -> Task:
        suffix = os.path.splitext(path)[1].lower()
        if suffix in {".yaml", ".yml"}:
            return cls.load_yaml(path)
        if suffix == ".json":
            return cls.load_json(path)
        raise TaskError(f"Unsupported task file extension: {suffix or '(none)'}")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Task:
        if not isinstance(data, Mapping):
            raise TaskError("Task definition must be a mapping")
        eval_command = None
        if "eval_command" in data:
            eval_command = _require_str(data, "eval_command")
        llm_mode = None
        if "llm_mode" in data:
            llm_mode = _require_str(data, "llm_mode")
            if llm_mode not in {"mock", "real"}:
                raise TaskError(
                    f"Task field llm_mode must be 'mock' or 'real', got {llm_mode!r}"
                )
        return Task(
            id=_require_str(data, "id"),
            prompt=_require_str(data, "prompt"),
            eval_command=eval_command,
            max_iterations=_require_int(data, "max_iterations", minimum=1, default=Task.max_iterations),
            timeout=_require_number(data, "timeout", default=Task.timeout),
            llm_mode=llm_mode,
        )
