"""Tests for analysis-state lineage and SQL transform capture."""

from __future__ import annotations

from pathlib import Path

from dimer.data_context.analysis_state import AnalysisState, format_trace, lineage_from_sql
from dimer.data_context.sql_lineage import extract_sql_lineage
from dimer.storage.artifacts import ensure_workspace_dirs
from dimer.tools.chart import register_chart
from dimer.tools.dataset_profile import tool_inspect_dataset
from dimer.tools.report import save_report


def test_extract_sql_lineage_captures_filter_group_and_columns() -> None:
    query = (
        "SELECT region, SUM(revenue) AS total "
        "FROM sales WHERE month = '2024-03' "
        "GROUP BY region ORDER BY total DESC"
    )
    lineage = extract_sql_lineage(query)

    assert "region" in lineage["columns"]
    assert "revenue" in lineage["columns"]
    assert "total" in lineage["columns"]
    ops = {t["op"] for t in lineage["transforms"]}
    assert {"filter", "group_by", "order_by", "aggregate"} <= ops


def test_analysis_state_redacts_secrets_before_persistence(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)
    secret = "sk-supersecretvalue123456"

    event = AnalysisState(tmp_path).record(
        "test_event",
        inputs={"query": f"SELECT '{secret}'"},
        reason=f"token={secret}",
    )

    raw = (tmp_path / ".dimer" / "analysis_state.jsonl").read_text(encoding="utf-8")
    assert secret not in raw
    assert "[REDACTED_SECRET]" in raw
    assert secret not in str(event)


def test_lineage_from_sql_adds_source_transform() -> None:
    lineage = lineage_from_sql(
        "SELECT region, SUM(revenue) FROM sales GROUP BY region",
        data_paths=["examples/sales/sales.csv"],
    )
    assert lineage["transforms"][0] == {"op": "source", "paths": ["examples/sales/sales.csv"]}
    assert "revenue" in lineage["columns"]


def test_analysis_state_graph_trace_walks_parents(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)
    state = AnalysisState(tmp_path)

    query_event = state.record(
        "sql_query_run",
        inputs={"query": "SELECT region, SUM(revenue) AS total FROM sales GROUP BY region"},
        outputs={"columns": ["region", "total"]},
        artifact_paths=[str(tmp_path / ".dimer" / "artifacts" / "queries" / "q1.sql")],
        columns=["region", "revenue", "total"],
        transforms=[
            {"op": "source", "paths": ["sales.csv"]},
            {"op": "group_by", "expr": "region", "columns": ["region"]},
            {"op": "aggregate", "expr": "SUM(revenue) AS total"},
        ],
        tool_source="run_duckdb_query",
    )
    chart_path = tmp_path / ".dimer" / "artifacts" / "charts" / "region.png"
    chart_path.parent.mkdir(parents=True, exist_ok=True)
    chart_path.write_bytes(b"png")
    chart_event = state.record(
        "chart_created",
        inputs={"source_artifacts": [query_event.artifact_paths[0]]},
        outputs={"chart_type": "bar"},
        artifact_paths=[str(chart_path)],
        parent_ids=[query_event.id],
        columns=["region", "revenue"],
        tool_source="create_chart",
    )

    traced = state.trace(str(chart_path), limit=10)
    traced_ids = {event.id for event in traced}
    assert chart_event.id in traced_ids
    assert query_event.id in traced_ids

    by_column = state.trace("revenue", limit=10)
    assert any(event.id == query_event.id for event in by_column)
    assert any(event.id == chart_event.id for event in by_column)

    rendered = format_trace(traced)
    assert "Lineage:" in rendered
    assert "dataset `sales.csv`" in rendered
    assert "sql (" in rendered
    assert "chart `region.png`" in rendered
    assert "Events:" in rendered
    assert "Parents:" in rendered
    assert "Transforms:" in rendered
    assert query_event.id in rendered


