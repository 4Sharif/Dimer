"""Persistent Python execution in a bounded child process."""

from __future__ import annotations

import ast
import io
import multiprocessing
import os
import sys
import threading
import time
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

from dimer.data_context.dimerignore import (
    DimerIgnoreMatcher,
    is_path_ignored,
    load_dimerignore_patterns,
)
from dimer.safety.permissions import is_within_workspace
from dimer.safety.pii import redact_sensitive_text
from dimer.safety.process_limits import truncate_output
from dimer.storage.artifacts import ensure_workspace_dirs, get_dimer_dir, get_workspace_root


_SENSITIVE_ENV_PARTS = (
    "API_KEY",
    "AUTH",
    "COOKIE",
    "CREDENTIAL",
    "PASSWORD",
    "SECRET",
    "TOKEN",
)


class _BoundedTextBuffer(io.TextIOBase):
    """Keep at most ``max_chars`` while accepting normal text-stream writes."""

    def __init__(self, max_chars: int) -> None:
        super().__init__()
        self.max_chars = max(0, max_chars)
        self._parts: list[str] = []
        self._length = 0
        self.truncated = False

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        value = str(text)
        remaining = self.max_chars - self._length
        if remaining > 0:
            kept = value[:remaining]
            self._parts.append(kept)
            self._length += len(kept)
        if len(value) > max(remaining, 0):
            self.truncated = True
        return len(value)

    def rendered(self) -> str:
        value = "".join(self._parts)
        if self.truncated:
            return value + "\n... [truncated]"
        return value


