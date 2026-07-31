from harness.memory import ConversationMemory, Message


def test_add_and_get_history():
    memory = ConversationMemory()
    memory.add_message(role="user", content="hello")
    memory.add_message(Message(role="assistant", content="hi"))
    history = memory.get_history()
    assert [m.role for m in history] == ["user", "assistant"]
    assert history[0].content == "hello"
    assert history[1].content == "hi"


def test_context_window_truncation():
    memory = ConversationMemory()
    memory.add_message(role="system", content="s" * 40)
    for i in range(5):
        memory.add_message(role="user", content=f"user-{i}-" + "x" * 20)
    window = memory.get_context_window(max_tokens=30)
    assert [m.role for m in window] == ["system", "user", "user"]
    assert window[0].content == "s" * 40
    assert window[-1].content.startswith("user-4-")
    assert window[-2].content.startswith("user-3-")


def test_context_window_keeps_system_prompt():
    memory = ConversationMemory()
    memory.add_message(role="system", content="You are a coding agent.")
    for i in range(10):
        memory.add_message(role="user", content="m" * 40)
    memory.add_message(role="assistant", content="a" * 40)
    window = memory.get_context_window(max_tokens=50)
    assert window[0].role == "system"
    assert window[0].content == "You are a coding agent."
    assert len(window) == 5


def test_clear():
    memory = ConversationMemory()
    memory.add_message(role="user", content="x")
    memory.clear()
    assert memory.get_history() == []
    assert memory.get_context_window(max_tokens=10) == []


def test_context_window_budget_smaller_than_system_prompt():
    memory = ConversationMemory()
    memory.add_message(role="system", content="z" * 400)
    memory.add_message(role="user", content="w" * 100)
    window = memory.get_context_window(max_tokens=20)
    assert [m.role for m in window] == ["system"]


def test_context_window_handles_tool_call_only_message():
    memory = ConversationMemory()
    memory.add_message(role="system", content="s" * 40)
    memory.add_message(role="assistant", content=None, tool_calls=[{"name": "search", "args": {"q": "test"}}])
    memory.add_message(role="user", content="x" * 200)
    window = memory.get_context_window(max_tokens=200)
    roles = [m.role for m in window]
    assert "assistant" in roles
    assert window[-1].role == "user"
