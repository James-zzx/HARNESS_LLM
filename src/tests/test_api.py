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
from harness.llm_adapter import OpenAIClient, Response
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
    tasks_dir = base / "harness-tasks"
    assert (tasks_dir / "api-iso" / "result.txt").read_text(encoding="utf-8") == "hello"
    assert not (base / "result.txt").exists()


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


# ---------- task artifact files (P6-12) ----------


def test_api_files_list(tmp_path):
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    (work_dir / "result.txt").write_text("hello", encoding="utf-8")
    (work_dir / "sub").mkdir()
    (work_dir / "sub" / "nested.log").write_text("data", encoding="utf-8")

    manager = TaskManager()
    app = create_app(task_manager=manager, runner=_PauseRunner())
    with TestClient(app) as client:
        client.post("/api/tasks", json={"id": "api-files", "prompt": "hi"})
        manager.set_work_dir("api-files", str(work_dir))
        response = client.get("/api/tasks/api-files/files")

    assert response.status_code == 200
    body = response.json()
    assert body["task_id"] == "api-files"
    files = {entry["path"]: entry["size"] for entry in body["files"]}
    assert files == {"result.txt": 5, "sub/nested.log": 4}


def test_api_files_read(tmp_path):
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    (work_dir / "note.md").write_text("hello world", encoding="utf-8")

    manager = TaskManager()
    app = create_app(task_manager=manager, runner=_PauseRunner())
    with TestClient(app) as client:
        client.post("/api/tasks", json={"id": "api-read", "prompt": "hi"})
        manager.set_work_dir("api-read", str(work_dir))
        response = client.get("/api/tasks/api-read/files/note.md")

    assert response.status_code == 200
    body = response.json()
    assert body["task_id"] == "api-read"
    assert body["path"] == "note.md"
    assert body["content"] == "hello world"


def test_api_files_download(tmp_path):
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    (work_dir / "artifact.bin").write_bytes(b"\x00\x01\x02")

    manager = TaskManager()
    app = create_app(task_manager=manager, runner=_PauseRunner())
    with TestClient(app) as client:
        client.post("/api/tasks", json={"id": "api-dl", "prompt": "hi"})
        manager.set_work_dir("api-dl", str(work_dir))
        response = client.get("/api/tasks/api-dl/files/artifact.bin/download")

    assert response.status_code == 200
    assert response.content == b"\x00\x01\x02"


def test_api_files_path_traversal_blocked(tmp_path):
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    (work_dir / "safe.txt").write_text("hello", encoding="utf-8")
    outside = tmp_path / "secret.txt"
    outside.write_text("top secret", encoding="utf-8")

    manager = TaskManager()
    app = create_app(task_manager=manager, runner=_PauseRunner())
    with TestClient(app) as client:
        client.post("/api/tasks", json={"id": "api-trav", "prompt": "hi"})
        manager.set_work_dir("api-trav", str(work_dir))
        assert (
            client.get("/api/tasks/api-trav/files/safe.txt").status_code == 200
        )
        for path in ("..%2Fsecret.txt", "%2E%2E%2Fsecret.txt"):
            response = client.get(f"/api/tasks/api-trav/files/{path}")
            assert response.status_code == 404, path
        assert outside.read_text(encoding="utf-8") == "top secret"


def test_api_files_no_workdir():
    with _client() as client:
        client.post("/api/tasks", json={"id": "api-nowd", "prompt": "hi"})
        listing = client.get("/api/tasks/api-nowd/files")
        assert listing.status_code == 200
        assert listing.json()["files"] == []
        assert (
            client.get("/api/tasks/api-nowd/files/anything.txt").status_code
            == 404
        )


def test_api_files_redacts_secrets(tmp_path):
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    (work_dir / "config.json").write_text(
        '{"api_key": "sk-123", "token": "tok-456", "user": "alice"}',
        encoding="utf-8",
    )
    (work_dir / "note.txt").write_text("db password=hunter2 ok", encoding="utf-8")

    manager = TaskManager()
    app = create_app(task_manager=manager, runner=_PauseRunner())
    with TestClient(app) as client:
        client.post("/api/tasks", json={"id": "api-redact", "prompt": "hi"})
        manager.set_work_dir("api-redact", str(work_dir))
        json_resp = client.get("/api/tasks/api-redact/files/config.json")
        txt_resp = client.get("/api/tasks/api-redact/files/note.txt")

    assert (
        json_resp.json()["content"]
        == '{"api_key": "***", "token": "***", "user": "alice"}'
    )
    assert txt_resp.json()["content"] == "db password=*** ok"
    assert "sk-123" not in json_resp.text
    assert "tok-456" not in json_resp.text
    assert "hunter2" not in json_resp.text


