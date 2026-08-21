"""Tests for deterministic SQL session export."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dimer.cli import app
from dimer.data_context.artifact_registry import ArtifactRegistry
from dimer.pipeline.export_session import export_session
from dimer.storage.artifacts import ensure_workspace_dirs
from dimer.storage.sessions import save_session
from dimer.ui.session_controller import SessionController


def _save_sql_session(
    workspace: Path,
    session_id: str,
    data_path: Path,
) -> None:
    query = (
        "SELECT region, SUM(revenue) AS total "
        "FROM sales GROUP BY region ORDER BY total DESC"
    )
    successful = {
        "tool_name": "run_duckdb_query",
        "success": True,
        "arguments": {"query": query, "data_paths": [str(data_path)]},
    }
    save_session(
        session_id,
        {
            "question": "Which region contributed most revenue?",
            "assumptions": ["Revenue is additive."],
            "tool_results": [
                successful,
                {**successful, "duplicate": True},
                successful,
                {
                    "tool_name": "run_duckdb_query",
                    "success": False,
                    "arguments": {
                        "query": "SELECT missing FROM sales",
                        "data_paths": [str(data_path)],
                    },
                },
            ],
        },
        workspace,
    )


def test_export_session_creates_verified_runnable_script(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)
    data_path = tmp_path / "sales.csv"
    data_path.write_text("region,revenue\nWest,10\nEast,4\n", encoding="utf-8")
    session_id = "session-20260715-200000"
    _save_sql_session(tmp_path, session_id, data_path)

    result = export_session(session_id, tmp_path)

    assert result.verified is True
    assert result.query_count == 1
    assert result.script_path.exists()
    assert result.manifest_path.exists()
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert "mode" not in manifest
    assert manifest["sources"][0]["table_name"] == "sales"
    assert manifest["sources"][0]["schema_fingerprint"]
    assert manifest["queries"][0]["query"].startswith("SELECT region")

    replay = subprocess.run(
        [sys.executable, str(result.script_path)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )
    assert replay.returncode == 0
    assert "West" in replay.stdout

    scripts = ArtifactRegistry(tmp_path).list_filtered(
        artifact_type="script",
        session_id=session_id,
        limit=None,
    )
    assert len(scripts) == 1
    assert scripts[0].metadata["verified"] is True


def test_export_latest_session_and_chat_command(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)
    data_path = tmp_path / "sales.csv"
    data_path.write_text("region,revenue\nWest,10\n", encoding="utf-8")
    session_id = "session-20260715-210000"
    _save_sql_session(tmp_path, session_id, data_path)

    controller = SessionController(tmp_path)
    slash_result = controller.handle_slash("/export")

    assert slash_result.status_changed is True
    assert controller.last_session_id == session_id
    assert any("Script exported to" in line for line in slash_result.lines)
    assert any("Verified 1 SQL query replay" in line for line in slash_result.lines)


def test_export_cli_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ensure_workspace_dirs(tmp_path)
    data_path = tmp_path / "sales.csv"
    data_path.write_text("region,revenue\nWest,10\n", encoding="utf-8")
    session_id = "session-20260715-213000"
    _save_sql_session(tmp_path, session_id, data_path)
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(app, ["export", session_id])

    assert result.exit_code == 0
    assert "Script exported to" in result.stdout
    assert "Verified 1 SQL query" in result.stdout


def test_export_session_rejects_session_without_successful_sql(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)
    session_id = "session-20260715-220000"
    save_session(
        session_id,
        {
            "question": "Describe this data",
            "tool_results": [{"tool_name": "profile_dataset", "success": True}],
        },
        tmp_path,
    )

    with pytest.raises(ValueError, match="no successful DuckDB queries"):
        export_session(session_id, tmp_path)

    scripts_dir = tmp_path / ".dimer" / "artifacts" / "scripts"
    assert list(scripts_dir.iterdir()) == []


def test_export_session_records_missing_source_warning(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)
    missing = tmp_path / "missing.csv"
    session_id = "session-20260715-230000"
    _save_sql_session(tmp_path, session_id, missing)

    result = export_session(session_id, tmp_path)

    assert result.verified is False
    assert result.script_path.exists()
    assert any("missing" in warning.lower() for warning in result.warnings)
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["verified"] is False
    assert manifest["sources"][0]["exists"] is False
