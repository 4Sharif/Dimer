"""Chart artifact helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dimer.data_context.analysis_state import AnalysisState
from dimer.data_context.artifact_registry import ArtifactRegistry
from dimer.storage.artifacts import get_dimer_dir, get_workspace_root


def register_chart(
    path: str | Path,
    description: str | None = None,
    workspace: Path | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict:
    ws = get_workspace_root(workspace)
    p = Path(path).resolve()
    meta = metadata or {}
    artifact = ArtifactRegistry(ws).register(p, "chart", description=description or p.name, metadata=meta)
    state = AnalysisState(ws)
    source_artifacts = meta.get("source_artifacts", []) or []
    session_id = meta.get("session_id") if isinstance(meta.get("session_id"), str) else None
    parent_ids = state.find_event_ids_for_artifacts(
        [str(path) for path in source_artifacts if path],
        session_id=session_id,
    )
    columns = [str(c) for c in (meta.get("columns") or [])]
    state.record(
        "chart_created",
        inputs={
            "path": str(p),
            "source_dataset": meta.get("source_dataset"),
            "source_artifacts": source_artifacts,
            "columns": columns,
            "session_id": session_id,
        },
        outputs={
            "artifact_id": artifact.id,
            "chart_type": meta.get("chart_type"),
            "description": description or p.name,
        },
        artifact_paths=[str(p)],
        tool_source="create_chart",
        parent_ids=parent_ids,
        columns=columns,
        session_id=session_id,
    )
    return artifact.model_dump(mode="json")


def default_chart_path(filename: str, workspace: Path | None = None) -> Path:
    charts_dir = get_dimer_dir(workspace) / "artifacts" / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)
    return charts_dir / filename
