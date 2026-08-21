"""Report and assumption tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dimer.data_context.analysis_state import AnalysisState
from dimer.data_context.artifact_registry import ArtifactRegistry
from dimer.data_context.assumption_log import AssumptionLog
from dimer.safety.permissions import enforce_workspace_path
from dimer.safety.pii import redact_sensitive_data, redact_sensitive_text
from dimer.storage.artifacts import get_dimer_dir, get_workspace_root


def save_report(
    path: str,
    markdown_content: str,
    workspace: Path | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict:
    ws = get_workspace_root(workspace)
    meta = redact_sensitive_data(metadata or {})
    markdown_content = redact_sensitive_text(markdown_content)
    target = Path(path)
    if not target.is_absolute():
        if not str(target).startswith(".dimer"):
            target = get_dimer_dir(ws) / "artifacts" / "reports" / target.name
        else:
            target = ws / target
    target = enforce_workspace_path(target, ws)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(markdown_content, encoding="utf-8")
    artifact = ArtifactRegistry(ws).register(target, "report", description=target.name, metadata=meta)
    state = AnalysisState(ws)
    source_artifacts = meta.get("source_artifacts", []) or []
    session_id = meta.get("session_id") if isinstance(meta.get("session_id"), str) else None
    parent_ids = state.find_event_ids_for_artifacts(
        [str(path) for path in source_artifacts if path],
        session_id=session_id,
    )
    state.record(
        "report_created",
        inputs={
            "path": str(target),
            "question": meta.get("question"),
            "session_id": session_id,
            "source_artifacts": source_artifacts,
        },
        outputs={"artifact_id": artifact.id, "bytes": len(markdown_content)},
        artifact_paths=[str(target)],
        tool_source="save_report",
        parent_ids=parent_ids,
        session_id=session_id,
    )
    return {"path": str(target), "artifact_id": artifact.id, "bytes": len(markdown_content)}


def record_assumption(
    text: str,
    source: str | None = None,
    confidence: str | None = None,
    workspace: Path | None = None,
) -> dict:
    ws = get_workspace_root(workspace)
    assumption = AssumptionLog(ws).record(text, source=source, confidence=confidence)
    AnalysisState(ws).record(
        "assumption_added",
        inputs={"text": assumption.text},
        outputs={"id": assumption.id},
        tool_source="record_assumption",
    )
    return assumption.model_dump(mode="json")
