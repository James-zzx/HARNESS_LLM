import json
import os
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, get_args, get_origin, get_type_hints

import yaml

ENV_PREFIX = "HARNESS_"


class ConfigError(Exception):
    pass


def _coerce_value(name: str, value: Any, hint: Any) -> Any:
    origin = get_origin(hint)
    if origin is list:
        if isinstance(value, str):
            value = [part.strip() for part in value.split(",") if part.strip()]
        if isinstance(value, list):
            return [str(item) for item in value]
        raise ConfigError(f"Config field {name} must be a list, got {value!r}")
    if hint is bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "on"}:
                return True
            if normalized in {"false", "0", "no", "off"}:
                return False
        raise ConfigError(f"Config field {name} must be a boolean, got {value!r}")
    if hint is int:
        if isinstance(value, bool):
            raise ConfigError(f"Config field {name} must be an integer, got {value!r}")
        try:
            return int(value)
        except (TypeError, ValueError):
            raise ConfigError(f"Config field {name} must be an integer, got {value!r}") from None
    if hint is str:
        if isinstance(value, str):
            return value
        raise ConfigError(f"Config field {name} must be a string, got {value!r}")
    raise ConfigError(f"Config field {name} has unsupported type {hint!r}")


def _resolve_optional(hint: Any) -> tuple[Any, bool]:
    args = get_args(hint)
    if args and type(None) in args:
        non_none = [arg for arg in args if arg is not type(None)]
        return (non_none[0] if len(non_none) == 1 else hint), True
    return hint, False


def _build_section(cls: Any, data: Any, prefix: str, base: Any = None) -> Any:
    if not isinstance(data, Mapping):
        raise ConfigError(f"Config section {prefix} must be a mapping")
    hints = get_type_hints(cls)
    unknown = set(data) - set(hints)
    if unknown:
        raise ConfigError(f"Unknown config key(s) in {prefix}: {sorted(unknown)}")
    enums = getattr(cls, "_ENUMS", {})
    kwargs = {name: getattr(base, name) for name in hints} if base is not None else {}
    for name, hint in hints.items():
        if name not in data:
            continue
        value = data[name]
        inner, optional = _resolve_optional(hint)
        if value is None:
            if optional:
                kwargs[name] = None
                continue
            raise ConfigError(f"Config field {prefix}.{name} cannot be None")
        if optional and isinstance(value, str) and not value.strip():
            kwargs[name] = None
            continue
        coerced = _coerce_value(f"{prefix}.{name}", value, inner)
        if name in enums and coerced not in enums[name]:
            raise ConfigError(
                f"Config field {prefix}.{name} must be one of {sorted(enums[name])}, got {coerced!r}"
            )
        kwargs[name] = coerced
    return cls(**kwargs)


@dataclass
class LLMConfig:
    mock: bool = False
    model: str = "gpt-4o"
    base_url: Optional[str] = None
    credential_ref: Optional[str] = None
    timeout: int = 120
    max_retries: int = 3


@dataclass
class SandboxConfig:
    _ENUMS = {"network": {"allow", "deny"}}

    enabled: bool = True
    timeout: int = 300
    max_memory_mb: int = 1024
    allowed_dirs: list[str] = field(default_factory=lambda: ["."])
    blocked_dirs: list[str] = field(default_factory=list)
    blocked_commands: list[str] = field(
        default_factory=lambda: ["rm -rf /", "shutdown", "format", "dd if="]
    )
    network: str = "deny"


@dataclass
class HITLConfig:
    enabled: bool = True
    dangerous_commands: list[str] = field(
        default_factory=lambda: [
            "rm -rf",
            "shutdown",
            "format",
            "dd if=",
            "git push --force",
            "DROP TABLE",
        ]
    )
    approval_timeout: int = 300


@dataclass
class LoggingConfig:
    _ENUMS = {"level": {"DEBUG", "INFO", "WARNING", "ERROR"}, "format": {"console", "json"}}

    level: str = "INFO"
    format: str = "console"
    file_path: Optional[str] = None


@dataclass
class OpenDesignConfig:
    enabled: bool = False
    port: int = 3000
    data_dir: str = ".open_design"
    daemon_url: Optional[str] = None


@dataclass
class CredentialConfig:
    _ENUMS = {"backend": {"keyring", "env"}}

    service: str = "harness"
    backend: str = "keyring"


_SECTION_CLASSES: dict[str, Any] = {
    "llm": LLMConfig,
    "sandbox": SandboxConfig,
    "hitl": HITLConfig,
    "logging": LoggingConfig,
    "open_design": OpenDesignConfig,
    "credential": CredentialConfig,
}

_SECTION_FIELDS: dict[str, set[str]] = {
    name: set(get_type_hints(cls)) for name, cls in _SECTION_CLASSES.items()
}


@dataclass
class HarnessConfig:
    llm: LLMConfig = field(default_factory=LLMConfig)
    sandbox: SandboxConfig = field(default_factory=SandboxConfig)
    hitl: HITLConfig = field(default_factory=HITLConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    open_design: OpenDesignConfig = field(default_factory=OpenDesignConfig)
    credential: CredentialConfig = field(default_factory=CredentialConfig)

    def merge(self, data: Mapping[str, Any]) -> "HarnessConfig":
        if not isinstance(data, Mapping):
            raise ConfigError("Config overrides must be a mapping")
        unknown = set(data) - set(_SECTION_CLASSES)
        if unknown:
            raise ConfigError(f"Unknown config section(s): {sorted(unknown)}")
        kwargs = {}
        for name, section_cls in _SECTION_CLASSES.items():
            if name in data:
                kwargs[name] = _build_section(
                    section_cls, data[name], name, base=getattr(self, name)
                )
            else:
                kwargs[name] = getattr(self, name)
        return HarnessConfig(**kwargs)

    def apply_overrides(self, overrides: Mapping[str, Any]) -> "HarnessConfig":
        return self.merge(overrides)


def _read_file(path: str) -> dict[str, Any]:
    suffix = os.path.splitext(path)[1].lower()
    if suffix in {".yaml", ".yml"}:
        loader = yaml.safe_load
    elif suffix == ".json":
        loader = json.load
    else:
        raise ConfigError(f"Unsupported config file extension: {suffix or '(none)'}")
    try:
        with open(path, encoding="utf-8") as fh:
            data = loader(fh)
    except (yaml.YAMLError, json.JSONDecodeError, OSError) as exc:
        raise ConfigError(f"Failed to load config file {path}: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"Config file {path} must contain a mapping")
    return data


def _extract_env(env: Mapping[str, str]) -> dict[str, dict[str, str]]:
    extracted: dict[str, dict[str, str]] = {}
    for key, value in env.items():
        if not key.startswith(ENV_PREFIX):
            continue
        rest = key[len(ENV_PREFIX):]
        section, _, field_name = rest.partition("_")
        section, field_name = section.lower(), field_name.lower()
        if not field_name or field_name not in _SECTION_FIELDS.get(section, set()):
            continue
        extracted.setdefault(section, {})[field_name] = value
    return extracted


def load_config(path: Optional[str] = None, env: Optional[Mapping[str, str]] = None) -> HarnessConfig:
    env = os.environ if env is None else env
    config = HarnessConfig()
    if path:
        if not os.path.exists(path):
            raise ConfigError(f"Config file not found: {path}")
        config = config.merge(_read_file(path))
    if env:
        env_data = _extract_env(env)
        if env_data:
            config = config.merge(env_data)
    return config
