import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

DEFAULT_COMMAND = "make test"


@dataclass
class EvaluationResult:
    passed: bool
    output: str = ""
    error: str = ""
    exit_code: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "output": self.output,
            "error": self.error,
            "exit_code": self.exit_code,
        }


class Evaluator:
    def __init__(
        self,
        command: Optional[str] = None,
        cwd: Optional[Union[str, Path]] = None,
        timeout: Optional[float] = None,
    ):
        self.command = command if command is not None else DEFAULT_COMMAND
        self.cwd = cwd
        self.timeout = timeout

    def evaluate(
        self,
        command: Optional[str] = None,
        cwd: Optional[Union[str, Path]] = None,
        timeout: Optional[float] = None,
    ) -> EvaluationResult:
        cmd = command if command is not None else self.command
        work_dir = cwd if cwd is not None else self.cwd
        limit = timeout if timeout is not None else self.timeout
        if not cmd:
            return EvaluationResult(passed=True)
        try:
            completed = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                cwd=work_dir,
                timeout=limit,
            )
        except subprocess.TimeoutExpired as exc:
            return EvaluationResult(
                passed=False,
                output=exc.stdout or "",
                error=f"timeout after {limit}s",
            )
        except OSError as exc:
            return EvaluationResult(passed=False, error=str(exc))
        return EvaluationResult(
            passed=completed.returncode == 0,
            output=completed.stdout,
            error=completed.stderr,
            exit_code=completed.returncode,
        )
