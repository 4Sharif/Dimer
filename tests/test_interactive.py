"""Interactive chat tests."""

from __future__ import annotations

from pathlib import Path

from prompt_toolkit.document import Document

from dimer.agent.events import DimerEvent
from dimer.config import DimerConfig, PrivacyConfig
from dimer.storage.artifacts import ensure_workspace_dirs
from dimer.ui.approvals import request_tool_approval
from dimer.ui.console import DimerConsole
from dimer.ui.interactive import InteractiveSession, SlashCommandCompleter
from dimer.ui.status import format_status_strip


def test_removed_mode_command_is_not_available(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)
    session = InteractiveSession(workspace=tmp_path)

    raw = "   /mode ml"
    result = session.controller.handle_slash(raw)

    assert result.should_exit is False
    assert result.lines == [f"Unknown command: {raw}"]


def test_switching_provider_clears_an_incompatible_model_override(tmp_path: Path) -> None:
    session = InteractiveSession(workspace=tmp_path)
    session.controller.config = DimerConfig(
        default_provider="ollama",
        providers={
            "ollama": {"model": "ollama-model"},
            "lmstudio": {"model": "lmstudio-model"},
        },
    )
    session.controller.model = "ollama-only-model"

    result = session.controller.handle_slash("/provider lmstudio")

    assert result.status_changed is True
    assert session.controller.provider_name == "lmstudio"
    assert session.controller.model is None
    assert result.lines[0] == "Switched provider to lmstudio (model: lmstudio-model)"


def test_switching_to_a_custom_loopback_provider_has_no_cloud_warning(
    tmp_path: Path,
) -> None:
    session = InteractiveSession(workspace=tmp_path)
    session.controller.config = DimerConfig(
        default_provider="ollama",
        providers={
            "local-compatible": {"base_url": "http://127.0.0.1:8080/v1"},
        },
    )

    result = session.controller.handle_slash("/provider local-compatible")

    assert result.status_changed is True
    assert result.lines == [
        "Switched provider to local-compatible (model: qwen2.5-coder:7b)"
    ]


def test_chat_discloses_a_configured_cloud_provider_before_input(
    tmp_path: Path,
    capsys,
) -> None:
    class ExitPrompt:
        def prompt(self, *_args, **_kwargs):
            raise EOFError

    session = InteractiveSession(workspace=tmp_path)
    session.controller.config = DimerConfig(
        default_provider="remote-compatible",
        providers={
            "remote-compatible": {"base_url": "https://models.example/v1"},
        },
        privacy=PrivacyConfig(allow_cloud_llm=True),
    )
    session.controller.provider_name = "remote-compatible"
    session.prompt = ExitPrompt()

    session.run()

    assert "Cloud provider selected" in capsys.readouterr().out


def test_slash_completer_lists_commands_with_descriptions() -> None:
    completions = list(
        SlashCommandCompleter().get_completions(Document("/"), complete_event=None)
    )

    by_text = {completion.text: completion.display_meta_text for completion in completions}
    assert set(by_text) == {
        "/help",
        "/exit",
        "/context",
        "/artifacts",
        "/export",
        "/provider",
        "/model",
        "/trace",
        "/profile",
        "/status",
    }
    assert "/mode" not in by_text
    assert by_text["/trace"] == "Trace lineage for a column or artifact"


def test_slash_completer_filters_contextual_arguments() -> None:
    completer = SlashCommandCompleter()

    artifacts = list(
        completer.get_completions(Document("/artifacts "), complete_event=None)
    )
    trace = list(completer.get_completions(Document("/trace "), complete_event=None))

    assert {item.text for item in artifacts} == {"session", "all"}
    assert {item.text for item in trace} == {"all", "session"}
    assert all(item.display_meta_text for item in artifacts + trace)


def test_format_status_strip_includes_core_fields() -> None:
    line = format_status_strip(
        provider="lmstudio",
        model="qwopus",
        dataset="/tmp/data/sales.csv",
        session_id="session-20260713-120000",
        approvals="ask",
    )
    assert "mode=" not in line
    assert "provider=lmstudio" in line
    assert "model=qwopus" in line
    assert "dataset=sales.csv" in line
    assert "session=session-20260713-120000" in line
    assert "approvals=ask" in line


def test_format_status_strip_defaults() -> None:
    line = format_status_strip(provider="ollama")
    assert "model=default" in line
    assert "dataset=none" in line
    assert "session=none" in line


def test_request_tool_approval_uses_ask_callback() -> None:
    seen: list[str] = []

    def ask(message: str) -> bool:
        seen.append(message)
        return True

    assert request_tool_approval("run_python", {"code": "x = 1"}, ask=ask) is True
    assert seen and "run_python" in seen[0]


def test_render_event_tool_rows(capsys) -> None:
    console = DimerConsole()
    console.render_event(
        DimerEvent(type="tool_call_started", payload={"tool_name": "run_duckdb_query"})
    )
    console.render_event(
        DimerEvent(type="tool_call_finished", payload={"tool_name": "run_duckdb_query"})
    )
    console.render_event(
        DimerEvent(
            type="tool_call_failed",
            message="boom",
            payload={"tool_name": "run_python"},
        )
    )
    out = capsys.readouterr().out
    assert "tool run_duckdb_query" in out
    assert "tool run_python" in out
