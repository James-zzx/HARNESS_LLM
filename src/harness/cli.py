from dataclasses import asdict

import yaml

from harness.llm_adapter import build_llm as build_llm
from harness.orchestrator import Task as OrchestratorTask

_SENSITIVE_TERMS = ("api_key", "credential_ref", "secret", "password", "token")
_REDACTED = "***"


def _is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(term in lowered for term in _SENSITIVE_TERMS)


def redact_config(data):
    if isinstance(data, dict):
        return {
            k: (_REDACTED if _is_sensitive(k) else redact_config(v))
            for k, v in data.items()
        }
    if isinstance(data, list):
        return [redact_config(v) for v in data]
    return data


def config_to_yaml(config) -> str:
    return yaml.safe_dump(
        redact_config(asdict(config)),
        sort_keys=False,
        default_flow_style=False,
    )


def to_orchestrator_task(task) -> OrchestratorTask:
    return OrchestratorTask(
        id=task.id,
        prompt=task.prompt,
        eval_command=task.eval_command,
        max_iterations=task.max_iterations,
        timeout=task.timeout,
    )
