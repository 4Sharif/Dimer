"""Deterministic data-quality diagnostics for profiles and agent notes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import pandas as pd
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from dimer.data_context.schema_profile import DatasetProfile


class QualityFinding(BaseModel):
    code: str
    severity: Literal["info", "warning", "critical"] = "warning"
    message: str
    columns: list[str] = Field(default_factory=list)


def analyze_data_quality(
    profile: DatasetProfile,
    df: pd.DataFrame | None = None,
) -> list[QualityFinding]:
    """Return deterministic quality findings from a profile and optional dataframe.

    Designed as a deep module: callers pass a profile (+ optional df) and get
    human-readable findings without knowing the heuristics.
    """
    findings: list[QualityFinding] = []
    findings.extend(_missingness_findings(profile))
    findings.extend(_duplicate_findings(profile))
    findings.extend(_constant_column_findings(profile))
    findings.extend(_sample_size_findings(profile))
    findings.extend(_grain_findings(profile, df))
    findings.extend(_metric_value_findings(profile, df))
    findings.extend(_dimension_cardinality_findings(profile))
    return _dedupe_findings(findings)


def quality_messages(profile: DatasetProfile, df: pd.DataFrame | None = None) -> list[str]:
    """Convenience: message strings only, for warnings lists and agent notes."""
    return [finding.message for finding in analyze_data_quality(profile, df)]


def detect_schema_drift(
    previous: DatasetProfile,
    current: DatasetProfile,
) -> list[QualityFinding]:
    """Compare a saved profile to a fresh profile for column/type drift."""
    findings: list[QualityFinding] = []
    prev_cols = {col.name: col for col in previous.columns}
    curr_cols = {col.name: col for col in current.columns}

    added = sorted(set(curr_cols) - set(prev_cols))
    removed = sorted(set(prev_cols) - set(curr_cols))
    if added:
        findings.append(
            QualityFinding(
                code="schema_drift_added",
                severity="warning",
                message=f"Schema drift: new column(s) since last profile: {', '.join(f'`{c}`' for c in added)}.",
                columns=added,
            )
        )
    if removed:
        findings.append(
            QualityFinding(
                code="schema_drift_removed",
                severity="warning",
                message=(
                    f"Schema drift: column(s) missing since last profile: "
                    f"{', '.join(f'`{c}`' for c in removed)}."
                ),
                columns=removed,
            )
        )

    type_changes: list[str] = []
    for name in sorted(set(prev_cols) & set(curr_cols)):
        prev_dtype = _normalize_dtype(prev_cols[name].dtype)
        curr_dtype = _normalize_dtype(curr_cols[name].dtype)
        if prev_dtype != curr_dtype:
            type_changes.append(f"`{name}` ({prev_cols[name].dtype} → {curr_cols[name].dtype})")
    if type_changes:
        findings.append(
            QualityFinding(
                code="schema_drift_dtype",
                severity="warning",
                message="Schema drift: column type change(s): " + "; ".join(type_changes[:8]) + ".",
                columns=[name for name in sorted(set(prev_cols) & set(curr_cols)) if _normalize_dtype(prev_cols[name].dtype) != _normalize_dtype(curr_cols[name].dtype)],
            )
        )

    if previous.row_count and current.row_count:
        delta = current.row_count - previous.row_count
        if abs(delta) >= max(5, int(previous.row_count * 0.2)):
            direction = "grew" if delta > 0 else "shrank"
            findings.append(
                QualityFinding(
                    code="schema_drift_rows",
                    severity="info",
                    message=(
                        f"Row count {direction} since last profile "
                        f"({previous.row_count} → {current.row_count})."
                    ),
                )
            )
    return findings


def compare_dataset_schemas(profiles: list[DatasetProfile]) -> list[QualityFinding]:
    """Flag join/compare risks across multiple dataset profiles."""
    if len(profiles) < 2:
        return []
    findings: list[QualityFinding] = []
    base = profiles[0]
    base_cols = {col.name: _normalize_dtype(col.dtype) for col in base.columns}
    base_name = _short_name(base.path)

    for other in profiles[1:]:
        other_cols = {col.name: _normalize_dtype(col.dtype) for col in other.columns}
        other_name = _short_name(other.path)
        shared = sorted(set(base_cols) & set(other_cols))
        only_base = sorted(set(base_cols) - set(other_cols))
        only_other = sorted(set(other_cols) - set(base_cols))

        if not shared:
            findings.append(
                QualityFinding(
                    code="multi_dataset_no_overlap",
                    severity="warning",
                    message=(
                        f"`{base_name}` and `{other_name}` share no column names; "
                        "joins/compares need an explicit key mapping."
                    ),
                )
            )
            continue

        dtype_mismatches = [
            f"`{name}` ({base_cols[name]} vs {other_cols[name]})"
            for name in shared
            if base_cols[name] != other_cols[name]
        ]
        if dtype_mismatches:
            findings.append(
                QualityFinding(
                    code="multi_dataset_dtype_mismatch",
                    severity="warning",
                    message=(
                        f"Shared columns differ in type between `{base_name}` and `{other_name}`: "
                        + "; ".join(dtype_mismatches[:6])
                        + "."
                    ),
                    columns=[name for name in shared if base_cols[name] != other_cols[name]],
                )
            )
        if only_base or only_other:
            findings.append(
                QualityFinding(
                    code="multi_dataset_column_diff",
                    severity="info",
                    message=(
                        f"Schema overlap `{base_name}` vs `{other_name}`: "
                        f"{len(shared)} shared"
                        + (f", only in `{base_name}`: {', '.join(f'`{c}`' for c in only_base[:5])}" if only_base else "")
                        + (f", only in `{other_name}`: {', '.join(f'`{c}`' for c in only_other[:5])}" if only_other else "")
                        + "."
                    ),
                    columns=shared[:8],
                )
            )
    return findings


def question_aware_caveats(
    findings: list[QualityFinding],
    question: str,
) -> list[QualityFinding]:
    """Add extra caveats when the question implies totals/averages/comparisons."""
    lower = question.lower()
    asks_totals = any(term in lower for term in ("total", "sum", "contributed", "revenue", "sales", "how much"))
    asks_average = any(term in lower for term in ("average", "avg", "per ", "transaction", "order", "mean"))
    asks_trend = any(term in lower for term in ("trend", "drop", "increase", "decrease", "why", "march", "over time"))
    codes = {finding.code for finding in findings}
    extras: list[QualityFinding] = []

    if asks_totals and "metric_missingness" in codes:
        extras.append(
            QualityFinding(
                code="aggregate_caveat_missing",
                severity="warning",
                message="Totals/sums in this answer may be understated because a key metric column has missing values.",
            )
        )
    if asks_totals and "negative_metric" in codes:
        extras.append(
            QualityFinding(
                code="aggregate_caveat_negatives",
                severity="warning",
                message="Totals include negative metric values; confirm whether refunds/adjustments belong in the comparison.",
            )
        )
    if asks_average and ("row_grain_multi" in codes or "row_grain_unknown" in codes):
        extras.append(
            QualityFinding(
                code="aggregate_caveat_grain",
                severity="warning",
                message="Average/per-row metrics may be misleading until row grain is confirmed.",
            )
        )
    if asks_trend and "small_sample" in codes:
        extras.append(
            QualityFinding(
                code="aggregate_caveat_sample",
                severity="info",
                message="Trend/drop conclusions are based on a small sample and can shift with a few rows.",
            )
        )
    if asks_trend and "outlier_metric" in codes:
        extras.append(
            QualityFinding(
                code="aggregate_caveat_outlier",
                severity="info",
                message="Outliers in the metric column may distort period-over-period comparisons.",
            )
        )
    return extras


def apply_profile_quality(
    profile: DatasetProfile,
    df: pd.DataFrame | None = None,
    previous: DatasetProfile | None = None,
    peer_profiles: list[DatasetProfile] | None = None,
    question: str | None = None,
) -> list[QualityFinding]:
    """Run the full quality pack and merge messages onto profile.quality_warnings."""
    findings = analyze_data_quality(profile, df)
    if previous is not None:
        findings.extend(detect_schema_drift(previous, profile))
    if peer_profiles:
        findings.extend(compare_dataset_schemas([profile, *peer_profiles]))
    if question:
        findings.extend(question_aware_caveats(findings, question))
    findings = _dedupe_findings(findings)
    profile.quality_warnings = list(
        dict.fromkeys([*[f.message for f in findings], *profile.quality_warnings])
    )
    return findings


def _normalize_dtype(dtype: str) -> str:
    text = str(dtype).lower()
    if "int" in text:
        return "int"
    if "float" in text or "double" in text:
        return "float"
    if "bool" in text:
        return "bool"
    if "datetime" in text or "timestamp" in text or "date" in text:
        return "datetime"
    if "object" in text or "string" in text or "str" in text or "category" in text:
        return "string"
    return text


def _short_name(path: str) -> str:
    from pathlib import Path

    try:
        return Path(path).name or path
    except Exception:
        return path


def _missingness_findings(profile: DatasetProfile) -> list[QualityFinding]:
    findings: list[QualityFinding] = []
    metric_names = set(profile.likely_revenue_columns or profile.likely_metric_columns)
    for col in profile.columns:
        if col.missing_count <= 0:
            continue
        if col.missing_pct > 50:
            findings.append(
                QualityFinding(
                    code="high_missingness",
                    severity="critical",
                    message=f"Column `{col.name}` has {col.missing_pct:.1f}% missing values.",
                    columns=[col.name],
                )
            )
        elif col.name in metric_names:
            findings.append(
                QualityFinding(
                    code="metric_missingness",
                    severity="warning",
                    message=(
                        f"Metric column `{col.name}` has {col.missing_count} missing value(s) "
                        f"({col.missing_pct:.1f}%); aggregates may understate totals unless NULLs are intentional."
                    ),
                    columns=[col.name],
                )
            )
        elif col.missing_pct >= 5:
            findings.append(
                QualityFinding(
                    code="column_missingness",
                    severity="info",
                    message=f"Column `{col.name}` has {col.missing_pct:.1f}% missing values.",
                    columns=[col.name],
                )
            )
    return findings


def _duplicate_findings(profile: DatasetProfile) -> list[QualityFinding]:
    if not profile.duplicate_count:
        return []
    return [
        QualityFinding(
            code="duplicate_rows",
            severity="warning",
            message=(
                f"Dataset contains {profile.duplicate_count} duplicate row(s); "
                "confirm whether duplicates are expected before aggregating."
            ),
        )
    ]


def _constant_column_findings(profile: DatasetProfile) -> list[QualityFinding]:
    findings: list[QualityFinding] = []
    for col in profile.columns:
        if col.unique_count == 1 and profile.row_count > 1:
            findings.append(
                QualityFinding(
                    code="constant_column",
                    severity="info",
                    message=f"Column `{col.name}` has only one unique value and will not help segmentation.",
                    columns=[col.name],
                )
            )
    return findings


def _sample_size_findings(profile: DatasetProfile) -> list[QualityFinding]:
    if profile.row_count < 100:
        return [
            QualityFinding(
                code="small_sample",
                severity="info",
                message=(
                    f"Dataset has {profile.row_count} rows; conclusions may be sensitive to small-sample effects."
                ),
            )
        ]
    return []


def _grain_findings(profile: DatasetProfile, df: pd.DataFrame | None) -> list[QualityFinding]:
    findings: list[QualityFinding] = []
    if profile.potential_id_columns:
        findings.append(
            QualityFinding(
                code="row_grain_id",
                severity="info",
                message=(
                    "Likely row grain appears entity-level via id-like column(s): "
                    + ", ".join(f"`{c}`" for c in profile.potential_id_columns[:3])
                    + "."
                ),
                columns=list(profile.potential_id_columns[:3]),
            )
        )
        return findings

    grain_cols = _candidate_grain_columns(profile)
    if len(grain_cols) < 2:
        findings.append(
            QualityFinding(
                code="row_grain_unknown",
                severity="info",
                message=(
                    "No unique id column detected; treat each row carefully when computing "
                    "averages or per-transaction metrics until grain is confirmed."
                ),
            )
        )
        return findings

    if df is not None and all(col in df.columns for col in grain_cols):
        nunique = int(df.drop_duplicates(subset=grain_cols).shape[0])
        if nunique < profile.row_count:
            findings.append(
                QualityFinding(
                    code="row_grain_multi",
                    severity="warning",
                    message=(
                        f"Rows are not unique on {' + '.join(f'`{c}`' for c in grain_cols)} "
                        f"({nunique} distinct keys for {profile.row_count} rows). "
                        "Averages may mix multiple events per key; confirm transaction vs entity grain."
                    ),
                    columns=grain_cols,
                )
            )
        elif nunique == profile.row_count:
            findings.append(
                QualityFinding(
                    code="row_grain_composite",
                    severity="info",
                    message=(
                        "Likely row grain is the composite key "
                        + " + ".join(f"`{c}`" for c in grain_cols)
                        + "."
                    ),
                    columns=grain_cols,
                )
            )
    else:
        findings.append(
            QualityFinding(
                code="row_grain_candidate",
                severity="info",
                message=(
                    "Candidate row-grain columns: "
                    + ", ".join(f"`{c}`" for c in grain_cols)
                    + ". Validate uniqueness before interpreting per-row averages."
                ),
                columns=grain_cols,
            )
        )
    return findings


def _metric_value_findings(profile: DatasetProfile, df: pd.DataFrame | None) -> list[QualityFinding]:
    if df is None:
        return []
    findings: list[QualityFinding] = []
    metric_names = list(
        dict.fromkeys([*(profile.likely_revenue_columns or []), *(profile.likely_metric_columns or [])])
    )
    for name in metric_names:
        if name not in df.columns:
            continue
        series = pd.to_numeric(df[name], errors="coerce")
        valid = series.dropna()
        if valid.empty:
            continue
        neg = int((valid < 0).sum())
        if neg > 0:
            findings.append(
                QualityFinding(
                    code="negative_metric",
                    severity="warning",
                    message=(
                        f"Metric `{name}` has {neg} negative value(s); "
                        "confirm whether refunds/adjustments should be included in totals."
                    ),
                    columns=[name],
                )
            )
        zero_pct = float((valid == 0).mean() * 100)
        if zero_pct >= 40:
            findings.append(
                QualityFinding(
                    code="zero_heavy_metric",
                    severity="info",
                    message=(
                        f"Metric `{name}` is {zero_pct:.0f}% zeros; "
                        "aggregates and averages may be dominated by sparse activity."
                    ),
                    columns=[name],
                )
            )
        summary = next((c.numeric_summary for c in profile.columns if c.name == name), None)
        if summary and summary.get("max") is not None and summary.get("mean") is not None:
            mean = summary["mean"]
            mx = summary["max"]
            if mean > 0 and mx >= mean * 20 and profile.row_count >= 10:
                findings.append(
                    QualityFinding(
                        code="outlier_metric",
                        severity="info",
                        message=(
                            f"Metric `{name}` max ({mx:.4g}) is much larger than mean ({mean:.4g}); "
                            "check whether outliers distort totals or averages."
                        ),
                        columns=[name],
                    )
                )
    return findings


def _dimension_cardinality_findings(profile: DatasetProfile) -> list[QualityFinding]:
    findings: list[QualityFinding] = []
    if profile.row_count <= 0:
        return findings
    for name in profile.likely_categorical_dimensions:
        col = next((c for c in profile.columns if c.name == name), None)
        if col is None or not col.unique_count:
            continue
        ratio = col.unique_count / profile.row_count
        if ratio >= 0.8 and col.unique_count >= 10:
            findings.append(
                QualityFinding(
                    code="high_cardinality_dimension",
                    severity="warning",
                    message=(
                        f"`{name}` looks nearly unique ({col.unique_count}/{profile.row_count}); "
                        "it may be an identifier rather than a useful segment dimension."
                    ),
                    columns=[name],
                )
            )
    return findings


def _candidate_grain_columns(profile: DatasetProfile) -> list[str]:
    cols: list[str] = []
    for name in profile.likely_date_columns:
        if name not in cols:
            cols.append(name)
    for name in profile.likely_categorical_dimensions:
        if name not in cols:
            cols.append(name)
    return cols[:3]


def _dedupe_findings(findings: list[QualityFinding]) -> list[QualityFinding]:
    seen: set[str] = set()
    out: list[QualityFinding] = []
    for finding in findings:
        key = f"{finding.code}:{finding.message}"
        if key in seen:
            continue
        seen.add(key)
        out.append(finding)
    return out
