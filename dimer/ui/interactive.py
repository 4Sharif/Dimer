"""Interactive chat session."""

from __future__ import annotations

from pathlib import Path

from prompt_toolkit import PromptSession

from dimer.agent.events import CallbackEventSink
from dimer.agent.loop import AgentLoop
from dimer.agent.session import AgentContext
from dimer.agent.tool_router import ToolRouter
from dimer.config import load_config
from dimer.data_context.artifact_registry import ArtifactRegistry
from dimer.data_context.assumption_log import AssumptionLog
from dimer.data_context.schema_profile import profile_dataset, save_profile
from dimer.data_context.workspace_scanner import scan_workspace
from dimer.providers.base import create_provider
from dimer.storage.artifacts import ensure_workspace_dirs
from dimer.ui.console import DimerConsole


SLASH_COMMANDS = {
    "/help": "Show available commands",
    "/exit": "Exit chat",
    "/context": "Show workspace context",
    "/artifacts": "List artifacts",
    "/assumptions": "List assumptions",
    "/mode analysis": "Switch to analysis mode",
    "/mode sql": "Switch to SQL mode",
}


class InteractiveSession:
    def __init__(self, workspace: Path | None = None) -> None:
        self.workspace = (workspace or Path.cwd()).resolve()
        self.console = DimerConsole()
        self.config = load_config()
        self.mode = "analysis"
        self.dataset_path: str | None = None
        self.prompt = PromptSession()
        ensure_workspace_dirs(self.workspace)

    def _handle_slash(self, text: str) -> bool:
        cmd = text.strip().lower()
        if cmd in ("/exit", "/quit"):
            return False
        if cmd == "/help":
            for k, v in SLASH_COMMANDS.items():
                self.console.print(f"  {k}: {v}")
            self.console.print("  /profile <path>: Profile a dataset")
            return True
        if cmd == "/context":
            scan = scan_workspace(self.workspace)
            self.console.print(scan)
            return True
        if cmd == "/artifacts":
            for a in ArtifactRegistry(self.workspace).list_all():
                self.console.print(f"  [{a.artifact_type}] {a.path}")
            return True
        if cmd == "/assumptions":
            for a in AssumptionLog(self.workspace).list_all():
                self.console.print(f"  - {a.text}")
            return True
        if cmd == "/mode analysis":
            self.mode = "analysis"
            self.console.success("Switched to analysis mode")
            return True
        if cmd == "/mode sql":
            self.mode = "sql"
            self.console.success("Switched to SQL mode")
            return True
        if cmd.startswith("/profile "):
            path = text.split(maxsplit=1)[1].strip()
            profile = profile_dataset(path)
            out = save_profile(profile, self.workspace)
            self.console.render_profile_summary(profile.model_dump(mode="json"))
            self.console.success(f"Profile saved to {out}")
            self.dataset_path = str(Path(path).resolve())
            return True
        self.console.warn(f"Unknown command: {text}")
        return True

    def run(self) -> None:
        self.console.print("[bold]Dimer interactive chat[/bold] — type /help for commands, /exit to quit")
        provider = create_provider(config=self.config)
        router = ToolRouter(self.workspace, self.config)
        sink = CallbackEventSink(self.console.render_event)

        while True:
            try:
                user_input = self.prompt.prompt("dimer> ")
            except (EOFError, KeyboardInterrupt):
                break
            if not user_input.strip():
                continue
            if user_input.startswith("/"):
                if not self._handle_slash(user_input):
                    break
                continue

            context = AgentContext(
                workspace=self.workspace,
                dataset_path=self.dataset_path,
                mode=self.mode,
            )
            loop = AgentLoop(provider, router, event_sink=sink, config=self.config)
            try:
                result = loop.run(user_input, context, auto_approve=True)
                self.console.print()
                self.console.print(result.content)
                if result.artifacts:
                    self.console.print("\n[bold]Artifacts:[/bold]")
                    for a in result.artifacts[-5:]:
                        self.console.print(f"  - {a}")
            except Exception as e:
                self.console.error(str(e))

        self.console.info("Goodbye")
