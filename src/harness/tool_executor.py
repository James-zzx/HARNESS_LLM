import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from harness.logger import TraceContext, get_logger

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
            path = self._resolve(params.get("path", ""))
            return ToolResult(success=True, output=path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            return ToolResult(success=False, error=str(exc))


class WriteFileTool(_PathTool):
    name = "write_file"
    description = "Write content to a file within the working directory."

    def execute(self, params: Dict[str, Any]) -> ToolResult:
        try:
            path = self._resolve(params.get("path", ""))
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
            path = self._resolve(params.get("path", ""))
            old_string = params.get("old_string", "")
            new_string = params.get("new_string", "")
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

    def __init__(self, work_dir: Path):
        self._work_dir = work_dir.resolve()

    def execute(self, params: Dict[str, Any]) -> ToolResult:
        command = params.get("command", "")
        try:
            completed = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                cwd=str(self._work_dir),
            )
        except OSError as exc:
            return ToolResult(success=False, error=str(exc))
        return ToolResult(
            success=completed.returncode == 0,
            output=completed.stdout,
            error=completed.stderr,
            exit_code=completed.returncode,
        )


class ListDirTool(_PathTool):
    name = "list_dir"
    description = "List entries of a directory within the working directory."

    def execute(self, params: Dict[str, Any]) -> ToolResult:
        try:
            path = self._resolve(params.get("path", "."))
            entries = "\n".join(sorted(entry.name for entry in path.iterdir()))
            return ToolResult(success=True, output=entries)
        except (OSError, ValueError) as exc:
            return ToolResult(success=False, error=str(exc))


def default_tools(work_dir: Path) -> List[Tool]:
    return [
        ReadFileTool(work_dir),
        WriteFileTool(work_dir),
        EditFileTool(work_dir),
        RunShellTool(work_dir),
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
    ):
        self.work_dir = Path(work_dir or ".").resolve()
        self.registry = registry or ToolRegistry()
        for tool in default_tools(self.work_dir):
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
