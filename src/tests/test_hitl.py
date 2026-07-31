import io
import json

import pytest

from harness.hitl import GuardrailEngine, HITLGate, HITLStateMachine
from harness.mock_llm import MockLLM
from harness.orchestrator import Orchestrator, Task

DANGEROUS_ACTION = {"tool": "run_shell", "params": {"command": "rm -rf /"}}
SAFE_ACTION = {"tool": "run_shell", "params": {"command": "ls -la"}}


class _FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def _write(path, content):
    return json.dumps(
        {
            "thought": "writing file",
            "tool": "write_file",
            "params": {"path": path, "content": content},
        }
    )


def test_guardrail_detects_dangerous_command():
    engine = GuardrailEngine()
    assert engine.check(DANGEROUS_ACTION) is True
    assert engine.check("rm -rf /") is True


@pytest.mark.parametrize(
    "command",
    ["rm -rf /etc", "git push --force origin main", "DROP TABLE users;", "format C: /q"],
)
def test_guardrail_detects_static_rule_variants(command):
    engine = GuardrailEngine()
    assert engine.check({"tool": "run_shell", "params": {"command": command}}) is True


def test_guardrail_allows_safe_command():
    engine = GuardrailEngine()
    assert engine.check(SAFE_ACTION) is False
    assert engine.check({"tool": "run_shell", "params": {"command": "grep -r foo ."}}) is False
    assert engine.check({"tool": "write_file", "params": {"path": "x.txt", "content": "rm -rf /"}}) is False


def test_guardrail_empty_list_disables_static_rules():
    engine = GuardrailEngine(dangerous_commands=[])
    assert engine.check({"tool": "run_shell", "params": {"command": "rm -rf /"}}) is False
    assert engine.check(SAFE_ACTION) is False


def test_guardrail_none_uses_defaults():
    assert GuardrailEngine().check(DANGEROUS_ACTION) is True


def test_guardrail_empty_list_keeps_regex_rules():
    engine = GuardrailEngine(dangerous_commands=[], regex_rules=[r"kill\s+-9\s+\d+"])
    assert engine.check({"tool": "run_shell", "params": {"command": "rm -rf /"}}) is False
    assert engine.check({"tool": "run_shell", "params": {"command": "kill -9 1234"}}) is True


def test_guardrail_regex_pattern():
    engine = GuardrailEngine(regex_rules=[r"kill\s+-9\s+\d+"])
    assert engine.check({"tool": "run_shell", "params": {"command": "kill -9 1234"}}) is True
    assert engine.check({"tool": "run_shell", "params": {"command": "kill 1234"}}) is False


def test_hitl_state_transitions():
    sm = HITLStateMachine()
    assert sm.state == "RUNNING"
    sm.pause(DANGEROUS_ACTION)
    assert sm.state == "PAUSED"
    assert sm.approve() is True
    assert sm.state == "APPROVED"
    sm.resume()
    assert sm.state == "RUNNING"


def test_hitl_timeout():
    clock = _FakeClock()
    sm = HITLStateMachine(approval_timeout=300, clock=clock)
    sm.pause(DANGEROUS_ACTION)
    assert sm.state == "PAUSED"
    assert sm.check_timeout() is False
    clock.now = 301.0
    assert sm.check_timeout() is True
    assert sm.timeout() is False
    assert sm.state == "TIMEOUT"
    assert sm.outcome() is False


def test_hitl_rejection_feedback():
    sm = HITLStateMachine()
    sm.pause(DANGEROUS_ACTION)
    sm.reject()
    feedback = sm.rejection_feedback()
    assert feedback is not None
    assert "run_shell" in feedback
    assert "rm -rf /" in feedback


def test_hitl_cli_decision():
    sm = HITLStateMachine()
    sm.pause(DANGEROUS_ACTION)
    assert (
        sm.wait_for_decision(input_stream=io.StringIO("y\n"), output_stream=io.StringIO())
        == "approved"
    )
    assert sm.state == "APPROVED"

    sm2 = HITLStateMachine()
    sm2.pause(DANGEROUS_ACTION)
    assert (
        sm2.wait_for_decision(input_stream=io.StringIO("n\n"), output_stream=io.StringIO())
        == "rejected"
    )
    assert sm2.state == "REJECTED"


def _stdin_gate(choice):
    gate = HITLGate()
    gate._decision_source = lambda: gate._machine.wait_for_decision(
        input_stream=io.StringIO(choice), output_stream=io.StringIO()
    )
    return gate


def test_gate_decide_stdin_approved():
    gate = _stdin_gate("y\n")
    gate.check("run_shell", {"command": "rm -rf /"})
    assert gate.decide("run_shell", {"command": "rm -rf /"}) is True
    assert gate.state == "RUNNING"


def test_gate_decide_stdin_rejected():
    gate = _stdin_gate("n\n")
    gate.check("run_shell", {"command": "rm -rf /"})
    assert gate.decide("run_shell", {"command": "rm -rf /"}) is False
    assert gate.state == "REJECTED"


def test_orchestrator_hitl_approved_proceeds(work_dir):
    engine = GuardrailEngine(regex_rules=[r"^echo danger"])
    gate = HITLGate(engine=engine, decision_source=lambda: "approved")
    presets = [
        json.dumps({"tool": "run_shell", "params": {"command": "echo danger"}}),
        _write("ok.txt", "ok"),
        json.dumps({"done": True}),
    ]
    orch = Orchestrator(
        llm=MockLLM(presets),
        work_dir=work_dir,
        hitl_checker=gate.check,
        approval=gate.decide,
    )
    result = orch.run(Task(id="t6", prompt="do the task"))
    assert result.status == "COMPLETED"
    assert gate.state == "RUNNING"


def test_orchestrator_hitl_rejected_pauses(work_dir):
    engine = GuardrailEngine(regex_rules=[r"^echo danger"])
    gate = HITLGate(engine=engine, decision_source=lambda: "rejected")
    dangerous = json.dumps({"tool": "run_shell", "params": {"command": "echo danger"}})
    orch = Orchestrator(
        llm=MockLLM([dangerous]),
        work_dir=work_dir,
        hitl_checker=gate.check,
        approval=gate.decide,
    )
    result = orch.run(Task(id="t7", prompt="do the task"))
    assert result.status == "PAUSED"
    assert gate.state == "REJECTED"
    assert "echo danger" in gate.rejection_feedback()
