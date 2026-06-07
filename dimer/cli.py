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
from dimer.data_context.artifact_registry import ArtifactRegistry
from dimer.data_context.assumption_log import AssumptionLog
from dimer.data_context.schema_profile import profile_dataset, save_profile
from dimer.data_context.workspace_scanner import scan_workspace
from dimer.providers.base import create_provider
from dimer.storage.artifacts import ensure_workspace_dirs, get_dimer_dir, get_workspace_root
from dimer.tools.duckdb_exec import run_duckdb_query
from dimer.ui.console import DimerConsole
from dimer.ui.interactive import InteractiveSession

app = typer.Typer(name="dimer", help="Terminal-native AI agent for data workflows")
console = DimerConsole()


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
def profile(
    dataset_path: Path = typer.Argument(..., help="Path to dataset file"),
    sample: bool = typer.Option(False, "--sample", help="Include sample rows in profile"),
) -> None:
    """Profile a dataset (CSV, Parquet, Excel)."""
    config = load_config()
    ws = get_workspace_root()
    ensure_workspace_dirs(ws)
    prof = profile_dataset(
        dataset_path,
        include_sample=sample or config.privacy.send_sample_rows,
        max_sample_rows=config.privacy.max_sample_rows,
        redact_pii=config.privacy.redact_pii,
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
def artifacts() -> None:
    """List generated artifacts."""
    ws = get_workspace_root()
    items = ArtifactRegistry(ws).list_all()
    if not items:
        console.info("No artifacts registered yet")
        return
    for a in items:
        console.print(f"[{a.artifact_type}] {a.path}")


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
def ask(
    dataset_path: Path = typer.Argument(..., help="Path to dataset or workspace focus"),
    question: str = typer.Argument(..., help="Analysis question"),
    provider: Optional[str] = typer.Option(None, "--provider", help="LLM provider override"),
    mode: str = typer.Option("analysis", "--mode", help="Agent mode: analysis or sql"),
) -> None:
    """Run a one-shot data analysis question."""
    ws = get_workspace_root()
    ensure_workspace_dirs(ws)
    config = load_config()
    sink = CallbackEventSink(console.render_event)

    try:
        model_provider = create_provider(provider, config)
    except Exception as e:
        console.error(f"Failed to create provider: {e}")
        raise typer.Exit(1)

    router = ToolRouter(ws, config)
    loop = AgentLoop(model_provider, router, event_sink=sink, config=config)
    ctx = AgentContext(
        workspace=ws,
        dataset_path=str(dataset_path.resolve()),
        mode=mode,
    )

    console.info(
        f"Analyzing {dataset_path} with {provider or config.default_provider} "
        f"({config.default_model}) ..."
    )
    try:
        result = loop.run(question, ctx, auto_approve=True)
    except Exception as e:
        console.error(str(e))
        raise typer.Exit(1)

    console.print()
    console.print(result.content)
    if result.artifacts:
        console.print("\n[bold]Artifacts:[/bold]")
        for a in result.artifacts:
            console.print(f"  - {a}")
    if result.assumptions:
        console.print("\n[bold]Assumptions:[/bold]")
        for a in result.assumptions:
            console.print(f"  - {a}")
    console.success(f"Session saved: {result.session_id}")


@app.command()
def chat(
    path: Optional[Path] = typer.Argument(None, help="Workspace path (default: cwd)"),
) -> None:
    """Start an interactive chat session."""
    ws = get_workspace_root(path)
    ensure_workspace_dirs(ws)
    session = InteractiveSession(ws)
    session.run()


if __name__ == "__main__":
    app()
