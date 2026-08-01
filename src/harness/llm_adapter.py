from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_TIMEOUT = 120.0
DEFAULT_MAX_RETRIES = 2


@dataclass
class Message:
    role: str
    content: str
    tool_calls: list | None = None
    timestamp: float | None = None


@dataclass
class Response:
    content: str | None = None
    tool_calls: list | None = None
    raw: dict | None = None


class LLMClient(ABC):
    @abstractmethod
    def chat(self, messages: list[Message]) -> Response: ...


class OpenAIClient(LLMClient):
    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        transport: httpx.BaseTransport | None = None,
    ):
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max_retries
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def chat(self, messages: list[Message]) -> Response:
        payload = {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        last_error: httpx.TransportError | None = None
        for _ in range(self._max_retries + 1):
            try:
                response = self._client.post(
                    f"{self._base_url}/chat/completions", json=payload, headers=headers
                )
                response.raise_for_status()
                return self._parse_response(response.json())
            except httpx.TransportError as exc:
                last_error = exc
        raise last_error

    @staticmethod
    def _parse_response(data: dict) -> Response:
        message = data["choices"][0]["message"]
        return Response(
            content=message.get("content"),
            tool_calls=message.get("tool_calls"),
            raw=data,
        )


class LLMFactory:
    def __init__(
        self,
        *,
        mock: bool = False,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str = "",
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ):
        self._mock = mock
        self._model = model
        self._base_url = base_url
        self._api_key = api_key
        self._timeout = timeout
        self._max_retries = max_retries

    def create(self) -> LLMClient:
        if self._mock:
            from harness.mock_llm import MockLLM

            return MockLLM([])
        return OpenAIClient(
            api_key=self._api_key,
            model=self._model,
            base_url=self._base_url,
            timeout=self._timeout,
            max_retries=self._max_retries,
        )
