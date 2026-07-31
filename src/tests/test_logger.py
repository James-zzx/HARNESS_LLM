import io
import json
import re

import pytest

from harness.logger import TraceContext, get_logger, setup_logging, shutdown_logging


@pytest.fixture(autouse=True)
def _reset_logging_state():
    import structlog.contextvars

    structlog.contextvars.clear_contextvars()
    yield
    shutdown_logging()


def test_logger_creates_entry(work_dir):
    log_file = work_dir / "harness.jsonl"
    setup_logging(level="INFO", file_path=str(log_file))

    get_logger("harness.agent").info("agent started", attempt=1)

    records = [
        json.loads(line)
        for line in log_file.read_text(encoding="utf-8").splitlines()
    ]
    assert len(records) == 1
    record = records[0]
    assert record["event"] == "agent started"
    assert record["level"] == "info"
    assert record["module"] == "harness.agent"
    assert record["attempt"] == 1
    assert record["timestamp"]


def test_trace_context_adds_trace_id(work_dir):
    log_file = work_dir / "harness.jsonl"
    setup_logging(level="INFO", file_path=str(log_file))

    logger = get_logger("harness.trace")
    logger.info("outside")
    with TraceContext(trace_id="resume-me", phase="execute") as ctx:
        logger.info("inside")

    records = [
        json.loads(line)
        for line in log_file.read_text(encoding="utf-8").splitlines()
    ]
    outside, inside = records
    assert outside["trace_id"] == ""
    assert inside["trace_id"] == "resume-me"
    assert inside["phase"] == "execute"
    assert ctx.trace_id == "resume-me"
    assert ctx.phase == "execute"


def test_trace_context_nesting(work_dir):
    log_file = work_dir / "harness.jsonl"
    setup_logging(level="INFO", file_path=str(log_file))

    logger = get_logger("harness.trace")
    with TraceContext(phase="outer") as outer:
        logger.info("level-1")
        with TraceContext(phase="inner") as inner:
            logger.info("level-2")
        logger.info("level-1-again")

    records = [
        json.loads(line)
        for line in log_file.read_text(encoding="utf-8").splitlines()
    ]
    level1, level2, level1_again = records
    assert re.fullmatch(r"[0-9a-f]{32}", outer.trace_id)
    assert re.fullmatch(r"[0-9a-f]{32}", inner.trace_id)
    assert inner.trace_id != outer.trace_id
    assert level1["trace_id"] == outer.trace_id
    assert level2["trace_id"] == inner.trace_id
    assert level1_again["trace_id"] == outer.trace_id
    assert level2["phase"] == "inner"
    assert level1_again["phase"] == "outer"


def test_sensitive_field_redaction(work_dir):
    log_file = work_dir / "harness.jsonl"
    console = io.StringIO()
    setup_logging(level="INFO", file_path=str(log_file), stream=console)

    get_logger("harness.redact").info(
        "login",
        api_key="sk-live-123",
        AUTH_TOKEN="tok-456",
        password="hunter2",
        nested={"user": "alice", "key": "inner-secret", "note": None},
        items=[{"token": "t1"}, "plain"],
        status=200,
    )

    record = json.loads(
        log_file.read_text(encoding="utf-8").splitlines()[0]
    )
    assert record["api_key"] == "***"
    assert record["AUTH_TOKEN"] == "***"
    assert record["password"] == "***"
    assert record["nested"] == {"user": "alice", "key": "***", "note": None}
    assert record["items"] == [{"token": "***"}, "plain"]
    assert record["status"] == 200

    console_text = console.getvalue()
    for secret in ("sk-live-123", "tok-456", "hunter2", "inner-secret"):
        assert secret not in console_text
    assert "***" in console_text


def test_log_level_dispatch(work_dir):
    log_file = work_dir / "harness.jsonl"
    setup_logging(level="INFO", file_path=str(log_file))

    logger = get_logger("harness.levels")
    logger.debug("noise")
    logger.info("note")
    logger.warning("careful")
    logger.error("boom")

    records = [
        json.loads(line)
        for line in log_file.read_text(encoding="utf-8").splitlines()
    ]
    assert [record["event"] for record in records] == ["note", "careful", "boom"]
    assert [record["level"] for record in records] == ["info", "warning", "error"]
