"""Status strip helpers for interactive chat."""

from __future__ import annotations

from pathlib import Path


def format_status_strip(
    *,
    provider: str,
    model: str | None = None,
    dataset: str | None = None,
    session_id: str | None = None,
    notebook: str | None = None,
    approvals: str | None = None,
) -> str:
    """Return a single-line status strip for interactive chat."""
    parts = [
        f"provider={provider}",
        f"model={model or 'default'}",
        f"dataset={_short_path(dataset)}",
        f"session={session_id or 'none'}",
    ]
    if notebook:
        parts.append(f"notebook={_short_path(notebook)}")
    if approvals:
        parts.append(f"approvals={approvals}")
    return " | ".join(parts)


def _short_path(path: str | None) -> str:
    if not path:
        return "none"
    return Path(path).name
