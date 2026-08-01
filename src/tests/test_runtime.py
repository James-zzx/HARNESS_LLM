import io
import json
import sys
import time

from harness.config import HITLConfig, HarnessConfig, SandboxConfig
from harness.mock_llm import MockLLM
from harness.orchestrator import Task
from harness.runtime import build_runtime

DANGEROUS_COMMANDS = [
    "rm -rf",
    "shutdown",
    "format",
    "dd if=",
    "git push --force",
    "DROP TABLE",
]


def _config(tmp_path):
    work = tmp_path / "workspace"
    work.mkdir()
    config = HarnessConfig(
        sandbox=SandboxConfig(
            enabled=True,
            allowed_dirs=[str(work)],
            blocked_commands=["rm -rf /", "shutdown", "format", "dd if="],
            network="deny",
        ),
        hitl=HITLConfig(
            enabled=True,
            dangerous_commands=DANGEROUS_COMMANDS,
            approval_timeout=1,
        ),
    )
    return config, work


def _hitl_config(tmp_path):
    work = tmp_path / "workspace"
    work.mkdir()
    config = HarnessConfig(
        sandbox=SandboxConfig(
            enabled=True,
            allowed_dirs=[str(work)],
            blocked_commands=["rm -rf /", "shutdown", "format", "dd if="],
            network="deny",
        ),
        hitl=HITLConfig(
            enabled=True,
            dangerous_commands=["hitl-pause"],
            approval_timeout=1,
        ),
    )
    return config, work


def _dangerous_json():
    return json.dumps({"tool": "run_shell", "params": {"command": "echo hitl-pause"}})


def test_runtime_sandbox_blocks_dangerous_command(tmp_path):
    config, work = _config(tmp_path)
    runtime = build_runtime(config, work_dir=work)
    runtime.hitl_gate._decision_source = lambda: "approved"

    marker = work / "pwned.txt"
    command = f"rm -rf /; echo pwned > {marker}"
    presets = [
        json.dumps({"tool": "run_shell", "params": {"command": command}}),
        json.dumps({"done": True}),
    ]
    orch = runtime.build_orchestrator(llm=MockLLM(presets))
    result = orch.run(Task(id="rt-sandbox", prompt="delete everything"))

    assert result.status == "COMPLETED"
    assert not marker.exists()
    tool_messages = [m for m in orch.memory.get_history() if m.role == "tool"]
    assert any("sandbox" in m.content for m in tool_messages)


def test_runtime_hitl_pauses_git_push_force(tmp_path):
    config, work = _config(tmp_path)
    runtime = build_runtime(config, work_dir=work)
    runtime.hitl_gate._decision_source = lambda: "rejected"

    dangerous = json.dumps(
        {"tool": "run_shell", "params": {"command": "git push --force origin main"}}
    )
    orch = runtime.build_orchestrator(llm=MockLLM([dangerous]))
    result = orch.run(Task(id="rt-hitl", prompt="push changes"))

    assert result.status == "PAUSED"
    assert orch.state == "PAUSED"
    assert runtime.hitl_gate.state == "REJECTED"
    assert not any(m.role == "tool" for m in orch.memory.get_history())


def test_runtime_uses_config_guardrail_lists(tmp_path):
    work = tmp_path / "workspace"
    work.mkdir()
    config = HarnessConfig(
        sandbox=SandboxConfig(
            enabled=True,
            allowed_dirs=[str(work)],
            blocked_commands=["custom-doom"],
        ),
        hitl=HITLConfig(
            enabled=True,
            dangerous_commands=["sneaky-action"],
            approval_timeout=1,
        ),
    )
    runtime = build_runtime(config, work_dir=work)

    assert runtime.sandbox.check_command("custom-doom") is False
    assert (
        runtime.hitl_gate.engine.check(
            {"tool": "run_shell", "params": {"command": "sneaky-action --all"}}
        )
        is True
    )
    assert (
        runtime.hitl_gate.engine.check(
            {"tool": "run_shell", "params": {"command": "rm -rf /"}}
        )
        is False
    )


