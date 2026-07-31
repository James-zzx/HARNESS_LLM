from harness.evaluator import Evaluator


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


def test_evaluator_no_command_returns_passed(monkeypatch):
    def fail_if_run(*args, **kwargs):
        raise AssertionError("subprocess.run must not be called for the no-eval sentinel")

    monkeypatch.setattr("harness.evaluator.subprocess.run", fail_if_run)
    result = Evaluator().evaluate(command="")
    assert result.passed is True
    assert result.output == ""
    assert result.error == ""
    assert result.exit_code is None
