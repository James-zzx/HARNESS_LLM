import sys
import threading
import time

from harness.sandbox import Sandbox, sandbox_check_from
from harness.tool_executor import ToolExecutor


def _sandbox(tmp_path, **kwargs):
    allowed = tmp_path / "workspace"
    allowed.mkdir()
    kwargs.setdefault("allowed_dirs", [str(allowed)])
    return Sandbox(**kwargs), allowed


def test_sandbox_allows_whitelist_path(tmp_path):
    sb, allowed = _sandbox(tmp_path)
    target = allowed / "notes.txt"
    target.write_text("hello", encoding="utf-8")

    assert sb.is_allowed_path(str(target)) is True

    check = sb.build_check()
    assert check("read_file", {"path": str(target)}) is True
    assert check("write_file", {"path": str(target)}) is True


def test_sandbox_blocks_blacklist_path(tmp_path):
    allowed = tmp_path / "workspace"
    allowed.mkdir()
    blocked = tmp_path / "system"
    blocked.mkdir()
    sb = Sandbox(allowed_dirs=[str(allowed)], blocked_dirs=[str(blocked)])

    assert sb.is_allowed_path(str(tmp_path / "elsewhere.txt")) is False
    assert sb.is_allowed_path(str(blocked / "file.txt")) is False

    nested = allowed / "system"
    nested.mkdir()
    sb_nested = Sandbox(allowed_dirs=[str(allowed)], blocked_dirs=[str(nested)])
    assert sb_nested.is_allowed_path(str(nested / "x.txt")) is False
    assert sb_nested.is_allowed_path(str(allowed / "ok.txt")) is True

    check = sb.build_check()
    assert check("write_file", {"path": str(tmp_path / "elsewhere.txt")}) is False
    assert check("read_file", {"path": str(blocked / "file.txt")}) is False
    assert check("write_file", {"path": "relative.txt"}) is True


def test_sandbox_blocks_dangerous_command(tmp_path):
    sb, _ = _sandbox(tmp_path)

    assert sb.check_command("rm -rf /") is False
    assert sb.check_command("rm -rf /*") is False
    assert sb.check_command("rm -rf / --no-preserve-root") is False
    assert sb.check_command("rm -rf C:\\") is False
    assert sb.check_command("shutdown now") is False
    assert sb.check_command("echo hello harness") is True
    assert sb.check_command("rm -rf /tmp/somewhere") is True

    check = sb.build_check()
    assert check("run_shell", {"command": "rm -rf /"}) is False
    assert check("run_shell", {"command": "echo ok"}) is True


def test_sandbox_blocks_compound_and_system_dir_commands(tmp_path):
    sb, _ = _sandbox(tmp_path)

    assert sb.check_command("rm -rf /; echo done") is False
    assert sb.check_command("rm -rf /|cat") is False
    assert sb.check_command("rm -rf / && echo done") is False
    assert sb.check_command("echo $(rm -rf /)") is False
    assert sb.check_command("x=`rm -rf /`") is False

    assert sb.check_command("rm -rf C:\\Windows") is False
    assert sb.check_command("rm -rf C:/Windows") is False
    assert sb.check_command("rm -rf /Windows") is False
    assert sb.check_command("rm -rf /etc") is False
    assert sb.check_command("rm -rf /usr") is False
    assert sb.check_command("rm -rf /bin") is False

    assert sb.check_command("rm -rf /tmp/somewhere") is True
    assert sb.check_command("echo done; echo hi") is True


def test_sandbox_blocks_path_traversal_to_root(tmp_path):
    sb, _ = _sandbox(tmp_path)

    assert sb.check_command("rm -rf /tmp/../..") is False
    assert sb.check_command("rm -rf /tmp/../../../") is False
    assert sb.check_command("rm -rf /a/b/../../..") is False
    assert sb.check_command("rm -rf /tmp/../etc/passwd") is False
    assert sb.check_command("rm -rf C:\\Users\\..\\..") is False

    assert sb.check_command("rm -rf /tmp/x") is True
    assert sb.check_command("rm -rf /tmp/../x") is True