def _detect_risky(code: str) -> list[str]:
    risks: list[str] = []
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return risks
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in ("socket", "urllib", "requests", "httpx", "subprocess"):
                    risks.append(f"network/subprocess import: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.module in ("socket", "urllib", "requests", "httpx", "subprocess"):
                risks.append(f"network/subprocess import: {node.module}")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in ("open", "exec", "eval"):
                risks.append(f"potentially risky call: {node.func.id}")
    return risks


def _is_write_open(mode_or_flags: Any) -> bool:
    if isinstance(mode_or_flags, str):
        return any(flag in mode_or_flags for flag in ("w", "a", "x", "+"))
    if isinstance(mode_or_flags, int):
        write_flags = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
        return bool(mode_or_flags & write_flags)
    return False


def _resolve_audit_path(raw_path: Any, workspace: Path) -> Path:
    target = Path(os.fspath(raw_path)).expanduser()
    if not target.is_absolute():
        target = workspace / target
    return target.resolve(strict=False)


def _enforce_audit_path(
    raw_path: Any,
    *,
    workspace: Path,
    ignore: DimerIgnoreMatcher,
    operation: str,
    allowed_read_roots: tuple[Path, ...] = (),
) -> Path:
    if isinstance(raw_path, int):
        raise PermissionError(
            f"Python {operation} by file descriptor is unavailable in the isolated worker"
        )
    resolved = _resolve_audit_path(raw_path, workspace)
    if is_within_workspace(resolved, workspace):
        if is_path_ignored(resolved, workspace, ignore):
            raise PermissionError(
                f"Python {operation} is ignored by .dimerignore: {resolved}"
            )
        return resolved
    if any(is_within_workspace(resolved, root) for root in allowed_read_roots):
        return resolved
    raise PermissionError(f"Python {operation} is outside the workspace: {resolved}")


def _install_workspace_audit_hook(workspace: Path) -> DimerIgnoreMatcher:
    """Restrict user-code file/process/network access inside the worker."""

    ws = workspace.resolve()
    ignore = DimerIgnoreMatcher(patterns=[])
    allowed_read_roots = (
        Path(sys.prefix).resolve(),
        Path(sys.base_prefix).resolve(),
        Path("/System/Library").resolve(),
        Path("/Library/Fonts").resolve(),
        Path("/usr/share/fonts").resolve(),
    )

    def audit(event: str, args: tuple[Any, ...]) -> None:
        if event == "open" and args:
            raw_path = args[0]
            if isinstance(raw_path, int):
                return
            resolved = _resolve_audit_path(raw_path, ws)
            if resolved == Path("/dev/null"):
                return
            mode_or_flags = args[1] if len(args) > 1 else "r"
            _enforce_audit_path(
                raw_path,
                workspace=ws,
                ignore=ignore,
                operation="file access",
                allowed_read_roots=allowed_read_roots if not _is_write_open(mode_or_flags) else (),
            )

        if event == "os.chdir" and args:
            _enforce_audit_path(
                args[0],
                workspace=ws,
                ignore=ignore,
                operation="working directory",
            )

        if event in {"os.listdir", "os.scandir"} and args and args[0] is not None:
            _enforce_audit_path(
                args[0],
                workspace=ws,
                ignore=ignore,
                operation="directory access",
                allowed_read_roots=allowed_read_roots,
            )

        if event in {"os.mkdir", "os.remove", "os.rmdir", "os.truncate"} and args:
            dir_fd_index = {"os.mkdir": 2, "os.remove": 1, "os.rmdir": 1}.get(event)
            if (
                dir_fd_index is not None
                and len(args) > dir_fd_index
                and args[dir_fd_index] not in {-1, None}
            ):
                raise PermissionError(
                    f"Python {event} by directory descriptor is unavailable in the isolated worker"
                )
            _enforce_audit_path(
                args[0],
                workspace=ws,
                ignore=ignore,
                operation="filesystem mutation",
            )

        if event in {"os.link", "os.rename"} and len(args) >= 2:
            if any(value not in {-1, None} for value in args[2:4]):
                raise PermissionError(
                    f"Python {event} by directory descriptor is unavailable in the isolated worker"
                )
            for raw_path in args[:2]:
                _enforce_audit_path(
                    raw_path,
                    workspace=ws,
                    ignore=ignore,
                    operation=f"{event} target",
                )

        if event in {
            "ctypes.dlopen",
            "ctypes.dlsym",
            "ctypes.dlsym/handle",
            "os.chmod",
            "os.chown",
            "os.exec",
            "os.fork",
            "os.forkpty",
            "os.system",
            "os.posix_spawn",
            "os.spawn",
            "os.symlink",
            "os.utime",
            "pty.spawn",
            "subprocess.Popen",
            "socket.__new__",
            "socket.bind",
            "socket.connect",
            "socket.connect_ex",
        }:
            raise PermissionError(f"Python operation is unavailable in the isolated worker: {event}")

    sys.addaudithook(audit)

    def deny_unaudited_operation(name: str) -> Any:
        def denied(*args: Any, **kwargs: Any) -> None:
            raise PermissionError(
                f"Python operation is unavailable in the isolated worker: {name}"
            )

        return denied

    # CPython does not emit audit events for these filesystem mutations.
    # Patch both public and platform modules inside the disposable worker.
    import posix

    for operation_name in ("mkfifo", "mknod"):
        denied = deny_unaudited_operation(f"os.{operation_name}")
        if hasattr(os, operation_name):
            setattr(os, operation_name, denied)
        if hasattr(posix, operation_name):
            setattr(posix, operation_name, denied)
    return ignore


def _worker_namespace(workspace: Path) -> dict[str, Any]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import pandas as pd

    artifacts = get_dimer_dir(workspace) / "artifacts"
    return {
        "__name__": "__dimer__",
        "__file__": str(workspace),
        "pd": pd,
        "plt": plt,
        "WORKSPACE": str(workspace),
        "ARTIFACTS_DIR": str(artifacts),
        "CHARTS_DIR": str(artifacts / "charts"),
    }


def _execute_in_worker(
    code: str,
    namespace: dict[str, Any],
    workspace: Path,
    max_output_chars: int,
) -> dict[str, Any]:
    risks = _detect_risky(code)
    start = time.perf_counter()
    stdout_buf = _BoundedTextBuffer(max_output_chars)
    stderr_buf = _BoundedTextBuffer(max_output_chars)
    charts_dir = get_dimer_dir(workspace) / "artifacts" / "charts"
    charts_before = set(charts_dir.glob("*.png"))

    try:
        with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
            compiled = compile(code, "<dimer-python>", "exec")
            exec(compiled, namespace)  # noqa: S102
        charts_after = set(charts_dir.glob("*.png"))
        return {
            "stdout": redact_sensitive_text(stdout_buf.rendered()),
            "stderr": redact_sensitive_text(stderr_buf.rendered()),
            "stdout_truncated": stdout_buf.truncated,
            "stderr_truncated": stderr_buf.truncated,
            "return_value_summary": None,
            "created_files": [str(path) for path in sorted(charts_after - charts_before)],
            "execution_time_seconds": round(time.perf_counter() - start, 4),
            "error": None,
            "traceback": None,
            "risk_warnings": risks,
            "timed_out": False,
        }
    except BaseException as exc:
        import traceback

        trace, _ = truncate_output(traceback.format_exc(), max_output_chars)
        return {
            "stdout": redact_sensitive_text(stdout_buf.rendered()),
            "stderr": redact_sensitive_text(stderr_buf.rendered()),
            "stdout_truncated": stdout_buf.truncated,
            "stderr_truncated": stderr_buf.truncated,
            "return_value_summary": None,
            "created_files": [],
            "execution_time_seconds": round(time.perf_counter() - start, 4),
            "error": redact_sensitive_text(str(exc)),
            "traceback": redact_sensitive_text(trace),
            "risk_warnings": risks,
            "timed_out": False,
        }


def _python_worker(connection: Any, workspace_value: str) -> None:
    workspace = Path(workspace_value).resolve()
    os.chdir(workspace)
    for key in list(os.environ):
        upper = key.upper()
        if any(part in upper for part in _SENSITIVE_ENV_PARTS):
            os.environ.pop(key, None)
    try:
        namespace = _worker_namespace(workspace)
        ignore = _install_workspace_audit_hook(workspace)
        connection.send({"ready": True})
        while True:
            request = connection.recv()
            if request.get("command") == "stop":
                return
            ignore.patterns = [str(pattern) for pattern in request.get("ignore_patterns", [])]
            result = _execute_in_worker(
                str(request.get("code", "")),
                namespace,
                workspace,
                int(request.get("max_output_chars", 20000)),
            )
            connection.send(result)
    except EOFError:
        return
    except BaseException as exc:
        try:
            connection.send({"ready": False, "error": str(exc)})
        except Exception:
            pass
    finally:
        connection.close()


class PersistentPythonSession:
    """One persistent, isolated Python worker per workspace."""

    _instances: dict[Path, "PersistentPythonSession"] = {}
    _lock = threading.Lock()

    def __init__(self, workspace: Path | None = None) -> None:
        self.workspace = get_workspace_root(workspace)
        ensure_workspace_dirs(self.workspace)
        self._process: multiprocessing.Process | None = None
        self._connection: Any | None = None

    @classmethod
    def get(cls, workspace: Path | None = None) -> "PersistentPythonSession":
        resolved = get_workspace_root(workspace)
        with cls._lock:
            session = cls._instances.get(resolved)
            if session is None:
                session = cls(resolved)
                cls._instances[resolved] = session
            return session

    @classmethod
    def reset(cls, workspace: Path | None = None) -> None:
        with cls._lock:
            if workspace is None:
                sessions = list(cls._instances.values())
                cls._instances.clear()
            else:
                resolved = get_workspace_root(workspace)
                session = cls._instances.pop(resolved, None)
                sessions = [session] if session is not None else []
        for session in sessions:
            session.close()

    def _start(self) -> None:
        if self._process is not None and self._process.is_alive():
            return
        context = multiprocessing.get_context("spawn")
        parent_connection, child_connection = context.Pipe()
        process = context.Process(
            target=_python_worker,
            args=(child_connection, str(self.workspace)),
            daemon=True,
            name="dimer-python-worker",
        )
        process.start()
        child_connection.close()
        if not parent_connection.poll(30):
            process.terminate()
            process.join(timeout=2)
            parent_connection.close()
            raise RuntimeError("Python worker did not initialize within 30 seconds")
        ready = parent_connection.recv()
        if not ready.get("ready"):
            process.join(timeout=2)
            parent_connection.close()
            raise RuntimeError(f"Python worker failed to initialize: {ready.get('error', 'unknown error')}")
        self._process = process
        self._connection = parent_connection

    def _terminate(self) -> None:
        process = self._process
        connection = self._connection
        self._process = None
        self._connection = None
        if connection is not None:
            connection.close()
        if process is not None and process.is_alive():
            process.terminate()
            process.join(timeout=2)
            if process.is_alive():
                process.kill()
                process.join(timeout=2)

    def close(self) -> None:
        process = self._process
        connection = self._connection
        if process is not None and process.is_alive() and connection is not None:
            try:
                connection.send({"command": "stop"})
                process.join(timeout=1)
            except (BrokenPipeError, EOFError, OSError):
                pass
        self._terminate()

    def execute(
        self,
        code: str,
        timeout_seconds: float = 30,
        max_output_chars: int = 20000,
    ) -> dict[str, Any]:
        self._start()
        assert self._connection is not None
        started = time.perf_counter()
        self._connection.send(
            {
                "command": "execute",
                "code": code,
                "max_output_chars": max_output_chars,
                "ignore_patterns": load_dimerignore_patterns(self.workspace),
            }
        )
        if self._connection.poll(max(0, timeout_seconds)):
            try:
                result = self._connection.recv()
            except EOFError:
                self._terminate()
                return _worker_failure("Python worker exited without returning a result")
            if isinstance(result, dict):
                return result
            return _worker_failure("Python worker returned an invalid result")

        self._terminate()
        elapsed = round(time.perf_counter() - started, 4)
        return {
            "stdout": "",
            "stderr": "Python execution timed out",
            "stdout_truncated": False,
            "stderr_truncated": False,
            "return_value_summary": None,
            "created_files": [],
            "execution_time_seconds": elapsed,
            "error": "timeout",
            "traceback": None,
            "risk_warnings": _detect_risky(code),
            "timed_out": True,
        }


def _worker_failure(message: str) -> dict[str, Any]:
    return {
        "stdout": "",
        "stderr": message,
        "stdout_truncated": False,
        "stderr_truncated": False,
        "return_value_summary": None,
        "created_files": [],
        "execution_time_seconds": 0,
        "error": message,
        "traceback": None,
        "risk_warnings": [],
        "timed_out": False,
    }


def run_python(
    code: str,
    workspace: Path | None = None,
    timeout_seconds: float = 30,
    max_output_chars: int = 20000,
) -> dict[str, Any]:
    session = PersistentPythonSession.get(workspace)
    return session.execute(
        code,
        timeout_seconds=timeout_seconds,
        max_output_chars=max_output_chars,
    )
