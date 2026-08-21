"""Tests for workspace DuckDB auto-registration and related reliability fixes."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from dimer.agent.tool_router import ToolRouter
from dimer.data_context.analysis_state import format_trace
from dimer.data_context.workspace_scanner import duckdb_table_catalog, list_duckdb_dataset_paths
from dimer.storage.artifacts import ensure_workspace_dirs


def _write_retailish(tmp_path: Path) -> None:
    pd.DataFrame(
        {
            "order_id": ["O1", "O2", "O3", "O4"],
            "customer_id": ["C1", "C1", "C2", "C2"],
            "product_id": ["P1", "P2", "P1", "P2"],
            "revenue": [10.0, 20.0, 30.0, 40.0],
        }
    ).to_csv(tmp_path / "orders.csv", index=False)
    pd.DataFrame(
        {
            "customer_id": ["C1", "C2"],
            "region": ["West", "East"],
        }
    ).to_csv(tmp_path / "customers.csv", index=False)
    pd.DataFrame(
        {
            "product_id": ["P1", "P2"],
            "category": ["Subscription", "Hardware"],
        }
    ).to_csv(tmp_path / "products.csv", index=False)


def test_list_duckdb_dataset_paths(tmp_path: Path) -> None:
    _write_retailish(tmp_path)
    paths = list_duckdb_dataset_paths(tmp_path)
    assert len(paths) == 3
    catalog = duckdb_table_catalog(tmp_path)
    tables = {item["table"] for item in catalog}
    assert tables == {"orders", "customers", "products"}


def test_workspace_ask_auto_registers_duckdb_tables(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)
    _write_retailish(tmp_path)
    router = ToolRouter(tmp_path)
    out = router.execute(
        "run_duckdb_query",
        {
            "query": (
                "SELECT c.region, p.category, SUM(o.revenue) AS total "
                "FROM orders o "
                "JOIN customers c ON o.customer_id = c.customer_id "
                "JOIN products p ON o.product_id = p.product_id "
                "GROUP BY 1, 2 ORDER BY total DESC"
            )
        },
        auto_approve=True,
    )
    assert out["success"] is True
    assert out["result"]["error"] is None
    assert out["result"]["row_count"] >= 1
    assert "data_paths" in (out.get("arguments") or {})
    assert len(out["arguments"]["data_paths"]) == 3


def test_format_trace_empty_session_hints_all() -> None:
    text = format_trace([], target="revenue", session_id="session-abc")
    assert "session-abc" in text
    assert "--all" in text


def test_malformed_tool_call_final_uses_sql_fallback(tmp_path: Path) -> None:
    from dimer.agent.loop import AgentLoop
    from dimer.agent.session import AgentContext
    from dimer.providers.base import ModelResponse, ModelToolCall

    ensure_workspace_dirs(tmp_path)
    _write_retailish(tmp_path)

    class Provider:
        name = "mock"
        calls = 0

        def generate(self, messages, tools=None, model=None, temperature=0.2):
            self.calls += 1
            if self.calls == 1:
                return ModelResponse(
                    tool_calls=[
                        ModelToolCall(
                            id="1",
                            name="run_duckdb_query",
                            arguments={
                                "query": (
                                    "SELECT 1 AS month_ord, 100.0 AS total_revenue "
                                    "UNION ALL SELECT 2, 120.0"
                                )
                            },
                        )
                    ]
                )
            # Malformed local-model dump (missing tool_name key) — must not become Findings as-is.
            return ModelResponse(
                content=(
                    '{"type": "tool_call", "run_duckdb_query", "arguments": '
                    '{"query": "SELECT 1"}}'
                )
            )

        def stream(self, messages, tools=None, model=None, temperature=0.2):
            yield from ()

    loop = AgentLoop(Provider(), ToolRouter(tmp_path), max_iterations=4)
    result = loop.run(
        "Why did revenue drop in March?",
        AgentContext(workspace=tmp_path),
        auto_approve=True,
    )
    assert '"type": "tool_call"' not in result.content
    assert "Findings" in result.content
    assert "120" in result.content or "total_revenue" in result.content or "unverified" in result.content.lower()