def test_sandbox_blocks_traversal_with_attached_operator(tmp_path):
    sb, _ = _sandbox(tmp_path)

    assert sb.check_command("rm -rf /tmp/../..; echo x") is False
    assert sb.check_command("rm -rf /tmp/../..|cat") is False
    assert sb.check_command("rm -rf /tmp/../../&&echo x") is False
    assert sb.check_command("rm -rf /tmp/../..>/dev/null") is False
    assert sb.check_command("rm -rf `/tmp/../..`") is False
    assert sb.check_command("echo a; rm -rf /tmp/../../../; echo b") is False
    assert sb.check_command("rm -rf C:\\Users\\..\\..; echo x") is False

    assert sb.check_command("rm -rf /tmp/x; echo done") is True
    assert sb.check_command("rm -rf /tmp/../x; echo done") is True
    assert sb.check_command("rm -rf /tmp/x|cat") is True
    assert sb.check_command("echo done; rm -rf /tmp/y") is True


def test_sandbox_blocks_second_rm_glued_to_operator(tmp_path):
    sb, _ = _sandbox(tmp_path)

    assert sb.check_command("rm -rf /tmp/x&&rm -rf /tmp/../..") is False
    assert sb.check_command("rm -rf /tmp/x;rm -rf /tmp/../..") is False
    assert sb.check_command("rm -rf /tmp/x;rm -rf C:\\Users\\..\\..") is False
    assert sb.check_command("rm -rf /tmp/x && rm -rf /tmp/../..") is False

    assert sb.check_command("rm -rf /tmp/x") is True
    assert sb.check_command("rm -rf /tmp/../x") is True
    assert sb.check_command("echo done; rm -rf /tmp/y") is True
    assert sb.check_command("rm -rf /tmp/x && rm -rf /tmp/y") is True


def test_sandbox_timeout(tmp_path):
    sb, _ = _sandbox(tmp_path, timeout=1)

    start = time.monotonic()
    result = sb.run([sys.executable, "-c", "import time; time.sleep(30)"], timeout=1)
    elapsed = time.monotonic() - start

    assert result.timed_out is True
    assert elapsed < 10


def test_sandbox_context_manager(tmp_path):
    sb, _ = _sandbox(tmp_path, timeout=60)
    outcome = {}

    def worker():
        outcome["result"] = sb.run(
            [sys.executable, "-c", "import time; time.sleep(30)"], timeout=60
        )

    with sb:
        thread = threading.Thread(target=worker)
        thread.start()
        time.sleep(1)
        assert sb.active_processes() == 1

    thread.join(timeout=5)

    assert thread.is_alive() is False
    assert outcome["result"].returncode != 0
    assert sb.active_processes() == 0


def test_sandbox_check_integrates_with_tool_executor(tmp_path):
    sb, allowed = _sandbox(tmp_path)
    executor = ToolExecutor(work_dir=str(allowed), sandbox_check=sb.build_check())

    write = executor.execute(
        {"tool": "write_file", "params": {"path": "notes.txt", "content": "hi"}}
    )
    assert write.success is True
    assert (allowed / "notes.txt").read_text(encoding="utf-8") == "hi"

    denied = executor.execute({"tool": "run_shell", "params": {"command": "rm -rf /"}})
    assert denied.success is False
    assert "sandbox" in denied.error.lower()

    factory_check = sandbox_check_from(sb)
    assert factory_check("run_shell", {"command": "rm -rf /"}) is False
    assert factory_check("write_file", {"path": "notes.txt"}) is True


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


def test_sandbox_allow_dir_ancestor_idempotent(tmp_path):
    allowed = tmp_path / "workspace"
    allowed.mkdir()
    sb = Sandbox(allowed_dirs=[str(allowed)])
    ancestor = tmp_path
    sb.allow_dir(str(ancestor))
    sb.allow_dir(str(ancestor))
    assert sum(1 for a in sb.allowed_dirs if a == str(ancestor.resolve())) == 1


def test_sandbox_allow_dir_concurrent_no_duplicates(tmp_path):
    allowed = tmp_path / "workspace"
    allowed.mkdir()
    sb = Sandbox(allowed_dirs=[str(allowed)])
    extra = tmp_path / "extra"
    extra.mkdir()
    barrier = threading.Barrier(8)

    def add():
        barrier.wait()
        for _ in range(200):
            sb.allow_dir(str(extra))

    threads = [threading.Thread(target=add) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert sum(1 for a in sb.allowed_dirs if a == str(extra.resolve())) == 1


def test_sandbox_run_nonexistent_cwd_returns_error(tmp_path):
    sb = Sandbox(allowed_dirs=[str(tmp_path)])
    result = sb.run("echo hi", shell=True, cwd=str(tmp_path / "missing"))
    assert result.error is not None


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
    assert result.stdout.strip().lower().replace("\\", "/") == str(target).lower().replace("\\", "/")
