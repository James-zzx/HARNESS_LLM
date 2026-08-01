import dataclasses
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Protocol

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from harness.hitl import HITLGate
from harness.message_queue import MessageQueue
from harness.orchestrator import Orchestrator, RunResult
from harness.task import Task, TaskError, TaskParser, TaskStatus

_WEBUI_DIR = Path(__file__).resolve().parent / "webui"

_STATUS_MAP = {
    "COMPLETED": TaskStatus.COMPLETED,
    "FAILED": TaskStatus.FAILED,
    "PAUSED": TaskStatus.PAUSED,
}


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
            self._record(task_id).messages.append(message)

    def get_messages(self, task_id: str) -> list[dict]:
        with self._lock:
            return list(self._record(task_id).messages)

    def attach_orchestrator(self, task_id: str, orchestrator: Orchestrator) -> None:
        with self._lock:
            self._record(task_id).orchestrator = orchestrator

    def get_interrupt_requested(self, task_id: str) -> bool:
        with self._lock:
            return self._record(task_id).interrupt_requested

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


def _default_runner() -> TaskRunner:
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
        llm = build_llm(config)
        task_work_dir = tempfile.mkdtemp(
            prefix="harness-task-", dir=str(runtime.work_dir)
        )
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


def create_app(
    *,
    task_manager: Optional[TaskManager] = None,
    runner: Optional[TaskRunner] = None,
) -> FastAPI:
    manager = task_manager or TaskManager()
    run = runner or _default_runner()

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
