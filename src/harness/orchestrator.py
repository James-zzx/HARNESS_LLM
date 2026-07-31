import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Protocol

from harness.llm_adapter import LLMClient
from harness.logger import TraceContext, get_logger
from harness.memory import ConversationMemory
from harness.tool_executor import ToolExecutor

logger = get_logger("harness.orchestrator")

DEFAULT_MAX_CONTEXT_TOKENS = 8000

INIT = "INIT"
TASK_LOADED = "TASK_LOADED"
LLM_CALL = "LLM_CALL"
TOOL_EXEC = "TOOL_EXEC"
EVAL = "EVAL"
HITL_CHECK = "HITL_CHECK"
PAUSED = "PAUSED"
COMPLETED = "COMPLETED"
FAILED = "FAILED"

_SYSTEM_PROMPT = (
    "You are an autonomous coding agent. Reply with a single JSON object. "
    'To call a tool use {"thought": "...", "tool": "<tool_name>", "params": {...}}. '
    'To finish the task use {"done": true}. '
    "Available tools: write_file, read_file, edit_file, run_shell, list_dir."
)


@dataclass
class Task:
    id: str
    prompt: str
    eval_command: Optional[str] = None
    max_iterations: int = 10
    timeout: int = 120


@dataclass
class EvaluationResult:
    passed: bool
    output: str = ""
    error: str = ""
    exit_code: Optional[int] = None


@dataclass
class RunResult:
    status: str
    final_state: str
    iterations: int
    error: Optional[str] = None


class Evaluator(Protocol):
    def evaluate(self, task: Task) -> EvaluationResult: ...


class SubprocessEvaluator:
    def __init__(self, work_dir: str | Path = "."):
        self._work_dir = Path(work_dir).resolve()

    def evaluate(self, task: Task) -> EvaluationResult:
        if not task.eval_command:
            return EvaluationResult(passed=True)
        try:
            completed = subprocess.run(
                task.eval_command,
                shell=True,
                capture_output=True,
                text=True,
                cwd=str(self._work_dir),
            )
        except OSError as exc:
            return EvaluationResult(passed=False, error=str(exc))
        return EvaluationResult(
            passed=completed.returncode == 0,
            output=completed.stdout,
            error=completed.stderr,
            exit_code=completed.returncode,
        )


def _always_safe(tool_name: str, params: dict) -> bool:
    return False


def _auto_approve(tool_name: str, params: dict) -> bool:
    return True


