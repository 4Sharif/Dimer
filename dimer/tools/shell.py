"""Shell execution tool (restricted for MVP)."""

from __future__ import annotations

import subprocess
import time

from dimer.safety.permissions import is_dangerous_command
from dimer.safety.process_limits import truncate_output


def run_shell(command: str, workspace: str | None = None, timeout_seconds: int = 30, max_output_chars: int = 20000) -> dict:
    if is_dangerous_command(command):
        return {"error": "Dangerous command blocked", "stdout": "", "stderr": "", "exit_code": -1}
    start = time.perf_counter()
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            cwd=workspace,
        )
        stdout, _ = truncate_output(result.stdout, max_output_chars)
        stderr, _ = truncate_output(result.stderr, max_output_chars)
        return {
            "command": command,
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": result.returncode,
            "execution_time_seconds": round(time.perf_counter() - start, 4),
            "error": None,
        }
    except subprocess.TimeoutExpired:
        return {
            "command": command,
            "stdout": "",
            "stderr": "Command timed out",
            "exit_code": -1,
            "execution_time_seconds": timeout_seconds,
            "error": "timeout",
        }
