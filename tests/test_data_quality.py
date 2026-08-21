"""Tests for deterministic data-quality diagnostics."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from dimer.data_context.data_quality import analyze_data_quality
from dimer.data_context.schema_profile import profile_dataset


def test_sales_profile_includes_metric_missingness_and_grain(tmp_path: Path) -> None:
    src = Path(__file__).parent.parent / "examples" / "sales" / "sales.csv"
    path = tmp_path / "sales.csv"
    path.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    profile = profile_dataset(path)
    codes = {f.code for f in analyze_data_quality(profile, pd.read_csv(path))}

    assert "metric_missingness" in codes or any("revenue" in w.lower() and "missing" in w.lower() for w in profile.quality_warnings)
    assert "small_sample" in codes
    assert any(code.startswith("row_grain") for code in codes)
    assert any("missing" in w.lower() or "grain" in w.lower() for w in profile.quality_warnings)


def test_negative_metric_and_multi_grain(tmp_path: Path) -> None:
    df = pd.DataFrame(
        {
            "date": ["2024-01-01", "2024-01-01", "2024-02-01"],
            "region": ["West", "West", "East"],
            "revenue": [100.0, -20.0, 50.0],
        }
    )
    path = tmp_path / "refunds.csv"
    df.to_csv(path, index=False)
    profile = profile_dataset(path)
    findings = analyze_data_quality(profile, df)
    codes = {f.code for f in findings}

    assert "negative_metric" in codes
    assert "row_grain_multi" in codes


def test_schema_drift_and_multi_dataset_and_question_caveats(tmp_path: Path) -> None:
    from dimer.data_context.data_quality import (
        compare_dataset_schemas,
        detect_schema_drift,
        question_aware_caveats,
    )
    from dimer.data_context.schema_profile import save_profile
    from dimer.storage.artifacts import ensure_workspace_dirs

    ensure_workspace_dirs(tmp_path)
    first = pd.DataFrame({"date": ["2024-01-01"], "region": ["West"], "revenue": [10.0]})
    path = tmp_path / "sales.csv"
    first.to_csv(path, index=False)
    previous = profile_dataset(path)
    save_profile(previous, tmp_path)

    second = pd.DataFrame(
        {
            "date": ["2024-01-01", "2024-02-01"],
            "region": ["West", "East"],
            "revenue": [10.0, None],
            "units": [1, 2],
        }
    )
    second.to_csv(path, index=False)
    current = profile_dataset(path)
    drift = detect_schema_drift(previous, current)
    drift_codes = {f.code for f in drift}
    assert "schema_drift_added" in drift_codes
    assert any("units" in f.message for f in drift)

    other_path = tmp_path / "other.csv"
    pd.DataFrame({"date": ["2024-01-01"], "region": ["East"], "amount": [5]}).to_csv(other_path, index=False)
    other = profile_dataset(other_path)
    multi = compare_dataset_schemas([current, other])
    assert any(f.code.startswith("multi_dataset") for f in multi)

    findings = analyze_data_quality(current)
    findings.extend(drift)
    caveats = question_aware_caveats(findings, "Why did revenue drop in March?")
    assert any(f.code.startswith("aggregate_caveat") for f in caveats)
