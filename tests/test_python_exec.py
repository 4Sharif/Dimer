"""Behavioral tests for the isolated Python execution boundary."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from dimer.agent.tool_router import ToolRouter
from dimer.config import DimerConfig, LimitsConfig
from dimer.storage.artifacts import ensure_workspace_dirs
from dimer.tools.python_exec import PersistentPythonSession, run_python


@pytest.fixture(autouse=True)
def reset_python_workers() -> None:
    PersistentPythonSession.reset()
    yield
    PersistentPythonSession.reset()


def test_python_runs_in_a_child_process_rooted_at_workspace(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)

    result = run_python(
        "import os\nfrom pathlib import Path\nprint(os.getpid())\nprint(Path.cwd())",
        workspace=tmp_path,
    )

    lines = result["stdout"].splitlines()
    assert result["error"] is None
    assert int(lines[0]) != os.getpid()
    assert Path(lines[1]) == tmp_path.resolve()


def test_python_namespace_persists_in_the_isolated_worker(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)

    first = run_python("answer = 41", workspace=tmp_path)
    second = run_python("print(answer + 1)", workspace=tmp_path)

    assert first["error"] is None
    assert second["stdout"].strip() == "42"


def test_python_timeout_terminates_worker_and_next_run_recovers(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)

    timed_out = run_python(
        "import time\ntime.sleep(0.15)\nprint('too late')",
        workspace=tmp_path,
        timeout_seconds=0.01,
    )
    recovered = run_python("print('ready')", workspace=tmp_path)

    assert timed_out["error"] == "timeout"
    assert timed_out["timed_out"] is True
    assert "too late" not in timed_out["stdout"]
    assert recovered["error"] is None
    assert recovered["stdout"].strip() == "ready"


def test_python_output_is_bounded_before_returning(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)

    result = run_python("print('x' * 1000)", workspace=tmp_path, max_output_chars=40)

    assert result["stdout_truncated"] is True
    assert len(result["stdout"]) < 80
    assert result["stdout"].endswith("... [truncated]")


def test_python_cannot_access_files_outside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    ensure_workspace_dirs(workspace)
    outside = tmp_path / "outside.txt"
    outside.write_text("private", encoding="utf-8")

    result = run_python(
        f"from pathlib import Path\nprint(Path({str(outside)!r}).read_text())",
        workspace=workspace,
    )

    assert result["error"] is not None
    assert "outside the workspace" in result["error"]
    assert "private" not in result["stdout"]


def test_python_cannot_start_a_shell_process(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)

    result = run_python(
        "import os\nprint(os.system('/usr/bin/true'))",
        workspace=tmp_path,
    )

    assert result["error"] is not None
    assert "unavailable in the isolated worker: os.system" in result["error"]


def test_python_cannot_replace_worker_with_another_process(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)

    result = run_python(
        "import os\nos.execv('/usr/bin/true', ['true'])",
        workspace=tmp_path,
    )

    assert result["error"] is not None
    assert "unavailable in the isolated worker: os.exec" in result["error"]


def test_python_cannot_invoke_processes_through_ctypes(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)

    result = run_python(
        "import ctypes\nctypes.CDLL(None).system(b'/usr/bin/true')",
        workspace=tmp_path,
    )

    assert result["error"] is not None
    assert "unavailable in the isolated worker: ctypes.dlopen" in result["error"]


def test_python_cannot_list_directories_outside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    ensure_workspace_dirs(workspace)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "private.txt").write_text("private", encoding="utf-8")

    result = run_python(
        f"import os\nprint(os.listdir({str(outside)!r}))",
        workspace=workspace,
    )

    assert result["error"] is not None
    assert "outside the workspace" in result["error"]
    assert "private.txt" not in result["stdout"]


def test_python_cannot_scan_directories_outside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    ensure_workspace_dirs(workspace)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "private.txt").write_text("private", encoding="utf-8")

    result = run_python(
        f"from pathlib import Path\nprint(list(Path({str(outside)!r}).iterdir()))",
        workspace=workspace,
    )

    assert result["error"] is not None
    assert "outside the workspace" in result["error"]
    assert "private.txt" not in result["stdout"]


def test_python_cannot_delete_files_outside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    ensure_workspace_dirs(workspace)
    outside = tmp_path / "private.txt"
    outside.write_text("private", encoding="utf-8")

    result = run_python(
        f"from pathlib import Path\nPath({str(outside)!r}).unlink()",
        workspace=workspace,
    )

    assert result["error"] is not None
    assert "outside the workspace" in result["error"]
    assert outside.read_text(encoding="utf-8") == "private"


def test_python_cannot_hard_link_outside_files_into_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    ensure_workspace_dirs(workspace)
    outside = tmp_path / "private.txt"
    outside.write_text("private", encoding="utf-8")

    result = run_python(
        f"import os\nos.link({str(outside)!r}, 'linked.txt')\n"
        "print(open('linked.txt').read())",
        workspace=workspace,
    )

    assert result["error"] is not None
    assert "outside the workspace" in result["error"]
    assert "private" not in result["stdout"]
    assert not (workspace / "linked.txt").exists()


def test_python_cannot_create_network_sockets(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)

    result = run_python(
        "import socket\nsocket.socket()",
        workspace=tmp_path,
    )

    assert result["error"] is not None
    assert "unavailable in the isolated worker: socket.__new__" in result["error"]


def test_python_cannot_rename_files_outside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    ensure_workspace_dirs(workspace)
    source = workspace / "source.txt"
    source.write_text("private", encoding="utf-8")
    outside = tmp_path / "outside.txt"

    result = run_python(
        f"from pathlib import Path\nPath('source.txt').rename({str(outside)!r})",
        workspace=workspace,
    )

    assert result["error"] is not None
    assert "outside the workspace" in result["error"]
    assert source.read_text(encoding="utf-8") == "private"
    assert not outside.exists()


def test_python_cannot_create_directories_outside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    ensure_workspace_dirs(workspace)
    outside = tmp_path / "created-outside"

    result = run_python(
        f"from pathlib import Path\nPath({str(outside)!r}).mkdir()",
        workspace=workspace,
    )

    assert result["error"] is not None
    assert "outside the workspace" in result["error"]
    assert not outside.exists()


def test_python_cannot_create_fifos_outside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    ensure_workspace_dirs(workspace)
    outside = tmp_path / "outside.fifo"

    result = run_python(
        f"import os\nos.mkfifo({str(outside)!r})",
        workspace=workspace,
    )

    assert result["error"] is not None
    assert "unavailable in the isolated worker: os.mkfifo" in result["error"]
    assert not outside.exists()


def test_python_cannot_access_dimerignored_files(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)
    ignored = tmp_path / "private" / "secret.txt"
    ignored.parent.mkdir()
    ignored.write_text("not for Dimer", encoding="utf-8")
    (tmp_path / ".dimerignore").write_text("private/\n", encoding="utf-8")

    result = run_python(
        "from pathlib import Path\nprint(Path('private/secret.txt').read_text())",
        workspace=tmp_path,
    )

    assert result["error"] is not None
    assert "ignored by .dimerignore" in result["error"]
    assert "not for Dimer" not in result["stdout"]


def test_persistent_python_worker_reloads_dimerignore_between_runs(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)
    private_file = tmp_path / "private.txt"
    private_file.write_text("initially visible", encoding="utf-8")

    first = run_python("from pathlib import Path\nprint(Path('private.txt').read_text())", workspace=tmp_path)
    (tmp_path / ".dimerignore").write_text("private.txt\n", encoding="utf-8")
    second = run_python("print(Path('private.txt').read_text())", workspace=tmp_path)

    assert first["error"] is None
    assert second["error"] is not None
    assert "ignored by .dimerignore" in second["error"]


def test_tool_router_enforces_configured_timeout_over_model_argument(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)
    config = DimerConfig(limits=LimitsConfig(timeout_seconds=1, max_output_chars=200))
    router = ToolRouter(tmp_path, config)

    response = router.execute(
        "run_python",
        {"code": "import time\ntime.sleep(1.2)", "timeout_seconds": 30},
        auto_approve=True,
    )

    assert response["success"] is False
    assert response["error"] == "timeout"
    assert response["result"]["timed_out"] is True


def test_python_output_redacts_secret_values(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)

    result = run_python(
        "print('OPENAI_API_KEY=sk-supersecretvalue123456')",
        workspace=tmp_path,
    )

    assert "sk-supersecretvalue123456" not in result["stdout"]
    assert "[REDACTED_SECRET]" in result["stdout"]
