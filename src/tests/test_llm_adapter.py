import json

import httpx
import pytest

from harness.llm_adapter import LLMClient, LLMFactory, Message, OpenAIClient, Response
from harness.mock_llm import MockLLM
from tests.base import BaseHarnessTest


def _openai_response(content):
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "model": "gpt-test",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }


def test_llm_factory_creates_mock():
    client = LLMFactory(mock=True).create()
    assert isinstance(client, MockLLM)


def test_llm_factory_creates_openai():
    client = LLMFactory(mock=False, api_key="test-key").create()
    assert isinstance(client, OpenAIClient)


def test_llm_factory_passes_config_to_openai():
    client = LLMFactory(mock=False, api_key="test-key", model="gpt-x", base_url="https://example.com/v1").create()
    assert client._model == "gpt-x"
    assert client._base_url == "https://example.com/v1"


def test_llm_client_is_abstract():
    with pytest.raises(TypeError):
        LLMClient()


def test_message_dataclass_fields():
    msg = Message(role="user", content="hello")
    assert msg.role == "user"
    assert msg.content == "hello"
    assert msg.tool_calls is None
    assert msg.timestamp is None


def test_response_dataclass_fields():
    resp = Response(content="hi")
    assert resp.content == "hi"
    assert resp.tool_calls is None
    assert resp.raw is None


def test_openai_client_posts_openai_format():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["json"] = json.loads(request.content)
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json=_openai_response("pong"))

    client = OpenAIClient(
        api_key="test-key",
        model="gpt-test",
        base_url="https://api.example.com/v1",
        transport=httpx.MockTransport(handler),
    )
    result = client.chat([Message(role="user", content="ping")])

    assert captured["method"] == "POST"
    assert captured["url"] == "https://api.example.com/v1/chat/completions"
    assert captured["auth"] == "Bearer test-key"
    assert captured["json"] == {
        "model": "gpt-test",
        "messages": [{"role": "user", "content": "ping"}],
    }
    assert result.content == "pong"


def test_openai_client_parses_response():
    data = _openai_response("hello")
    data["choices"][0]["message"]["tool_calls"] = [
        {"id": "call-1", "type": "function", "function": {"name": "run_shell", "arguments": "{}"}}
    ]

    def handler(request):
        return httpx.Response(200, json=data)

    client = OpenAIClient(api_key="test-key", transport=httpx.MockTransport(handler))
    result = client.chat([Message(role="user", content="hi")])

    assert result.content == "hello"
    assert result.tool_calls[0]["id"] == "call-1"
    assert result.raw == data


def test_openai_client_retries_on_transport_error():
    attempts = {"n": 0}

    def handler(request):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise httpx.ConnectError("boom")
        return httpx.Response(200, json=_openai_response("ok"))

    client = OpenAIClient(api_key="test-key", max_retries=2, transport=httpx.MockTransport(handler))
    result = client.chat([Message(role="user", content="hi")])

    assert result.content == "ok"
    assert attempts["n"] == 3


class TestBaseHarnessTest(BaseHarnessTest):
    def test_mock_llm_fixture(self, mock_llm):
        assert isinstance(mock_llm, MockLLM)
        assert mock_llm.chat([]).content == ""
