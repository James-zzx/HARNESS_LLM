import json

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
