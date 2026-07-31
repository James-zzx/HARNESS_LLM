import ctypes
import ntpath
import os
import posixpath
import re
import signal
import subprocess
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

# A destructive `rm` whose TARGET is the filesystem/drive root: the target must be
# followed by end-of-string, whitespace, or a shell operator (`;` `|` `&&` `||` `>` `<`
# backtick `$(...)`) so scoped deletes like `rm -rf /tmp/x` stay allowed while compound
# forms like `rm -rf /; echo done` / `echo $(rm -rf /)` are caught.
_ARMED_RM_PREFIX = r"\brm\b\s+(?:-+\S+\s+)*"
DEFAULT_BLOCKED_COMMANDS = (
    r"\bshutdown\b",
    r"\breboot\b",
    _ARMED_RM_PREFIX
    + r"(?:/[*]?|[a-zA-Z]:[\\/])"
    r"(?=$|[\s;|&<>`()$])",
    # System-directory deletion is a different risk class than a scoped /tmp/x delete:
    # any `rm` targeting a system directory (Windows or unix) is blocked outright.
    _ARMED_RM_PREFIX
    + r".*?(?:/(?:etc|usr|bin|Windows)|[a-zA-Z]:[\\/](?:Windows|Program Files))",
    # --no-preserve-root is a deliberate root-deletion marker; never allow it with `rm`.
    r"\brm\b[\s\S]*--no-preserve-root",
)

# `..`-traversal is handled functionally (regexes can't count components vs. `..`):
# any `rm` target whose lexical normalization lands on a root or system directory is
# blocked, e.g. `rm -rf /tmp/../..` (-> `/`) or `rm -rf /tmp/../../Windows`.
_SYSTEM_DIR_NAMES = (
    "etc",
    "usr",
    "bin",
    "sbin",
    "lib",
    "boot",
    "dev",
    "proc",
    "sys",
    "Windows",
    "Program Files",
    "ProgramData",
    "System32",
    "System",
    "Users",
    "Windows.old",
)


def _normalized_target_is_dangerous(target: str) -> bool:
    """True when an absolute target lexically normalizes to root or a system dir."""
    raw = target.strip().strip("'\"")
    if not raw:
        return False
    if raw.startswith(("//", "\\\\")) or (len(raw) >= 2 and raw[1] == ":"):
        norm = ntpath.normpath(raw)
        drive, rest = ntpath.splitdrive(norm)
        if rest in ("\\", "/") and drive:
            return True
        if drive and not rest:
            return True
        if not rest:
            return False
        names = rest.replace("\\", "/").strip("/").split("/")
        return names and names[0].lower() in _SYSTEM_DIR_NAMES
    if raw.startswith(("/", "\\")):
        norm = posixpath.normpath(raw)
        if norm == "/":
            return True
        names = norm.strip("/").split("/")
        return names and names[0].lower() in _SYSTEM_DIR_NAMES
    return False


def _rm_targets_root_or_system(command: str) -> bool:
    """True if an `rm` invocation targets a path normalizing to root/system dir."""
    if not re.search(r"\brm\b", command, re.IGNORECASE):
        return False
    tokens = command.split()
    for index, token in enumerate(tokens):
        if not re.fullmatch(r"rm", token, re.IGNORECASE):
            continue
        for following in tokens[index + 1 :]:
            if following == "-" or following.startswith("-"):
                continue
            if re.search(r"[;|&<>()`$]", following):
                break
            if _normalized_target_is_dangerous(following):
                return True
    return False

_PATH_TOOLS = frozenset({"read_file", "write_file", "edit_file", "list_dir"})

_WINDOWS_QUERY_LIMITED_INFO = 0x1000
_WINDOWS_SET_INFORMATION = 0x0200
_WINDOWS_BELOW_NORMAL = 0x00004000


@dataclass
class RunResult:
    returncode: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    error: Optional[str] = None


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _terminate_process(proc: subprocess.Popen) -> None:
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True,
                timeout=5,
            )
        except Exception:
            pass
        try:
            proc.kill()
        except Exception:
            pass
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.kill()
            except Exception:
                pass


def communicate_with_timeout(
    proc: subprocess.Popen, timeout: Optional[float]
) -> Tuple[str, str, bool]:
    """communicate() bounded by ``timeout``, killing the whole tree on expiry.

    Returns ``(stdout, stderr, timed_out)``. Without this the direct child is
    killed on timeout but its descendants (e.g. ``shell=True`` grandchildren)
    can keep the pipes open, hanging the caller.
    """
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return stdout, stderr, False
    except subprocess.TimeoutExpired:
        _terminate_process(proc)
        try:
            stdout, stderr = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            _terminate_process(proc)
            stdout, stderr = proc.communicate()
        return stdout, stderr, True


