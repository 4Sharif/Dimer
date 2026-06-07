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
    AnalysisState(workspace).record("dataset_inspected", inputs={"path": path}, outputs=result)
    return result


def tool_profile_dataset(
    path: str,
    workspace: Path | None = None,
    config: DimerConfig | None = None,
) -> dict[str, Any]:
    cfg = config or load_config()
    profile = profile_dataset(
        path,
        include_sample=cfg.privacy.send_sample_rows,
        max_sample_rows=cfg.privacy.max_sample_rows,
        redact_pii=cfg.privacy.redact_pii,
    )
    out = save_profile(profile, workspace)
    DatasetRegistry(workspace).register(path, profile)
    AnalysisState(workspace).record(
        "dataset_profiled",
        inputs={"path": path},
        outputs={"profile_path": str(out)},
        artifact_paths=[str(out)],
    )
    return profile.model_dump(mode="json")
