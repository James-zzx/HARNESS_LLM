import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harness.api import (
    TaskManager,
    TaskNotFoundError,
    _default_runner,
    _map_status,
    create_app,
)
from harness.hitl import GuardrailEngine, HITLGate
from harness.mock_llm import MockLLM
from harness.orchestrator import RunResult, Task
from harness.task import TaskError, TaskStatus


class _PauseRunner:
    def __call__(self, task, gate):
        gate.check("run_shell", {"command": "rm -rf /"})
        return RunResult(status="PAUSED", final_state="PAUSED", iterations=0)


def _client():
    manager = TaskManager()
    app = create_app(task_manager=manager, runner=_PauseRunner())
    return TestClient(app)


def test_api_create_task():
    with _client() as client:
        response = client.post(
            "/api/tasks", json={"id": "api-1", "prompt": "fix the lint errors"}
        )
        assert response.status_code == 201
        assert response.json()["task_id"] == "api-1"


def test_api_get_task_status():
    with _client() as client:
        client.post("/api/tasks", json={"id": "api-2", "prompt": "fix the lint errors"})
        response = client.get("/api/tasks/api-2")
        assert response.status_code == 200
        body = response.json()
        assert body["task_id"] == "api-2"
        assert body["status"] in {"pending", "running", "completed", "failed", "paused"}


def test_api_hitl_approve():
    with _client() as client:
        client.post("/api/tasks", json={"id": "api-3", "prompt": "fix the lint errors"})
        response = client.post("/api/hitl/api-3/approve")
        assert response.status_code == 200
        assert response.json()["hitl_state"] == "APPROVED"


def test_api_task_not_found():
    with _client() as client:
        response = client.get("/api/tasks/does-not-exist")
        assert response.status_code == 404


def test_api_default_runner_builds_llm_via_shared_helper(monkeypatch, tmp_path):
    seen = {}

    def spy_build_llm(config, credential_store=None):
        seen["called"] = True
        return MockLLM([json.dumps({"done": True})])

    monkeypatch.setattr("harness.llm_adapter.build_llm", spy_build_llm)
    monkeypatch.chdir(tmp_path)

    runner = _default_runner()
    result = runner(Task(id="api-cred", prompt="hi"), HITLGate())

    assert seen.get("called") is True
    assert result.status == "COMPLETED"


def test_api_default_runner_isolates_task_work_dirs(tmp_path, monkeypatch):
    def fake_build_llm(config, credential_store=None):
        return MockLLM(
            [
                json.dumps(
                    {
                        "tool": "write_file",
                        "params": {"path": "result.txt", "content": "hello"},
                    }
                ),
                json.dumps({"done": True}),
            ]
        )

    monkeypatch.setattr("harness.llm_adapter.build_llm", fake_build_llm)
    monkeypatch.chdir(tmp_path)

    runner = _default_runner()
    result = runner(Task(id="api-iso", prompt="write a file"), HITLGate())

    assert result.status == "COMPLETED"
    base = Path(tmp_path)
    assert not (base / "result.txt").exists()
    subdirs = [
        p for p in base.iterdir() if p.is_dir() and p.name.startswith("harness-task-")
    ]
    assert subdirs
    assert (subdirs[0] / "result.txt").read_text(encoding="utf-8") == "hello"


def test_get_task_returns_snapshot_copy():
    manager = TaskManager()
    manager.create(Task(id="copy-1", prompt="hi"))
    returned = manager.get_task("copy-1")
    returned.prompt = "mutated"
    assert manager.get_task("copy-1").prompt == "hi"


def test_map_status_unknown_raises():
    with pytest.raises(TaskError):
        _map_status("NOT_A_STATUS")


def test_manager_setters_unknown_task_raise_not_found():
    manager = TaskManager()
    with pytest.raises(TaskNotFoundError):
        manager.set_status("nope", TaskStatus.RUNNING)
    with pytest.raises(TaskNotFoundError):
        manager.set_error("nope", "boom")
    with pytest.raises(TaskNotFoundError):
        manager.set_iterations("nope", 1)
    with pytest.raises(TaskNotFoundError):
        manager.append_log("nope", "line")
    with pytest.raises(TaskNotFoundError):
        manager.attach_hitl_gate("nope", HITLGate())


def test_snapshot_reports_paused_when_gate_paused():
    manager = TaskManager()
    manager.create(Task(id="paused-1", prompt="hi"))
    manager.set_status("paused-1", TaskStatus.RUNNING)
    gate = HITLGate()
    gate.check("run_shell", {"command": "rm -rf /"})
    manager.attach_hitl_gate("paused-1", gate)

    body = manager.snapshot("paused-1")
    assert body["status"] == "paused"


def test_manager_snapshot_includes_rejection_feedback():
    manager = TaskManager()
    manager.create(Task(id="fb-1", prompt="dangerous"))
    manager.set_status("fb-1", TaskStatus.PAUSED)
    manager.set_feedback("fb-1", '{"error": "action rejected by human-in-the-loop"}')

    body = manager.snapshot("fb-1")
    assert body["status"] == "paused"
    assert "action rejected by human-in-the-loop" in body["feedback"]


def test_api_default_runner_wires_rejection_feedback(tmp_path, monkeypatch):
    def fake_build_llm(config, credential_store=None):
        return MockLLM(
            [json.dumps({"tool": "run_shell", "params": {"command": "echo danger"}})]
        )

    monkeypatch.setattr("harness.llm_adapter.build_llm", fake_build_llm)
    monkeypatch.chdir(tmp_path)

    gate = HITLGate(
        engine=GuardrailEngine(regex_rules=[r"^echo danger"]),
        decision_source=lambda: "rejected",
    )
    runner = _default_runner()
    result = runner(Task(id="api-fb", prompt="dangerous"), gate)

    assert result.status == "PAUSED"
    assert result.feedback is not None
    assert "echo danger" in result.feedback
