"""Artifact tracking."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

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
            path=str(Path(path).resolve()),
            artifact_type=artifact_type,
            description=description,
            metadata=metadata or {},
        )
        self._artifacts.append(artifact)
        self._save()
        return artifact

    def list_all(self, artifact_type: str | None = None) -> list[Artifact]:
        if artifact_type:
            return [a for a in self._artifacts if a.artifact_type == artifact_type]
        return list(self._artifacts)
