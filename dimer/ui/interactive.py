"""Interactive chat session (scrollback REPL)."""

from __future__ import annotations

from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document

from dimer.agent.events import CallbackEventSink
from dimer.agent.loop import AgentLoop
from dimer.agent.tool_router import ToolRouter
from dimer.providers.base import create_provider
from dimer.ui.approvals import request_tool_approval
from dimer.ui.console import DimerConsole
from dimer.ui.session_controller import SLASH_ARGUMENTS, SLASH_COMMANDS, SessionController


class SlashCommandCompleter(Completer):
    """Complete slash commands and their common arguments."""

    def get_completions(self, document: Document, complete_event):
        text = document.text_before_cursor.lstrip()
        if not text.startswith("/"):
            return

        if " " not in text:
            prefix = text.lower()
            for command, description in SLASH_COMMANDS.items():
                if command.startswith(prefix):
                    yield Completion(
                        command,
                        start_position=-len(text),
                        display_meta=description,
                    )
            return

        command, _, argument_prefix = text.partition(" ")
        options = SLASH_ARGUMENTS.get(command.lower())
        if options is None:
            return
        prefix = argument_prefix.lower()
        for argument, description in options.items():
            if argument.startswith(prefix):
                yield Completion(
                    argument,
                    start_position=-len(argument_prefix),
                    display_meta=description,
                )


class InteractiveSession:
    def __init__(self, workspace: Path | None = None) -> None:
        self.controller = SessionController(workspace)
        self.console = DimerConsole()
        self.prompt = PromptSession(
            completer=SlashCommandCompleter(),
            complete_while_typing=True,
        )

    @property
    def workspace(self) -> Path:
        return self.controller.workspace

    @property
    def last_session_id(self) -> str | None:
        return self.controller.last_session_id

    @last_session_id.setter
    def last_session_id(self, value: str | None) -> None:
        self.controller.last_session_id = value

    def _print_status_strip(self) -> None:
        self.console.render_status_strip(
            provider=self.controller.provider_name,
            model=self.controller.model,
            dataset=self.controller.dataset_path,
            session_id=self.controller.last_session_id,
            notebook=self.controller.notebook_path,
            approvals=self.controller.approvals_label(),
        )

    def _approval_ask(self, message: str) -> bool:
        self.console.warn(message)
        try:
            answer = self.prompt.prompt("approve? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        return answer in {"y", "yes"}

    def _approval_callback(self, tool_name: str, arguments: dict) -> bool:
        return request_tool_approval(
            tool_name,
            arguments,
            event_sink=None,
            default=False,
            ask=self._approval_ask,
        )

    def _handle_slash(self, text: str) -> bool:
        result = self.controller.handle_slash(text)
        for line in result.lines:
            self.console.print(line)
        if result.profile is not None:
            self.console.render_profile_summary(result.profile)
        if result.status_changed:
            self._print_status_strip()
        return not result.should_exit

    def run(self) -> None:
        self.console.print("Dimer — interactive analysis chat", style="bold")
        self.console.print("Type /help for commands, /exit to quit")
        self._print_status_strip()
        privacy_warning = self.controller.provider_context_warning()
        if privacy_warning:
            self.console.warn(privacy_warning)
        router = ToolRouter(self.controller.workspace, self.controller.config)
        sink = CallbackEventSink(self.console.render_event)

        while True:
            try:
                user_input = self.prompt.prompt("dimer> ")
            except (EOFError, KeyboardInterrupt):
                break
            user_input = user_input.strip()
            if not user_input:
                continue
            if user_input.startswith("/"):
                if not self._handle_slash(user_input):
                    break
                continue

            self.console.render_user(user_input)
            try:
                provider = create_provider(
                    self.controller.provider_name,
                    self.controller.config,
                )
                loop = AgentLoop(
                    provider,
                    router,
                    event_sink=sink,
                    config=self.controller.config,
                    model=self.controller.model,
                    approval_callback=(
                        None if self.controller.auto_approve else self._approval_callback
                    ),
                )
                result = loop.run(
                    user_input,
                    self.controller.agent_context(),
                    auto_approve=self.controller.auto_approve,
                )
                self.controller.last_session_id = result.session_id
                self.console.render_assistant(result.content)
                self.console.info(f"Session saved: {result.session_id}")
                self._print_status_strip()
            except Exception as e:
                self.console.error(str(e))

        self.console.info("Goodbye")
