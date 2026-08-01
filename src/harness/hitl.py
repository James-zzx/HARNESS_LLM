import json
import re
import sys
import threading
import time
from typing import Any, Callable, Optional, TextIO

DEFAULT_DANGEROUS_COMMANDS = [
    "rm -rf",
    "shutdown",
    "format",
    "dd if=",
    "git push --force",
    "DROP TABLE",
]


class GuardrailEngine:
    def __init__(
        self,
        dangerous_commands: Optional[list[str]] = None,
        regex_rules: Optional[list[str]] = None,
    ):
        self._dangerous_commands = [
            command.lower() for command in (dangerous_commands or DEFAULT_DANGEROUS_COMMANDS)
        ]
        self._regex_rules = [re.compile(pattern) for pattern in (regex_rules or [])]

    @staticmethod
    def _extract_command(action: Any) -> str:
        if isinstance(action, str):
            return action
        if isinstance(action, dict):
            params = action.get("params")
            if isinstance(params, dict) and isinstance(params.get("command"), str):
                return params["command"]
            if isinstance(action.get("command"), str):
                return action["command"]
        return ""

    def check(self, action: Any) -> bool:
        command = self._extract_command(action)
        if not command:
            return False
        lowered = command.lower()
        if any(rule in lowered for rule in self._dangerous_commands):
            return True
        return any(pattern.search(command) for pattern in self._regex_rules)


class HITLStateMachine:
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    TIMEOUT = "TIMEOUT"

    def __init__(
        self,
        approval_timeout: int = 300,
        clock: Optional[Callable[[], float]] = None,
    ):
        self._approval_timeout = approval_timeout
        self._clock = clock or time.monotonic
        self._state = self.RUNNING
        self._pending: Optional[dict] = None
        self._paused_at: Optional[float] = None
        self._decision_event = threading.Event()

    @property
    def state(self) -> str:
        return self._state

    def pause(self, action: dict) -> None:
        if self._state != self.RUNNING:
            raise ValueError(f"cannot pause from state {self._state}")
        self._pending = action
        self._paused_at = self._clock()
        self._state = self.PAUSED
        self._decision_event.clear()

    def approve(self) -> bool:
        if self._state != self.PAUSED:
            raise ValueError(f"cannot approve from state {self._state}")
        self._state = self.APPROVED
        self._decision_event.set()
        return True

    def reject(self) -> bool:
        if self._state != self.PAUSED:
            raise ValueError(f"cannot reject from state {self._state}")
        self._state = self.REJECTED
        self._decision_event.set()
        return False

    def timeout(self) -> bool:
        if self._state != self.PAUSED:
            raise ValueError(f"cannot timeout from state {self._state}")
        self._state = self.TIMEOUT
        self._decision_event.set()
        return False

    def resume(self) -> None:
        if self._state != self.APPROVED:
            raise ValueError(f"cannot resume from state {self._state}")
        self._state = self.RUNNING

    def check_timeout(self) -> bool:
        if self._state != self.PAUSED or self._paused_at is None:
            return False
        return self._clock() - self._paused_at >= self._approval_timeout

    def await_external_decision(self, timeout: Optional[float] = None) -> str:
        if self._state != self.PAUSED:
            raise ValueError(f"cannot wait for decision from state {self._state}")
        deadline = self._clock() + (self._approval_timeout if timeout is None else timeout)
        while self._state == self.PAUSED:
            remaining = deadline - self._clock()
            if remaining <= 0:
                self.timeout()
                return "timeout"
            self._decision_event.wait(remaining)
        if self._state == self.APPROVED:
            return "approved"
        if self._state == self.REJECTED:
            return "rejected"
        return "timeout"

    def outcome(self) -> Optional[bool]:
        if self._state == self.APPROVED:
            return True
        if self._state in (self.REJECTED, self.TIMEOUT):
            return False
        return None

    def rejection_feedback(self) -> Optional[str]:
        if self._state not in (self.REJECTED, self.TIMEOUT) or self._pending is None:
            return None
        return json.dumps(
            {
                "error": "action rejected by human-in-the-loop: approval required",
                "decision": self._state,
                "tool": self._pending.get("tool"),
                "params": self._pending.get("params"),
            },
            ensure_ascii=False,
        )

    def wait_for_decision(
        self,
        input_stream: Optional[TextIO] = None,
        output_stream: Optional[TextIO] = None,
    ) -> str:
        if self._state != self.PAUSED:
            raise ValueError(f"cannot wait for decision from state {self._state}")
        source = input_stream or sys.stdin
        out = output_stream or sys.stdout
        while True:
            if self.check_timeout():
                self.timeout()
                return "timeout"
            out.write("Approve dangerous action? (y/n/t) ")
            out.flush()
            line = source.readline()
            if not line:
                self.timeout()
                return "timeout"
            choice = line.strip().lower()
            if choice == "y":
                self.approve()
                return "approved"
            if choice == "n":
                self.reject()
                return "rejected"
            if choice == "t":
                self.timeout()
                return "timeout"


class HITLGate:
    def __init__(
        self,
        engine: Optional[GuardrailEngine] = None,
        approval_timeout: int = 300,
        clock: Optional[Callable[[], float]] = None,
        decision_source: Optional[Callable[[], str]] = None,
    ):
        self.engine = engine or GuardrailEngine()
        self._machine = HITLStateMachine(approval_timeout=approval_timeout, clock=clock)
        self._decision_source = decision_source or self._machine.await_external_decision

    @property
    def state(self) -> str:
        return self._machine.state

    def check(self, tool_name: str, params: dict) -> bool:
        action = {"tool": tool_name, "params": params}
        if not self.engine.check(action):
            return False
        self._machine.pause(action)
        return True

    def decide(self, tool_name: str, params: dict) -> bool:
        if self._machine.check_timeout():
            self._machine.timeout()
            return False
        decision = self._decision_source()
        if decision == "approved":
            if self._machine.state != self._machine.APPROVED:
                self._machine.approve()
            self._machine.resume()
            return True
        if self._machine.state == self._machine.PAUSED:
            if decision == "timeout":
                self._machine.timeout()
            else:
                self._machine.reject()
        return False

    def approve(self) -> bool:
        return self._machine.approve()

    def reject(self) -> bool:
        return self._machine.reject()

    def rejection_feedback(self) -> Optional[str]:
        return self._machine.rejection_feedback()
