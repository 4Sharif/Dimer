"""File system tools."""

from __future__ import annotations

from pathlib import Path

from dimer.data_context.dimerignore import is_path_ignored
from dimer.safety.permissions import enforce_workspace_path, requires_approval_for_read
from dimer.safety.pii import redact_sensitive_text
from dimer.storage.artifacts import get_workspace_root


def list_files(path: str = ".", workspace: Path | None = None) -> dict:
    ws = get_workspace_root(workspace)
    target = enforce_workspace_path(path, ws)
    if not target.exists():
        raise FileNotFoundError(f"Path not found: {target}")
    if target.is_file():
        return {"path": str(target.relative_to(ws)), "type": "file"}
    entries = []
    for p in sorted(target.iterdir()):
        if p.name.startswith(".") or is_path_ignored(p, ws):
            continue
        entries.append({
            "name": p.name,
            "type": "dir" if p.is_dir() else "file",
            "path": str(p.relative_to(ws)),
        })
    return {"path": str(target.relative_to(ws)), "entries": entries}


def read_file(path: str, workspace: Path | None = None, max_chars: int = 20000) -> dict:
    ws = get_workspace_root(workspace)
    target = enforce_workspace_path(path, ws)
    if requires_approval_for_read(target):
        raise PermissionError(f"Reading {target.name} requires approval")
    if not target.is_file():
        raise FileNotFoundError(f"File not found: {target}")
    content = target.read_text(encoding="utf-8", errors="replace")
    content = redact_sensitive_text(content)
    truncated = len(content) > max_chars
    if truncated:
        content = content[:max_chars]
    return {
        "path": str(target.relative_to(ws)),
        "content": content,
        "truncated": truncated,
    }


def write_file(path: str, content: str, workspace: Path | None = None) -> dict:
    ws = get_workspace_root(workspace)
    target = enforce_workspace_path(path, ws)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {"path": str(target.relative_to(ws)), "bytes_written": len(content.encode("utf-8"))}
