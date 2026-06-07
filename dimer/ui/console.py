"""Rich console renderer for Dimer events and output."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from dimer.agent.events import DimerEvent


class DimerConsole:
    def __init__(self) -> None:
        self.console = Console()

    def print(self, *args, **kwargs) -> None:
        self.console.print(*args, **kwargs)

    def success(self, message: str) -> None:
        self.console.print(f"[green]✓[/green] {message}")

    def error(self, message: str) -> None:
        self.console.print(f"[red]✗[/red] {message}")

    def info(self, message: str) -> None:
        self.console.print(f"[blue]→[/blue] {message}")

    def warn(self, message: str) -> None:
        self.console.print(f"[yellow]![/yellow] {message}")

    def render_event(self, event: DimerEvent) -> None:
        if event.type in ("agent_message_delta",):
            if event.message:
                self.console.print(event.message, end="")
            return
        if event.type == "model_call_started":
            self.info(event.message or "Calling model...")
            return
        if event.type == "model_call_finished":
            if event.payload.get("has_tool_calls"):
                self.info("Model requested tool call(s)")
            return
        if event.type.startswith("tool_call"):
            tool = event.payload.get("tool_name", "")
            if event.type == "tool_call_started":
                self.info(f"Running tool: {tool}")
            elif event.type == "tool_call_failed":
                self.error(f"Tool failed: {tool}")
            elif event.type == "tool_call_finished":
                self.success(f"Tool finished: {tool}")
            else:
                self.info(f"{event.type}: {tool}")
            return
        if event.type in ("dataset_profile_finished", "chart_created", "report_saved"):
            self.success(event.message or event.type)
            return
        if event.type in ("agent_started", "agent_iteration", "agent_finished"):
            if event.message:
                self.info(event.message)
            return
        if event.message:
            self.info(event.message)

    def render_profile_summary(self, profile: dict) -> None:
        table = Table(title=f"Dataset Profile: {profile.get('path', '')}")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="white")
        table.add_row("File type", str(profile.get("file_type", "")))
        table.add_row("File size", _format_bytes(profile.get("file_size_bytes", 0)))
        table.add_row("Rows", str(profile.get("row_count", "")))
        table.add_row("Columns", str(profile.get("column_count", "")))
        table.add_row("Duplicates", str(profile.get("duplicate_count", "")))
        self.console.print(table)

        cols = profile.get("columns", [])
        if cols:
            col_table = Table(title="Columns")
            col_table.add_column("Name")
            col_table.add_column("Dtype")
            col_table.add_column("Missing")
            col_table.add_column("Missing %")
            for col in cols:
                col_table.add_row(
                    col["name"],
                    col.get("dtype", ""),
                    str(col.get("missing_count", 0)),
                    f"{col.get('missing_pct', 0):.1f}%",
                )
            self.console.print(col_table)

        warnings = profile.get("quality_warnings", [])
        if warnings:
            self.console.print(Panel("\n".join(f"• {w}" for w in warnings), title="Quality Warnings"))

        id_cols = profile.get("potential_id_columns", [])
        target_cols = profile.get("potential_target_columns", [])
        if id_cols or target_cols:
            hints = Table(title="Column Hints")
            hints.add_column("Type")
            hints.add_column("Columns")
            if id_cols:
                hints.add_row("Potential IDs", ", ".join(id_cols))
            if target_cols:
                hints.add_row("Potential targets", ", ".join(target_cols))
            self.console.print(hints)


def _format_bytes(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}" if unit != "B" else f"{size} B"
        size /= 1024
    return f"{size:.1f} TB"
