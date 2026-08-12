import json
import threading
import time
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
from harness.credential_store import CredentialStore, MemoryBackend
from harness.hitl import GuardrailEngine, HITLGate
from harness.llm_adapter import Response
from harness.message_queue import MessageQueue
from harness.mock_llm import MockLLM
from harness.orchestrator import RunResult, Task
from harness.task import TaskError, TaskStatus


class _PauseRunner:
    def __call__(self, task, gate, message_queue=None, on_orchestrator=None):
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


def test_api_health_endpoint():
    with _client() as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


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


class _QueueCapturingRunner:
    def __init__(self):
        self.seen = []

    def __call__(self, task, gate, message_queue=None, on_orchestrator=None):
        self.seen.append(message_queue)
        return RunResult(status="COMPLETED", final_state="COMPLETED", iterations=1)


class _StubOrchestrator:
    def __init__(self):
        self.interrupted = False

    def interrupt(self):
        self.interrupted = True


def _client_with_manager():
    manager = TaskManager()
    app = create_app(task_manager=manager, runner=_PauseRunner())
    return TestClient(app), manager


def test_manager_creates_message_queue_per_task():
    manager = TaskManager()
    manager.create(Task(id="mq-1", prompt="hi"))
    manager.create(Task(id="mq-2", prompt="hi"))
    q1 = manager.get_message_queue("mq-1")
    q2 = manager.get_message_queue("mq-2")
    assert q1.task_id == "mq-1"
    assert q2.task_id == "mq-2"
    assert q1 is not q2
    with pytest.raises(TaskNotFoundError):
        manager.get_message_queue("does-not-exist")


def test_api_post_message_pushes_to_queue_and_reads_back():
    client, manager = _client_with_manager()
    client.post("/api/tasks", json={"id": "api-msg", "prompt": "hi"})
    r1 = client.post("/api/tasks/api-msg/message", json={"content": "hello"})
    assert r1.status_code == 200
    assert r1.json() == {"ok": True}
    client.post("/api/tasks/api-msg/message", json={"content": "again"})
    queue = manager.get_message_queue("api-msg")
    assert queue.pop_all() == [
        {"role": "user", "content": "hello"},
        {"role": "user", "content": "again"},
    ]
    body = client.get("/api/tasks/api-msg/messages").json()
    assert body["task_id"] == "api-msg"
    assert body["messages"] == [
        {"role": "user", "content": "hello"},
        {"role": "user", "content": "again"},
    ]


def test_api_post_message_rejects_empty_content():
    with _client() as client:
        client.post("/api/tasks", json={"id": "api-empty", "prompt": "hi"})
        for payload in ({"content": ""}, {"content": "   "}, {}):
            response = client.post("/api/tasks/api-empty/message", json=payload)
            assert response.status_code == 400, payload


def test_api_missing_task_returns_404_for_message_endpoints():
    with _client() as client:
        assert (
            client.post("/api/tasks/nope/message", json={"content": "hi"}).status_code
            == 404
        )
        assert client.post("/api/tasks/nope/interrupt").status_code == 404
        assert client.get("/api/tasks/nope/messages").status_code == 404


def test_api_interrupt_sets_flag_and_interrupts_live_orchestrator():
    client, manager = _client_with_manager()
    client.post("/api/tasks", json={"id": "api-int", "prompt": "hi"})
    stub = _StubOrchestrator()
    manager.attach_orchestrator("api-int", stub)
    response = client.post("/api/tasks/api-int/interrupt")
    assert response.status_code == 200
    assert response.json()["interrupt_requested"] is True
    assert manager.get_interrupt_requested("api-int") is True
    assert stub.interrupted is True


