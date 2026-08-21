"""Agent loop tests with mocked provider."""

from __future__ import annotations

from pathlib import Path

import pytest

from dimer.agent.loop import AgentLoop
from dimer.agent.session import AgentContext
from dimer.agent.tool_router import ToolRouter
from dimer.data_context.analysis_state import AnalysisState
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


@pytest.mark.parametrize(
    "question",
    [
        "What are the trends?",
        "Which region led?",
        "Which region had the highest revenue?",
    ],
)
def test_agent_loop_with_mock(tmp_path: Path, question: str) -> None:
    ensure_workspace_dirs(tmp_path)
    provider = MockProvider()
    router = ToolRouter(tmp_path)
    loop = AgentLoop(provider, router, max_iterations=3)
    ctx = AgentContext(
        workspace=tmp_path,
        dataset_path=str(Path(__file__).parent.parent / "examples" / "sales" / "sales.csv"),
    )
    result = loop.run(question, ctx)
    assert "Findings" in result.content
    assert "Unverified analytical synthesis" in result.findings
    assert provider.calls == 2


class UnrelatedSQLProvider:
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
                        name="run_duckdb_query",
                        arguments={"query": "SELECT 1 AS value"},
                    )
                ]
            )
        return ModelResponse(content="## Findings\nNorth had the highest revenue.")

    def stream(self, messages, tools=None, model=None, temperature=0.2):
        yield from ()


@pytest.mark.parametrize(
    "question",
    ["Which region had the highest revenue?", "Which product had the highest sales?"],
)
def test_agent_loop_does_not_treat_unrelated_computation_as_support(
    tmp_path: Path,
    question: str,
) -> None:
    ensure_workspace_dirs(tmp_path)
    dataset = Path(__file__).parent.parent / "examples" / "sales" / "sales.csv"
    loop = AgentLoop(UnrelatedSQLProvider(), ToolRouter(tmp_path), max_iterations=3)

    result = loop.run(
        question,
        AgentContext(workspace=tmp_path, dataset_path=str(dataset)),
    )

    assert "Unverified analytical synthesis" in result.findings


def test_agent_loop_requires_computation_for_data_summary_by_dimension(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)
    dataset = Path(__file__).parent.parent / "examples" / "sales" / "sales.csv"
    loop = AgentLoop(MockProvider(), ToolRouter(tmp_path), max_iterations=3)

    result = loop.run(
        "Summarize revenue by region.",
        AgentContext(workspace=tmp_path, dataset_path=str(dataset)),
    )

    assert "Unverified analytical synthesis" in result.findings


class ShallowRankingSQLProvider(UnrelatedSQLProvider):
    def generate(self, messages, tools=None, model=None, temperature=0.2):
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                tool_calls=[
                    ModelToolCall(
                        id="1",
                        name="run_duckdb_query",
                        arguments={"query": "SELECT region, revenue FROM sales LIMIT 1"},
                    )
                ]
            )
        return ModelResponse(content="## Findings\nNorth had the highest revenue.")


class WrongColumnRankingSQLProvider(ShallowRankingSQLProvider):
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
                                "SELECT region, revenue FROM sales "
                                "ORDER BY region LIMIT 1"
                            )
                        },
                    )
                ]
            )
        return ModelResponse(content="## Findings\nNorth had the highest revenue.")


def test_agent_loop_rejects_computation_without_the_requested_ranking(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)
    dataset = Path(__file__).parent.parent / "examples" / "sales" / "sales.csv"
    loop = AgentLoop(ShallowRankingSQLProvider(), ToolRouter(tmp_path), max_iterations=3)

    result = loop.run(
        "Which region had the highest revenue?",
        AgentContext(workspace=tmp_path, dataset_path=str(dataset)),
    )

    assert "Unverified analytical synthesis" in result.findings


