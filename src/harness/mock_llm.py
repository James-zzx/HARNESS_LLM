from harness.llm_adapter import LLMClient, Message, Response


class MockLLM(LLMClient):
    def __init__(self, preset_responses: list[str]):
        self._presets = list(preset_responses)
        self._index = 0

    def chat(self, messages: list[Message]) -> Response:
        if not self._presets:
            return Response(content="")
        content = self._presets[self._index % len(self._presets)]
        self._index += 1
        return Response(content=content)
