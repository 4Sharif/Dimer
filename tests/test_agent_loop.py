"""Agent loop tests with mocked provider."""

from __future__ import annotations

from pathlib import Path

import pytest

from dimer.agent.loop import AgentLoop
from dimer.agent.session import AgentContext
from dimer.agent.tool_router import ToolRouter
from dimer.data_context.artifact_registry import ArtifactRegistry
from dimer.providers.base import ModelMessage, ModelResponse, ModelToolCall, ToolSchema
from dimer.storage.artifacts import ensure_workspace_dirs


class MockProvider:
    name = "mock"
    calls = 0

    def generate(self, messages, tools=None, model=None, temperature=0.2):
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                tool_calls=[
                    ModelToolCall(
                        id="1",
                        name="inspect_dataset",
                        arguments={"path": str(Path(__file__).parent.parent / "examples" / "sales" / "sales.csv")},
                    )
                ]
            )
        return ModelResponse(content="## Findings\nRevenue trends analyzed.")

    def stream(self, messages, tools=None, model=None, temperature=0.2):
        yield from ()


def test_agent_loop_with_mock(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)
    provider = MockProvider()
    router = ToolRouter(tmp_path)
    loop = AgentLoop(provider, router, max_iterations=3)
    ctx = AgentContext(
        workspace=tmp_path,
        dataset_path=str(Path(__file__).parent.parent / "examples" / "sales" / "sales.csv"),
    )
    result = loop.run("What are the trends?", ctx)
    assert "Findings" in result.content
    assert provider.calls == 2


class AliasSQLProvider:
    name = "mock"

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, messages, tools=None, model=None, temperature=0.2):
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                tool_calls=[
                    ModelToolCall(
                        id="1",
                        name="duckdb",
                        arguments={
                            "sql": "SELECT region, SUM(revenue) AS total FROM sales GROUP BY region ORDER BY total DESC"
                        },
                    )
                ]
            )
        return ModelResponse(content='{"type":"final","content":"## Findings\\nNorth contributed the most revenue."}')

    def stream(self, messages, tools=None, model=None, temperature=0.2):
        yield from ()


def test_agent_loop_normalizes_sql_alias_and_saves_artifacts(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)
    provider = AliasSQLProvider()
    router = ToolRouter(tmp_path)
    loop = AgentLoop(provider, router, max_iterations=3)
    dataset = Path(__file__).parent.parent / "examples" / "sales" / "sales.csv"
    ctx = AgentContext(workspace=tmp_path, dataset_path=str(dataset))

    result = loop.run("Which region contributed most revenue?", ctx)

    assert "North contributed" in result.content
    artifacts = ArtifactRegistry(tmp_path).list_all()
    artifact_types = {a.artifact_type for a in artifacts}
    assert "query" in artifact_types
    assert "report" in artifact_types
    assert any(a.path.endswith(".sql") for a in artifacts)


class RepeatedFailureProvider:
    name = "mock"

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, messages, tools=None, model=None, temperature=0.2):
        self.calls += 1
        return ModelResponse(
            tool_calls=[
                ModelToolCall(
                    id=str(self.calls),
                    name="run_duckdb_query",
                    arguments={"query": "SELECT missing_column FROM sales"},
                )
            ]
        )

    def stream(self, messages, tools=None, model=None, temperature=0.2):
        yield from ()


def test_agent_loop_stops_repeated_identical_tool_failures(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)
    provider = RepeatedFailureProvider()
    router = ToolRouter(tmp_path)
    loop = AgentLoop(provider, router, max_iterations=12)
    dataset = Path(__file__).parent.parent / "examples" / "sales" / "sales.csv"
    ctx = AgentContext(workspace=tmp_path, dataset_path=str(dataset))

    result = loop.run("Use a bad query twice.", ctx)

    assert provider.calls == 2
    assert "failed repeatedly" in result.content
    assert "Repair hint" in result.content


class MarchDropProvider:
    name = "mock"

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, messages, tools=None, model=None, temperature=0.2):
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                tool_calls=[
                    ModelToolCall(
                        id="1",
                        name="sql",
                        arguments={
                            "statement": (
                                "SELECT date_trunc('month', CAST(date AS DATE)) AS month, "
                                "SUM(revenue) AS revenue FROM sales GROUP BY 1 ORDER BY 1"
                            )
                        },
                    )
                ]
            )
        return ModelResponse(content="## Findings\nMarch revenue was computed from monthly aggregates.")

    def stream(self, messages, tools=None, model=None, temperature=0.2):
        yield from ()


def test_agent_loop_creates_basic_chart_for_march_drop_question(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)
    provider = MarchDropProvider()
    router = ToolRouter(tmp_path)
    loop = AgentLoop(provider, router, max_iterations=3)
    dataset = Path(__file__).parent.parent / "examples" / "sales" / "sales.csv"
    ctx = AgentContext(workspace=tmp_path, dataset_path=str(dataset))

    result = loop.run("Why did revenue drop in March?", ctx)

    assert "March revenue" in result.content
    artifacts = ArtifactRegistry(tmp_path).list_all()
    assert any(a.artifact_type == "chart" and a.path.endswith(".png") for a in artifacts)