def test_agent_loop_rejects_ranking_the_wrong_field(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)
    dataset = Path(__file__).parent.parent / "examples" / "sales" / "sales.csv"
    loop = AgentLoop(WrongColumnRankingSQLProvider(), ToolRouter(tmp_path), max_iterations=3)

    result = loop.run(
        "Which region had the highest revenue?",
        AgentContext(workspace=tmp_path, dataset_path=str(dataset)),
    )

    assert "Unverified analytical synthesis" in result.findings


class RawGroupedSQLProvider(UnrelatedSQLProvider):
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
                                "SELECT region, revenue FROM sales "
                                "GROUP BY region, revenue"
                            )
                        },
                    )
                ]
            )
        return ModelResponse(content="## Findings\nNorth led revenue by region.")


def test_agent_loop_requires_an_aggregate_for_summary_by_dimension(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)
    dataset = Path(__file__).parent.parent / "examples" / "sales" / "sales.csv"
    loop = AgentLoop(RawGroupedSQLProvider(), ToolRouter(tmp_path), max_iterations=3)

    result = loop.run(
        "Summarize revenue by region.",
        AgentContext(workspace=tmp_path, dataset_path=str(dataset)),
    )

    assert "Unverified analytical synthesis" in result.findings


class AliasSQLProvider:
    name = "mock"

    def __init__(self) -> None:
        self.calls = 0
        self.messages_seen: list[list[ModelMessage]] = []

    def generate(self, messages, tools=None, model=None, temperature=0.2):
        self.calls += 1
        self.messages_seen.append(list(messages))
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
    assert "report" not in artifact_types
    assert any(a.path.endswith(".sql") for a in artifacts)
    final_nudge = provider.messages_seen[-1][-1].content or ""
    assert "core analytical checks look covered" in final_nudge
    assert "create charts or reports" not in final_nudge


def test_agent_loop_returns_only_current_session_artifacts(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)
    old_query = tmp_path / "old.sql"
    old_query.write_text("SELECT 1", encoding="utf-8")
    old_artifact = ArtifactRegistry(tmp_path).register(old_query, "query", description="old query")

    provider = AliasSQLProvider()
    router = ToolRouter(tmp_path)
    loop = AgentLoop(provider, router, max_iterations=3)
    dataset = Path(__file__).parent.parent / "examples" / "sales" / "sales.csv"
    ctx = AgentContext(workspace=tmp_path, dataset_path=str(dataset))

    result = loop.run("Which region contributed most revenue?", ctx)

    assert old_artifact.path not in result.artifacts
    assert any(path.endswith(".sql") for path in result.artifacts)
    assert not any(path.endswith(".md") for path in result.artifacts)


def test_agent_loop_returns_structured_evidence_backed_result(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)
    provider = AliasSQLProvider()
    router = ToolRouter(tmp_path)
    loop = AgentLoop(provider, router, max_iterations=3)
    dataset = Path(__file__).parent.parent / "examples" / "sales" / "sales.csv"
    ctx = AgentContext(workspace=tmp_path, dataset_path=str(dataset))

    result = loop.run("Which region contributed most revenue?", ctx)

    assert "North contributed" in result.findings
    assert result.evidence
    assert result.artifacts
    assert result.assumptions
    assert result.caveats
    assert "## Findings" in result.content
    assert "## Evidence" in result.content
    assert "## Artifacts" in result.content
    assert "## Assumptions" in result.content
    assert "## Caveats" in result.content


class ModelCaptureProvider:
    name = "mock"

    def __init__(self) -> None:
        self.models: list[str | None] = []

    def generate(self, messages, tools=None, model=None, temperature=0.2):
        self.models.append(model)
        return ModelResponse(content="Plain final answer")

    def stream(self, messages, tools=None, model=None, temperature=0.2):
        yield from ()


