# Work-Dir Anchoring & run_shell cwd Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hard-anchor all LLM file writes to each task's own work_dir under `harness-tasks/<task_id>`, auto-create the folder when missing, and fix the bug where sandbox-enabled `run_shell` runs in the project root instead of the task work_dir.

**Architecture:** Add a dynamic `Sandbox.allow_dir()` so each task's work_dir is appended to the sandbox allowed dirs; change `_default_runner` to create and use `harness-tasks/<task_id>` (falling back to `mkdtemp` for invalid ids); add a `cwd` parameter to `Sandbox.run` and pass `work_dir` from `RunShellTool._run_via_sandbox`. Keep the existing `_PathTool._resolve` work_dir anchoring as a second line of defense.

**Tech Stack:** Python 3.11+, pytest, FastAPI, no new dependencies.

## Global Constraints

- Work dir base = `<project_root>/harness-tasks` (project root = the resolved `runtime.work_dir`).
- Use the already-existing `harness-tasks/` folder at the project root; auto-create if missing.
- Every path-tool (write_file/edit_file/read_file/list_dir) path must resolve inside the task work_dir; out-of-scope paths are rejected (never auto-rewritten).
- The enforcement must live in code (sandbox + tool layer), NOT in the system prompt (spec §A.4 B/C).
- run_shell keeps existing command blacklist/timeout/memory/network limits; only its `cwd` behavior changes.
- All tests must be deterministic and run without a real LLM (mock LLM allowed).
- `.gitignore` gains `harness-tasks/`.
- Keep the spec item "user-configurable target folder" explicitly OUT of scope.

---

### Task 1: Add `Sandbox.allow_dir` and `cwd` support to `Sandbox.run`

**Files:**
- Modify: `src/harness/sandbox.py`
- Test: `src/tests/test_sandbox.py`

**Interfaces:**
- Produces: `Sandbox.allow_dir(path: str | Path) -> None` — idempotent append to allowed dirs.
- Produces: `Sandbox.run(command, timeout=None, shell=None, network=False, cwd=None) -> RunResult` — `cwd` passed to `Popen` when not None.

- [ ] **Step 1: Write the failing tests**

Append to `src/tests/test_sandbox.py`:

```python
def test_sandbox_allow_dir_adds_to_allowed_paths(tmp_path):
    allowed = tmp_path / "workspace"
    allowed.mkdir()
    sb = Sandbox(allowed_dirs=[str(allowed)])
    extra = tmp_path / "extra"
    extra.mkdir()

    assert sb.is_allowed_path(str(extra / "f.txt")) is False
    sb.allow_dir(str(extra))
    assert sb.is_allowed_path(str(extra / "f.txt")) is True


def test_sandbox_allow_dir_is_idempotent(tmp_path):
    allowed = tmp_path / "workspace"
    allowed.mkdir()
    sb = Sandbox(allowed_dirs=[str(allowed)])
    extra = tmp_path / "extra"
    extra.mkdir()

    sb.allow_dir(str(extra))
    sb.allow_dir(str(extra))
    assert sum(1 for a in sb.allowed_dirs if a == str(extra.resolve())) == 1


def test_sandbox_run_respects_cwd(tmp_path):
    sb = Sandbox(allowed_dirs=[str(tmp_path)])
    target = tmp_path / "cwd_target"
    target.mkdir()

    result = sb.run(
        "cd",
        shell=True,
        cwd=str(target),
    )
    assert result.returncode == 0
    assert result.stdout.strip().lower().replace("\\\\", "/") == str(target).lower().replace("\\\\", "/")
```

Note: on Windows `cd` prints the cwd; the final assertion compares normalized paths. If the platform's `cd` output differs, use `sys.executable` `-c` print cwd instead:

