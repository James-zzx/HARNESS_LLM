import dataclasses
import json
import re
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Protocol
from urllib.parse import unquote

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from harness.credential_store import CredentialStore
from harness.hitl import HITLGate
from harness.logger import redact as redact_data
from harness.message_queue import MessageQueue
from harness.orchestrator import Orchestrator, RunResult
from harness.task import Task, TaskError, TaskParser, TaskStatus

_WEBUI_DIR = Path(__file__).resolve().parent / "webui"

_STATUS_MAP = {
    "COMPLETED": TaskStatus.COMPLETED,
    "FAILED": TaskStatus.FAILED,
    "PAUSED": TaskStatus.PAUSED,
}

_SENSITIVE_PAIR = re.compile(
    r"(?i)([a-z0-9_]*"
    r"(?:(?<![a-z0-9])key(?![a-z0-9])|secret|token|password|credential_ref)"
    r"[a-z0-9_]*\s*[:=]\s*)"
    r"(\"[^\"]*\"|'[^']*'|[^\s\"',}]+)"
)


def _make_task_work_dir(base: Path, task_id: str) -> str:
    tasks_dir = Path(base) / "harness-tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    if task_id and not any(sep in task_id for sep in ("/", "\\")):
        work_dir = tasks_dir / task_id
        work_dir.mkdir(parents=True, exist_ok=True)
        return str(work_dir)
    return tempfile.mkdtemp(prefix="harness-task-", dir=str(tasks_dir))


def _redact_text(content: str) -> str:
    return _SENSITIVE_PAIR.sub(lambda match: match.group(1) + "***", content)


def _redact_content(content: str) -> str:
    stripped = content.strip()
    if stripped[:1] in ("{", "["):
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, (dict, list)):
            return json.dumps(redact_data(parsed), ensure_ascii=False)
    return _redact_text(content)


def redact_message(message: dict) -> dict:
    """Copy a message with sensitive content redacted before storage (§3.1)."""
    role = message.get("role")
    content = message.get("content")
    if isinstance(content, str):
        content = _redact_content(content)
    return {"role": role, "content": content}


class TaskNotFoundError(TaskError):
    pass


class TaskRunner(Protocol):
    def __call__(
        self,
        task: Task,
        gate: HITLGate,
        message_queue: Optional[MessageQueue] = None,
        on_orchestrator: Optional[Callable[[Orchestrator], None]] = None,
    ) -> RunResult: ...


@dataclass
class TaskRecord:
    task: Task
    status: TaskStatus = TaskStatus.PENDING
    error: Optional[str] = None
    iterations: int = 0
    logs: list[str] = field(default_factory=list)
    hitl_gate: Optional[HITLGate] = None
    feedback: Optional[str] = None
    message_queue: Optional[MessageQueue] = None
    messages: list[dict] = field(default_factory=list)
    interrupt_requested: bool = False
    orchestrator: Optional[Orchestrator] = None
    work_dir: Optional[str] = None