def test_agent_loop_uses_model_override(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)
    provider = ModelCaptureProvider()
    router = ToolRouter(tmp_path)
    loop = AgentLoop(provider, router, model="phase-a-model", max_iterations=3)
    dataset = Path(__file__).parent.parent / "examples" / "sales" / "sales.csv"
    ctx = AgentContext(workspace=tmp_path, dataset_path=str(dataset))

    result = loop.run("Summarize this dataset.", ctx)

    assert provider.models == ["phase-a-model"]
    assert "Unverified analytical synthesis" in result.findings
    evidence = "\n".join(result.evidence)
    assert "row_count" in evidence
    assert "column_count" in evidence


def test_agent_result_omits_empty_rendering_sections(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)
    provider = ModelCaptureProvider()
    loop = AgentLoop(provider, ToolRouter(tmp_path), max_iterations=2)

    result = loop.run("Say hello without analyzing data.", AgentContext(workspace=tmp_path))

    assert result.findings == "Plain final answer"
    assert result.evidence == []
    assert result.artifacts == []
    assert result.assumptions == []
    assert result.caveats == ["No successful tool-backed evidence was produced for this answer."]
    assert "## Evidence" not in result.content
    assert "## Artifacts" not in result.content
    assert "## Assumptions" not in result.content
    assert "## Caveats" in result.content
    assert "## Suggested Next Steps" not in result.content


def test_workspace_data_answer_without_tool_is_labeled_unverified(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)
    (tmp_path / "sales.csv").write_text("region,revenue\nWest,10\n", encoding="utf-8")
    loop = AgentLoop(ModelCaptureProvider(), ToolRouter(tmp_path), max_iterations=2)

    result = loop.run("Which region led?", AgentContext(workspace=tmp_path))

    assert "Unverified analytical synthesis" in result.findings
    assert "workspace inventory" in "\n".join(result.evidence).lower()


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
    assert "Available table(s): sales" in result.content
    assert "Available columns:" in result.content


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


def test_agent_loop_does_not_create_unrequested_chart(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)
    provider = MarchDropProvider()
    router = ToolRouter(tmp_path)
    loop = AgentLoop(provider, router, max_iterations=3)
    dataset = Path(__file__).parent.parent / "examples" / "sales" / "sales.csv"
    ctx = AgentContext(workspace=tmp_path, dataset_path=str(dataset))

    result = loop.run("Why did revenue drop in March?", ctx)

    assert "March revenue" in result.content
    artifacts = ArtifactRegistry(tmp_path).list_all()
    assert not any(a.artifact_type == "chart" for a in artifacts)


def test_agent_loop_records_analysis_plan_and_traceable_query(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)
    provider = AliasSQLProvider()
    router = ToolRouter(tmp_path)
    loop = AgentLoop(provider, router, max_iterations=3)
    dataset = Path(__file__).parent.parent / "examples" / "sales" / "sales.csv"
    ctx = AgentContext(workspace=tmp_path, dataset_path=str(dataset))

    result = loop.run("Which region contributed most revenue?", ctx)
    events = AnalysisState(tmp_path).list_events()

    assert result.analysis_plan
    assert any(event.event_type == "analysis_plan_created" for event in events)
    traced = AnalysisState(tmp_path).trace("revenue")
    assert any(event.event_type == "sql_query_run" for event in traced)


class BreakdownProvider:
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
                        name="run_duckdb_query",
                        arguments={
                            "query": "SELECT region, SUM(revenue) AS total FROM sales GROUP BY region ORDER BY total DESC"
                        },
                    )
                ]
            )
        return ModelResponse(content="## Findings\nNorth contributed the most revenue.")

    def stream(self, messages, tools=None, model=None, temperature=0.2):
        yield from ()


def test_agent_loop_creates_chart_when_explicitly_requested(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)
    provider = BreakdownProvider()
    router = ToolRouter(tmp_path)
    loop = AgentLoop(provider, router, max_iterations=3)
    dataset = Path(__file__).parent.parent / "examples" / "sales" / "sales.csv"
    ctx = AgentContext(workspace=tmp_path, dataset_path=str(dataset))

    result = loop.run(
        "Create a chart showing which region contributed most revenue.",
        ctx,
        auto_approve=True,
    )

    assert any(path.endswith("region_revenue_breakdown.png") for path in result.artifacts)
    chart_events = [event for event in AnalysisState(tmp_path).list_events() if event.event_type == "chart_created"]
    assert any(event.outputs.get("chart_type") == "bar" for event in chart_events)


