import json

from fastapi.testclient import TestClient

from harness.api import TaskManager, _default_runner, create_app
from harness.hitl import HITLGate
from harness.mock_llm import MockLLM
from harness.orchestrator import RunResult, Task


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
