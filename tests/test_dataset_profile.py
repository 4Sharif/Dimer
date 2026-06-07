"""Tests for dataset profiling."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from dimer.data_context.schema_profile import detect_file_type, profile_dataset


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def sales_csv(tmp_path: Path) -> Path:
    src = Path(__file__).parent.parent / "examples" / "sales" / "sales.csv"
    dest = tmp_path / "sales.csv"
    dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return dest


def test_dataset_profile_csv(sales_csv: Path) -> None:
    profile = profile_dataset(sales_csv)
    assert profile.row_count == 30
    assert profile.column_count == 5
    assert profile.file_type == "csv"
    names = [c.name for c in profile.columns]
    assert "revenue" in names
    assert "date" in names


def test_dataset_profile_missing_values(tmp_path: Path) -> None:
    df = pd.DataFrame({"a": [1, None, 3], "b": ["x", "y", None]})
    path = tmp_path / "missing.csv"
    df.to_csv(path, index=False)
    profile = profile_dataset(path)
    missing = {c.name: c.missing_count for c in profile.columns}
    assert missing["a"] == 1
    assert missing["b"] == 1
    assert any("missing" in w.lower() for w in profile.quality_warnings) or profile.columns[0].missing_pct > 0


def test_dataset_profile_date_detection(tmp_path: Path) -> None:
    df = pd.DataFrame({
        "order_date": ["2024-01-01", "2024-02-01", "2024-03-01"],
        "amount": [10, 20, 30],
    })
    path = tmp_path / "dates.csv"
    df.to_csv(path, index=False)
    profile = profile_dataset(path)
    date_col = next(c for c in profile.columns if c.name == "order_date")
    assert date_col.date_range is not None
    assert "2024" in date_col.date_range["min"]


def test_detect_file_type_parquet(tmp_path: Path) -> None:
    df = pd.DataFrame({"x": [1, 2]})
    path = tmp_path / "data.parquet"
    df.to_parquet(path)
    assert detect_file_type(path) == "parquet"
