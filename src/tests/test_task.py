import json

import pytest

from harness.task import Task, TaskError, TaskParser


def test_parse_yaml_task(work_dir):
    task_file = work_dir / "task.yaml"
    task_file.write_text(
        "id: fix-lint-errors\n"
        "prompt: Fix all lint errors in src/\n"
        "eval_command: make lint\n"
        "max_iterations: 5\n"
        "timeout: 60\n",
        encoding="utf-8",
    )

    task = TaskParser.load_yaml(str(task_file))

    assert isinstance(task, Task)
    assert task.id == "fix-lint-errors"
    assert task.prompt == "Fix all lint errors in src/"
    assert task.eval_command == "make lint"
    assert task.max_iterations == 5
    assert task.timeout == 60


def test_parse_json_task(work_dir):
    task_file = work_dir / "task.json"
    task_file.write_text(
        json.dumps(
            {
                "id": "add-unit-tests",
                "prompt": "Add unit tests for the parser module",
                "max_iterations": 3,
            }
        ),
        encoding="utf-8",
    )

    task = TaskParser.load_json(str(task_file))

    assert isinstance(task, Task)
    assert task.id == "add-unit-tests"
    assert task.prompt == "Add unit tests for the parser module"
    assert task.eval_command is None
    assert task.max_iterations == 3
    assert task.timeout == 300


def test_task_validation_missing_field(work_dir):
    task_file = work_dir / "task.yaml"
    task_file.write_text("prompt: Missing an id field\n", encoding="utf-8")

    with pytest.raises(TaskError):
        TaskParser.load_yaml(str(task_file))


def test_task_validation_type_error(work_dir):
    task_file = work_dir / "task.yaml"
    task_file.write_text(
        "id: my-task\nprompt: A prompt\nmax_iterations: many\n", encoding="utf-8"
    )

    with pytest.raises(TaskError):
        TaskParser.load_yaml(str(task_file))
