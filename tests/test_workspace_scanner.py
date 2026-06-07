"""Tests for workspace scanner and .dimerignore."""

from __future__ import annotations

import json
from pathlib import Path

from dimer.data_context.dimerignore import DimerIgnoreMatcher, ensure_dimerignore
from dimer.data_context.workspace_scanner import compact_workspace_summary, scan_workspace


def test_dimerignore_excludes_directory(tmp_path: Path) -> None:
    agents = tmp_path / "agents" / "codex"
    agents.mkdir(parents=True)
    (agents / "migration.sql").write_text("SELECT 1", encoding="utf-8")
    data = tmp_path / "examples"
    data.mkdir()
    (data / "sales.csv").write_text("a,b\n1,2", encoding="utf-8")

    (tmp_path / ".dimerignore").write_text("agents/\n", encoding="utf-8")
    scan = scan_workspace(tmp_path)
    assert scan["datasets"] == ["examples/sales.csv"]
    assert scan["sql_files"] == []


def test_without_dimerignore_includes_agents_sql(tmp_path: Path) -> None:
    agents = tmp_path / "agents"
    agents.mkdir()
    (agents / "query.sql").write_text("SELECT 1", encoding="utf-8")

    scan = scan_workspace(tmp_path)
    assert "agents/query.sql" in scan["sql_files"]


def test_compact_workspace_summary_is_small(tmp_path: Path) -> None:
    agents = tmp_path / "agents" / "codex"
    agents.mkdir(parents=True)
    for i in range(200):
        (agents / f"file_{i}.sql").write_text("SELECT 1", encoding="utf-8")
    (tmp_path / "sales.csv").write_text("a,b\n1,2", encoding="utf-8")
    (tmp_path / ".dimerignore").write_text("agents/\n", encoding="utf-8")

    summary = compact_workspace_summary(tmp_path)
    text = json.dumps(summary)
    assert len(text) < 2000
    assert summary["counts"]["datasets"] == 1
    assert summary["counts"]["sql_files"] == 0


def test_dimerignore_wildcard(tmp_path: Path) -> None:
    (tmp_path / "notes.md").write_text("# hi", encoding="utf-8")
    (tmp_path / "data.csv").write_text("a\n1", encoding="utf-8")
    (tmp_path / ".dimerignore").write_text("*.md\n", encoding="utf-8")

    scan = scan_workspace(tmp_path)
    assert scan["datasets"] == ["data.csv"]
    assert scan["markdown_files"] == []


def test_ensure_dimerignore_creates_template(tmp_path: Path) -> None:
    path = ensure_dimerignore(tmp_path)
    assert path.exists()
    assert "agents/" in path.read_text(encoding="utf-8")


def test_dimerignore_matcher_negation(tmp_path: Path) -> None:
    matcher = DimerIgnoreMatcher(["agents/", "!agents/keep.sql"], workspace=tmp_path)
    assert matcher.is_ignored("agents/other.sql") is True
    assert matcher.is_ignored("agents/keep.sql") is False
