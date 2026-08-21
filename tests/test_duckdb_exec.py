"""Tests for DuckDB execution."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from dimer.agent.tool_router import ToolRouter
from dimer.config import DimerConfig, LimitsConfig
from dimer.storage.artifacts import ensure_workspace_dirs
from dimer.tools.duckdb_exec import run_duckdb_query


def test_duckdb_query_preview(tmp_path: Path) -> None:
    df = pd.DataFrame({"region": ["North", "West", "East"], "revenue": [100, 200, 150]})
    path = tmp_path / "sales.csv"
    df.to_csv(path, index=False)
    result = run_duckdb_query(
        "SELECT region, SUM(revenue) AS total FROM sales GROUP BY region ORDER BY total DESC",
        data_paths=[str(path)],
        max_rows=10,
    )
    assert result["error"] is None
    assert result["row_count"] == 3
    assert "region" in result["column_names"]
    assert len(result["preview_rows"]) == 3


def test_model_visible_duckdb_blocks_write_statements(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)
    target = tmp_path / "should-not-exist.csv"
    router = ToolRouter(tmp_path)

    response = router.execute(
        "run_duckdb_query",
        {"query": f"COPY (SELECT 1 AS value) TO '{target}'"},
    )

    assert response["success"] is False
    assert "read-only" in response["error"]
    assert not target.exists()


def test_model_visible_duckdb_blocks_unregistered_file_reads(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    ensure_workspace_dirs(workspace)
    outside = tmp_path / "outside.csv"
    outside.write_text("value\n1\n", encoding="utf-8")
    router = ToolRouter(workspace)

    response = router.execute(
        "run_duckdb_query",
        {"query": f"SELECT * FROM read_csv_auto('{outside}')"},
    )

    assert response["success"] is False
    assert "registered workspace tables" in response["error"]


def test_model_visible_duckdb_blocks_generic_table_function_reads(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    ensure_workspace_dirs(workspace)
    outside = tmp_path / "outside.txt"
    outside.write_text("private", encoding="utf-8")

    response = ToolRouter(workspace).execute(
        "run_duckdb_query",
        {"query": f"SELECT content FROM read_text('{outside}')"},
    )

    assert response["success"] is False
    assert "registered workspace tables" in response["error"]
    assert "not for Dimer" not in str(response)


def test_model_visible_duckdb_blocks_quoted_table_function_reads(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    ensure_workspace_dirs(workspace)
    outside = tmp_path / "outside.txt"
    outside.write_text("not for Dimer", encoding="utf-8")

    response = ToolRouter(workspace).execute(
        "run_duckdb_query",
        {"query": f'SELECT content FROM "read_text"(\'{outside}\')'},
    )

    assert response["success"] is False
    assert "registered workspace tables" in response["error"]
    assert "not for Dimer" not in str(response)


def test_model_visible_duckdb_blocks_comma_joined_table_functions(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    ensure_workspace_dirs(workspace)
    outside = tmp_path / "outside.txt"
    outside.write_text("not for Dimer", encoding="utf-8")

    response = ToolRouter(workspace).execute(
        "run_duckdb_query",
        {
            "query": (
                "SELECT content FROM (VALUES (1)) t(x), "
                f"read_text('{outside}')"
            )
        },
    )

    assert response["success"] is False
    assert "registered workspace tables" in response["error"]
    assert "not for Dimer" not in str(response)


def test_model_visible_duckdb_allows_nested_scalar_functions(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)

    response = ToolRouter(tmp_path).execute(
        "run_duckdb_query",
        {"query": "SELECT COALESCE(NULL, ABS(-1)) AS value"},
    )

    assert response["success"] is True
    assert response["result"]["preview_rows"] == [{"value": 1}]


def test_duckdb_guard_preserves_line_comment_markers_inside_literals(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    ensure_workspace_dirs(workspace)
    outside = tmp_path / "outside.txt"
    outside.write_text("not for Dimer", encoding="utf-8")

    response = ToolRouter(workspace).execute(
        "run_duckdb_query",
        {"query": f"SELECT '--' AS marker, content FROM read_text('{outside}')"},
    )

    assert response["success"] is False
    assert "registered workspace tables" in response["error"]
    assert "not for Dimer" not in str(response)


def test_duckdb_guard_preserves_block_comment_markers_inside_literals(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    ensure_workspace_dirs(workspace)
    outside = tmp_path / "outside.txt"
    outside.write_text("not for Dimer", encoding="utf-8")

    response = ToolRouter(workspace).execute(
        "run_duckdb_query",
        {
            "query": (
                f"SELECT '/*' AS marker, content FROM read_text('{outside}') "
                "/* actual comment */"
            )
        },
    )

    assert response["success"] is False
    assert "registered workspace tables" in response["error"]
    assert "not for Dimer" not in str(response)


def test_model_visible_duckdb_allows_real_sql_comments(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)

    response = ToolRouter(tmp_path).execute(
        "run_duckdb_query",
        {"query": "SELECT 1 /* bounded query */ AS value -- trailing comment"},
    )

    assert response["success"] is True
    assert response["result"]["preview_rows"] == [{"value": 1}]


def test_model_visible_duckdb_rejects_secret_literals_before_persistence(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)
    secret = "sk-supersecretvalue123456"

    response = ToolRouter(tmp_path).execute(
        "run_duckdb_query",
        {"query": f"SELECT '{secret}' AS token"},
    )

    assert response["success"] is False
    assert "secret" in response["error"].lower()
    assert secret not in str(response)
    persisted = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in (tmp_path / ".dimer").rglob("*")
        if path.is_file()
    )
    assert secret not in persisted


def test_model_visible_duckdb_enforces_configured_preview_limit(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)
    path = tmp_path / "sales.csv"
    path.write_text("value\n1\n2\n3\n4\n", encoding="utf-8")
    config = DimerConfig(limits=LimitsConfig(max_preview_rows=2))
    router = ToolRouter(tmp_path, config)

    response = router.execute(
        "run_duckdb_query",
        {
            "query": "SELECT * FROM sales ORDER BY value",
            "data_paths": [str(path)],
            "max_rows": 1000,
        },
    )

    assert response["success"] is True
    assert len(response["result"]["preview_rows"]) == 2
    assert response["result"]["truncated"] is True
