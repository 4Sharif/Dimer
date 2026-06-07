"""Session persistence."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dimer.storage.artifacts import get_dimer_dir


def _session_path(session_id: str, workspace: Path | None = None) -> Path:
    return get_dimer_dir(workspace) / "sessions" / f"{session_id}.json"


def new_session_id() -> str:
    return datetime.now(timezone.utc).strftime("session-%Y%m%d-%H%M%S")


def save_session(session_id: str, data: dict[str, Any], workspace: Path | None = None) -> Path:
    path = _session_path(session_id, workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return path


def load_session(session_id: str, workspace: Path | None = None) -> dict[str, Any]:
    path = _session_path(session_id, workspace)
    return json.loads(path.read_text(encoding="utf-8"))
