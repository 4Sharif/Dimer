"""Workspace directory management."""

from __future__ import annotations

from pathlib import Path

from dimer.data_context.dimerignore import ensure_dimerignore

DIMER_DIR = ".dimer"

SUBDIRS = [
    "sessions",
    "artifacts/charts",
    "artifacts/reports",
    "artifacts/queries",
    "artifacts/scripts",
    "artifacts/logs",
    "profiles",
    "cache",
]


def get_workspace_root(cwd: Path | None = None) -> Path:
    return (cwd or Path.cwd()).resolve()


def get_dimer_dir(workspace: Path | None = None) -> Path:
    return get_workspace_root(workspace) / DIMER_DIR


def ensure_workspace_dirs(workspace: Path | None = None) -> Path:
    dimer_dir = get_dimer_dir(workspace)
    for sub in SUBDIRS:
        (dimer_dir / sub).mkdir(parents=True, exist_ok=True)
    assumptions = dimer_dir / "assumptions.md"
    if not assumptions.exists():
        assumptions.write_text("# Dimer Assumptions\n\n", encoding="utf-8")
    state = dimer_dir / "analysis_state.jsonl"
    if not state.exists():
        state.touch()
    ensure_dimerignore(workspace)
    return dimer_dir
