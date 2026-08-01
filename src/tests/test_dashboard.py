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
    assert re.search(r"@import\b", _read("style.css")) is None


def test_dashboard_markers():
    html = _read("index.html")
    for marker in MARKERS:
        assert re.search(rf'id="{marker}"', html) is not None, marker