def test_sql_links_to_dataset_and_trace_shows_full_chain(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)
    dataset = Path(__file__).parent.parent / "examples" / "sales" / "sales.csv"
    tool_inspect_dataset(str(dataset), workspace=tmp_path)

    state = AnalysisState(tmp_path)
    parent_ids = state.find_event_ids_for_datasets([str(dataset)])
    assert len(parent_ids) == 1

    query_path = tmp_path / ".dimer" / "artifacts" / "queries" / "q.sql"
    query_path.parent.mkdir(parents=True, exist_ok=True)
    query_path.write_text("SELECT region, SUM(revenue) FROM sales GROUP BY region", encoding="utf-8")
    query_event = state.record(
        "sql_query_run",
        inputs={"query": "SELECT region, SUM(revenue) FROM sales GROUP BY region", "data_paths": [str(dataset)]},
        artifact_paths=[str(query_path.resolve())],
        parent_ids=parent_ids,
        columns=["region", "revenue"],
        transforms=[
            {"op": "source", "paths": [str(dataset)]},
            {"op": "group_by", "expr": "region"},
            {"op": "aggregate", "expr": "SUM(revenue)"},
        ],
    )
    chart_path = tmp_path / ".dimer" / "artifacts" / "charts" / "out.png"
    chart_path.parent.mkdir(parents=True, exist_ok=True)
    chart_path.write_bytes(b"png")
    register_chart(
        chart_path,
        description="region breakdown",
        workspace=tmp_path,
        metadata={
            "source_artifacts": [str(query_path.resolve())],
            "columns": ["region", "revenue"],
            "chart_type": "bar",
        },
    )

    traced = state.trace(str(chart_path), limit=10)
    types = {event.event_type for event in traced}
    assert "dataset_inspected" in types
    assert "sql_query_run" in types
    assert "chart_created" in types
    assert query_event.id in {event.id for event in traced}

    rendered = format_trace(traced)
    assert "dataset `sales.csv` → sql (" in rendered
    assert "→ chart `out.png`" in rendered


def test_column_centric_trace_shows_usage(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)
    state = AnalysisState(tmp_path)
    dataset_event = state.record(
        "dataset_inspected",
        inputs={"path": "sales.csv"},
        artifact_paths=[str((tmp_path / "sales.csv").resolve())],
        columns=["region", "revenue", "date"],
    )
    query_event = state.record(
        "sql_query_run",
        inputs={"query": "SELECT region, SUM(revenue) FROM sales GROUP BY region"},
        artifact_paths=[str(tmp_path / ".dimer" / "artifacts" / "queries" / "q.sql")],
        parent_ids=[dataset_event.id],
        columns=["region", "revenue"],
        transforms=[
            {"op": "source", "paths": ["sales.csv"]},
            {"op": "group_by", "expr": "region", "columns": ["region"]},
            {"op": "aggregate", "expr": "SUM(revenue)"},
        ],
    )
    chart_path = tmp_path / ".dimer" / "artifacts" / "charts" / "rev.png"
    chart_path.parent.mkdir(parents=True, exist_ok=True)
    chart_path.write_bytes(b"png")
    state.record(
        "chart_created",
        artifact_paths=[str(chart_path)],
        parent_ids=[query_event.id],
        columns=["region", "revenue"],
    )

    # Unrelated noise that mentions revenue only in free text should not seed first.
    state.record(
        "assumption_added",
        inputs={"text": "Ignore revenue wording here"},
        outputs={},
    )

    traced = state.trace("revenue", limit=10)
    assert all(event.event_type != "assumption_added" for event in traced)
    assert any(event.event_type == "sql_query_run" for event in traced)
    assert any(event.event_type == "chart_created" for event in traced)

    rendered = format_trace(traced, target="revenue")
    assert "Column `revenue`:" in rendered
    assert "aggregate" in rendered
    assert "plotted" in rendered
    assert "Column use:" in rendered


