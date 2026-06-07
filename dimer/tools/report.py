"""Report and assumption tools."""

from __future__ import annotations

from pathlib import Path

from dimer.data_context.analysis_state import AnalysisState
from dimer.data_context.artifact_registry import ArtifactRegistry
from dimer.data_context.assumption_log import AssumptionLog
from dimer.storage.artifacts import get_dimer_dir, get_workspace_root


def save_report(path: str, markdown_content: str, workspace: Path | None = None) -> dict:
    ws = get_workspace_root(workspace)
    target = Path(path)
    if not target.is_absolute():
        if not str(target).startswith(".dimer"):
            target = get_dimer_dir(ws) / "artifacts" / "reports" / target.name
        else:
            target = ws / target
    target = target.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(markdown_content, encoding="utf-8")
    artifact = ArtifactRegistry(ws).register(target, "report", description=target.name)
    AnalysisState(ws).record(
        "report_created",
        inputs={"path": str(target)},
        artifact_paths=[str(target)],
        tool_source="save_report",
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
        inputs={"text": text},
        outputs={"id": assumption.id},
        tool_source="record_assumption",
    )
    return assumption.model_dump(mode="json")
