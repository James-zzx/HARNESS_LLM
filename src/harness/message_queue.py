import threading
import time
from typing import Any


class MessageQueue:
    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        self._pending: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._event = threading.Event()

    def push(self, message: dict) -> None:
        with self._lock:
            self._pending.append(message)
            self._event.set()

    def pop_all(self) -> list[dict]:
        with self._lock:
            messages = self._pending
            self._pending = []
            self._event.clear()
        return messages

    def has_pending(self) -> bool:
        with self._lock:
            return bool(self._pending)

    def wait_for_message(self, timeout: float) -> list[dict]:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return []
            if self.has_pending():
                messages = self.pop_all()
                if messages:
                    return messages
                continue
            self._event.wait(timeout=remaining)

    def reset(self) -> None:
        with self._lock:
            self._pending = []
            self._event.clear()