class Orchestrator:
    def __init__(
        self,
        llm: LLMClient,
        work_dir: str | Path = ".",
        evaluator: Optional[Evaluator] = None,
        hitl_checker: Callable[[str, dict], bool] = _always_safe,
        approval: Callable[[str, dict], bool] = _auto_approve,
        max_context_tokens: int = DEFAULT_MAX_CONTEXT_TOKENS,
        tool_executor: Optional[ToolExecutor] = None,
    ):
        self._llm = llm
        self._work_dir = Path(work_dir).resolve()
        self._evaluator = evaluator or SubprocessEvaluator(self._work_dir)
        self._hitl_checker = hitl_checker
        self._approval = approval
        self._max_context_tokens = max_context_tokens
        self._tool_executor = tool_executor or ToolExecutor(work_dir=str(self._work_dir))
        self._memory = ConversationMemory()
        self._state = INIT
        self._error: Optional[str] = None
        self._iterations = 0

    @property
    def state(self) -> str:
        return self._state

    @property
    def memory(self) -> ConversationMemory:
        return self._memory

    @property
    def iterations(self) -> int:
        return self._iterations

    @property
    def error(self) -> Optional[str]:
        return self._error

    def run(self, task: Task) -> RunResult:
        if not task.prompt:
            raise ValueError("task.prompt is required")
        if task.max_iterations <= 0:
            raise ValueError("task.max_iterations must be positive")
        if task.timeout <= 0:
            raise ValueError("task.timeout must be positive")

        with TraceContext(trace_id=task.id, phase="orchestrator"):
            self._task = task
            self._iterations = 0
            self._error = None
            self._state = INIT
            self._memory.clear()
            self._seed_memory(task)
            self._state = TASK_LOADED
            logger.info("orchestrator.started", task_id=task.id)
            deadline = time.monotonic() + task.timeout
            try:
                return self._run_loop(deadline)
            except Exception as exc:
                logger.error("orchestrator.crash", error=str(exc))
                return self._fail(f"unexpected error: {exc}")

    def _run_loop(self, deadline: float) -> RunResult:
        while True:
            if time.monotonic() > deadline:
                return self._fail("timeout exceeded")
            if self._iterations >= self._task.max_iterations:
                return self._fail("max iterations reached")

            self._state = LLM_CALL
            self._iterations += 1
            context = self._memory.get_context_window(self._max_context_tokens)
            response = self._llm.chat(context)
            if response is None or not response.content:
                self._memory.add_message(role="assistant", content=response.content if response else "")
                self._memory.add_message(
                    role="tool",
                    content=json.dumps({"error": "LLM returned an empty response"}),
                )
                continue

            intent = self._parse_intent(response.content)
            if intent is None:
                self._memory.add_message(role="assistant", content=response.content)
                self._memory.add_message(
                    role="tool",
                    content=json.dumps({"error": "intent must be a JSON object with 'tool' or 'done'"}),
                )
                continue

            if intent.get("done"):
                self._state = EVAL
                eval_result = self._evaluator.evaluate(self._task)
                self._memory.add_message(role="assistant", content=response.content)
                self._memory.add_message(role="tool", content=self._format_eval_result(eval_result))
                if eval_result.passed:
                    self._state = COMPLETED
                    logger.info("orchestrator.completed", iterations=self._iterations)
                    return RunResult(status=COMPLETED, final_state=COMPLETED, iterations=self._iterations)
                continue

            tool_name = intent.get("tool")
            if not isinstance(tool_name, str) or not tool_name:
                self._memory.add_message(role="assistant", content=response.content)
                self._memory.add_message(
                    role="tool",
                    content=json.dumps({"error": "intent missing 'tool' name"}),
                )
                continue

            self._state = HITL_CHECK
            params = intent.get("params", {}) if isinstance(intent.get("params", {}), dict) else {}
            if self._hitl_checker(tool_name, params):
                self._state = PAUSED
                approved = self._approval(tool_name, params)
                if not approved:
                    logger.warning("orchestrator.paused", tool=tool_name, iterations=self._iterations)
                    return RunResult(status=PAUSED, final_state=PAUSED, iterations=self._iterations)

            self._state = TOOL_EXEC
            result = self._tool_executor.execute(intent)
            self._memory.add_message(role="assistant", content=response.content)
            self._memory.add_message(role="tool", content=self._format_tool_result(tool_name, result))

    def _seed_memory(self, task: Task) -> None:
        self._memory.add_message(role="system", content=_SYSTEM_PROMPT)
        self._memory.add_message(role="user", content=task.prompt)

    @staticmethod
    def _parse_intent(content: str):
        text = content.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
        return None

    @staticmethod
    def _format_tool_result(tool_name: str, result) -> str:
        return json.dumps(
            {
                "tool": tool_name,
                "success": result.success,
                "output": result.output,
                "error": result.error,
                "exit_code": result.exit_code,
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _format_eval_result(result: EvaluationResult) -> str:
        return json.dumps(
            {
                "evaluation": {
                    "passed": result.passed,
                    "output": result.output,
                    "error": result.error,
                    "exit_code": result.exit_code,
                }
            },
            ensure_ascii=False,
        )

    def _fail(self, error: str) -> RunResult:
        self._state = FAILED
        self._error = error
        logger.error("orchestrator.failed", error=error, iterations=self._iterations)
        return RunResult(status=FAILED, final_state=FAILED, iterations=self._iterations, error=error)
