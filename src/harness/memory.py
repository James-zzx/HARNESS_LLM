import json
import math
from dataclasses import dataclass
from typing import Any, Optional

from harness.logger import get_logger

TOKENS_PER_CHAR = 4


@dataclass
class Message:
    role: str
    content: Optional[str] = None
    tool_calls: Optional[list] = None
    timestamp: Optional[Any] = None


class ConversationMemory:
    def __init__(self) -> None:
        self._messages: list[Message] = []
        self._logger = get_logger("harness.memory")

    def add_message(
        self,
        msg: Optional[Message] = None,
        *,
        role: Optional[str] = None,
        content: Optional[str] = None,
        tool_calls: Optional[list] = None,
        timestamp: Optional[Any] = None,
    ) -> Message:
        if msg is not None:
            message = msg
        else:
            if role is None:
                raise ValueError("role is required when msg is not provided")
            message = Message(role=role, content=content, tool_calls=tool_calls, timestamp=timestamp)
        self._messages.append(message)
        self._logger.debug("message_added", role=message.role, tokens=self._estimate_tokens(message))
        return message

    def get_history(self) -> list[Message]:
        return list(self._messages)

    def get_context_window(self, max_tokens: int) -> list[Message]:
        if max_tokens < 0:
            raise ValueError("max_tokens must be non-negative")
        if not self._messages:
            return []
        if self._tokens(self._messages) <= max_tokens:
            return list(self._messages)
        system = [m for m in self._messages if m.role == "system"]
        non_system = [m for m in self._messages if m.role != "system"]
        used = self._tokens(system)
        kept = []
        for message in reversed(non_system):
            tokens = self._estimate_tokens(message)
            if used + tokens > max_tokens:
                break
            kept.append(message)
            used += tokens
        kept.reverse()
        window = system + kept
        self._logger.debug("context_window_trimmed", kept=len(window), total=len(self._messages), max_tokens=max_tokens)
        return window

    def clear(self) -> None:
        self._messages.clear()
        self._logger.debug("memory_cleared")

    def _estimate_tokens(self, message: Message) -> int:
        if message.content is not None:
            text = message.content
        elif message.tool_calls:
            text = json.dumps(message.tool_calls, ensure_ascii=False)
        else:
            text = ""
        return max(1, math.ceil(len(text) / TOKENS_PER_CHAR))

    def _tokens(self, messages: list[Message]) -> int:
        return sum(self._estimate_tokens(m) for m in messages)
