"""Dimer CLI entry point."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from dimer.agent.events import CallbackEventSink
from dimer.agent.loop import AgentLoop
from dimer.agent.session import AgentContext
from dimer.agent.tool_router import ToolRouter
from dimer.config import ensure_user_config, load_config
from dimer.data_context.analysis_state import AnalysisState, format_trace
from dimer.data_context.artifact_registry import ArtifactRegistry
from dimer.data_context.assumption_log import AssumptionLog
from dimer.data_context.schema_profile import profile_dataset, save_profile
from dimer.data_context.workspace_scanner import scan_workspace
from dimer.providers.base import create_provider
from dimer.safety.permissions import enforce_workspace_path
from dimer.safety.pii import redact_sensitive_text
from dimer.safety.privacy import provider_context_warning
from dimer.storage.artifacts import ensure_workspace_dirs, get_dimer_dir, get_workspace_root
from dimer.tools.duckdb_exec import run_duckdb_query
from dimer.ui.console import DimerConsole
from dimer.ui.interactive import InteractiveSession

app = typer.Typer(name="dimer", help="Chat-first terminal agent for evidence-backed data analysis")
console = DimerConsole()


def _resolve_explicit_focus_path(path: Path, workspace: Path) -> Path:
    """Apply ignore policy while allowing a user-selected focus outside the workspace."""

    candidate = path.expanduser()
    if not candidate.is_absolute():
        candidate = workspace / candidate
    try:
        return enforce_workspace_path(
            candidate,
            workspace,
            allowed_outside_paths=(candidate,),
        )
    except PermissionError as exc:
        console.error(str(exc))
        raise typer.Exit(1) from exc


@app.callback()
def main() -> None:
    """Dimer CLI."""
    ensure_user_config()


@app.command()
def init(
    path: Optional[Path] = typer.Argument(None, help="Workspace path (default: cwd)"),
) -> None:
    """Initialize .dimer workspace directory."""
    ws = get_workspace_root(path)
    dimer_dir = ensure_workspace_dirs(ws)
    console.success(f"Initialized Dimer workspace at {dimer_dir}")


@app.command()
def doctor() -> None:
    """Check selected provider configuration, completion, and tool round trip."""
    from dimer.application.doctor import run_doctor

    try:
        config = load_config()
        report = run_doctor(config)
    except Exception as exc:
        console.error(
            f"Configuration could not be loaded: {redact_sensitive_text(str(exc))}"
        )
        raise typer.Exit(1) from exc

    console.info(f"Provider: {report.provider}")
    console.info(f"Model: {report.model}")
    console.info(f"Endpoint: {report.endpoint}")
    if report.data_locality == "local":
        console.info("Data handling: local — model context stays on this machine")
    elif report.data_locality == "cloud":
        console.warn("Data handling: cloud — model context may leave this machine")
    else:
        console.warn("Data handling: unknown — review the configured endpoint")

    for check in report.checks:
        message = f"{check.name}: {check.status} — {check.detail}"
        if check.status == "pass":
            console.success(message)
        elif check.status == "fail":
            console.error(message)
        else:
            console.info(message)

    if not report.ok:
        raise typer.Exit(1)


@app.command()
def profile(
    dataset_path: Path = typer.Argument(..., help="Path to dataset file"),
    sample: bool = typer.Option(False, "--sample", help="Include sample rows in profile"),
) -> None:
    """Profile a dataset (CSV, Parquet, Excel)."""
    from dimer.data_context.data_quality import detect_schema_drift
    from dimer.data_context.schema_profile import load_profile

    config = load_config()
    ws = get_workspace_root()
    ensure_workspace_dirs(ws)
    dataset_path = _resolve_explicit_focus_path(dataset_path, ws)
    previous = load_profile(dataset_path, ws)
    prof = profile_dataset(
        dataset_path,
        include_sample=sample or config.privacy.send_sample_rows,
        max_sample_rows=config.privacy.max_sample_rows,
        redact_pii=config.privacy.redact_pii,
    )
    if previous is not None:
        drift = detect_schema_drift(previous, prof)
        if drift:
            prof.quality_warnings = list(
                dict.fromkeys([*[f.message for f in drift], *prof.quality_warnings])
            )
    out = save_profile(prof, ws)
    console.render_profile_summary(prof.model_dump(mode="json"))
    console.success(f"Profile saved to {out}")


@app.command()
def context(
    path: Optional[Path] = typer.Argument(None, help="Workspace path (default: cwd)"),
) -> None:
    """Scan workspace and summarize data assets."""
    ws = get_workspace_root(path)
    ensure_workspace_dirs(ws)
    scan = scan_workspace(ws)
    console.print(json.dumps(scan, indent=2))


@app.command()
def sql(
    dataset_path: Path = typer.Argument(..., help="Path to dataset"),
    query: str = typer.Argument(..., help="SQL query"),
    max_rows: int = typer.Option(50, "--max-rows", help="Max preview rows"),
) -> None:
    """Run a DuckDB SQL query against a local dataset."""
    ws = get_workspace_root()
    ensure_workspace_dirs(ws)
    dataset_path = _resolve_explicit_focus_path(dataset_path, ws)
    if redact_sensitive_text(query) != query:
        console.error("Queries containing secret-shaped values cannot be persisted")
        raise typer.Exit(1)
    result = run_duckdb_query(query, data_paths=[str(dataset_path)], max_rows=max_rows)
    if result.get("error"):
        console.error(result["error"])
        raise typer.Exit(1)
    from datetime import datetime, timezone

    queries_dir = get_dimer_dir(ws) / "artifacts" / "queries"
    queries_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    query_path = queries_dir / f"query-{stamp}.sql"
    query_path.write_text(query, encoding="utf-8")
    ArtifactRegistry(ws).register(query_path, "query", description=query[:120])
    console.print(json.dumps(result, indent=2, default=str))
    console.success(f"Query saved to {query_path}")


@app.command()
def artifacts(
    all_artifacts: bool = typer.Option(False, "--all", help="List all artifacts instead of recent ones"),
    limit: int = typer.Option(15, "--limit", help="Maximum artifacts to show (ignored with --all)"),
    artifact_type: Optional[str] = typer.Option(None, "--type", help="Filter by type: query, report, chart, ..."),
    session: Optional[str] = typer.Option(None, "--session", help="Filter by session id"),
) -> None:
    """List generated artifacts (newest first; defaults to recent)."""
    from dimer.data_context.artifact_registry import format_artifact_line

    ws = get_workspace_root()
    reg = ArtifactRegistry(ws)
    items = reg.list_filtered(
        artifact_type=artifact_type,
        session_id=session,
        limit=None if all_artifacts else limit,
    )
    if not items:
        if session:
            console.info(f"No artifacts found for session {session}")
        else:
            console.info("No artifacts registered yet")
        return
    scope = "all" if all_artifacts else f"latest {len(items)}"
    if session:
        scope = f"session {session}"
    console.info(f"Showing {scope} artifact(s)")
    for a in items:
        console.print(format_artifact_line(a, ws))


@app.command()
def assumptions() -> None:
    """List recorded assumptions."""
    ws = get_workspace_root()
    items = AssumptionLog(ws).list_all()
    if not items:
        console.info("No assumptions recorded yet")
        return
    for a in items:
        conf = f" ({a.confidence})" if a.confidence else ""
        console.print(f"- {a.text}{conf}")


@app.command()
def trace(
    target: str = typer.Argument(..., help="Artifact path, event id, column, or lineage target"),
    limit: int = typer.Option(20, "--limit", help="Maximum lineage events to show"),
    session: Optional[str] = typer.Option(
        None,
        "--session",
        help="Session id to scope the trace (default: latest session)",
    ),
    all_sessions: bool = typer.Option(
        False,
        "--all",
        help="Search all analysis history instead of the latest/selected session",
    ),
) -> None:
    """Trace analysis lineage for a target (defaults to latest session)."""
    from dimer.data_context.analysis_state import resolve_trace_session

    ws = get_workspace_root()
    ensure_workspace_dirs(ws)
    session_id = resolve_trace_session(ws, session=session, all_sessions=all_sessions)
    events = AnalysisState(ws).trace(target, limit=limit, session_id=session_id)
    if session_id and not all_sessions:
        console.info(f"Tracing session {session_id} (use --all for full history)")
    console.print(format_trace(events, target=target, session_id=session_id))


@app.command()
def notebook(
    path: Path = typer.Argument(..., help="Path to a .ipynb notebook"),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON summary"),
) -> None:
    """Summarize a Jupyter notebook (read-only)."""
    from dimer.data_context.notebook_context import format_notebook_summary, summarize_notebook

    ws = get_workspace_root()
    ensure_workspace_dirs(ws)
    target = _resolve_explicit_focus_path(path, ws)
    try:
        summary = summarize_notebook(target)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as e:
        console.error(str(e))
        raise typer.Exit(1)
    if json_output:
        console.print(json.dumps(summary, indent=2, default=str))
    else:
        console.print(format_notebook_summary(summary))


@app.command()
def sessions(
    limit: int = typer.Option(20, "--limit", help="Maximum sessions to list"),
) -> None:
    """List recent saved agent sessions."""
    from dimer.storage.sessions import format_session_list, list_sessions

    ws = get_workspace_root()
    ensure_workspace_dirs(ws)
    console.print(format_session_list(list_sessions(ws, limit=limit)))


@app.command("session")
def session_cmd(
    session_id: str = typer.Argument(..., help="Session id, e.g. session-20260711-190354"),
) -> None:
    """Replay a saved agent session."""
    from dimer.storage.sessions import format_session_replay, load_session

    ws = get_workspace_root()
    ensure_workspace_dirs(ws)
    try:
        data = load_session(session_id, ws)
    except FileNotFoundError as e:
        console.error(str(e))
        raise typer.Exit(1)
    console.print(format_session_replay(session_id, data))


@app.command("export")
def export_cmd(
    session_id: Optional[str] = typer.Argument(
        None,
        help="Session id (default: latest saved session)",
    ),
) -> None:
    """Export successful session SQL as a replayable DuckDB script."""
    from dimer.pipeline.export_session import export_session

    ws = get_workspace_root()
    try:
        result = export_session(session_id, ws)
    except (FileNotFoundError, ValueError) as e:
        console.error(str(e))
        raise typer.Exit(1)

    console.success(f"Script exported to {result.script_path}")
    console.info(f"Manifest: {result.manifest_path}")
    if result.verified:
        noun = "query" if result.query_count == 1 else "queries"
        console.success(f"Verified {result.query_count} SQL {noun}")
    else:
        console.warn("Export created, but replay verification reported warnings:")
        for warning in result.warnings:
            console.warn(f"- {warning}")


@app.command()
def ask(
    dataset_path: Path = typer.Argument(..., help="Path to dataset or workspace focus"),
    question: str = typer.Argument(..., help="Analysis question"),
    provider: Optional[str] = typer.Option(None, "--provider", help="LLM provider override"),
    model: Optional[str] = typer.Option(None, "--model", help="Model override for this run"),
    auto_approve: bool = typer.Option(
        False,
        "--auto-approve/--no-auto-approve",
        help="Run unsafe operations without prompting (advanced)",
    ),
) -> None:
    """Run a one-shot data analysis question."""
    from dimer.ui.approvals import request_tool_approval

    focus = dataset_path.resolve()
    ws = get_workspace_root(focus if focus.is_dir() else None)
    ensure_workspace_dirs(ws)
    config = load_config()
    sink = CallbackEventSink(console.render_event)

    if auto_approve:
        console.warn(
            "Automatic approval is enabled: Python and workspace writes may run without prompting."
        )

    try:
        model_provider = create_provider(provider, config)
    except Exception as e:
        console.error(f"Failed to create provider: {e}")
        raise typer.Exit(1)

    provider_name = provider or config.default_provider
    privacy_warning = provider_context_warning(config, provider_name)
    if privacy_warning:
        console.warn(privacy_warning)

    approval_callback = None
    if not auto_approve:
        approval_callback = lambda tool_name, arguments: request_tool_approval(
            tool_name,
            arguments,
            event_sink=sink,
            default=False,
        )

    router = ToolRouter(ws, config)
    loop = AgentLoop(
        model_provider,
        router,
        event_sink=sink,
        config=config,
        model=model,
        approval_callback=approval_callback,
    )
    dataset_path_value: str | None = None
    notebook_path_value: str | None = None
    if focus.is_file():
        if focus.suffix.lower() == ".ipynb":
            notebook_path_value = str(focus)
        else:
            dataset_path_value = str(focus)
    ctx = AgentContext(
        workspace=ws,
        dataset_path=dataset_path_value,
        notebook_path=notebook_path_value,
    )
    selected_model = model or str(getattr(model_provider, "default_model", config.default_model))

    console.info(
        f"Analyzing {dataset_path} with {provider_name} "
        f"({selected_model}) ..."
    )
    try:
        result = loop.run(question, ctx, auto_approve=auto_approve)
    except Exception as e:
        console.error(str(e))
        raise typer.Exit(1)

    console.print()
    console.print(result.content)
    console.success(f"Session saved: {result.session_id}")


@app.command()
def chat(
    path: Optional[Path] = typer.Argument(None, help="Workspace path (default: cwd)"),
) -> None:
    """Start an interactive scrollback chat session."""
    ws = get_workspace_root(path)
    ensure_workspace_dirs(ws)
    session = InteractiveSession(ws)
    session.run()


if __name__ == "__main__":
    app()