def test_api_interrupt_e2e_default_runner_enters_user_input(tmp_path, monkeypatch):
    first_call_started = threading.Event()
    release_first_call = threading.Event()
    seen = {}

    def write_intent(path, content):
        return json.dumps(
            {
                "thought": "writing file",
                "tool": "write_file",
                "params": {"path": path, "content": content},
            }
        )

    class GatedLLM(MockLLM):
        def __init__(self):
            super().__init__([""])
            self._calls = 0

        def chat(self, messages):
            self._calls += 1
            if self._calls == 1:
                first_call_started.set()
                assert release_first_call.wait(timeout=10)
                return Response(content=write_intent("e2e.txt", "v1"))
            if self._calls == 2:
                seen["context"] = [
                    (message.role, message.content or "") for message in messages
                ]
                return Response(content=json.dumps({"done": True}))
            return Response(content=json.dumps({"done": True}))

    llm = GatedLLM()

    def fake_build_llm(config, credential_store=None):
        return llm

    monkeypatch.setattr("harness.llm_adapter.build_llm", fake_build_llm)
    monkeypatch.chdir(tmp_path)

    manager = TaskManager()
    app = create_app(task_manager=manager)
    client_a = TestClient(app)
    client_b = TestClient(app)

    with client_a, client_b:
        result = {}

        def submit():
            result["response"] = client_a.post(
                "/api/tasks", json={"id": "e2e-int", "prompt": "write e2e.txt"}
            )

        thread = threading.Thread(target=submit)
        thread.start()
        try:
            assert first_call_started.wait(timeout=10)
            interrupt = client_b.post("/api/tasks/e2e-int/interrupt")
            assert interrupt.status_code == 200
            assert interrupt.json()["interrupt_requested"] is True
            release_first_call.set()
            time.sleep(0.3)
            message = client_b.post(
                "/api/tasks/e2e-int/message", json={"content": "use python instead"}
            )
            assert message.status_code == 200
            thread.join(timeout=10)
        finally:
            release_first_call.set()
            thread.join(timeout=10)

        assert not thread.is_alive()
        assert result["response"].status_code == 201
        assert manager.get_interrupt_requested("e2e-int") is True
        snapshot = client_b.get("/api/tasks/e2e-int").json()
        assert snapshot["status"] == "completed"

    assert any(
        role == "user" and content == "use python instead"
        for role, content in seen["context"]
    )


def test_api_runner_receives_task_message_queue():
    runner = _QueueCapturingRunner()
    manager = TaskManager()
    app = create_app(task_manager=manager, runner=runner)
    with TestClient(app) as client:
        client.post("/api/tasks", json={"id": "api-q", "prompt": "hi"})
    assert runner.seen == [manager.get_message_queue("api-q")]


def test_api_default_runner_wires_message_queue_to_orchestrator(tmp_path, monkeypatch):
    seen = {}

    class _InspectLLM(MockLLM):
        def __init__(self):
            super().__init__([json.dumps({"done": True})])

        def chat(self, messages):
            seen["contexts"] = [m.content for m in messages]
            return super().chat(messages)

    def fake_build_llm(config, credential_store=None):
        return _InspectLLM()

    monkeypatch.setattr("harness.llm_adapter.build_llm", fake_build_llm)
    monkeypatch.chdir(tmp_path)

    queue = MessageQueue(task_id="api-wire")
    queue.push({"role": "user", "content": "use python instead"})
    runner = _default_runner()
    result = runner(
        Task(id="api-wire", prompt="write a file"),
        HITLGate(),
        queue,
    )

    assert result.status == "COMPLETED"
    assert any("use python instead" in content for content in seen["contexts"])


# ---------- credential endpoints (P6-07) ----------


def _cred_client():
    store = CredentialStore(backend=MemoryBackend())
    app = create_app(
        credential_store=store,
        runner=lambda task, gate, message_queue=None, on_orchestrator=None: None,
    )
    return TestClient(app), store


def test_api_credential_put():
    client, store = _cred_client()
    with client:
        response = client.put(
            "/api/credential/harness/openai", json={"value": "sk-secret"}
        )
        assert response.status_code == 200
        assert response.json() == {"configured": True}
        assert store.get_key("harness", "openai") == "sk-secret"
        status = client.get("/api/credential/harness/openai")
        assert status.status_code == 200
        assert status.json()["configured"] is True


def test_api_credential_get_no_leak():
    client, store = _cred_client()
    store.set_key("harness", "openai", "sk-topsecret-123")
    with client:
        response = client.get("/api/credential/harness/openai")
        assert response.status_code == 200
        body = response.json()
        assert body["configured"] is True
        assert body["service"] == "harness"
        assert body["key"] == "openai"
        assert "sk-topsecret-123" not in response.text
        assert "sk-topsecret-123" not in json.dumps(body)


