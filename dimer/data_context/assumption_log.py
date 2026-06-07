"""Assumption tracking."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from dimer.storage.artifacts import get_dimer_dir


class Assumption(BaseModel):
    id: str
    text: str
    source: str | None = None
    confidence: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AssumptionLog:
    def __init__(self, workspace: Path | None = None) -> None:
        self.workspace = workspace
        self._path = get_dimer_dir(workspace) / "assumptions.jsonl"
        self._md_path = get_dimer_dir(workspace) / "assumptions.md"

    def record(self, text: str, source: str | None = None, confidence: str | None = None) -> Assumption:
        assumption = Assumption(
            id=f"asm-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}",
            text=text,
            source=source,
            confidence=confidence,
        )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as f:
            f.write(assumption.model_dump_json() + "\n")
        with self._md_path.open("a", encoding="utf-8") as f:
            conf = f" (confidence: {confidence})" if confidence else ""
            src = f" [source: {source}]" if source else ""
            f.write(f"- {assumption.text}{conf}{src}\n")
        return assumption

    def list_all(self) -> list[Assumption]:
        if not self._path.exists():
            return []
        items = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                items.append(Assumption.model_validate_json(line))
        return items
