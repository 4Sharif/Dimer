"""Scan workspace for data-relevant files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dimer.data_context.dimerignore import DimerIgnoreMatcher, is_path_ignored

DATASET_EXTS = {".csv", ".xlsx", ".xls", ".parquet"}
NOTEBOOK_EXTS = {".ipynb"}


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
        rel = str(path.relative_to(workspace))
        ext = path.suffix.lower()
        if ext in DATASET_EXTS:
            result["datasets"].append(rel)
        elif ext in NOTEBOOK_EXTS:
            result["notebooks"].append(rel)
        elif ext == ".sql":
            result["sql_files"].append(rel)
        elif ext == ".py":
            result["python_files"].append(rel)
        elif ext == ".md" and not rel.startswith(".dimer"):
            result["markdown_files"].append(rel)
        elif ".dimer/artifacts" in rel:
            result["artifacts"].append(rel)

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
