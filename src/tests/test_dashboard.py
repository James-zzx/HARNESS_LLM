import re
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

WEBUI_DIR = Path(__file__).resolve().parent.parent / "harness" / "webui"

MARKERS = [
    "task-list",
    "task-detail",
    "log-area",
    "hitl-approve",
    "hitl-reject",
    "message-input",
    "upload-button",
]


def _webui_client() -> TestClient:
    app = FastAPI()
    app.mount("/", StaticFiles(directory=WEBUI_DIR, html=True), name="webui")
    return TestClient(app)


def _read(name: str) -> str:
    return (WEBUI_DIR / name).read_text(encoding="utf-8")


def test_dashboard_index_served():
    with _webui_client() as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    for marker in MARKERS:
        assert marker in response.text


def test_dashboard_static_assets():
    assert (WEBUI_DIR / "index.html").is_file()
    assert (WEBUI_DIR / "style.css").is_file()
    assert (WEBUI_DIR / "app.js").is_file()
    assert 'id="task-list"' in _read("index.html")
    assert 'id="log-area"' in _read("index.html")
    with _webui_client() as client:
        assert client.get("/style.css").status_code == 200
        assert client.get("/app.js").status_code == 200


def test_dashboard_no_external_refs():
    for name in ("index.html", "style.css", "app.js"):
        content = _read(name)
        assert "http://" not in content, name
        assert "https://" not in content, name
        assert "url(" not in content, name
        assert re.search(r"//[A-Za-z0-9.-]+\.[A-Za-z]{2,}", content) is None, name
    assert re.search(r"@import\b", _read("style.css")) is None


def test_dashboard_index_assets_resolve_through_create_app():
    from urllib.parse import urljoin

    from harness.api import create_app

    app = create_app(
        runner=lambda task, gate, message_queue=None, on_orchestrator=None: None
    )
    with TestClient(app) as client:
        index = client.get("/")
        assert index.status_code == 200
        refs = re.findall(r'(?:href|src)="([^"]+)"', index.text)
        refs = [ref for ref in refs if not ref.startswith("data:")]
        assert refs, "expected at least one stylesheet/script reference"
        for ref in refs:
            resolved = urljoin("/", ref)
            response = client.get(resolved)
            assert response.status_code == 200, resolved


def test_dashboard_connection_probe_runs_without_tasks():
    js = _read("app.js")
    assert 'fetch("/api/health")' in js
    probe = js.index("probeConnection()")
    loop = js.index("for (const id of taskIds)")
    assert 0 <= probe < loop


def test_dashboard_markers():
    html = _read("index.html")
    for marker in MARKERS:
        assert re.search(rf'id="{marker}"', html) is not None, marker


def test_dashboard_uvicorn_invoked(monkeypatch):
    from harness.config import HarnessConfig
    from harness.dashboard import run_dashboard

    config = HarnessConfig()
    config.webui.host = "0.0.0.0"
    config.webui.port = 9876

    calls = []

    def fake_uvicorn_run(app, **kwargs):
        calls.append((app, kwargs))

    monkeypatch.setattr("harness.dashboard.uvicorn.run", fake_uvicorn_run)

    run_dashboard(config)

    assert len(calls) == 1
    app, kwargs = calls[0]
    assert kwargs["host"] == "0.0.0.0"
    assert kwargs["port"] == 9876


def test_api_mounts_static():
    from harness.api import create_app

    app = create_app(
        runner=lambda task, gate, message_queue=None, on_orchestrator=None: None
    )
    with TestClient(app) as client:
        index = client.get("/static/webui/index.html")
        assert index.status_code == 200
        assert "text/html" in index.headers["content-type"]
        assert client.get("/static/webui/style.css").status_code == 200
        assert client.get("/static/webui/app.js").status_code == 200
        landing = client.get("/")
        assert landing.status_code == 200
        assert "AI Agent Harness" in landing.text


def test_dashboard_llm_mode_toggle():
    html = _read("index.html")
    assert 'id="llm-mode"' in html
    assert 'value="mock"' in html
    assert 'value="real"' in html
    js = _read("app.js")
    assert "harness.dashboard.llm_mode" in js
    assert "localStorage.getItem" in js
    assert "/api/credential/" in js


def test_dashboard_api_key_button():
    html = _read("index.html")
    assert 'id="api-key-btn"' in html
    assert 'id="api-key-modal"' in html
    assert 'id="cred-service"' in html
    assert 'id="cred-key"' in html
    assert 'id="cred-value"' in html
    assert 'id="cred-status"' in html
    js = _read("app.js")
    assert '"/api/credential/"' in js
    assert 'method: "PUT"' in js
    assert 'method: "DELETE"' in js


def test_dashboard_files_section():
    html = _read("index.html")
    assert "产物文件" in html
    assert 'id="files-panel"' in html
    assert 'id="files-list"' in html
    assert 'id="file-viewer"' in html
    js = _read("app.js")
    assert '"/files"' in js
    assert "/download" in js
    assert "renderFiles" in js


def _function_body(js: str, name: str) -> str:
    start = js.index(f"function {name}(")
    start = js.index("{", start)
    depth = 0
    for i in range(start, len(js)):
        ch = js[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return js[start : i + 1]
    raise AssertionError(f"function {name} not closed")


def test_dashboard_conversation_keeps_scroll_position():
    js = _read("app.js")
    body = _function_body(js, "renderConversation")
    assert "getAttribute(\"data-task-id\")" in body
    assert "setAttribute(\"data-task-id\", selectedId)" in body
    assert "scrollHeight - box.scrollTop - box.clientHeight < 24" in body
    assert "if (stick) box.scrollTop = box.scrollHeight;" in body


def test_dashboard_render_files_guards_stale_task():
    js = _read("app.js")
    body = _function_body(js, "renderFiles")
    assert 'encodeURIComponent(id)' in body
    assert "id !== selectedId" in body
    assert "if (id !== selectedId) return;" in body

