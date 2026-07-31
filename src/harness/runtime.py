from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Union

from harness.config import HarnessConfig
from harness.hitl import GuardrailEngine, HITLGate
from harness.orchestrator import Orchestrator
from harness.sandbox import Sandbox
from harness.tool_executor import ToolExecutor

_MB = 1024 * 1024


def _permissive_check(tool_name: str, params: Dict[str, Any]) -> bool:
    return True


def _make_tool_executor(
    config: HarnessConfig, sandbox: Sandbox, work_dir_path: Path
) -> ToolExecutor:
    sandbox_check = sandbox.build_check() if config.sandbox.enabled else _permissive_check
    return ToolExecutor(
        work_dir=str(work_dir_path),
        sandbox_check=sandbox_check,
        sandbox=sandbox if config.sandbox.enabled else None,
        shell_timeout=config.sandbox.timeout,
    )


def _never_pause(tool_name: str, params: dict) -> bool:
    return False


def _always_approve(tool_name: str, params: dict) -> bool:
    return True


@dataclass
class Runtime:
    """Wired sandbox + rule engine + HITL components built from a HarnessConfig."""

    config: HarnessConfig
    work_dir: Path
    sandbox: Sandbox
    tool_executor: ToolExecutor
    hitl_gate: HITLGate
    default_hitl_checker: Callable[[str, dict], bool]
    default_approval: Callable[[str, dict], bool]

    def build_orchestrator(
        self,
        llm,
        *,
        work_dir: Optional[Union[str, Path]] = None,
        hitl_checker: Optional[Callable[[str, dict], bool]] = None,
        approval: Optional[Callable[[str, dict], bool]] = None,
        **kwargs,
    ) -> Orchestrator:
        kwargs.setdefault(
            "hitl_checker", hitl_checker if hitl_checker is not None else self.default_hitl_checker
        )
        kwargs.setdefault(
            "approval", approval if approval is not None else self.default_approval
        )
        orch_work_dir = self.work_dir if work_dir is None else Path(work_dir).resolve()
        tool_executor = self.tool_executor
        if orch_work_dir != self.work_dir:
            tool_executor = _make_tool_executor(self.config, self.sandbox, orch_work_dir)
        return Orchestrator(
            llm=llm,
            work_dir=str(orch_work_dir),
            tool_executor=tool_executor,
            **kwargs,
        )

    def new_gate(self) -> HITLGate:
        """A fresh per-run HITL gate honoring config.hitl (inert when disabled)."""
        if not self.config.hitl.enabled:
            return HITLGate(engine=GuardrailEngine([]))
        return HITLGate(
            engine=GuardrailEngine(self.config.hitl.dangerous_commands),
            approval_timeout=self.config.hitl.approval_timeout,
        )


def build_runtime(config: HarnessConfig, work_dir: Union[str, Path] = ".") -> Runtime:
    work_dir_path = Path(work_dir).resolve()

    sandbox = Sandbox(
        allowed_dirs=config.sandbox.allowed_dirs,
        blocked_dirs=config.sandbox.blocked_dirs,
        blocked_commands=config.sandbox.blocked_commands,
        timeout=config.sandbox.timeout,
        memory_limit=config.sandbox.max_memory_mb * _MB,
        network=config.sandbox.network == "allow",
    )

    if config.hitl.enabled:
        hitl_gate = HITLGate(
            engine=GuardrailEngine(config.hitl.dangerous_commands),
            approval_timeout=config.hitl.approval_timeout,
        )
        default_hitl_checker: Callable[[str, dict], bool] = hitl_gate.check
        default_approval: Callable[[str, dict], bool] = hitl_gate.decide
    else:
        hitl_gate = HITLGate(engine=GuardrailEngine([]))
        default_hitl_checker = _never_pause
        default_approval = _always_approve

    tool_executor = _make_tool_executor(config, sandbox, work_dir_path)

    return Runtime(
        config=config,
        work_dir=work_dir_path,
        sandbox=sandbox,
        tool_executor=tool_executor,
        hitl_gate=hitl_gate,
        default_hitl_checker=default_hitl_checker,
        default_approval=default_approval,
    )
