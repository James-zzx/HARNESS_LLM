import json

from harness.llm_adapter import Message, Response
from harness.mock_llm import MockLLM


def test_mock_llm_default_demo_cycle():
    llm = MockLLM()
    first = llm.chat([Message(role="user", content="hi")]).content
    second = llm.chat([Message(role="user", content="hi")]).content
    assert first != second
    intent1 = json.loads(first)
    intent2 = json.loads(second)
    assert intent1["tool"] == "write_file"
    assert intent1["params"]["path"] == "mock-output.txt"
    assert intent1["params"]["content"] == "mock demo output"
    assert intent2 == {"done": True}


def test_mock_llm_returns_preset():
    llm = MockLLM(["first", "second"])
    assert llm.chat([Message(role="user", content="hi")]).content == "first"
    assert llm.chat([Message(role="user", content="hi")]).content == "second"


def test_mock_llm_cycles():
    llm = MockLLM(["a", "b", "c"])
    contents = [llm.chat([]).content for _ in range(4)]
    assert contents == ["a", "b", "c", "a"]


def test_mock_llm_is_deterministic():
    presets = ["alpha", "beta"]

    def run():
        llm = MockLLM(presets)
        return [llm.chat([]).content for _ in range(100)]

    first_run = run()
    second_run = run()
    assert first_run == second_run
    assert first_run == ["alpha", "beta"] * 50


def test_mock_llm_returns_response_object():
    llm = MockLLM(["x"])
    result = llm.chat([])
    assert isinstance(result, Response)
    assert result.content == "x"


def test_mock_llm_ignores_messages():
    llm = MockLLM(["fixed"])
    assert llm.chat([Message(role="user", content="q1")]).content == "fixed"
    assert llm.chat([Message(role="user", content="q2")]).content == "fixed"


def test_mock_llm_empty_presets_returns_empty_content():
    llm = MockLLM([])
    assert llm.chat([]).content == ""
    assert llm.chat([]).content == ""