class TaskManager:
    def __init__(self) -> None:
        self._records: dict[str, TaskRecord] = {}
        self._lock = threading.Lock()

    def create(self, task: Task) -> None:
        with self._lock:
            if task.id in self._records:
                raise TaskError(f"task already exists: {task.id}")
            self._records[task.id] = TaskRecord(
                task=task, message_queue=MessageQueue(task.id)
            )

    def _record(self, task_id: str) -> TaskRecord:
        record = self._records.get(task_id)
        if record is None:
            raise TaskNotFoundError(f"task not found: {task_id}")
        return record

    def snapshot(self, task_id: str) -> dict:
        with self._lock:
            record = self._record(task_id)
            status = record.status
            gate = record.hitl_gate
            if gate is not None and gate.state == "PAUSED":
                status = TaskStatus.PAUSED
            return {
                "task_id": record.task.id,
                "status": status.value,
                "iterations": record.iterations,
                "error": record.error,
                "logs": list(record.logs),
                "feedback": record.feedback,
            }

    def get_gate(self, task_id: str) -> Optional[HITLGate]:
        with self._lock:
            return self._record(task_id).hitl_gate

    def get_task(self, task_id: str) -> Task:
        with self._lock:
            return dataclasses.replace(self._record(task_id).task)

    def set_status(self, task_id: str, status: TaskStatus) -> None:
        with self._lock:
            self._record(task_id).status = status

    def set_error(self, task_id: str, error: str) -> None:
        with self._lock:
            self._record(task_id).error = error

    def set_iterations(self, task_id: str, iterations: int) -> None:
        with self._lock:
            self._record(task_id).iterations = iterations

    def set_feedback(self, task_id: str, feedback: str) -> None:
        with self._lock:
            self._record(task_id).feedback = feedback

    def append_log(self, task_id: str, line: str) -> None:
        with self._lock:
            self._record(task_id).logs.append(line)

    def attach_hitl_gate(self, task_id: str, gate: HITLGate) -> None:
        with self._lock:
            self._record(task_id).hitl_gate = gate

    def get_message_queue(self, task_id: str) -> MessageQueue:
        with self._lock:
            queue = self._record(task_id).message_queue
            if queue is None:
                raise TaskError(f"task has no message queue: {task_id}")
            return queue

    def append_message(self, task_id: str, message: dict) -> None:
        with self._lock:
            self._record(task_id).messages.append(redact_message(message))

    def get_messages(self, task_id: str) -> list[dict]:
        with self._lock:
            return list(self._record(task_id).messages)

    def attach_orchestrator(self, task_id: str, orchestrator: Orchestrator) -> None:
        with self._lock:
            self._record(task_id).orchestrator = orchestrator

    def get_interrupt_requested(self, task_id: str) -> bool:
        with self._lock:
            return self._record(task_id).interrupt_requested

    def set_work_dir(self, task_id: str, work_dir: str) -> None:
        with self._lock:
            self._record(task_id).work_dir = work_dir

    def get_work_dir(self, task_id: str) -> Optional[str]:
        with self._lock:
            return self._record(task_id).work_dir

    def request_interrupt(self, task_id: str) -> bool:
        with self._lock:
            record = self._record(task_id)
            record.interrupt_requested = True
            orchestrator = record.orchestrator
        if orchestrator is not None:
            orchestrator.interrupt()
        return True


def _map_status(status: str) -> TaskStatus:
    try:
        return _STATUS_MAP[status]
    except KeyError:
        raise TaskError(f"unknown orchestrator status: {status}") from None


def _default_runner(manager: Optional[TaskManager] = None) -> TaskRunner:
    from harness.config import load_config
    from harness.llm_adapter import build_llm
    from harness.runtime import build_runtime

    config = load_config()
    runtime = build_runtime(config)

    def run(
        task: Task,
        gate: HITLGate,
        message_queue: Optional[MessageQueue] = None,
        on_orchestrator: Optional[Callable[[Orchestrator], None]] = None,
    ) -> RunResult:
        llm_mode = getattr(task, "llm_mode", None)
        task_config = config
        if llm_mode in {"mock", "real"}:
            task_config = dataclasses.replace(
                config, llm=dataclasses.replace(config.llm, mock=(llm_mode == "mock"))
            )
        base_url = getattr(task, "base_url", None)
        if base_url:
            task_config = dataclasses.replace(
                task_config, llm=dataclasses.replace(task_config.llm, base_url=base_url)
            )
        llm = build_llm(task_config)
        task_work_dir = _make_task_work_dir(runtime.work_dir, task.id)
        runtime.sandbox.allow_dir(task_work_dir)
        if manager is not None:
            manager.set_work_dir(task.id, task_work_dir)
        orchestrator = runtime.build_orchestrator(
            llm=llm,
            work_dir=task_work_dir,
            hitl_checker=gate.check,
            approval=gate.decide,
            feedback_provider=gate.rejection_feedback,
            message_queue=message_queue,
        )
        if on_orchestrator is not None:
            on_orchestrator(orchestrator)
        return orchestrator.run(task)

    return run


