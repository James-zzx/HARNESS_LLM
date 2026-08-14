import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from harness.logger import TraceContext, get_logger
from harness.sandbox import communicate_with_timeout

logger = get_logger("harness.tool_executor")


@dataclass
class ToolResult:
    success: bool
    output: str = ""
    error: str = ""
    exit_code: Optional[int] = None


class Tool:
    name: str = ""
    description: str = ""

    def execute(self, params: Dict[str, Any]) -> ToolResult:
        raise NotImplementedError


_PATH_KEYS = ("path", "file_path", "filepath")


def _path_param(params: dict) -> str:
    """Return the target path from tool params, honoring the aliases some
    LLMs emit alongside the canonical ``path`` key (``file_path``, ``filepath``)."""
    for key in _PATH_KEYS:
        raw = params.get(key)
        if raw is not None:
            return str(raw)
    return ""


class _PathTool(Tool):
    def __init__(self, work_dir: Path):
        self._work_dir = work_dir.resolve()

    def _resolve(self, raw_path: str) -> Path:
        candidate = (self._work_dir / raw_path).resolve()
        if not candidate.is_relative_to(self._work_dir):
            raise ValueError(f"path escapes working directory: {raw_path}")
        return candidate


class ReadFileTool(_PathTool):
    name = "read_file"
    description = "Read the contents of a file within the working directory."

    def execute(self, params: Dict[str, Any]) -> ToolResult:
        try:
            path = self._resolve(_path_param(params))
            return ToolResult(success=True, output=path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            return ToolResult(success=False, error=str(exc))


class WriteFileTool(_PathTool):
    name = "write_file"
    description = "Write content to a file within the working directory."

    def execute(self, params: Dict[str, Any]) -> ToolResult:
        try:
            path = self._resolve(_path_param(params))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(params.get("content", "")), encoding="utf-8")
            return ToolResult(success=True, output=f"wrote {path}")
        except (OSError, ValueError) as exc:
            return ToolResult(success=False, error=str(exc))


class EditFileTool(_PathTool):
    name = "edit_file"
    description = "Replace the first occurrence of old_string with new_string in a file."

    def execute(self, params: Dict[str, Any]) -> ToolResult:
        try:
            path = self._resolve(_path_param(params))
            old_string = params.get("old_string", "")
            new_string = params.get("new_string", "")
            if not old_string:
                return ToolResult(success=False, error="old_string must not be empty")
            text = path.read_text(encoding="utf-8")
            if old_string not in text:
                return ToolResult(
                    success=False,
                    error="old_string not found in file",
                )
            path.write_text(text.replace(old_string, new_string, 1), encoding="utf-8")
            return ToolResult(success=True, output="edited")
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            return ToolResult(success=False, error=str(exc))


class RunShellTool(Tool):
    name = "run_shell"
    description = "Execute a shell command within the working directory."

    def __init__(self, work_dir: Path, timeout: Optional[float] = None, sandbox=None):
        self._work_dir = work_dir.resolve()
        self._timeout = timeout
        self._sandbox = sandbox

    def execute(self, params: Dict[str, Any]) -> ToolResult:
        command = params.get("command", "")
        if self._sandbox is not None:
            return self._run_via_sandbox(command)
        return self._run_subprocess(command)

    def _run_via_sandbox(self, command: str) -> ToolResult:
        result = self._sandbox.run(command, timeout=self._timeout, cwd=str(self._work_dir))
        if result.error:
            return ToolResult(success=False, error=result.error, exit_code=result.returncode)
        if result.timed_out:
            return ToolResult(
                success=False,
                error=f"command timed out after {self._effective_timeout()}s",
                output=result.stdout,
                exit_code=result.returncode,
            )
        return ToolResult(
            success=result.returncode == 0,
            output=result.stdout,
            error=result.stderr,
            exit_code=result.returncode,
        )

    def _run_subprocess(self, command: str) -> ToolResult:
        try:
            proc = subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=str(self._work_dir),
                start_new_session=True,
            )
        except OSError as exc:
            return ToolResult(success=False, error=str(exc))
        stdout, stderr, timed_out = communicate_with_timeout(proc, self._timeout)
        if timed_out:
            return ToolResult(
                success=False,
                error=f"command timed out after {self._timeout}s",
                output=stdout,
                exit_code=proc.returncode,
            )
        return ToolResult(
            success=proc.returncode == 0,
            output=stdout,
            error=stderr,
            exit_code=proc.returncode,
        )

    def _effective_timeout(self) -> Optional[float]:
        if self._timeout is not None:
            return self._timeout
        return self._sandbox.timeout if self._sandbox is not None else None


