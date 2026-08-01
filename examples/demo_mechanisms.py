#!/usr/bin/env python3
"""Mechanism demo for the AI Agent Harness.

Reproduces, deterministically and offline (MockLLM only, no real LLM, no network),
the three mechanism behaviors required by AI4SE requirements section A.6:

  1. Governance guardrail blocks a dangerous action
  2. The feedback loop injects a failure, the agent receives the signal and
     changes its next action accordingly
  3. A deterministic behavior of the focus dimension (governance): the
     sandbox + guardrail + HITL layered chain intercepts a destructive
     command before it can execute

Run:  python examples/demo_mechanisms.py
Each demonstration exits non-zero if its assertions fail.

The harness kernel code under test lives in `src/harness/`. Import via the
`src/` layout: run with PYTHONPATH=src or from an editable install.
"""

from __future__ import annotations

import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from harness.hitl import GuardrailEngine, HITLStateMachine
from harness.mock_llm import MockLLM
from harness.orchestrator import Orchestrator, Task


def _write(path: str, content: str) -> str:
    return json.dumps({"tool": "write_file", "params": {"path": path, "content": content}})


def _done() -> str:
    return json.dumps({"done": True})


def demo_1_guardrail_blocks_dangerous_action() -> None:
    """A dangerous command is intercepted by the guardrail engine (no LLM)."""
    engine = GuardrailEngine(dangerous_commands=["rm -rf", "git push --force", "DROP TABLE"])

    assert engine.check({"tool": "run_shell", "params": {"command": "rm -rf /"}}), (
        "guardrail must flag rm -rf /"
    )
    assert engine.check({"tool": "run_shell", "params": {"command": "git push --force origin main"}})
    assert not engine.check({"tool": "run_shell", "params": {"command": "ls -la"}}), (
        "safe command must pass"
    )
    assert not engine.check({"tool": "write_file", "params": {"path": "a.txt", "content": "rm -rf /"}}), (
        "file content is not a command"
    )
    print("[demo 1] guardrail blocks dangerous actions: PASS")


def demo_2_feedback_loop_changes_behavior() -> None:
    """The feedback loop: a failing eval is reported back and the agent fixes it.

    MockLLM first writes the wrong content, the evaluator fails, the failure is
    fed back, and the next LLM turn writes the correct content so the eval passes.
    """
    with tempfile.TemporaryDirectory() as tmp:
        work_dir = pathlib.Path(tmp)
        (work_dir / "check.py").write_text(
            "import sys\n"
            "from pathlib import Path\n"
            "ok = Path('solution.txt').read_text(encoding='utf-8').strip() == 'right'\n"
            "sys.exit(0 if ok else 1)\n",
            encoding="utf-8",
        )
        presets = [
            _write("solution.txt", "wrong"),   # first attempt: fails the check
            _done(),                            # tries to finish early -> eval fails -> fed back
            _write("solution.txt", "right"),   # corrected after receiving the failure signal
            _done(),
        ]

        orch = Orchestrator(llm=MockLLM(presets), work_dir=work_dir)
        result = orch.run(
            Task(id="demo2", prompt="make solution.txt contain 'right'", eval_command="python check.py")
        )

        assert result.status == "COMPLETED", f"expected COMPLETED, got {result.status}"
        assert (work_dir / "solution.txt").read_text(encoding="utf-8").strip() == "right"

        history = orch.memory.get_history()
        eval_messages = [m for m in history if m.role == "tool" and "evaluation" in m.content]
        assert eval_messages, "evaluation result must be fed back to the LLM"

    print("[demo 2] feedback loop (fail -> fix -> pass): PASS")


def demo_3_focus_dimension_governance_chain() -> None:
    """The focus dimension (governance) as a deterministic, layered chain.

    The sandbox command blacklist AND the guardrail engine both reject a
    destructive command, and the HITL state machine pauses on it. Approving
    proceeds; rejecting surfaces the rejection feedback. All deterministic.
    """
    from harness.sandbox import Sandbox

    dangerous_action = {"tool": "run_shell", "params": {"command": "rm -rf /"}}

    # Layer 1: sandbox command blacklist
    sb = Sandbox(allowed_dirs=[str(pathlib.Path.cwd())], blocked_commands=["rm -rf /"])
    assert not sb.check_command("rm -rf /"), "sandbox must block rm -rf /"
    assert sb.check_command("ls -la"), "sandbox must allow a safe command"

    # Layer 2: guardrail rule engine
    engine = GuardrailEngine(dangerous_commands=["rm -rf"])
    assert engine.check(dangerous_action), "guardrail must flag rm -rf /"

    # Layer 3: HITL state machine pauses on the dangerous action, resumes on approval
    machine = HITLStateMachine(approval_timeout=300)
    assert machine.state == machine.RUNNING
    machine.pause(dangerous_action)
    assert machine.state == machine.PAUSED
    machine.approve()
    assert machine.state == machine.APPROVED
    machine.resume()
    assert machine.state == machine.RUNNING

    # Rejection surfaces feedback containing the dangerous command info
    machine.pause(dangerous_action)
    machine.reject()
    assert machine.state == machine.REJECTED
    rejection = machine.rejection_feedback()
    assert rejection is not None and "rm -rf /" in str(rejection), (
        "rejection feedback must mention the command"
    )

    print("[demo 3] governance chain (sandbox -> guardrail -> HITL): PASS")


def main() -> int:
    demo_1_guardrail_blocks_dangerous_action()
    demo_2_feedback_loop_changes_behavior()
    demo_3_focus_dimension_governance_chain()
    print("\nAll mechanism demos passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
