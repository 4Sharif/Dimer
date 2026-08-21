"""Tests for privacy and permissions."""

from __future__ import annotations

from pathlib import Path

import pytest

from dimer.agent.tool_router import ToolRouter
from dimer.safety.permissions import is_within_workspace, requires_approval_for_read
from dimer.safety.pii import redact_text
from dimer.storage.artifacts import ensure_workspace_dirs
from dimer.tools.files import list_files, read_file, write_file
from dimer.tools.report import record_assumption, save_report


def test_privacy_redacts_email() -> None:
    text = "Contact user@example.com for details"
    redacted = redact_text(text)
    assert "user@example.com" not in redacted
    assert "[REDACTED_EMAIL]" in redacted


def test_permissions_blocks_path_escape(tmp_path: Path) -> None:
    ws = tmp_path / "workspace"
    ws.mkdir()
    inside = ws / "data.csv"
    inside.touch()
    outside = tmp_path / "outside.csv"
    outside.touch()
    assert is_within_workspace(inside, ws) is True
    assert is_within_workspace(outside, ws) is False


def test_requires_approval_for_env() -> None:
    assert requires_approval_for_read(Path(".env")) is True
    assert requires_approval_for_read(Path("data.csv")) is False


def test_file_tools_apply_dimerignore_consistently(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)
    ignored = tmp_path / "private"
    ignored.mkdir()
    (ignored / "notes.txt").write_text("not for Dimer", encoding="utf-8")
    (tmp_path / ".dimerignore").write_text("private/\n", encoding="utf-8")

    listing = list_files(".", tmp_path)

    assert "private" not in {entry["name"] for entry in listing["entries"]}
    with pytest.raises(PermissionError, match="ignored by .dimerignore"):
        read_file("private/notes.txt", tmp_path)
    with pytest.raises(PermissionError, match="ignored by .dimerignore"):
        write_file("private/output.txt", "no", tmp_path)


def test_explicit_dimerignore_pattern_can_hide_artifact_subpaths(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)
    (tmp_path / ".dimerignore").write_text(".dimer/artifacts/private/\n", encoding="utf-8")

    with pytest.raises(PermissionError, match="ignored by .dimerignore"):
        write_file(".dimer/artifacts/private/output.txt", "no", tmp_path)


def test_data_and_report_tools_cannot_bypass_workspace_policy(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)
    ignored = tmp_path / "ignored"
    ignored.mkdir()
    dataset = ignored / "data.csv"
    dataset.write_text("value\n1\n", encoding="utf-8")
    notebook = ignored / "analysis.ipynb"
    notebook.write_text('{"nbformat": 4, "nbformat_minor": 5, "metadata": {}, "cells": []}', encoding="utf-8")
    (tmp_path / ".dimerignore").write_text("ignored/\n", encoding="utf-8")
    outside_report = tmp_path.parent / "outside-report.md"
    router = ToolRouter(tmp_path)

    profile_result = router.execute(
        "inspect_dataset",
        {"path": str(dataset)},
    )
    report_result = router.execute(
        "save_report",
        {"path": str(outside_report), "markdown_content": "# no"},
        auto_approve=True,
    )
    sql_result = router.execute(
        "run_duckdb_query",
        {"query": "SELECT * FROM data", "data_paths": [str(dataset)]},
    )
    notebook_result = router.execute(
        "summarize_notebook",
        {"path": str(notebook)},
    )

    assert profile_result["success"] is False
    assert "ignored by .dimerignore" in profile_result["error"]
    assert sql_result["success"] is False
    assert "ignored by .dimerignore" in sql_result["error"]
    assert notebook_result["success"] is False
    assert "ignored by .dimerignore" in notebook_result["error"]
    assert report_result["success"] is False
    assert "outside workspace" in report_result["error"]
    assert not outside_report.exists()


def test_read_file_redacts_embedded_credentials(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)
    (tmp_path / "notes.txt").write_text(
        "temporary token=secret-file-token",
        encoding="utf-8",
    )

    result = read_file("notes.txt", tmp_path)

    assert "secret-file-token" not in result["content"]
    assert "[REDACTED_SECRET]" in result["content"]


def test_reports_and_assumptions_redact_secrets_before_writing(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)
    secret = "sk-supersecretvalue123456"

    report = save_report("report.md", f"# Finding\n\ntoken={secret}", workspace=tmp_path)
    record_assumption(f"token={secret}", workspace=tmp_path)

    persisted = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in (tmp_path / ".dimer").rglob("*")
        if path.is_file()
    )
    assert secret not in persisted
    assert "[REDACTED_SECRET]" in Path(report["path"]).read_text(encoding="utf-8")