class ListDirTool(_PathTool):
    name = "list_dir"
    description = "List entries of a directory within the working directory."

    def execute(self, params: Dict[str, Any]) -> ToolResult:
        try:
            path = self._resolve(_path_param(params) or ".")
            entries = "\n".join(sorted(entry.name for entry in path.iterdir()))
            return ToolResult(success=True, output=entries)
        except (OSError, ValueError) as exc:
            return ToolResult(success=False, error=str(exc))


def default_tools(
    work_dir: Path,
    shell_timeout: Optional[float] = None,
    sandbox=None,
) -> List[Tool]:
    return [
        ReadFileTool(work_dir),
        WriteFileTool(work_dir),
        EditFileTool(work_dir),
        RunShellTool(work_dir, timeout=shell_timeout, sandbox=sandbox),
        ListDirTool(work_dir),
    ]


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def list_tools(self) -> List[str]:
        return sorted(self._tools)


class ToolExecutor:
    def __init__(
        self,
        work_dir: Optional[str] = None,
        sandbox_check: Optional[Callable[[str, Dict[str, Any]], bool]] = None,
        registry: Optional[ToolRegistry] = None,
        shell_timeout: Optional[float] = None,
        sandbox=None,
    ):
        self.work_dir = Path(work_dir or ".").resolve()
        self.registry = registry or ToolRegistry()
        for tool in default_tools(self.work_dir, shell_timeout=shell_timeout, sandbox=sandbox):
            self.registry.register(tool)
        self.sandbox_check = sandbox_check or (lambda tool_name, params: True)

    def _parse_intent(self, intent: Any) -> Tuple[Optional[dict], Optional[ToolResult]]:
        if isinstance(intent, str):
            try:
                action = json.loads(intent)
            except json.JSONDecodeError as exc:
                return None, ToolResult(success=False, error=f"invalid JSON intent: {exc}")
        else:
            action = intent
        if not isinstance(action, dict):
            return None, ToolResult(success=False, error="intent must be a JSON object")
        return action, None

    def execute(self, intent: Any) -> ToolResult:
        action, error = self._parse_intent(intent)
        if error is not None:
            return error

        tool_name = action.get("tool")
        params = action.get("params", {})
        if not isinstance(tool_name, str) or not tool_name:
            return ToolResult(success=False, error="intent missing 'tool' name")
        if not isinstance(params, dict):
            return ToolResult(success=False, error="intent 'params' must be an object")

        tool = self.registry.get(tool_name)
        if tool is None:
            return ToolResult(success=False, error=f"unknown tool: {tool_name}")

        try:
            allowed = self.sandbox_check(tool_name, params)
        except Exception as exc:
            return ToolResult(success=False, error=f"sandbox check failed: {exc}")
        if not allowed:
            return ToolResult(
                success=False, error=f"sandbox denied execution of {tool_name}"
            )

        with TraceContext(phase=f"tool:{tool_name}"):
            logger.info("tool.execute", tool=tool_name)
            try:
                result = tool.execute(params)
            except Exception as exc:
                return ToolResult(success=False, error=f"tool error: {exc}")
            logger.info("tool.completed", tool=tool_name, success=result.success)
            return result