class Sandbox:
    def __init__(self, config: Optional[Dict[str, Any]] = None, **kwargs):
        if config is not None and not isinstance(config, dict):
            raise TypeError("config must be a dict or keyword arguments")
        cfg = dict(config or {})
        cfg.update(kwargs)
        self.allowed_dirs: List[str] = [str(d) for d in cfg.get("allowed_dirs", [])]
        self.blocked_dirs: List[str] = [str(d) for d in cfg.get("blocked_dirs", [])]
        blocked_commands = cfg.get("blocked_commands", ())
        if isinstance(blocked_commands, str):
            blocked_commands = (blocked_commands,)
        self.blocked_commands: Sequence[str] = DEFAULT_BLOCKED_COMMANDS + tuple(
            blocked_commands
        )
        self.timeout: Optional[float] = cfg.get("timeout")
        self.memory_limit: Optional[int] = cfg.get("memory_limit")
        self.network: bool = bool(cfg.get("network", True))
        self._processes: set = set()
        self._blocked_paths = [Path(b).resolve() for b in self.blocked_dirs]
        self._allowed_paths = [Path(a).resolve() for a in self.allowed_dirs]

    def _resolve_candidates(self, path: Union[str, Path]) -> List[Path]:
        candidate = Path(path)
        if candidate.is_absolute():
            return [candidate.resolve()]
        return [(Path(allowed) / candidate).resolve() for allowed in self.allowed_dirs]

    def is_allowed_path(self, path: Union[str, Path]) -> bool:
        if not self.allowed_dirs or not path:
            return False
        for candidate in self._resolve_candidates(path):
            if any(_is_within(candidate, b) for b in self._blocked_paths):
                continue
            if any(_is_within(candidate, a) for a in self._allowed_paths):
                return True
        return False

    def check_command(self, command: Union[str, Sequence[str]]) -> bool:
        if isinstance(command, (list, tuple)):
            command = " ".join(str(c) for c in command)
        command = command.strip()
        if not command:
            return False
        for pattern in self.blocked_commands:
            if re.search(pattern, command, re.IGNORECASE):
                return False
        if _rm_targets_root_or_system(command):
            return False
        return True

    def check_network(self) -> bool:
        return self.network

    def build_check(self) -> Callable[[str, Dict[str, Any]], bool]:
        def check(tool_name: str, params: Dict[str, Any]) -> bool:
            if tool_name in _PATH_TOOLS:
                return self.is_allowed_path(params.get("path", ""))
            if tool_name == "run_shell":
                return self.check_command(params.get("command", ""))
            return True

        return check

    def run(
        self,
        command: Union[str, Sequence[str]],
        timeout: Optional[float] = None,
        shell: Optional[bool] = None,
        network: bool = False,
    ) -> RunResult:
        if timeout is None:
            timeout = self.timeout
        if network and not self.check_network():
            return RunResult(error="network access denied by sandbox")
        if not self.check_command(command):
            return RunResult(error="command blocked by sandbox blacklist")
        if shell is None:
            shell = isinstance(command, str)

        popen_kwargs = dict(
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            start_new_session=True,
        )
        if shell:
            proc = subprocess.Popen(command, shell=True, **popen_kwargs)
        else:
            proc = subprocess.Popen(list(command), shell=False, **popen_kwargs)

        self._processes.add(proc)
        try:
            self._apply_process_limits(proc)
            if self.memory_limit is not None:
                self._start_memory_watcher(proc)
            stdout, stderr, timed_out = communicate_with_timeout(proc, timeout)
            return RunResult(
                returncode=proc.returncode,
                stdout=stdout,
                stderr=stderr,
                timed_out=timed_out,
            )
        finally:
            self._processes.discard(proc)

    def active_processes(self) -> int:
        return len(self._processes)

    def close(self) -> None:
        for proc in list(self._processes):
            self._terminate(proc)
            self._processes.discard(proc)

    def __enter__(self) -> "Sandbox":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def _terminate(self, proc: subprocess.Popen) -> None:
        _terminate_process(proc)

    def _apply_process_limits(self, proc: subprocess.Popen) -> None:
        if os.name == "nt":
            try:
                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                handle = kernel32.OpenProcess(_WINDOWS_SET_INFORMATION, False, proc.pid)
                if handle:
                    try:
                        kernel32.SetPriorityClass(handle, _WINDOWS_BELOW_NORMAL)
                    finally:
                        kernel32.CloseHandle(handle)
            except Exception:
                pass
        else:
            try:
                os.setpriority(os.PRIO_PROCESS, proc.pid, 10)
            except (AttributeError, OSError):
                pass

    def _start_memory_watcher(self, proc: subprocess.Popen) -> None:
        def watch() -> None:
            while proc.poll() is None:
                rss = self._sample_rss(proc.pid)
                if rss is not None and rss > self.memory_limit:
                    self._terminate(proc)
                    return
                time.sleep(0.05)

        threading.Thread(target=watch, daemon=True, name="sandbox-memory-watch").start()

    def _sample_rss(self, pid: int) -> Optional[int]:
        try:
            if os.name == "nt":
                return self._sample_rss_windows(pid)
            if os.name == "posix":
                with open(f"/proc/{pid}/statm", encoding="utf-8") as handle:
                    fields = handle.read().split()
                if len(fields) >= 2:
                    return int(fields[1]) * os.sysconf("SC_PAGESIZE")
        except Exception:
            pass
        return None

    @staticmethod
    def _sample_rss_windows(pid: int) -> Optional[int]:
        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            handle = kernel32.OpenProcess(_WINDOWS_QUERY_LIMITED_INFO, False, pid)
            if not handle:
                return None
            try:
                counters = ProcessMemoryCounters()
                counters.cb = ctypes.sizeof(ProcessMemoryCounters)
                if psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                    return int(counters.WorkingSetSize)
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            return None
        return None


def sandbox_check_from(sandbox: Sandbox) -> Callable[[str, Dict[str, Any]], bool]:
    return sandbox.build_check()
