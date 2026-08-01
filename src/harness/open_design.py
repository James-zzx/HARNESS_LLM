import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional, Protocol

import httpx

from harness.config import OpenDesignConfig
from harness.logger import get_logger

DEFAULT_HEALTH_TIMEOUT = 30.0
DEFAULT_HEALTH_POLL = 0.2
DEFAULT_REQUEST_TIMEOUT = 10.0


class ODNotFoundError(Exception):
    pass


class ODDaemonError(Exception):
    pass


class OpenDesignConfigLike(Protocol):
    enabled: bool
    port: int
    data_dir: str
    daemon_url: Optional[str]


class OpenDesignClient:
    def __init__(
        self,
        *,
        config: Optional[OpenDesignConfigLike] = None,
        od_path: Optional[str] = None,
        transport: Optional[httpx.BaseTransport] = None,
        logger: Optional[object] = None,
    ) -> None:
        config = config or OpenDesignConfig()
        self._config = config
        self._od_path = od_path
        self._data_dir = Path(config.data_dir)
        self._base_url = config.daemon_url or f"http://127.0.0.1:{config.port}"
        self._logger = logger or get_logger("harness.open_design")
        self._process: Optional[subprocess.Popen] = None
        self._log_threads: list[threading.Thread] = []
        self._client = httpx.Client(
            base_url=self._base_url,
            timeout=DEFAULT_REQUEST_TIMEOUT,
            transport=transport,
        )

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "OpenDesignClient":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def health_check(self) -> bool:
        try:
            response = self._client.get("/api/health")
        except (httpx.HTTPError, OSError):
            return False
        return response.status_code == 200

    def wait_until_healthy(self, timeout: float = DEFAULT_HEALTH_TIMEOUT) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.health_check():
                return True
            time.sleep(DEFAULT_HEALTH_POLL)
        return False

    def list_projects(self) -> list:
        response = self._client.get("/api/projects")
        response.raise_for_status()
        data = response.json()
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("projects"), list):
            return data["projects"]
        return []

    def create_artifact(self, project_id: str, type: str, content: str) -> str:
        response = self._client.post(
            f"/api/projects/{project_id}/artifacts",
            json={"type": type, "content": content},
        )
        response.raise_for_status()
        data = response.json()
        artifact_id = None
        if isinstance(data, dict):
            artifact_id = data.get("artifact_id") or data.get("id")
        if artifact_id is None:
            raise ODDaemonError("Open Design daemon returned no artifact id")
        return str(artifact_id)

    def start_daemon(self, *, health_timeout: float = DEFAULT_HEALTH_TIMEOUT) -> None:
        if self.is_running:
            return
        od_path = self._find_od()
        self._data_dir.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        env["OD_DATA_DIR"] = str(self._data_dir)
        self._process = subprocess.Popen(
            [od_path, "--headless", "--no-open"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self._redirect_logs()
        if not self.wait_until_healthy(timeout=health_timeout):
            self._logger.warning("open_design.daemon.unhealthy", base_url=self._base_url)

    def stop_daemon(self, *, timeout: float = 5.0) -> None:
        if self._process is None:
            return
        self._process.terminate()
        try:
            self._process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait(timeout=timeout)
        self._process = None
        self._log_threads.clear()

    def restart(self) -> None:
        self.stop_daemon()
        self.start_daemon()

    def _find_od(self) -> str:
        if self._od_path:
            return self._od_path
        found = shutil.which("od")
        if not found:
            raise ODNotFoundError("Open Design executable 'od' not found in PATH")
        return found

    def _redirect_logs(self) -> None:
        for stream, log_callable in (
            (self._process.stdout, self._logger.info),
            (self._process.stderr, self._logger.warning),
        ):
            thread = threading.Thread(
                target=self._pump_stream,
                args=(stream, log_callable),
                daemon=True,
            )
            thread.start()
            self._log_threads.append(thread)

    @staticmethod
    def _pump_stream(stream, log_callable) -> None:
        if stream is None:
            return
        for line in iter(stream.readline, ""):
            if line and line.strip():
                log_callable("open_design.daemon", line=line.rstrip())
