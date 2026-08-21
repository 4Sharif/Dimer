"""Shared interactive session state and slash-command handling."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dimer.config import load_config
from dimer.data_context.analysis_state import AnalysisState, format_trace
from dimer.data_context.artifact_registry import ArtifactRegistry, format_artifact_line
from dimer.data_context.assumption_log import AssumptionLog
from dimer.data_context.schema_profile import profile_dataset, save_profile
from dimer.data_context.workspace_scanner import compact_workspace_summary
from dimer.providers.base import create_provider
from dimer.safety.privacy import provider_context_warning
from dimer.storage.artifacts import ensure_workspace_dirs
from dimer.storage.sessions import (
    format_session_list,
    format_session_replay,
    list_sessions,
    load_session,
)
from dimer.ui.status import format_status_strip


SLASH_COMMANDS = {
    "/help": "Show available commands",
    "/exit": "Exit",
    "/context": "Show workspace context",
    "/artifacts": "List recent artifacts",
    "/export": "Export session SQL as a replayable script",
    "/provider": "Show or switch the model provider",
    "/model": "Show or switch the model",
    "/trace": "Trace lineage for a column or artifact",
    "/profile": "Profile and select a dataset",
    "/status": "Show focus, provider, model, approvals, and session",
}

SLASH_ARGUMENTS = {
    "/artifacts": {
        "session": "Artifacts from the latest session",
        "all": "All recorded artifacts",
    },
    "/model": {
        "default": "Use the provider default model",
    },
    "/trace": {
        "all": "Trace across all analysis history",
        "session": "Trace within a specific session",
    },
}

SLASH_USAGE = {
    "/profile": "<path>",
    "/export": "[session_id]",
    "/provider": "[name]",
    "/model": "[name]",
    "/trace": "<target> | all <target> | session <id> <target>",
}


@dataclass
class SlashResult:
    """Outcome of a slash command."""

    should_exit: bool = False
    lines: list[str] = field(default_factory=list)
    profile: dict[str, Any] | None = None
    status_changed: bool = False


class SessionController:
    """Workspace session state for the scrollback chat interface."""

    def __init__(self, workspace: Path | None = None) -> None:
        self.workspace = (workspace or Path.cwd()).resolve()
        self.config = load_config()
        self.provider_name = self.config.default_provider
        self.model: str | None = None
        self.dataset_path: str | None = None
        self.notebook_path: str | None = None
        self.last_session_id: str | None = None
        self.auto_approve = False
        ensure_workspace_dirs(self.workspace)

    def approvals_label(self) -> str:
        return "auto" if self.auto_approve else "ask"

    def provider_context_warning(self) -> str | None:
        return provider_context_warning(self.config, self.provider_name)

    def status_strip(self) -> str:
        return format_status_strip(
            provider=self.provider_name,
            model=self.model,
            dataset=self.dataset_path,
            session_id=self.last_session_id,
            notebook=self.notebook_path,
            approvals=self.approvals_label(),
        )

    def agent_context(self):
        from dimer.agent.session import AgentContext

        return AgentContext(
            workspace=self.workspace,
            dataset_path=self.dataset_path,
            notebook_path=self.notebook_path,
        )

    def handle_slash(self, text: str) -> SlashResult:
        command = text.strip()
        cmd = command.lower()
        if cmd in ("/exit", "/quit"):
            return SlashResult(should_exit=True, lines=["Goodbye"])

        if cmd == "/help":
            lines = [
                f"  {command} {SLASH_USAGE.get(command, ''):<42} {description}".rstrip()
                for command, description in SLASH_COMMANDS.items()
            ]
            return SlashResult(lines=lines)

        if cmd == "/context":
            summary = compact_workspace_summary(self.workspace)
            return SlashResult(lines=[json.dumps(summary, indent=2)])

        if cmd == "/artifacts" or cmd.startswith("/artifacts "):
            return self._artifacts(command)

        if cmd == "/assumptions":
            lines = [f"  - {a.text}" for a in AssumptionLog(self.workspace).list_all()]
            return SlashResult(lines=lines or ["(no assumptions)"])

        if cmd.startswith("/notebook "):
            return self._notebook(text)

        if cmd == "/sessions":
            return SlashResult(lines=[format_session_list(list_sessions(self.workspace, limit=20))])

        if cmd.startswith("/replay "):
            return self._replay(command)

        if cmd == "/export" or cmd.startswith("/export "):
            return self._export(command)

        if cmd.startswith("/trace "):
            return self._trace(command)

        if cmd == "/status":
            lines = [
                f"Provider: {self.provider_name}",
                f"Model: {self.model or 'provider default'}",
                f"Dataset: {self.dataset_path or 'none'}",
                f"Notebook: {self.notebook_path or 'none'}",
                f"Approvals: {'interactive' if not self.auto_approve else 'auto'}",
                f"Last session: {self.last_session_id or 'none'}",
                self.status_strip(),
            ]
            return SlashResult(lines=lines)

        if cmd.startswith("/provider"):
            return self._provider(command)

        if cmd.startswith("/model"):
            return self._model(command)

        if cmd.startswith("/profile "):
            return self._profile(text)

        return SlashResult(lines=[f"Unknown command: {text}"])

    def _artifacts(self, command: str) -> SlashResult:
        parts = command.split()
        scope = parts[1].lower() if len(parts) > 1 else "recent"
        reg = ArtifactRegistry(self.workspace)
        if scope == "all":
            items = reg.list_filtered(limit=None)
            label = "all artifacts"
        elif scope == "session":
            if not self.last_session_id:
                return SlashResult(lines=["No session yet. Ask a question first."])
            items = reg.list_filtered(session_id=self.last_session_id, limit=None)
            label = f"session {self.last_session_id}"
        else:
            items = reg.list_filtered(limit=15)
            label = "recent artifacts"
        if not items:
            return SlashResult(lines=[f"No artifacts for {label}"])
        lines = [f"Showing {label} ({len(items)})"]
        lines.extend(f"  {format_artifact_line(a, self.workspace)}" for a in items)
        return SlashResult(lines=lines)

    def _notebook(self, text: str) -> SlashResult:
        from dimer.data_context.notebook_context import format_notebook_summary, summarize_notebook

        nb_path = text.split(maxsplit=1)[1].strip()
        try:
            summary = summarize_notebook(nb_path)
        except (FileNotFoundError, ValueError, json.JSONDecodeError) as e:
            return SlashResult(lines=[str(e)])
        self.notebook_path = str(Path(summary["path"]).resolve())
        return SlashResult(lines=[format_notebook_summary(summary)], status_changed=True)

    def _replay(self, command: str) -> SlashResult:
        session_id = command.split(maxsplit=1)[1].strip()
        try:
            data = load_session(session_id, self.workspace)
        except FileNotFoundError as e:
            return SlashResult(lines=[str(e)])
        self.last_session_id = session_id
        return SlashResult(lines=[format_session_replay(session_id, data)], status_changed=True)

    def _export(self, command: str) -> SlashResult:
        from dimer.pipeline.export_session import export_session

        parts = command.split(maxsplit=1)
        session_id = parts[1].strip() if len(parts) > 1 else None
        try:
            result = export_session(session_id or None, self.workspace)
        except (FileNotFoundError, ValueError) as e:
            return SlashResult(lines=[str(e)])

        self.last_session_id = result.session_id
        lines = [
            f"Script exported to {result.script_path}",
            f"Manifest: {result.manifest_path}",
        ]
        if result.verified:
            lines.append(f"Verified {result.query_count} SQL query replay(s).")
        else:
            lines.append("Export created with verification warnings:")
            lines.extend(f"  - {warning}" for warning in result.warnings)
        return SlashResult(lines=lines, status_changed=True)

    def _trace(self, command: str) -> SlashResult:
        from dimer.data_context.analysis_state import resolve_trace_session

        rest = command.split(maxsplit=1)[1].strip()
        parts = rest.split()
        session_id: str | None = None
        all_sessions = False
        target = rest
        if parts and parts[0] == "all" and len(parts) >= 2:
            all_sessions = True
            target = " ".join(parts[1:])
        elif parts and parts[0] == "session" and len(parts) >= 3:
            session_id = parts[1]
            target = " ".join(parts[2:])
        else:
            session_id = self.last_session_id or resolve_trace_session(self.workspace)
        if all_sessions:
            session_id = None
        events = AnalysisState(self.workspace).trace(target, session_id=session_id)
        lines: list[str] = []
        if session_id:
            lines.append(f"Tracing session {session_id} (use /trace all <target> for full history)")
        lines.append(format_trace(events, target=target, session_id=session_id))
        return SlashResult(lines=lines)

    def _provider(self, command: str) -> SlashResult:
        parts = command.split(maxsplit=1)
        if len(parts) == 1:
            return SlashResult(lines=[f"Provider: {self.provider_name}"])
        provider_name = parts[1].strip()
        try:
            provider = create_provider(provider_name, self.config)
        except Exception as e:
            return SlashResult(lines=[f"Failed to create provider: {e}"])
        self.provider_name = provider_name
        self.model = None
        default_model = str(getattr(provider, "default_model", self.config.default_model))
        lines = [f"Switched provider to {provider_name} (model: {default_model})"]
        privacy_warning = self.provider_context_warning()
        if privacy_warning:
            lines.append(privacy_warning)
        return SlashResult(lines=lines, status_changed=True)

    def _model(self, command: str) -> SlashResult:
        parts = command.split(maxsplit=1)
        if len(parts) == 1:
            return SlashResult(lines=[f"Model: {self.model or 'provider default'}"])
        model = parts[1].strip()
        self.model = None if model.lower() == "default" else model
        return SlashResult(
            lines=[f"Switched model to {self.model or 'provider default'}"],
            status_changed=True,
        )

    def _profile(self, text: str) -> SlashResult:
        path = text.split(maxsplit=1)[1].strip()
        profile = profile_dataset(path)
        out = save_profile(profile, self.workspace)
        self.dataset_path = str(Path(path).resolve())
        return SlashResult(
            lines=[f"Profile saved to {out}"],
            profile=profile.model_dump(mode="json"),
            status_changed=True,
        )