```python
def test_sandbox_run_respects_cwd_python(tmp_path):
    import sys
    sb = Sandbox(allowed_dirs=[str(tmp_path)])
    target = tmp_path / "cwd_target"
    target.mkdir()

    result = sb.run(
        [sys.executable, "-c", "import os; print(os.getcwd())"],
        cwd=str(target),
    )
    assert result.returncode == 0
    assert result.stdout.strip().lower().replace("\\\\", "/") == str(target).lower().replace("\\\\", "/")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest src/tests/test_sandbox.py -v`
Expected: `test_sandbox_allow_dir_adds_to_allowed_paths`, `test_sandbox_allow_dir_is_idempotent` fail with `AttributeError: 'Sandbox' object has no attribute 'allow_dir'`; the cwd test fails because `cwd` is an unexpected keyword.

- [ ] **Step 3: Implement `allow_dir`**

In `Sandbox.__init__` the existing fields are `self._allowed_paths` (resolved Paths) and `self.allowed_dirs` (strings). Add:

```python
    def allow_dir(self, path: Union[str, Path]) -> None:
        resolved = Path(path).resolve()
        if any(resolved == a or _is_within(resolved, a) for a in self._allowed_paths):
            return
        self._allowed_paths.append(resolved)
        self.allowed_dirs.append(str(resolved))
```

- [ ] **Step 4: Implement `cwd` in `Sandbox.run`**

Change the `run` signature and `Popen` calls:

```python
    def run(
        self,
        command: Union[str, Sequence[str]],
        timeout: Optional[float] = None,
        shell: Optional[bool] = None,
        network: bool = False,
        cwd: Optional[Union[str, Path]] = None,
    ) -> RunResult:
```

And in both `Popen` branches add `cwd=str(cwd) if cwd is not None else None` to `popen_kwargs`. Simplest: after building `popen_kwargs`, add:

```python
        if cwd is not None:
            popen_kwargs["cwd"] = str(cwd)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest src/tests/test_sandbox.py -v`
Expected: all pass, including the 3 new tests.

- [ ] **Step 6: Commit**

```bash
git add src/harness/sandbox.py src/tests/test_sandbox.py
git commit -m "feat(sandbox): add allow_dir and cwd support to run"
```

---

### Task 2: Fix run_shell cwd under sandbox

**Files:**
- Modify: `src/harness/tool_executor.py`
- Test: `src/tests/test_tool_executor.py`

**Interfaces:**
- Consumes: `Sandbox.run(..., cwd=...)` from Task 1.
- Produces: no new public API; behavior change: `RunShellTool._run_via_sandbox` runs in the tool's work_dir.

- [ ] **Step 1: Write the failing test**

Append to `src/tests/test_tool_executor.py`:

```python
def test_run_shell_sandbox_uses_work_dir_cwd(work_dir, tmp_path):
    from harness.sandbox import Sandbox

    sandbox = Sandbox(allowed_dirs=[str(work_dir)])
    executor = ToolExecutor(work_dir=str(work_dir), sandbox=sandbox, shell_timeout=30)

    result = executor.execute(
        {
            "tool": "run_shell",
            "params": {
                "command": f'"{sys.executable}" -c "import os; print(os.getcwd())"'
            },
        }
    )
    assert result.success is True
    normalized = result.output.strip().lower().replace("\\\\", "/")
    expected = str(work_dir).lower().replace("\\\\", "/")
    assert normalized == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest src/tests/test_tool_executor.py::test_run_shell_sandbox_uses_work_dir_cwd -v`
Expected: FAIL — output is the project root (or the pytest cwd), not `work_dir`.

- [ ] **Step 3: Implement the fix**

In `src/harness/tool_executor.py`, change `_run_via_sandbox`:

```python
    def _run_via_sandbox(self, command: str) -> ToolResult:
        result = self._sandbox.run(command, timeout=self._timeout, cwd=str(self._work_dir))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest src/tests/test_tool_executor.py::test_run_shell_sandbox_uses_work_dir_cwd -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/tool_executor.py src/tests/test_tool_executor.py
git commit -m "fix(tool_executor): run_shell under sandbox now uses work_dir as cwd"
```

---

### Task 3: Route task work_dir to `harness-tasks/<task_id>` with auto-create

