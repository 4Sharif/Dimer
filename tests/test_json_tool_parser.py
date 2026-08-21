"""Tests for JSON tool-call fallback parsing."""

from __future__ import annotations

from pathlib import Path

from dimer.agent.loop import AgentLoop
from dimer.agent.session import AgentContext
from dimer.agent.tool_router import ToolRouter
from dimer.data_context.artifact_registry import ArtifactRegistry
from dimer.providers.base import ModelResponse, parse_json_tool_response
from dimer.storage.artifacts import ensure_workspace_dirs


def test_parse_single_tool_call_json() -> None:
    parsed = parse_json_tool_response(
        '{"type":"tool_call","tool_name":"run_duckdb_query","arguments":{"query":"SELECT 1"}}'
    )
    assert parsed is not None
    assert len(parsed.tool_calls) == 1
    assert parsed.tool_calls[0].name == "run_duckdb_query"
    assert parsed.tool_calls[0].arguments["query"] == "SELECT 1"


def test_parse_multiple_tool_calls_mixed_with_prose() -> None:
    text = """
## Findings
I'll analyze why revenue dropped in March.

{"type":"tool_call","tool_name":"run_duckdb_query","arguments":{"query":"SELECT 1 AS n"}}
{"type":"tool_call","tool_name":"run_duckdb_query","arguments":{"query":"SELECT 2 AS n"}}
{"type":"tool_call","tool_name":"run_duckdb_query","arguments":{"query":"SELECT region, SUM(revenue) AS total FROM sales GROUP BY region"}}
"""
    parsed = parse_json_tool_response(text)
    assert parsed is not None
    # Only the first tool call is kept per turn to avoid local-model thrash.
    assert len(parsed.tool_calls) == 1
    assert parsed.tool_calls[0].arguments["query"] == "SELECT 1 AS n"
    assert parsed.content is None


def test_parse_prefers_tool_calls_over_final() -> None:
    text = """
{"type":"tool_call","tool_name":"run_duckdb_query","arguments":{"query":"SELECT 1"}}
{"type":"final","content":"## Findings\\nDone early"}
"""
    parsed = parse_json_tool_response(text)
    assert parsed is not None
    assert len(parsed.tool_calls) == 1
    assert parsed.content is None


def test_parse_final_only() -> None:
    parsed = parse_json_tool_response('{"type":"final","content":"## Findings\\nHello"}')
    assert parsed is not None
    assert parsed.tool_calls == []
    assert parsed.content == "## Findings\nHello"


class ProseToolDumpProvider:
    name = "mock"

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, messages, tools=None, model=None, temperature=0.2):
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                content=(
                    "## Findings\nI'll start with monthly totals.\n"
                    '{"type":"tool_call","tool_name":"run_duckdb_query",'
                    '"arguments":{"query":"SELECT region, SUM(revenue) AS total '
                    'FROM sales GROUP BY region ORDER BY total DESC"}}'
                )
            )
        return ModelResponse(content="## Findings\nWest contributed the most revenue.")

    def stream(self, messages, tools=None, model=None, temperature=0.2):
        yield from ()


def test_agent_loop_recovers_tool_calls_from_prose_content(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)
    provider = ProseToolDumpProvider()
    router = ToolRouter(tmp_path)
    loop = AgentLoop(provider, router, max_iterations=4)
    dataset = Path(__file__).parent.parent / "examples" / "sales" / "sales.csv"
    ctx = AgentContext(workspace=tmp_path, dataset_path=str(dataset))

    result = loop.run("Which region contributed most revenue?", ctx)

    assert provider.calls >= 2
    assert "West" in result.content or "Findings" in result.content
    assert any(a.artifact_type == "query" for a in ArtifactRegistry(tmp_path).list_all())
    assert "No tools were executed" not in result.content