def test_runtime_sandbox_disabled_is_permissive(tmp_path):
    config, work = _config(tmp_path)
    config.sandbox.enabled = False
    runtime = build_runtime(config, work_dir=work)

    assert (
        runtime.tool_executor.sandbox_check("run_shell", {"command": "rm -rf /"}) is True
    )
    assert (
        runtime.tool_executor.sandbox_check("write_file", {"path": "/etc/passwd"}) is True
    )


def test_runtime_hitl_disabled_does_not_pause(tmp_path):
    config, work = _config(tmp_path)
    config.hitl.enabled = False
    runtime = build_runtime(config, work_dir=work)

    presets = [
        json.dumps(
            {"tool": "run_shell", "params": {"command": "git push --force origin main"}}
        ),
        json.dumps({"done": True}),
    ]
    orch = runtime.build_orchestrator(llm=MockLLM(presets))
    result = orch.run(Task(id="rt-no-hitl", prompt="push changes"))

    assert result.status == "COMPLETED"


def test_runtime_run_shell_enforces_sandbox_timeout(tmp_path):
    work = tmp_path / "workspace"
    work.mkdir()
    config = HarnessConfig(
        sandbox=SandboxConfig(
            enabled=True,
            timeout=1,
            allowed_dirs=[str(work)],
            blocked_commands=["rm -rf /", "shutdown", "format", "dd if="],
            network="deny",
        )
    )
    runtime = build_runtime(config, work_dir=work)

    start = time.monotonic()
    result = runtime.tool_executor.execute(
        {
            "tool": "run_shell",
            "params": {
                "command": f'"{sys.executable}" -c "import time; time.sleep(30)"'
            },
        }
    )
    elapsed = time.monotonic() - start

    assert result.success is False
    assert elapsed < 10


def test_build_orchestrator_per_task_work_dir(tmp_path):
    config, work = _config(tmp_path)
    runtime = build_runtime(config, work_dir=work)
    task_dir = work / "task-1"
    presets = [
        json.dumps(
            {"tool": "write_file", "params": {"path": "note.txt", "content": "iso"}}
        ),
        json.dumps({"done": True}),
    ]

    orch = runtime.build_orchestrator(llm=MockLLM(presets), work_dir=str(task_dir))
    result = orch.run(Task(id="rt-iso", prompt="write"))

    assert result.status == "COMPLETED"
    assert (task_dir / "note.txt").read_text(encoding="utf-8") == "iso"
    assert not (work / "note.txt").exists()


def test_runtime_hitl_interactive_stdin_approve(tmp_path):
    config, work = _hitl_config(tmp_path)
    runtime = build_runtime(config, work_dir=work, hitl_input_stream=io.StringIO("y\n"))
    orch = runtime.build_orchestrator(
        llm=MockLLM([_dangerous_json(), json.dumps({"done": True})])
    )
    result = orch.run(Task(id="rt-cli-approve", prompt="do the task"))

    assert result.status == "COMPLETED"
    assert runtime.hitl_gate.state == "RUNNING"


def test_runtime_hitl_interactive_stdin_reject(tmp_path):
    config, work = _hitl_config(tmp_path)
    runtime = build_runtime(config, work_dir=work, hitl_input_stream=io.StringIO("n\n"))
    orch = runtime.build_orchestrator(llm=MockLLM([_dangerous_json()]))
    result = orch.run(Task(id="rt-cli-reject", prompt="do the task"))

    assert result.status == "PAUSED"
    assert runtime.hitl_gate.state == "REJECTED"
    assert "echo hitl-pause" in result.feedback


def test_runtime_hitl_interactive_stdin_timeout(tmp_path):
    config, work = _hitl_config(tmp_path)
    runtime = build_runtime(config, work_dir=work, hitl_input_stream=io.StringIO("t\n"))
    orch = runtime.build_orchestrator(llm=MockLLM([_dangerous_json()]))
    result = orch.run(Task(id="rt-cli-timeout", prompt="do the task"))

    assert result.status == "PAUSED"
    assert runtime.hitl_gate.state == "TIMEOUT"
