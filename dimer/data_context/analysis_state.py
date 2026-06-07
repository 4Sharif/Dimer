"""Analysis state event tracking."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from dimer.storage.artifacts import get_dimer_dir


class AnalysisEvent(BaseModel):
    id: str
    event_type: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = None
    tool_source: str | None = None
    artifact_paths: list[str] = Field(default_factory=list)


class AnalysisState:
    def __init__(self, workspace: Path | None = None) -> None:
        self.workspace = workspace
        self._path = get_dimer_dir(workspace) / "analysis_state.jsonl"

    def record(
        self,
        event_type: str,
        inputs: dict[str, Any] | None = None,
        outputs: dict[str, Any] | None = None,
        reason: str | None = None,
        tool_source: str | None = None,
        artifact_paths: list[str] | None = None,
    ) -> AnalysisEvent:
        event = AnalysisEvent(
            id=f"evt-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}",
            event_type=event_type,
            inputs=inputs or {},
            outputs=outputs or {},
            reason=reason,
            tool_source=tool_source,
            artifact_paths=artifact_paths or [],
        )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as f:
            f.write(event.model_dump_json() + "\n")
        return event

    def list_events(self) -> list[AnalysisEvent]:
        if not self._path.exists():
            return []
        events = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(AnalysisEvent.model_validate_json(line))
        return events
