"""Tests for artifact registry."""

from __future__ import annotations

from dimer.data_context.artifact_registry import ArtifactRegistry
from dimer.storage.artifacts import ensure_workspace_dirs


def test_artifact_registry_register(tmp_path) -> None:
    ensure_workspace_dirs(tmp_path)
    reg = ArtifactRegistry(tmp_path)
    chart = tmp_path / ".dimer" / "artifacts" / "charts" / "test.png"
    chart.parent.mkdir(parents=True, exist_ok=True)
    chart.write_bytes(b"fake")
    artifact = reg.register(chart, "chart", description="Test chart")
    items = reg.list_all()
    assert len(items) == 1
    assert items[0].id == artifact.id
    assert items[0].artifact_type == "chart"
