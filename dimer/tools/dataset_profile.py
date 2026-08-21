"""Dataset profiling tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dimer.config import DimerConfig, load_config
from dimer.data_context.analysis_state import AnalysisState
from dimer.data_context.dataset_registry import DatasetRegistry
from dimer.data_context.schema_profile import inspect_dataset, profile_dataset, save_profile


def tool_inspect_dataset(path: str, workspace: Path | None = None) -> dict[str, Any]:
    result = inspect_dataset(path)
    dataset_path = str(Path(path).resolve())
    AnalysisState(workspace).record(
        "dataset_inspected",
        inputs={"path": path},
        outputs=result,
        artifact_paths=[dataset_path],
        columns=[c["name"] for c in result.get("columns", []) if isinstance(c, dict) and c.get("name")],
    )
    return result


def tool_profile_dataset(
    path: str,
    workspace: Path | None = None,
    config: DimerConfig | None = None,
) -> dict[str, Any]:
    from dimer.data_context.data_quality import detect_schema_drift
    from dimer.data_context.schema_profile import load_profile

    cfg = config or load_config()
    previous = load_profile(path, workspace)
    profile = profile_dataset(
        path,
        include_sample=cfg.privacy.send_sample_rows,
        max_sample_rows=cfg.privacy.max_sample_rows,
        redact_pii=cfg.privacy.redact_pii,
    )
    if previous is not None:
        drift = detect_schema_drift(previous, profile)
        if drift:
            profile.quality_warnings = list(
                dict.fromkeys([*[f.message for f in drift], *profile.quality_warnings])
            )
    out = save_profile(profile, workspace)
    DatasetRegistry(workspace).register(path, profile)
    dataset_path = str(Path(path).resolve())
    state = AnalysisState(workspace)
    state.record(
        "dataset_profiled",
        inputs={"path": path},
        outputs={
            "profile_path": str(out),
            "quality_warning_count": len(profile.quality_warnings),
        },
        artifact_paths=[dataset_path, str(out)],
        columns=[c.name for c in profile.columns],
    )
    for warning in profile.quality_warnings[:12]:
        state.record(
            "quality_issue_found",
            inputs={"path": path, "warning": warning},
            outputs={"source": "profile_dataset"},
            artifact_paths=[dataset_path],
            columns=[c.name for c in profile.columns if c.name in warning],
            reason=warning,
            tool_source="profile_dataset",
        )
    return profile.model_dump(mode="json")
