import io
import json
import threading
import time
from types import SimpleNamespace

import httpx
import pytest

from harness.hitl import HITLGate
from harness.open_design import ODDaemonError, ODNotFoundError, OpenDesignClient


class _FakeDaemonProcess:
    def __init__(self):
        self.stdout = io.StringIO("daemon ready\n")
        self.stderr = io.StringIO("")
        self._code = None

    def poll(self):
        return self._code

    def terminate(self):
        self._code = 0

    def kill(self):
        self._code = -9

    def wait(self, timeout=None):
        return self._code


def _od_config(data_dir=".open_design"):
    return SimpleNamespace(enabled=True, port=7456, data_dir=data_dir, daemon_url=None)


def _healthy_transport():
    return httpx.MockTransport(handler=lambda request: httpx.Response(200, json={"status": "ok"}))


def test_od_client_health_check():
    client = OpenDesignClient(config=_od_config(), transport=_healthy_transport())
    assert client.health_check() is True


def test_od_client_health_failure():
    transport = httpx.MockTransport(
        handler=lambda request: httpx.Response(500, json={"error": "boom"})
    )
    client = OpenDesignClient(config=_od_config(), transport=transport)
    assert client.health_check() is False


def test_od_client_health_connection_error():
    def handler(request):
        raise httpx.ConnectError("connection refused")

    client = OpenDesignClient(config=_od_config(), transport=httpx.MockTransport(handler=handler))
    assert client.health_check() is False


def test_od_daemon_start_stop(tmp_path, monkeypatch):
    process = _FakeDaemonProcess()
    calls = []

    def fake_popen(args, **kwargs):
        calls.append((args, kwargs))
        return process

    monkeypatch.setattr("harness.open_design.subprocess.Popen", fake_popen)
    data_dir = str(tmp_path / "od")
    client = OpenDesignClient(
        config=_od_config(data_dir=data_dir),
        od_path="od",
        transport=_healthy_transport(),
    )

    client.start_daemon()
    assert client.is_running is True
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == ["od", "--headless", "--no-open"]
    assert kwargs["env"]["OD_DATA_DIR"] == data_dir

    client.start_daemon()
    assert len(calls) == 1

    client.stop_daemon()
    assert client.is_running is False


def test_od_daemon_not_found(monkeypatch):
    monkeypatch.setattr("harness.open_design.shutil.which", lambda name: None)
    client = OpenDesignClient(config=_od_config())
    with pytest.raises(ODNotFoundError):
        client.start_daemon()
    with pytest.raises(ODNotFoundError):
        client.restart()


def test_od_create_artifact():
    def handler(request):
        assert request.method == "POST"
        assert request.url.path == "/api/projects/proj-1/artifacts"
        assert json.loads(request.content) == {"type": "diagram", "content": "architecture"}
        return httpx.Response(201, json={"artifact_id": "art-42"})

    client = OpenDesignClient(
        config=_od_config(), transport=httpx.MockTransport(handler=handler)
    )
    assert client.create_artifact("proj-1", "diagram", "architecture") == "art-42"


def test_od_daemon_start_returns_url_and_stops():
    from harness.main import start_open_design_daemon, stop_open_design_daemon

    class _FakeClient:
        base_url = "http://127.0.0.1:7456"

        def start_daemon(self):
            calls.append("start")

        def stop_daemon(self):
            calls.append("stop")

        def health_check(self):
            return True

    calls = []
    client = _FakeClient()
    assert start_open_design_daemon(client) == "http://127.0.0.1:7456"
    stop_open_design_daemon(client)
    assert calls == ["start", "stop"]


def test_od_daemon_unhealthy_raises():
    from harness.main import start_open_design_daemon

    class _UnhealthyClient:
        base_url = "http://127.0.0.1:3000"

        def start_daemon(self):
            pass

        def health_check(self):
            return False

    with pytest.raises(ODDaemonError):
        start_open_design_daemon(_UnhealthyClient())


def test_api_approval_resumes_paused_task():
    from fastapi.testclient import TestClient

    from harness.api import TaskManager, create_app
    from harness.orchestrator import RunResult
    from harness.task import Task, TaskStatus

    class _DecisionRunner:
        def __call__(self, task, gate):
            gate.check("run_shell", {"command": "rm -rf /"})
            approved = gate.decide("run_shell", {"command": "rm -rf /"})
            if approved:
                return RunResult(status="COMPLETED", final_state="COMPLETED", iterations=1)
            return RunResult(status="PAUSED", final_state="PAUSED", iterations=0)

    manager = TaskManager()
    app = create_app(task_manager=manager, runner=_DecisionRunner())
    task = Task(id="bridge-1", prompt="fix the lint errors")
    manager.create(task)

    def run_background():
        gate = HITLGate()
        manager.attach_hitl_gate(task.id, gate)
        result = _DecisionRunner()(task, gate)
        status = (
            TaskStatus.COMPLETED if result.status == "COMPLETED" else TaskStatus.PAUSED
        )
        manager.set_status(task.id, status)
        manager.set_iterations(task.id, result.iterations)

    thread = threading.Thread(target=run_background, daemon=True)
    thread.start()

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        gate = manager.get_gate(task.id)
        if gate is not None and gate.state == "PAUSED":
            break
        time.sleep(0.05)
    else:
        thread.join(timeout=1)
        pytest.fail("gate never reached PAUSED")

    with TestClient(app) as client:
        response = client.post("/api/hitl/bridge-1/approve")
        assert response.status_code == 200
        assert response.json()["hitl_state"] == "APPROVED"

    thread.join(timeout=10)
    assert not thread.is_alive(), "task thread did not resume after approval"
    assert manager.snapshot(task.id)["status"] == "completed"
