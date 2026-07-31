from dataclasses import asdict

import yaml

from harness.credential_store import CredentialStore
from harness.llm_adapter import DEFAULT_BASE_URL, LLMFactory
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


def build_llm(config):
    api_key = ""
    credential_ref = config.llm.credential_ref
    if credential_ref and "/" in credential_ref:
        service, _, key = credential_ref.partition("/")
        api_key = CredentialStore().get_key(service, key) or ""
    return LLMFactory(
        mock=config.llm.mock,
        model=config.llm.model,
        base_url=config.llm.base_url or DEFAULT_BASE_URL,
        api_key=api_key,
        timeout=config.llm.timeout,
        max_retries=config.llm.max_retries,
    ).create()
