"""DuckDB query execution."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import duckdb


def _table_name(path: Path) -> str:
    return path.stem.replace("-", "_").replace(" ", "_")


def run_duckdb_query(
    query: str,
    data_paths: list[str] | None = None,
    max_rows: int = 50,
) -> dict[str, Any]:
    start = time.perf_counter()
    con = duckdb.connect()
    paths = [Path(p).resolve() for p in (data_paths or [])]

    try:
        for p in paths:
            if not p.exists():
                raise FileNotFoundError(f"Data file not found: {p}")
            ext = p.suffix.lower()
            tbl = _table_name(p)
            path_literal = str(p).replace("'", "''")
            if ext == ".csv":
                con.execute(f"CREATE OR REPLACE VIEW {tbl} AS SELECT * FROM read_csv_auto('{path_literal}')")
            elif ext == ".parquet":
                con.execute(f"CREATE OR REPLACE VIEW {tbl} AS SELECT * FROM read_parquet('{path_literal}')")
            else:
                raise ValueError(f"Unsupported data file for DuckDB: {ext}")

        result = con.execute(query)
        columns = [d[0] for d in result.description] if result.description else []
        rows = result.fetchmany(max_rows + 1)
        truncated = len(rows) > max_rows
        if truncated:
            rows = rows[:max_rows]
        preview = [dict(zip(columns, row)) for row in rows]
        elapsed = time.perf_counter() - start

        count_result = None
        try:
            count_result = con.execute(f"SELECT COUNT(*) FROM ({query}) AS _q").fetchone()
        except duckdb.Error:
            pass

        return {
            "query": query,
            "row_count": count_result[0] if count_result else len(preview),
            "column_names": columns,
            "preview_rows": preview,
            "truncated": truncated,
            "execution_time_seconds": round(elapsed, 4),
            "error": None,
        }
    except Exception as e:
        elapsed = time.perf_counter() - start
        return {
            "query": query,
            "row_count": 0,
            "column_names": [],
            "preview_rows": [],
            "truncated": False,
            "execution_time_seconds": round(elapsed, 4),
            "error": str(e),
        }
    finally:
        con.close()
