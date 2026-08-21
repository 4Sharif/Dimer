"""Scan workspace for data-relevant files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dimer.data_context.dimerignore import DimerIgnoreMatcher, is_path_ignored

DATASET_EXTS = {".csv", ".xlsx", ".xls", ".parquet"}
NOTEBOOK_EXTS = {".ipynb"}
DUCKDB_EXTS = {".csv", ".parquet"}


def scan_workspace(root: Path | None = None, matcher: DimerIgnoreMatcher | None = None) -> dict[str, Any]:
    workspace = (root or Path.cwd()).resolve()
    ignore = matcher or DimerIgnoreMatcher(workspace=workspace)
    result: dict[str, list[str]] = {
        "datasets": [],
        "notebooks": [],
        "sql_files": [],
        "python_files": [],
        "markdown_files": [],
        "artifacts": [],
    }

    if not workspace.exists():
        return {"workspace": str(workspace), **result}

    for path in workspace.rglob("*"):
        if not path.is_file() or is_path_ignored(path, workspace, ignore):
            continue
        rel = str(path.relative_to(workspace)).replace("\\", "/")
        ext = path.suffix.lower()
        if rel.startswith(".dimer/artifacts/"):
            result["artifacts"].append(rel)
        elif ext in DATASET_EXTS:
            result["datasets"].append(rel)
        elif ext in NOTEBOOK_EXTS:
            result["notebooks"].append(rel)
        elif ext == ".sql":
            result["sql_files"].append(rel)
        elif ext == ".py":
            result["python_files"].append(rel)
        elif ext == ".md" and not rel.startswith(".dimer"):
            result["markdown_files"].append(rel)

    for key in result:
        result[key] = sorted(result[key])
    return {"workspace": str(workspace), **result}


def compact_workspace_summary(
    root: Path | None = None,
    max_sample_paths: int = 5,
    matcher: DimerIgnoreMatcher | None = None,
) -> dict[str, Any]:
    """Compact scan for agent context — counts and a few sample paths only."""
    scan = scan_workspace(root, matcher=matcher)
    counts: dict[str, int] = {}
    samples: dict[str, list[str]] = {}
    for key in ("datasets", "notebooks", "sql_files", "python_files", "markdown_files", "artifacts"):
        items = scan.get(key, [])
        counts[key] = len(items)
        samples[key] = items[:max_sample_paths]
    return {
        "workspace": scan["workspace"],
        "counts": counts,
        "samples": samples,
    }


def list_duckdb_dataset_paths(root: Path | None = None, matcher: DimerIgnoreMatcher | None = None) -> list[str]:
    """Absolute CSV/Parquet paths in the workspace for DuckDB registration."""
    workspace = (root or Path.cwd()).resolve()
    scan = scan_workspace(workspace, matcher=matcher)
    paths: list[str] = []
    for rel in scan.get("datasets", []):
        path = (workspace / rel).resolve()
        if path.suffix.lower() in DUCKDB_EXTS and path.exists():
            paths.append(str(path))
    return paths


def duckdb_table_catalog(root: Path | None = None, matcher: DimerIgnoreMatcher | None = None) -> list[dict[str, str]]:
    """Map file stems (DuckDB view names) to dataset paths."""
    catalog: list[dict[str, str]] = []
    for path_str in list_duckdb_dataset_paths(root, matcher=matcher):
        path = Path(path_str)
        table = path.stem.replace("-", "_").replace(" ", "_")
        catalog.append({"table": table, "path": path_str})
    return catalog
