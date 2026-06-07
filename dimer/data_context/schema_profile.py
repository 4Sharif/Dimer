"""Dataset profiling models and logic."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from dimer.safety.pii import redact_sample_rows
from dimer.storage.artifacts import get_dimer_dir


class ColumnProfile(BaseModel):
    name: str
    dtype: str
    missing_count: int = 0
    missing_pct: float = 0.0
    unique_count: int | None = None
    numeric_summary: dict[str, float] | None = None
    categorical_top_values: list[dict[str, Any]] | None = None
    date_range: dict[str, str] | None = None


class DatasetProfile(BaseModel):
    path: str
    file_type: str
    file_size_bytes: int
    row_count: int
    column_count: int
    columns: list[ColumnProfile]
    duplicate_count: int | None = None
    potential_id_columns: list[str] = Field(default_factory=list)
    potential_target_columns: list[str] = Field(default_factory=list)
    quality_warnings: list[str] = Field(default_factory=list)
    sample_rows: list[dict[str, Any]] | None = None
    profiled_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


SUPPORTED_EXTENSIONS = {".csv", ".parquet", ".xlsx", ".xls"}


def detect_file_type(path: Path) -> str:
    ext = path.suffix.lower()
    mapping = {".csv": "csv", ".parquet": "parquet", ".xlsx": "excel", ".xls": "excel"}
    if ext not in mapping:
        raise ValueError(f"Unsupported file type: {ext}")
    return mapping[ext]


def load_dataframe(path: Path, file_type: str | None = None) -> pd.DataFrame:
    ft = file_type or detect_file_type(path)
    if ft == "csv":
        return pd.read_csv(path)
    if ft == "parquet":
        return pd.read_parquet(path)
    if ft == "excel":
        return pd.read_excel(path)
    raise ValueError(f"Cannot load file type: {ft}")


def _is_likely_id(series: pd.Series) -> bool:
    name = series.name or ""
    if re.search(r"(^id$|_id$|^uuid$|key$)", str(name), re.I):
        return True
    if series.dtype in ("int64", "object", "string"):
        nunique = series.nunique(dropna=True)
        return nunique == len(series) and nunique > 0
    return False


def _is_likely_target(name: str, series: pd.Series) -> bool:
    if re.search(r"(target|label|revenue|sales|price|amount|count|score)", name, re.I):
        return True
    if pd.api.types.is_numeric_dtype(series):
        return series.nunique(dropna=True) > 1 and series.nunique(dropna=True) < max(len(series) * 0.5, 2)
    return False


def _profile_column(series: pd.Series) -> ColumnProfile:
    missing = int(series.isna().sum())
    total = len(series)
    missing_pct = (missing / total * 100) if total else 0.0
    profile = ColumnProfile(
        name=str(series.name),
        dtype=str(series.dtype),
        missing_count=missing,
        missing_pct=round(missing_pct, 2),
        unique_count=int(series.nunique(dropna=True)),
    )

    if pd.api.types.is_numeric_dtype(series):
        desc = series.describe()
        profile.numeric_summary = {
            k: float(desc[k]) for k in ("min", "max", "mean", "std", "25%", "50%", "75%") if k in desc
        }
    elif pd.api.types.is_datetime64_any_dtype(series):
        valid = series.dropna()
        if not valid.empty:
            profile.date_range = {
                "min": str(valid.min()),
                "max": str(valid.max()),
            }
    else:
        counts = series.astype(str).value_counts().head(5)
        profile.categorical_top_values = [
            {"value": str(idx), "count": int(cnt)} for idx, cnt in counts.items()
        ]

    return profile


def _detect_date_columns(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    for col in result.columns:
        if pd.api.types.is_datetime64_any_dtype(result[col]):
            continue
        if not (pd.api.types.is_object_dtype(result[col]) or pd.api.types.is_string_dtype(result[col])):
            continue
        sample = result[col].dropna().head(20)
        if len(sample) == 0:
            continue
        try:
            parsed = pd.to_datetime(sample, errors="coerce")
            if parsed.notna().mean() >= 0.8:
                result[col] = pd.to_datetime(result[col], errors="coerce")
        except (ValueError, TypeError):
            pass
    return result


def profile_dataset(
    path: str | Path,
    include_sample: bool = False,
    max_sample_rows: int = 5,
    redact_pii: bool = True,
) -> DatasetProfile:
    p = Path(path).resolve()
    if not p.exists():
        raise FileNotFoundError(f"Dataset not found: {p}")

    file_type = detect_file_type(p)
    df = load_dataframe(p, file_type)
    df = _detect_date_columns(df)

    columns = [_profile_column(df[col]) for col in df.columns]
    id_cols = [str(c) for c in df.columns if _is_likely_id(df[c])]
    target_cols = [str(c) for c in df.columns if _is_likely_target(str(c), df[c])]

    warnings: list[str] = []
    for col in columns:
        if col.missing_pct > 50:
            warnings.append(f"Column '{col.name}' has {col.missing_pct:.1f}% missing values")
        if col.unique_count == 1:
            warnings.append(f"Column '{col.name}' has only one unique value")

    dup_count = int(df.duplicated().sum()) if len(df) > 0 else 0
    if dup_count > 0:
        warnings.append(f"Found {dup_count} duplicate rows")

    sample_rows = None
    if include_sample and len(df) > 0:
        sample = df.head(max_sample_rows).to_dict(orient="records")
        sample_rows = redact_sample_rows(sample) if redact_pii else sample

    return DatasetProfile(
        path=str(p),
        file_type=file_type,
        file_size_bytes=p.stat().st_size,
        row_count=len(df),
        column_count=len(df.columns),
        columns=columns,
        duplicate_count=dup_count,
        potential_id_columns=id_cols,
        potential_target_columns=target_cols,
        quality_warnings=warnings,
        sample_rows=sample_rows,
    )


def inspect_dataset(path: str | Path) -> dict[str, Any]:
    p = Path(path).resolve()
    file_type = detect_file_type(p)
    df = load_dataframe(p, file_type)
    return {
        "path": str(p),
        "file_type": file_type,
        "row_count": len(df),
        "column_count": len(df.columns),
        "columns": [{"name": str(c), "dtype": str(df[c].dtype)} for c in df.columns],
    }


def save_profile(profile: DatasetProfile, workspace: Path | None = None) -> Path:
    dimer_dir = get_dimer_dir(workspace)
    profiles_dir = dimer_dir / "profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(profile.path).name
    out = profiles_dir / f"{stem}.profile.json"
    out.write_text(profile.model_dump_json(indent=2), encoding="utf-8")
    return out


def load_profile(path: str | Path, workspace: Path | None = None) -> DatasetProfile | None:
    p = Path(path)
    if p.exists() and p.suffix == ".json":
        return DatasetProfile.model_validate_json(p.read_text(encoding="utf-8"))
    stem = p.name
    profile_path = get_dimer_dir(workspace) / "profiles" / f"{stem}.profile.json"
    if profile_path.exists():
        return DatasetProfile.model_validate_json(profile_path.read_text(encoding="utf-8"))
    return None
