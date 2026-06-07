"""Tests for DuckDB execution."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

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
