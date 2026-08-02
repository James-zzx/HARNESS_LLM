import json

from harness.llm_adapter import LLMClient, Message, Response

DEFAULT_DEMO_PRESETS = [
    json.dumps(
        {
            "tool": "write_file",
            "params": {"path": "mock-output.txt", "content": "mock demo output"},
        }
    ),
    json.dumps({"done": True}),
]


class MockLLM(LLMClient):
    def __init__(self, preset_responses: list[str] | None = None):
        if preset_responses is None:
            preset_responses = DEFAULT_DEMO_PRESETS
        self._presets = list(preset_responses)
        self._index = 0

    def chat(self, messages: list[Message]) -> Response:
        if not self._presets:
            return Response(content="")
        content = self._presets[self._index % len(self._presets)]
        self._index += 1
        return Response(content=content)
