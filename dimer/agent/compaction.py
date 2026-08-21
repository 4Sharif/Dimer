"""Output compaction for agent context."""

from __future__ import annotations

import json
from typing import Any

from dimer.safety.process_limits import truncate_output


def compact_tool_result(result: Any, max_chars: int = 8000) -> str:
    text = json.dumps(result, default=str) if not isinstance(result, str) else result
    compact, _ = truncate_output(text, max_chars)
    return compact


def compact_profile_for_context(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": profile.get("path"),
        "row_count": profile.get("row_count"),
        "column_count": profile.get("column_count"),
        "columns": [
            {
                "name": c.get("name"),
                "dtype": c.get("dtype"),
                "missing_pct": c.get("missing_pct"),
            }
            for c in profile.get("columns", [])
        ],
        "quality_warnings": profile.get("quality_warnings", [])[:5],
        "potential_id_columns": profile.get("potential_id_columns", []),
        "potential_target_columns": profile.get("potential_target_columns", []),
        "likely_date_columns": profile.get("likely_date_columns", []),
        "likely_metric_columns": profile.get("likely_metric_columns", []),
        "likely_revenue_columns": profile.get("likely_revenue_columns", []),
        "likely_categorical_dimensions": profile.get("likely_categorical_dimensions", []),
    }