def test_api_credential_delete():
    client, store = _cred_client()
    store.set_key("harness", "openai", "sk-secret")
    with client:
        response = client.delete("/api/credential/harness/openai")
        assert response.status_code == 200
        assert response.json() == {"configured": False}
        assert store.get_key("harness", "openai") is None
        assert client.get("/api/credential/harness/openai").json()["configured"] is False


def test_api_credential_empty_rejected():
    client, _ = _cred_client()
    with client:
        for payload in ({"value": ""}, {"value": "   "}, {}):
            response = client.put("/api/credential/harness/openai", json=payload)
            assert response.status_code == 400, payload


def test_api_credential_missing_parts_404():
    client, _ = _cred_client()
    with client:
        assert client.get("/api/credential//openai").status_code == 404
        assert client.put("/api/credential/harness/", json={"value": "x"}).status_code == 404
        assert client.delete("/api/credential//").status_code == 404


def test_api_messages_include_assistant(tmp_path, monkeypatch):
    def fake_build_llm(config, credential_store=None):
        return MockLLM(["ok I will do it", json.dumps({"done": True})])

    monkeypatch.setattr("harness.llm_adapter.build_llm", fake_build_llm)
    monkeypatch.chdir(tmp_path)

    manager = TaskManager()
    app = create_app(task_manager=manager)
    with TestClient(app) as client:
        client.post("/api/tasks", json={"id": "api-asst", "prompt": "do the work"})
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if manager.snapshot("api-asst")["status"] == "completed":
                break
            time.sleep(0.05)
        body = client.get("/api/tasks/api-asst/messages").json()

    assert manager.snapshot("api-asst")["status"] == "completed"
    assert {"role": "assistant", "content": "ok I will do it"} in body["messages"]


def test_api_messages_no_tool_content(tmp_path, monkeypatch):
    def fake_build_llm(config, credential_store=None):
        return MockLLM(
            [
                json.dumps(
                    {
                        "tool": "write_file",
                        "params": {"path": "notes.txt", "content": "AWS_ACCESS_KEY sk-12345"},
                    }
                ),
                "I wrote the file.",
                json.dumps({"done": True}),
            ]
        )

    monkeypatch.setattr("harness.llm_adapter.build_llm", fake_build_llm)
    monkeypatch.chdir(tmp_path)

    manager = TaskManager()
    app = create_app(task_manager=manager)
    with TestClient(app) as client:
        client.post("/api/tasks", json={"id": "api-noc", "prompt": "write notes.txt"})
        client.post("/api/tasks/api-noc/message", json={"content": "use the plan"})
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if manager.snapshot("api-noc")["status"] == "completed":
                break
            time.sleep(0.05)
        body = client.get("/api/tasks/api-noc/messages").json()

    for message in body["messages"]:
        assert message["role"] in {"user", "assistant"}
    assert {"role": "assistant", "content": "I wrote the file."} in body["messages"]
    text = json.dumps(body, ensure_ascii=False)
    assert "sk-12345" not in text
    assert "notes.txt" not in text
    assert "write_file" not in text


def test_api_messages_redacts_secrets():
    with _client() as client:
        client.post("/api/tasks", json={"id": "api-red", "prompt": "hi"})
        client.post(
            "/api/tasks/api-red/message",
            json={"content": '{"api_key": "sk-123", "token": "tok-456", "user": "alice"}'},
        )
        client.post(
            "/api/tasks/api-red/message",
            json={"content": "db password=hunter2 ok"},
        )
        client.post(
            "/api/tasks/api-red/message",
            json={"content": "api_key: sk-abc plain text"},
        )
        response = client.get("/api/tasks/api-red/messages")

    body = response.json()
    assert body["messages"] == [
        {"role": "user", "content": '{"api_key": "***", "token": "***", "user": "alice"}'},
        {"role": "user", "content": "db password=*** ok"},
        {"role": "user", "content": "api_key: *** plain text"},
    ]
    assert "sk-123" not in response.text
    assert "tok-456" not in response.text
    assert "hunter2" not in response.text
    assert "sk-abc" not in response.text
