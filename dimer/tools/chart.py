"""Chart artifact helpers."""

from __future__ import annotations

from pathlib import Path

from dimer.data_context.analysis_state import AnalysisState
from dimer.data_context.artifact_registry import ArtifactRegistry
from dimer.storage.artifacts import get_dimer_dir, get_workspace_root


def register_chart(path: str | Path, description: str | None = None, workspace: Path | None = None) -> dict:
    ws = get_workspace_root(workspace)
    p = Path(path).resolve()
    artifact = ArtifactRegistry(ws).register(p, "chart", description=description or p.name)
    AnalysisState(ws).record(
        "chart_created",
        inputs={"path": str(p)},
        artifact_paths=[str(p)],
        tool_source="create_chart",
    )
    return artifact.model_dump(mode="json")


def default_chart_path(filename: str, workspace: Path | None = None) -> Path:
    charts_dir = get_dimer_dir(workspace) / "artifacts" / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)
    return charts_dir / filename
