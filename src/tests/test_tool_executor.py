import json

import pytest

from harness.tool_executor import Tool, ToolExecutor, ToolRegistry, ToolResult


class _StubTool(Tool):
    name = "stub"
    description = "stub tool for registry tests"

    def execute(self, params):
        return ToolResult(success=True, output="stubbed")


@pytest.fixture
def executor(work_dir):
    return ToolExecutor(work_dir=work_dir)


def test_write_and_read_file(executor, work_dir):
    write = executor.execute(
        {"tool": "write_file", "params": {"path": "notes.txt", "content": "hello harness"}}
    )
    assert write.success is True
    assert (work_dir / "notes.txt").read_text(encoding="utf-8") == "hello harness"

    read = executor.execute({"tool": "read_file", "params": {"path": "notes.txt"}})
    assert read.success is True
    assert read.output == "hello harness"


def test_edit_file(executor, work_dir):
    (work_dir / "doc.txt").write_text("the quick brown fox", encoding="utf-8")

    result = executor.execute(
        {
            "tool": "edit_file",
            "params": {"path": "doc.txt", "old_string": "brown", "new_string": "red"},
        }
    )
    assert result.success is True
    assert (work_dir / "doc.txt").read_text(encoding="utf-8") == "the quick red fox"


def test_run_shell_echo(executor):
    result = executor.execute({"tool": "run_shell", "params": {"command": "echo hello harness"}})
    assert result.success is True
    assert result.exit_code == 0
    assert "hello harness" in result.output


def test_run_shell_failure(executor):
    result = executor.execute(
        {"tool": "run_shell", "params": {"command": "definitely_not_a_real_command_xyz"}}
    )
    assert result.success is False
    assert result.exit_code is not None
    assert result.exit_code != 0


def test_tool_registry_lookup():
    registry = ToolRegistry()
    registry.register(_StubTool())
    assert registry.get("stub") is not None
    assert registry.get("stub").name == "stub"
    assert registry.get("missing") is None


def test_tool_executor_parse_intent(executor, work_dir):
    intent = json.dumps(
        {"tool": "write_file", "params": {"path": "parsed.txt", "content": "from intent"}}
    )
    result = executor.execute(intent)
    assert result.success is True
    assert (work_dir / "parsed.txt").read_text(encoding="utf-8") == "from intent"


def test_path_traversal_blocked(executor, work_dir):
    outside = work_dir.parent / "secret.txt"
    outside.write_text("do not leak", encoding="utf-8")

    result = executor.execute(
        {"tool": "read_file", "params": {"path": "../secret.txt"}}
    )
    assert result.success is False
    assert "working directory" in result.error


def test_unknown_tool(executor):
    result = executor.execute({"tool": "nope", "params": {}})
    assert result.success is False
    assert "nope" in result.error


def test_malformed_intent(executor):
    result = executor.execute("this is not json")
    assert result.success is False
    assert "json" in result.error.lower()


def test_edit_file_missing_old_string(executor, work_dir):
    (work_dir / "doc.txt").write_text("unchanged", encoding="utf-8")

    result = executor.execute(
        {
            "tool": "edit_file",
            "params": {"path": "doc.txt", "old_string": "absent", "new_string": "x"},
        }
    )
    assert result.success is False
    assert "old_string" in result.error
    assert (work_dir / "doc.txt").read_text(encoding="utf-8") == "unchanged"


def test_sandbox_check_can_deny(work_dir):
    denied = ToolExecutor(work_dir=work_dir, sandbox_check=lambda tool, params: False)

    result = denied.execute({"tool": "read_file", "params": {"path": "x.txt"}})
    assert result.success is False
    assert "sandbox" in result.error.lower()


def test_sandbox_check_receives_shell_command(work_dir):
    seen = {}

    def check(tool_name, params):
        seen[tool_name] = params.get("command")
        return False

    denied = ToolExecutor(work_dir=work_dir, sandbox_check=check)
    result = denied.execute({"tool": "run_shell", "params": {"command": "rm -rf /"}})

    assert result.success is False
    assert seen.get("run_shell") == "rm -rf /"
