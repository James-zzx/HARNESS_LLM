import json
import threading
import time

from harness.llm_adapter import Response
from harness.message_queue import MessageQueue
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


def test_orchestrator_non_dict_intent_feeds_back_error(work_dir):
    presets = [json.dumps(42), DONE]
    orch = Orchestrator(llm=MockLLM(presets), work_dir=work_dir)

    result = orch.run(Task(id="t6", prompt="reply with 42"))

    assert result.status == "COMPLETED"
    assert orch.state == "COMPLETED"
    messages = orch.memory.get_history()
    assert any(m.role == "tool" and "JSON object" in m.content for m in messages)


def test_orchestrator_rejection_feedback_in_result(work_dir):
    from harness.hitl import GuardrailEngine, HITLGate

    engine = GuardrailEngine(regex_rules=[r"^echo danger"])
    gate = HITLGate(engine=engine, decision_source=lambda: "rejected")
    dangerous = json.dumps({"tool": "run_shell", "params": {"command": "echo danger"}})
    orch = Orchestrator(
        llm=MockLLM([dangerous]),
        work_dir=work_dir,
        hitl_checker=gate.check,
        approval=gate.decide,
        feedback_provider=gate.rejection_feedback,
    )
    result = orch.run(Task(id="t8", prompt="do the task"))

    assert result.status == "PAUSED"
    assert orch.state == "PAUSED"
    assert result.feedback is not None
    assert "run_shell" in result.feedback
    assert "echo danger" in result.feedback


def test_orchestrator_user_input(work_dir):
    queue = MessageQueue(task_id="t9-ui")
    first_call_started = threading.Event()
    message_pushed = threading.Event()
    result_holder = {}

    class GatedLLM(MockLLM):
        def __init__(self):
            super().__init__([""])
            self._calls = 0

        def chat(self, messages):
            self._calls += 1
            if self._calls == 1:
                first_call_started.set()
                assert message_pushed.wait(timeout=10)
                return Response(content=_write("note.txt", "v1"))
            if self._calls == 2:
                user_text = " ".join(
                    (m.content or "") for m in messages if m.role == "user"
                )
                if "改成另一种写法" in user_text:
                    return Response(content=_write("note.txt", "v2"))
                return Response(content=_write("note.txt", "v1b"))
            return Response(content=DONE)

    orch = Orchestrator(llm=GatedLLM(), work_dir=work_dir, message_queue=queue)

    def _run():
        result_holder["result"] = orch.run(Task(id="t9-ui", prompt="write note.txt"))

    thread = threading.Thread(target=_run)
    thread.start()
    assert first_call_started.wait(timeout=10)
    queue.push({"content": "改成另一种写法"})
    message_pushed.set()
    thread.join(timeout=10)

    result = result_holder["result"]
    assert result.status == "COMPLETED"
    assert (work_dir / "note.txt").read_text(encoding="utf-8") == "v2"
    history = orch.memory.get_history()
    assert any(
        m.role == "user" and "改成另一种写法" in m.content for m in history
    )


def test_orchestrator_user_input_timeout(work_dir):
    queue = MessageQueue(task_id="t9-timeout")
    orch = Orchestrator(
        llm=MockLLM([_write("t.txt", "ok"), DONE]),
        work_dir=work_dir,
        message_queue=queue,
    )
    orch.interrupt()
    start = time.monotonic()
    result = orch.run(Task(id="t9-timeout", prompt="write t.txt", timeout=2))
    elapsed = time.monotonic() - start

    assert result.status == "FAILED"
    assert "timeout" in result.error
    assert elapsed >= 1.5
    assert elapsed < 5.0


def test_orchestrator_no_queue_backward_compat(work_dir):
    orch = Orchestrator(llm=MockLLM([_write("bc.txt", "ok"), DONE]), work_dir=work_dir)
    orch.interrupt()
    result = orch.run(Task(id="t9-bc", prompt="write bc.txt"))

    assert result.status == "COMPLETED"
    assert orch.state == "COMPLETED"
    assert (work_dir / "bc.txt").read_text(encoding="utf-8") == "ok"
    user_msgs = [m for m in orch.memory.get_history() if m.role == "user"]
    assert len(user_msgs) == 1
    assert user_msgs[0].content == "write bc.txt"


def test_orchestrator_interrupt(work_dir):
    queue = MessageQueue(task_id="t9-int")
    first_call_started = threading.Event()
    release_first_call = threading.Event()
    result_holder = {}

    class GatedLLM(MockLLM):
        def __init__(self):
            super().__init__([""])
            self._calls = 0

        def chat(self, messages):
            self._calls += 1
            if self._calls == 1:
                first_call_started.set()
                assert release_first_call.wait(timeout=10)
                return Response(content=_write("int.txt", "v1"))
            return Response(content=DONE)

    orch = Orchestrator(llm=GatedLLM(), work_dir=work_dir, message_queue=queue)

    def _run():
        result_holder["result"] = orch.run(Task(id="t9-int", prompt="write int.txt"))

    thread = threading.Thread(target=_run)
    thread.start()
    assert first_call_started.wait(timeout=10)
    orch.interrupt()
    release_first_call.set()

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and orch.state != "USER_INPUT":
        time.sleep(0.01)
    assert orch.state == "USER_INPUT"

    queue.push({"content": "resume"})
    thread.join(timeout=10)

    result = result_holder["result"]
    assert result.status == "COMPLETED"
    assert (work_dir / "int.txt").read_text(encoding="utf-8") == "v1"
    assert any(
        m.role == "user" and m.content == "resume"
        for m in orch.memory.get_history()
    )
