"""Notebook reader tool."""

from __future__ import annotations

from pathlib import Path

from dimer.data_context.notebook_context import format_notebook_summary, read_notebook, summarize_notebook


def read_notebook_tool(path: str) -> dict:
    return read_notebook(path)


def summarize_notebook_tool(path: str) -> dict:
    summary = summarize_notebook(path)
    summary["markdown"] = format_notebook_summary(summary)
    return summary


def resolve_notebook_path(path: str, workspace: Path | None = None) -> Path:
    candidate = Path(path)
    if candidate.is_absolute() and candidate.exists():
        return candidate
    if workspace is not None:
        ws_candidate = (workspace / path).resolve()
        if ws_candidate.exists():
            return ws_candidate
    if candidate.exists():
        return candidate.resolve()
    raise FileNotFoundError(f"Notebook not found: {path}")