def test_api_files_workdir_wired_through_default_runner(tmp_path, monkeypatch):
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

    manager = TaskManager()
    app = create_app(task_manager=manager)
    with TestClient(app) as client:
        client.post("/api/tasks", json={"id": "api-wd", "prompt": "write a file"})
        snapshot = _wait_for_task(manager, "api-wd")
        assert snapshot["status"] == "completed"
        assert manager.get_work_dir("api-wd") is not None
        body = client.get("/api/tasks/api-wd/files").json()
        assert [entry["path"] for entry in body["files"]] == ["result.txt"]


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


# ---------- llm_mode runtime override (P6-10) ----------


def _wait_for_task(manager, task_id, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snapshot = manager.snapshot(task_id)
        if snapshot["status"] in {"completed", "failed"}:
            if snapshot["status"] != "failed" or snapshot.get("error"):
                return snapshot
        time.sleep(0.05)
    return manager.snapshot(task_id)


def _spy_build_llm(seen):
    def spy_build_llm(config, credential_store=None):
        seen["mock"] = config.llm.mock
        return MockLLM([json.dumps({"done": True})])

    return spy_build_llm


def test_api_task_llm_mode_real_uses_real_llm(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr("harness.llm_adapter.build_llm", _spy_build_llm(seen))
    monkeypatch.chdir(tmp_path)

    manager = TaskManager()
    app = create_app(task_manager=manager)
    with TestClient(app) as client:
        client.post(
            "/api/tasks", json={"id": "api-real", "prompt": "do it", "llm_mode": "real"}
        )
        snapshot = _wait_for_task(manager, "api-real")

    assert snapshot["status"] == "completed"
    assert seen.get("mock") is False


def test_api_task_llm_mode_mock_uses_mock(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_LLM_MOCK", "false")
    seen = {}
    monkeypatch.setattr("harness.llm_adapter.build_llm", _spy_build_llm(seen))
    monkeypatch.chdir(tmp_path)

    manager = TaskManager()
    app = create_app(task_manager=manager)
    with TestClient(app) as client:
        client.post(
            "/api/tasks", json={"id": "api-mock", "prompt": "do it", "llm_mode": "mock"}
        )
        snapshot = _wait_for_task(manager, "api-mock")

    assert snapshot["status"] == "completed"
    assert seen.get("mock") is True


def test_api_task_default_mock(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr("harness.llm_adapter.build_llm", _spy_build_llm(seen))
    monkeypatch.chdir(tmp_path)

    manager = TaskManager()
    app = create_app(task_manager=manager)
    with TestClient(app) as client:
        client.post("/api/tasks", json={"id": "api-default", "prompt": "do it"})
        snapshot = _wait_for_task(manager, "api-default")

    assert snapshot["status"] == "completed"
    assert seen.get("mock") is True


def test_api_task_llm_mode_real_without_key_fails_clearly(tmp_path, monkeypatch):
    monkeypatch.setattr("keyring.get_password", lambda service, key: None)
    monkeypatch.chdir(tmp_path)

    manager = TaskManager()
    app = create_app(task_manager=manager)
    with TestClient(app) as client:
        client.post(
            "/api/tasks",
            json={"id": "api-nokey", "prompt": "do it", "llm_mode": "real"},
        )
        snapshot = _wait_for_task(manager, "api-nokey")

    assert snapshot["status"] == "failed"
    assert "credential" in snapshot["error"].lower()


# ---------- task-level base_url runtime override ----------


def test_api_task_base_url_used_in_build_llm(tmp_path, monkeypatch):
    from harness import llm_adapter

    real_build_llm = llm_adapter.build_llm
    seen = {}

    def spy_build_llm(config, credential_store=None):
        client = real_build_llm(config, credential_store=credential_store)
        seen["client"] = client
        seen["base_url"] = config.llm.base_url
        return MockLLM([json.dumps({"done": True})])

    monkeypatch.setattr("keyring.get_password", lambda service, key: "sk-test")
    monkeypatch.setattr("harness.llm_adapter.build_llm", spy_build_llm)
    monkeypatch.chdir(tmp_path)

    manager = TaskManager()
    app = create_app(task_manager=manager)
    with TestClient(app) as client:
        client.post(
            "/api/tasks",
            json={
                "id": "api-base-url",
                "prompt": "do it",
                "llm_mode": "real",
                "base_url": "http://127.0.0.1:9888/v1",
            },
        )
        snapshot = _wait_for_task(manager, "api-base-url")

    assert snapshot["status"] == "completed"
    assert seen.get("base_url") == "http://127.0.0.1:9888/v1"
    assert isinstance(seen["client"], OpenAIClient)
    assert seen["client"]._base_url == "http://127.0.0.1:9888/v1"


def test_api_work_dir_under_harness_tasks(tmp_path, monkeypatch):
    def fake_build_llm(config, credential_store=None):
        return MockLLM([json.dumps({"done": True})])

    monkeypatch.setattr("harness.llm_adapter.build_llm", fake_build_llm)
    monkeypatch.chdir(tmp_path)

    manager = TaskManager()
    app = create_app(task_manager=manager)
    with TestClient(app) as client:
        client.post("/api/tasks", json={"id": "api-wd2", "prompt": "write"})
        snapshot = _wait_for_task(manager, "api-wd2")

    assert snapshot["status"] == "completed"
    work_dir = Path(manager.get_work_dir("api-wd2"))
    assert work_dir.parent.name == "harness-tasks"
    assert work_dir.name == "api-wd2"


def test_api_harness_tasks_dir_autocreated(tmp_path, monkeypatch):
    def fake_build_llm(config, credential_store=None):
        return MockLLM([json.dumps({"done": True})])

    monkeypatch.setattr("harness.llm_adapter.build_llm", fake_build_llm)
    monkeypatch.chdir(tmp_path)

    manager = TaskManager()
    app = create_app(task_manager=manager)
    with TestClient(app) as client:
        client.post("/api/tasks", json={"id": "api-auto", "prompt": "write"})
        snapshot = _wait_for_task(manager, "api-auto")

    assert snapshot["status"] == "completed"
    tasks_dir = Path(tmp_path) / "harness-tasks"
    assert tasks_dir.is_dir()
    assert (tasks_dir / "api-auto").is_dir()


def test_api_work_dir_added_to_sandbox_allowed_dirs(tmp_path, monkeypatch):
    def fake_build_llm(config, credential_store=None):
        return MockLLM([json.dumps({"done": True})])

    monkeypatch.setattr("harness.llm_adapter.build_llm", fake_build_llm)
    monkeypatch.chdir(tmp_path)

    manager = TaskManager()
    app = create_app(task_manager=manager)
    with TestClient(app) as client:
        client.post("/api/tasks", json={"id": "api-sb", "prompt": "write"})
        _wait_for_task(manager, "api-sb")

    work_dir = Path(manager.get_work_dir("api-sb")).resolve()
    assert work_dir.is_dir()
    assert work_dir.parent.name == "harness-tasks"
    assert work_dir.name == "api-sb"


@pytest.mark.parametrize("bad_id", ["..", "."])
def test_api_work_dir_dot_ids_fall_back_inside_harness_tasks(
    tmp_path, monkeypatch, bad_id
):
    def fake_build_llm(config, credential_store=None):
        return MockLLM([json.dumps({"done": True})])

    monkeypatch.setattr("harness.llm_adapter.build_llm", fake_build_llm)
    monkeypatch.chdir(tmp_path)

    manager = TaskManager()
    app = create_app(task_manager=manager)
    with TestClient(app) as client:
        client.post("/api/tasks", json={"id": bad_id, "prompt": "write"})
        snapshot = _wait_for_task(manager, bad_id)

    assert snapshot["status"] == "completed"
    work_dir = Path(manager.get_work_dir(bad_id)).resolve()
    base = Path(tmp_path).resolve()
    assert work_dir != base
    assert work_dir.is_relative_to(base / "harness-tasks")


def test_api_work_dir_drive_colon_id_does_not_escape(tmp_path, monkeypatch):
    def fake_build_llm(config, credential_store=None):
        return MockLLM([json.dumps({"done": True})])

    monkeypatch.setattr("harness.llm_adapter.build_llm", fake_build_llm)
    monkeypatch.chdir(tmp_path)

    manager = TaskManager()
    app = create_app(task_manager=manager)
    with TestClient(app) as client:
        client.post("/api/tasks", json={"id": "D:foo", "prompt": "write"})
        snapshot = _wait_for_task(manager, "D:foo")

    assert snapshot["status"] == "completed"
    work_dir = Path(manager.get_work_dir("D:foo")).resolve()
    base = Path(tmp_path).resolve()
    assert work_dir != base
    assert work_dir.is_relative_to(base / "harness-tasks")
