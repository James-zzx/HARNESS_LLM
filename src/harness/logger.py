import logging
import sys
import uuid
from typing import Any, Optional, TextIO

import structlog
import structlog.contextvars
import structlog.processors
import structlog.stdlib
from structlog import BoundLogger

_REDACT = "***"
_SENSITIVE_TERMS = ("key", "secret", "token", "password")


def _is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(term in lowered for term in _SENSITIVE_TERMS)


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: (_REDACT if _is_sensitive(k) else _redact(v)) for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


def _redact_sensitive(logger: Any, method_name: str, event_dict: dict) -> dict:
    return _redact(event_dict)


def _module_from_logger(logger: Any, method_name: str, event_dict: dict) -> dict:
    event_dict["module"] = getattr(logger, "name", "") or ""
    return event_dict


def _trace_enrich(logger: Any, method_name: str, event_dict: dict) -> dict:
    context = structlog.contextvars.get_contextvars()
    event_dict.setdefault("trace_id", context.get("trace_id", ""))
    event_dict.setdefault("phase", context.get("phase", ""))
    return event_dict


def _normalize_level(level: Any) -> int:
    if isinstance(level, int):
        return level
    level_no = logging.getLevelName(str(level).upper())
    return level_no if isinstance(level_no, int) else logging.INFO


def setup_logging(
    level: Any = "INFO",
    format: str = "console",
    file_path: Optional[str] = None,
    stream: Optional[TextIO] = None,
) -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            _module_from_logger,
            _trace_enrich,
            _redact_sensitive,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    console_renderer = (
        structlog.processors.JSONRenderer(ensure_ascii=False)
        if format == "json"
        else structlog.dev.ConsoleRenderer()
    )
    formatter_console = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            console_renderer,
        ]
    )
    formatter_json = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ]
    )

    root = logging.getLogger()
    shutdown_logging()

    console_handler = logging.StreamHandler(stream or sys.stdout)
    console_handler.setFormatter(formatter_console)
    root.addHandler(console_handler)

    file_handler = None
    if file_path:
        file_handler = logging.FileHandler(file_path, encoding="utf-8")
        file_handler.setFormatter(formatter_json)
        root.addHandler(file_handler)

    root.setLevel(_normalize_level(level))


def shutdown_logging() -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        if isinstance(handler.formatter, structlog.stdlib.ProcessorFormatter):
            root.removeHandler(handler)
            handler.close()


def get_logger(name: str) -> BoundLogger:
    return structlog.get_logger(name)


class TraceContext:
    def __init__(self, trace_id: Optional[str] = None, phase: str = ""):
        self._trace_id = trace_id or uuid.uuid4().hex
        self._phase = phase
        self.trace_id = self._trace_id
        self.phase = self._phase

    def __enter__(self) -> "TraceContext":
        self._tokens = structlog.contextvars.bind_contextvars(
            trace_id=self._trace_id, phase=self._phase
        )
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> bool:
        structlog.contextvars.reset_contextvars(**self._tokens)
        return False
