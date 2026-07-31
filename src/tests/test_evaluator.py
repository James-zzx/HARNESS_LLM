import pytest

from harness.evaluator import EvaluationResult, Evaluator


def test_evaluator_passed():
    result = Evaluator().evaluate(command='python -c "import sys; sys.exit(0)"')
    assert result.passed is True
    assert result.exit_code == 0


def test_evaluator_failed():
    result = Evaluator().evaluate(command='python -c "import sys; sys.exit(1)"')
    assert result.passed is False
    assert result.exit_code == 1


def test_evaluator_captures_output():
    result = Evaluator().evaluate(command="python -c \"print('hello evaluator')\"")
    assert result.passed is True
    assert "hello evaluator" in result.output


def test_evaluator_custom_command(work_dir):
    result = Evaluator(command="make test").evaluate(
        command="python -c \"import os; print(os.getcwd())\"",
        cwd=work_dir,
    )
    assert result.passed is True
    assert str(work_dir) in result.output


def test_evaluator_timeout():
    result = Evaluator().evaluate(
        command='python -c "import time; time.sleep(2)"',
        timeout=0.1,
    )
    assert result.passed is False
    assert "timeout" in result.error.lower()