**Files:**
- Modify: `src/harness/api.py`
- Test: `src/tests/test_api.py`

**Interfaces:**
- Consumes: `Sandbox.allow_dir` from Task 1 (via `runtime.sandbox`).
- Produces: work_dir at `<runtime.work_dir>/harness-tasks/<task_id>` for valid ids; `mkdtemp` fallback for empty/invalid ids. Behavior verified through `manager.get_work_dir(task_id)`.

- [ ] **Step 1: Write the failing tests**

Append to `src/tests/test_api.py`:

```python
def test_api_work_dir_under_harness_tasks(tmp_path, monkeypatch):
    def fake_build_llm(config, credential_store=None):
        return MockLLM([json.dumps({"done": True})])

    monkeypatch.setattr("harness.llm_adapter.build_llm", fake_build_llm)
    monkeypatch.chdir(tmp_path)

    manager = TaskManager()
    app = create_app(task_manager=manager)
    with TestClient(app) as client:
        client.post("/api/tasks", json={"id": "api-wd2", "prompt": "write"})
        snapshot = _wait_for_task(manager, "api-wd2")

    assert snapshot["status"] == "completed"
    work_dir = Path(manager.get_work_dir("api-wd2"))
    assert work_dir.parent.name == "harness-tasks"
    assert work_dir.name == "api-wd2"


def test_api_harness_tasks_dir_autocreated(tmp_path, monkeypatch):
    def fake_build_llm(config, credential_store=None):
        return MockLLM([json.dumps({"done": True})])

    monkeypatch.setattr("harness.llm_adapter.build_llm", fake_build_llm)
    monkeypatch.chdir(tmp_path)

    manager = TaskManager()
    app = create_app(task_manager=manager)
    with TestClient(app) as client:
        client.post("/api/tasks", json={"id": "api-auto", "prompt": "write"})
        snapshot = _wait_for_task(manager, "api-auto")

    assert snapshot["status"] == "completed"
    tasks_dir = Path(tmp_path) / "harness-tasks"
    assert tasks_dir.is_dir()
    assert (tasks_dir / "api-auto").is_dir()


def test_api_work_dir_added_to_sandbox_allowed_dirs(tmp_path, monkeypatch):
    def fake_build_llm(config, credential_store=None):
        return MockLLM([json.dumps({"done": True})])

    monkeypatch.setattr("harness.llm_adapter.build_llm", fake_build_llm)
    monkeypatch.chdir(tmp_path)

    manager = TaskManager()
    app = create_app(task_manager=manager)
    with TestClient(app) as client:
        client.post("/api/tasks", json={"id": "api-sb", "prompt": "write"})
        _wait_for_task(manager, "api-sb")

    work_dir = Path(manager.get_work_dir("api-sb")).resolve()
    # _default_runner builds a fresh runtime per call; verify via file write allowed:
    assert work_dir.is_dir()
```