def test_session_scoped_trace_excludes_other_sessions(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)
    state = AnalysisState(tmp_path)
    dataset = state.record(
        "dataset_inspected",
        inputs={"path": "sales.csv"},
        artifact_paths=[str((tmp_path / "sales.csv").resolve())],
        columns=["revenue", "region"],
    )
    old_query = state.record(
        "sql_query_run",
        inputs={"query": "SELECT SUM(revenue) FROM sales", "session_id": "session-old"},
        artifact_paths=[str(tmp_path / ".dimer" / "artifacts" / "queries" / "old.sql")],
        parent_ids=[dataset.id],
        columns=["revenue"],
        transforms=[{"op": "aggregate", "expr": "SUM(revenue)"}],
        session_id="session-old",
    )
    new_query = state.record(
        "sql_query_run",
        inputs={"query": "SELECT region, SUM(revenue) FROM sales GROUP BY region", "session_id": "session-new"},
        artifact_paths=[str(tmp_path / ".dimer" / "artifacts" / "queries" / "new.sql")],
        parent_ids=[dataset.id],
        columns=["region", "revenue"],
        transforms=[
            {"op": "group_by", "expr": "region", "columns": ["region"]},
            {"op": "aggregate", "expr": "SUM(revenue)"},
        ],
        session_id="session-new",
    )
    chart_path = tmp_path / ".dimer" / "artifacts" / "charts" / "shared_name.png"
    chart_path.parent.mkdir(parents=True, exist_ok=True)
    chart_path.write_bytes(b"png")
    # Old chart reuses the same filename later runs will use.
    state.record(
        "chart_created",
        artifact_paths=[str(chart_path)],
        parent_ids=[old_query.id],
        columns=["revenue"],
        session_id="session-old",
    )
    new_chart = state.record(
        "chart_created",
        artifact_paths=[str(chart_path)],
        parent_ids=[new_query.id],
        columns=["region", "revenue"],
        session_id="session-new",
    )

    scoped = state.trace("revenue", session_id="session-new", limit=20)
    scoped_ids = {event.id for event in scoped}
    assert new_query.id in scoped_ids
    assert new_chart.id in scoped_ids
    assert dataset.id in scoped_ids  # ancestor still included
    assert old_query.id not in scoped_ids

    parents = state.find_event_ids_for_artifacts([str(chart_path)], session_id="session-new")
    assert new_chart.id in parents or new_query.id in parents
    assert old_query.id not in parents

    rendered = format_trace(scoped, target="revenue", session_id="session-new")
    assert "Scope: session `session-new`" in rendered
    assert "session-old" not in rendered


def test_resolve_trace_session_defaults_to_latest(tmp_path: Path) -> None:
    from dimer.data_context.analysis_state import resolve_trace_session
    from dimer.storage.sessions import save_session

    ensure_workspace_dirs(tmp_path)
    save_session("session-20260712-100000", {"question": "older"}, workspace=tmp_path)
    save_session("session-20260712-200000", {"question": "newer"}, workspace=tmp_path)

    assert resolve_trace_session(tmp_path) == "session-20260712-200000"
    assert resolve_trace_session(tmp_path, all_sessions=True) is None
    assert resolve_trace_session(tmp_path, session="session-custom") == "session-custom"


def test_register_chart_links_parent_query_event(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)
    state = AnalysisState(tmp_path)
    query_path = tmp_path / ".dimer" / "artifacts" / "queries" / "q.sql"
    query_path.parent.mkdir(parents=True, exist_ok=True)
    query_path.write_text("SELECT 1", encoding="utf-8")
    query_event = state.record(
        "sql_query_run",
        inputs={"query": "SELECT region, SUM(revenue) FROM sales GROUP BY region"},
        artifact_paths=[str(query_path.resolve())],
        columns=["region", "revenue"],
        transforms=[{"op": "group_by", "expr": "region"}],
    )

    chart_path = tmp_path / ".dimer" / "artifacts" / "charts" / "out.png"
    chart_path.parent.mkdir(parents=True, exist_ok=True)
    chart_path.write_bytes(b"png")
    register_chart(
        chart_path,
        description="region breakdown",
        workspace=tmp_path,
        metadata={
            "source_artifacts": [str(query_path.resolve())],
            "columns": ["region", "revenue"],
            "chart_type": "bar",
        },
    )

    chart_events = [e for e in state.list_events() if e.event_type == "chart_created"]
    assert len(chart_events) == 1
    assert query_event.id in chart_events[0].parent_ids

    report = save_report(
        "lineage-report.md",
        "# Report\n",
        workspace=tmp_path,
        metadata={"source_artifacts": [str(query_path.resolve())], "question": "why"},
    )
    report_events = [e for e in state.list_events() if e.event_type == "report_created"]
    assert len(report_events) == 1
    assert query_event.id in report_events[0].parent_ids
    assert Path(report["path"]).exists()
