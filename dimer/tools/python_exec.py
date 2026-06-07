"""Persistent Python execution session."""

from __future__ import annotations

import ast
import io
import sys
import threading
import time
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

from dimer.safety.process_limits import truncate_output
from dimer.storage.artifacts import get_dimer_dir, get_workspace_root


class PersistentPythonSession:
    """Single persistent Python namespace across tool invocations."""

    _instance: "PersistentPythonSession | None" = None
    _lock = threading.Lock()

    def __init__(self, workspace: Path | None = None) -> None:
        self.workspace = get_workspace_root(workspace)
        self.namespace: dict[str, Any] = {
            "__name__": "__dimer__",
            "__file__": str(self.workspace),
        }
        self._inject_helpers()

    @classmethod
    def get(cls, workspace: Path | None = None) -> "PersistentPythonSession":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(workspace)
            return cls._instance

    @classmethod
    def reset(cls) -> None:
        with cls._lock:
            cls._instance = None

    def _inject_helpers(self) -> None:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import pandas as pd

        artifacts = get_dimer_dir(self.workspace) / "artifacts"
        self.namespace.update({
            "pd": pd,
            "plt": plt,
            "WORKSPACE": str(self.workspace),
            "ARTIFACTS_DIR": str(artifacts),
            "CHARTS_DIR": str(artifacts / "charts"),
        })

    def _detect_risky(self, code: str) -> list[str]:
        risks = []
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

    def execute(self, code: str, timeout_seconds: int = 30, max_output_chars: int = 20000) -> dict[str, Any]:
        risks = self._detect_risky(code)
        start = time.perf_counter()
        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        created_files: list[str] = []
        charts_before = set((get_dimer_dir(self.workspace) / "artifacts" / "charts").glob("*.png"))

        try:
            with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
                compiled = compile(code, "<dimer-python>", "exec")
                exec(compiled, self.namespace)  # noqa: S102

            charts_after = set((get_dimer_dir(self.workspace) / "artifacts" / "charts").glob("*.png"))
            created_files = [str(p) for p in charts_after - charts_before]

            stdout, stdout_trunc = truncate_output(stdout_buf.getvalue(), max_output_chars)
            stderr, stderr_trunc = truncate_output(stderr_buf.getvalue(), max_output_chars)
            elapsed = time.perf_counter() - start

            return {
                "stdout": stdout,
                "stderr": stderr,
                "stdout_truncated": stdout_trunc,
                "stderr_truncated": stderr_trunc,
                "return_value_summary": None,
                "created_files": created_files,
                "execution_time_seconds": round(elapsed, 4),
                "error": None,
                "traceback": None,
                "risk_warnings": risks,
            }
        except Exception as e:
            import traceback

            elapsed = time.perf_counter() - start
            tb = traceback.format_exc()
            stdout, _ = truncate_output(stdout_buf.getvalue(), max_output_chars)
            stderr, _ = truncate_output(stderr_buf.getvalue(), max_output_chars)
            return {
                "stdout": stdout,
                "stderr": stderr,
                "stdout_truncated": False,
                "stderr_truncated": False,
                "return_value_summary": None,
                "created_files": created_files,
                "execution_time_seconds": round(elapsed, 4),
                "error": str(e),
                "traceback": tb,
                "risk_warnings": risks,
            }


def run_python(
    code: str,
    workspace: Path | None = None,
    timeout_seconds: int = 30,
    max_output_chars: int = 20000,
) -> dict[str, Any]:
    session = PersistentPythonSession.get(workspace)
    return session.execute(code, timeout_seconds=timeout_seconds, max_output_chars=max_output_chars)
