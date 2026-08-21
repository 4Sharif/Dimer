"""Tests for artifact registry."""

from __future__ import annotations

from dimer.data_context.artifact_registry import ArtifactRegistry, format_artifact_line
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


def test_artifact_registry_redacts_secrets_before_persistence(tmp_path) -> None:
    ensure_workspace_dirs(tmp_path)
    secret = "sk-supersecretvalue123456"
    target = tmp_path / ".dimer" / "artifacts" / "queries" / "safe.sql"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("SELECT 1", encoding="utf-8")

    artifact = ArtifactRegistry(tmp_path).register(
        target,
        "query",
        description=f"token={secret}",
        metadata={"query": f"SELECT '{secret}'", "api_key": "unstructured-value"},
    )

    raw = (tmp_path / ".dimer" / "artifacts_registry.json").read_text(encoding="utf-8")
    assert secret not in raw
    assert "[REDACTED_SECRET]" in raw
    assert "unstructured-value" not in raw
    assert secret not in str(artifact)


def test_artifact_registry_list_filtered_by_session_and_limit(tmp_path) -> None:
    ensure_workspace_dirs(tmp_path)
    reg = ArtifactRegistry(tmp_path)
    base = tmp_path / ".dimer" / "artifacts" / "queries"
    base.mkdir(parents=True, exist_ok=True)

    for i in range(3):
        path = base / f"q{i}.sql"
        path.write_text(f"SELECT {i}", encoding="utf-8")
        reg.register(
            path,
            "query",
            description=f"q{i}",
            metadata={"session_id": "session-a" if i < 2 else "session-b"},
        )

    recent = reg.list_filtered(limit=2)
    assert len(recent) == 2
    assert recent[0].path.endswith("q2.sql")

    session_a = reg.list_filtered(session_id="session-a", limit=None)
    assert len(session_a) == 2
    assert all(a.metadata["session_id"] == "session-a" for a in session_a)

    line = format_artifact_line(session_a[0], tmp_path)
    assert "query |" in line
    assert "session=session-a" in line
