import json

from harness.mock_llm import MockLLM
from harness.orchestrator import Orchestrator, Task

DONE = json.dumps({"done": True})


def _write(path, content):
    return json.dumps(
        {
            "thought": "writing file",
            "tool": "write_file",
            "params": {"path": path, "content": content},
        }
    )


def test_orchestrator_completes_task(work_dir):
    orch = Orchestrator(llm=MockLLM([_write("hello.txt", "hi"), DONE]), work_dir=work_dir)

    result = orch.run(Task(id="t1", prompt="write hello.txt"))

    assert result.status == "COMPLETED"
    assert orch.state == "COMPLETED"
    assert (work_dir / "hello.txt").read_text(encoding="utf-8") == "hi"


def test_orchestrator_max_iterations(work_dir):
    orch = Orchestrator(llm=MockLLM([_write("loop.txt", "x")]), work_dir=work_dir)

    result = orch.run(Task(id="t2", prompt="write loop.txt", max_iterations=3))

    assert result.status == "FAILED"
    assert orch.state == "FAILED"
    assert result.iterations == 3
    assert "iteration" in result.error.lower()


def test_orchestrator_tool_error(work_dir):
    bad = json.dumps(
        {"tool": "write_file", "params": {"path": "../escape.txt", "content": "nope"}}
    )
    presets = [bad, _write("safe.txt", "ok"), DONE]

    orch = Orchestrator(llm=MockLLM(presets), work_dir=work_dir)
    result = orch.run(Task(id="t3", prompt="write safely"))

    assert result.status == "COMPLETED"
    messages = orch.memory.get_history()
    assert any(m.role == "tool" and "working directory" in m.content for m in messages)
    assert (work_dir / "safe.txt").read_text(encoding="utf-8") == "ok"


def test_orchestrator_hitl_pause(work_dir):
    dangerous = json.dumps(
        {"tool": "run_shell", "params": {"command": "rm -rf /"}}
    )
    seen = {}

    def checker(tool_name, params):
        seen["checked"] = params.get("command")
        return tool_name == "run_shell" and "rm -rf" in params.get("command", "")

    def approval(tool_name, params):
        seen["approved"] = False
        return False

    orch = Orchestrator(
        llm=MockLLM([dangerous]),
        work_dir=work_dir,
        hitl_checker=checker,
        approval=approval,
    )
    result = orch.run(Task(id="t4", prompt="run dangerous command"))

    assert result.status == "PAUSED"
    assert orch.state == "PAUSED"
    assert seen["checked"] == "rm -rf /"
    assert not any(m.role == "tool" for m in orch.memory.get_history())


def test_orchestrator_full_cycle(work_dir):
    (work_dir / "check.py").write_text(
        "import sys\n"
        "from pathlib import Path\n"
        "text = Path('solution.txt').read_text(encoding='utf-8')\n"
        "sys.exit(0 if text.strip() == 'right' else 1)\n",
        encoding="utf-8",
    )
    presets = [
        _write("solution.txt", "wrong"),
        DONE,
        _write("solution.txt", "right"),
        DONE,
    ]

    orch = Orchestrator(llm=MockLLM(presets), work_dir=work_dir)
    result = orch.run(
        Task(id="t5", prompt="make solution.txt contain 'right'", eval_command="python check.py")
    )

    assert result.status == "COMPLETED"
    assert orch.state == "COMPLETED"
    assert (work_dir / "solution.txt").read_text(encoding="utf-8") == "right"
    messages = orch.memory.get_history()
    assert any(m.role == "tool" and "evaluation" in m.content for m in messages)