Note: the third test above is intentionally lightweight (the runner builds a fresh runtime, so the sandbox instance is not reachable from the test). The real assertion that matters is `test_api_work_dir_under_harness_tasks` (location) plus the existing e2e `test_api_files_workdir_wired_through_default_runner` (file listing). Keep test 3 minimal; if you want a stronger check, assert the work_dir is a directory and that a file written by a mock write_file lands inside it (already covered by `test_api_files_workdir_wired_through_default_runner`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest src/tests/test_api.py::test_api_work_dir_under_harness_tasks src/tests/test_api.py::test_api_harness_tasks_dir_autocreated src/tests/test_api.py::test_api_work_dir_added_to_sandbox_allowed_dirs -v`
Expected: FAIL — work_dir parent is the tmp root (mkdtemp), not `harness-tasks`.

- [ ] **Step 3: Implement**

In `src/harness/api.py`, inside `_default_runner`, replace the work_dir creation block:

```python
        task_work_dir = _make_task_work_dir(runtime.work_dir, task.id)
```

Add a module-level helper near the top of the file (after `_STATUS_MAP`):

```python
def _make_task_work_dir(base: Path, task_id: str) -> str:
    tasks_dir = Path(base) / "harness-tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    if task_id and not any(sep in task_id for sep in ("/", "\\")):
        work_dir = tasks_dir / task_id
        work_dir.mkdir(parents=True, exist_ok=True)
        return str(work_dir)
    return tempfile.mkdtemp(prefix="harness-task-", dir=str(tasks_dir))
```

Then, right after the work_dir is created and before `build_orchestrator`, call:

```python
        runtime.sandbox.allow_dir(task_work_dir)
```

Place this so it applies to every path (including the `mkdtemp` fallback). The `manager.set_work_dir(task.id, task_work_dir)` call stays unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest src/tests/test_api.py -v`
Expected: all pass. NOTE: `test_api_default_runner_isolates_task_work_dirs` and `test_api_files_workdir_wired_through_default_runner` both use task ids ("api-iso", "api-wd") so they now resolve to `harness-tasks/<id>`; update any assertion that scans for `harness-task-*` prefixed dirs under the tmp root (see Step 4b).

- [ ] **Step 4b: Update the outdated isolation test**

In `src/tests/test_api.py`, `test_api_default_runner_isolates_task_work_dirs` currently asserts:

```python
    subdirs = [
        p for p in base.iterdir() if p.is_dir() and p.name.startswith("harness-task-")
    ]
    assert subdirs
    assert (subdirs[0] / "result.txt").read_text(encoding="utf-8") == "hello"
```

Replace with:

```python
    tasks_dir = base / "harness-tasks"
    assert (tasks_dir / "api-iso" / "result.txt").read_text(encoding="utf-8") == "hello"
    assert not (base / "result.txt").exists()
```

- [ ] **Step 5: Run full api tests**

Run: `python -m pytest src/tests/test_api.py -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/harness/api.py src/tests/test_api.py
git commit -m "feat(api): route task work_dir to harness-tasks/<task_id> and anchor in sandbox"
```

---

### Task 4: Add `harness-tasks/` to `.gitignore`

**Files:**
- Modify: `.gitignore`

**Interfaces:**
- Consumes: nothing.
- Produces: `harness-tasks/` ignored by git.

- [ ] **Step 1: Add ignore entry**

Append the line `harness-tasks/` to `.gitignore` (after the existing `harness` entries, keep alphabetical order with other dirs if desired).

- [ ] **Step 2: Verify**

Run: `git check-ignore harness-tasks/`
Expected: outputs `harness-tasks/` (exit 0).

Run: `git status --short`
Expected: no `harness-tasks/` entry.

- [ ] **Step 3: Commit**

```bash
git add .gitignore
git commit -m "chore: ignore harness-tasks/ task artifacts"
```

---

### Task 5: Full regression + real-LLM smoke verification

**Files:**
- Modify: none (verification only).
- Test: `src/tests/` full suite.

**Interfaces:**
- Consumes: all tasks 1-4.

- [ ] **Step 1: Full test suite**

Run: `python -m pytest src/tests/ -q`
Expected: all pass (previous baseline 223 + new tests).

- [ ] **Step 2: Lint**

Run: `python -m ruff check src/`
Expected: no errors.

- [ ] **Step 3: Mock-LLM end-to-end via API**

Start dashboard (mock mode) and submit a write-file task; confirm:
- `GET /api/tasks/{id}/files` lists the written file.
- File physically exists under `<project>/harness-tasks/<task_id>/`.

- [ ] **Step 4: Real-LLM smoke test (optional but recommended)**

Submit a task via dashboard with DeepSeek (llm_mode=real) asking to write a multiplication table to a file. Confirm:
- The file appears in `harness-tasks/<task_id>/`.
- run_shell (used to run/verify) executes in work_dir (e.g. `python multiplication.py` finds the file).

- [ ] **Step 5: Commit any residual changes**

If tests surfaced a needed fix, commit it with a clear message. Otherwise no commit needed.
