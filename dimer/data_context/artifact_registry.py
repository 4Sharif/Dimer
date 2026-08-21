"""Artifact tracking."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from dimer.safety.pii import redact_sensitive_data, redact_sensitive_text
from dimer.storage.artifacts import get_dimer_dir


class Artifact(BaseModel):
    id: str
    path: str
    artifact_type: str
    description: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ArtifactRegistry:
    def __init__(self, workspace: Path | None = None) -> None:
        self.workspace = workspace
        self._path = get_dimer_dir(workspace) / "artifacts_registry.json"
        self._artifacts: list[Artifact] = []
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            self._artifacts = [Artifact.model_validate(a) for a in raw]

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = [a.model_dump(mode="json") for a in self._artifacts]
        self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def register(
        self,
        path: str | Path,
        artifact_type: str,
        description: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Artifact:
        artifact = Artifact(
            id=f"art-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}",
            path=redact_sensitive_text(str(Path(path).resolve())),
            artifact_type=artifact_type,
            description=redact_sensitive_data(description),
            metadata=redact_sensitive_data(metadata or {}),
        )
        self._artifacts.append(artifact)
        self._save()
        return artifact

    def list_all(self, artifact_type: str | None = None) -> list[Artifact]:
        if artifact_type:
            return [a for a in self._artifacts if a.artifact_type == artifact_type]
        return list(self._artifacts)

    def list_filtered(
        self,
        *,
        artifact_type: str | None = None,
        session_id: str | None = None,
        limit: int | None = 15,
        newest_first: bool = True,
    ) -> list[Artifact]:
        items = self.list_all(artifact_type=artifact_type)
        if session_id:
            items = [a for a in items if a.metadata.get("session_id") == session_id]
        items = sorted(items, key=lambda a: a.created_at, reverse=newest_first)
        if limit is not None and limit >= 0:
            items = items[:limit]
        return items


def format_artifact_line(artifact: Artifact, workspace: Path | None = None) -> str:
    path = artifact.path
    if workspace is not None:
        try:
            path = str(Path(artifact.path).resolve().relative_to(Path(workspace).resolve()))
        except ValueError:
            path = artifact.path
    stamp = artifact.created_at.astimezone().strftime("%Y-%m-%d %H:%M")
    session = artifact.metadata.get("session_id")
    session_bit = f" session={session}" if session else ""
    return f"{artifact.artifact_type} | {stamp}{session_bit} | {path}"