def _default_credential_store() -> CredentialStore:
    from harness.config import load_config
    from harness.credential_store import EnvBackend

    backend = getattr(getattr(load_config(), "credential", None), "backend", "keyring")
    if backend == "env":
        return CredentialStore(backend=EnvBackend())
    return CredentialStore()


def create_app(
    *,
    task_manager: Optional[TaskManager] = None,
    runner: Optional[TaskRunner] = None,
    credential_store: Optional[CredentialStore] = None,
) -> FastAPI:
    manager = task_manager or TaskManager()
    run = runner or _default_runner(manager)
    store = credential_store if credential_store is not None else _default_credential_store()

    default_runtime = None
    if runner is None:
        from harness.config import load_config
        from harness.runtime import build_runtime

        default_runtime = build_runtime(load_config())

    app = FastAPI(title="AI Agent Harness API")

    def _run_task(task_id: str) -> None:
        manager.set_status(task_id, TaskStatus.RUNNING)
        manager.append_log(task_id, "task started")
        gate = default_runtime.new_gate() if default_runtime is not None else HITLGate()
        manager.attach_hitl_gate(task_id, gate)
        queue = manager.get_message_queue(task_id)

        def on_orchestrator(orchestrator: Orchestrator) -> None:
            manager.attach_orchestrator(task_id, orchestrator)
            orchestrator.conversation_sink = lambda message: manager.append_message(
                task_id, message
            )
            if manager.get_interrupt_requested(task_id):
                orchestrator.interrupt()

        try:
            result = run(manager.get_task(task_id), gate, queue, on_orchestrator)
        except Exception as exc:
            manager.set_status(task_id, TaskStatus.FAILED)
            manager.set_error(task_id, str(exc))
            manager.append_log(task_id, f"task failed: {exc}")
            return
        status = _map_status(result.status)
        manager.set_status(task_id, status)
        manager.set_iterations(task_id, getattr(result, "iterations", 0))
        if getattr(result, "error", None):
            manager.set_error(task_id, result.error)
        if getattr(result, "feedback", None):
            manager.set_feedback(task_id, result.feedback)
        manager.append_log(task_id, f"task finished with status {status.value}")

    def _resolve_gate(task_id: str) -> HITLGate:
        gate = manager.get_gate(task_id)
        if gate is None:
            raise TaskError(f"no HITL decision pending for task: {task_id}")
        return gate

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.post("/api/tasks", status_code=201)
    def create_task(body: dict, background_tasks: BackgroundTasks):
        task = TaskParser.from_dict(body)
        manager.create(task)
        background_tasks.add_task(_run_task, task.id)
        return {"task_id": task.id, "status": task.status.value}

    @app.get("/api/tasks/{task_id}")
    def get_task(task_id: str):
        return manager.snapshot(task_id)

    @app.get("/api/tasks/{task_id}/logs")
    def get_task_logs(task_id: str):
        return {"task_id": task_id, "logs": manager.snapshot(task_id)["logs"]}

    @app.post("/api/hitl/{task_id}/approve")
    def hitl_approve(task_id: str):
        gate = _resolve_gate(task_id)
        try:
            gate.approve()
        except ValueError as exc:
            raise TaskError(f"cannot approve task {task_id}: {exc}") from exc
        return {
            "task_id": task_id,
            "status": manager.snapshot(task_id)["status"],
            "hitl_state": gate.state,
        }

    @app.post("/api/hitl/{task_id}/reject")
    def hitl_reject(task_id: str):
        gate = _resolve_gate(task_id)
        try:
            gate.reject()
        except ValueError as exc:
            raise TaskError(f"cannot reject task {task_id}: {exc}") from exc
        return {
            "task_id": task_id,
            "status": manager.snapshot(task_id)["status"],
            "hitl_state": gate.state,
        }

    @app.post("/api/tasks/{task_id}/message")
    def post_task_message(task_id: str, body: dict):
        content = body.get("content")
        if not isinstance(content, str) or not content.strip():
            raise TaskError("message content must be a non-empty string")
        message = {"role": "user", "content": content}
        manager.get_message_queue(task_id).push(message)
        manager.append_message(task_id, message)
        return {"ok": True}

    @app.get("/api/tasks/{task_id}/messages")
    def get_task_messages(task_id: str):
        return {"task_id": task_id, "messages": manager.get_messages(task_id)}

    @app.post("/api/tasks/{task_id}/interrupt")
    def interrupt_task(task_id: str):
        requested = manager.request_interrupt(task_id)
        return {"task_id": task_id, "interrupt_requested": requested}

    def _resolve_work_file(task_id: str, raw_path: str) -> Path:
        work_dir = manager.get_work_dir(task_id)
        if not work_dir:
            raise TaskNotFoundError("task has no work directory")
        base = Path(work_dir).resolve()
        candidate = (base / unquote(raw_path)).resolve()
        if not candidate.is_relative_to(base) or not candidate.is_file():
            raise TaskNotFoundError("file not found")
        return candidate

    @app.get("/api/tasks/{task_id}/files")
    def list_task_files(task_id: str):
        work_dir = manager.get_work_dir(task_id)
        files = []
        if work_dir:
            base = Path(work_dir).resolve()
            if base.is_dir():
                for path in sorted(base.rglob("*")):
                    if path.is_file():
                        files.append(
                            {
                                "path": path.relative_to(base).as_posix(),
                                "size": path.stat().st_size,
                            }
                        )
        return {"task_id": task_id, "files": files}

    @app.get("/api/tasks/{task_id}/files/{path:path}/download")
    def download_task_file(task_id: str, path: str):
        file_path = _resolve_work_file(task_id, path)
        return FileResponse(file_path, filename=file_path.name)

    @app.get("/api/tasks/{task_id}/files/{path:path}")
    def read_task_file(task_id: str, path: str):
        file_path = _resolve_work_file(task_id, path)
        content = file_path.read_text(encoding="utf-8", errors="replace")
        return {"task_id": task_id, "path": path, "content": _redact_content(content)}

    def _require_credential_parts(service: str, key: str) -> None:
        if not service or not key:
            raise TaskNotFoundError("credential service/key not found")

    @app.get("/api/credential/{service}/{key}")
    def get_credential(service: str, key: str):
        _require_credential_parts(service, key)
        return {
            "service": service,
            "key": key,
            "configured": store.get_key(service, key) is not None,
        }

    @app.put("/api/credential/{service}/{key}")
    def put_credential(service: str, key: str, body: dict):
        _require_credential_parts(service, key)
        value = body.get("value")
        if not isinstance(value, str) or not value.strip():
            raise TaskError("credential value must be a non-empty string")
        store.set_key(service, key, value)
        return {"configured": True}

    @app.delete("/api/credential/{service}/{key}")
    def delete_credential(service: str, key: str):
        _require_credential_parts(service, key)
        store.delete_key(service, key)
        return {"configured": False}

    @app.exception_handler(TaskNotFoundError)
    def handle_not_found(request: Request, exc: TaskNotFoundError):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(TaskError)
    def handle_task_error(request: Request, exc: TaskError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(Exception)
    def handle_unexpected(request: Request, exc: Exception):
        if isinstance(exc, HTTPException):
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        return JSONResponse(status_code=500, content={"detail": "internal server error"})

    if _WEBUI_DIR.is_dir():
        app.mount(
            "/static/webui",
            StaticFiles(directory=_WEBUI_DIR, html=True),
            name="webui",
        )

        @app.get("/", include_in_schema=False)
        def dashboard_index():
            return FileResponse(_WEBUI_DIR / "index.html", media_type="text/html")

    return app


app = create_app()