def test_agent_loop_denied_chart_write_keeps_session_usable(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)
    requested: list[str] = []

    def deny(tool_name: str, arguments: dict) -> bool:
        requested.append(tool_name)
        return False

    loop = AgentLoop(
        BreakdownProvider(),
        ToolRouter(tmp_path),
        max_iterations=3,
        approval_callback=deny,
    )
    dataset = Path(__file__).parent.parent / "examples" / "sales" / "sales.csv"
    ctx = AgentContext(workspace=tmp_path, dataset_path=str(dataset))

    result = loop.run("Create a chart showing which region contributed most revenue.", ctx)

    assert requested == ["create_chart"]
    assert not any(path.endswith(".png") for path in result.artifacts)
    assert "North contributed" in result.findings
    assert result.session_id


def test_agent_loop_plan_includes_driver_checks_for_drop_question(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)
    provider = MarchDropProvider()
    router = ToolRouter(tmp_path)
    loop = AgentLoop(provider, router, max_iterations=3)
    dataset = Path(__file__).parent.parent / "examples" / "sales" / "sales.csv"
    ctx = AgentContext(workspace=tmp_path, dataset_path=str(dataset))

    result = loop.run("Why did revenue drop in March?", ctx)

    joined = " ".join(result.analysis_plan).lower()
    assert "average or per-transaction" in joined
    assert "categorical dimensions" in joined


class DuplicateSuccessSQLProvider:
    name = "mock"

    def __init__(self) -> None:
        self.calls = 0
        self.messages_seen: list[list[ModelMessage]] = []

    def generate(self, messages, tools=None, model=None, temperature=0.2):
        self.calls += 1
        self.messages_seen.append(list(messages))
        query = (
            "SELECT date_trunc('month', CAST(date AS DATE)) AS month, "
            "SUM(revenue) AS revenue FROM sales GROUP BY 1 ORDER BY 1"
        )
        if self.calls <= 2:
            return ModelResponse(
                tool_calls=[
                    ModelToolCall(
                        id=str(self.calls),
                        name="run_duckdb_query",
                        arguments={"query": query},
                    )
                ]
            )
        return ModelResponse(content="## Findings\nStopped repeating the same monthly totals query.")

    def stream(self, messages, tools=None, model=None, temperature=0.2):
        yield from ()


def test_agent_loop_blocks_duplicate_successful_sql_and_nudges_plan(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)
    provider = DuplicateSuccessSQLProvider()
    router = ToolRouter(tmp_path)
    loop = AgentLoop(provider, router, max_iterations=5)
    dataset = Path(__file__).parent.parent / "examples" / "sales" / "sales.csv"
    ctx = AgentContext(workspace=tmp_path, dataset_path=str(dataset))

    result = loop.run("Why did revenue drop in March?", ctx)

    query_artifacts = [a for a in ArtifactRegistry(tmp_path).list_all() if a.artifact_type == "query"]
    assert len(query_artifacts) == 1
    assert any(
        "Adaptive checklist" in (m.content or "")
        for batch in provider.messages_seen
        for m in batch
    )
    assert any(
        "Do not repeat identical successful queries" in (m.content or "")
        or "exactly one next tool call" in (m.content or "")
        or "Still needed:" in (m.content or "")
        for batch in provider.messages_seen
        for m in batch
    )
    assert any(event.event_type == "analysis_plan_revised" for event in AnalysisState(tmp_path).list_events())
    assert "average or per-transaction" in " ".join(result.analysis_plan).lower()
    assert "Repair hint" in result.content or "identical successful" in result.content.lower()
