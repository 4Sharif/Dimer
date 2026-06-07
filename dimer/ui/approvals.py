"""Approval prompts for risky actions."""

from __future__ import annotations

from rich.prompt import Confirm

from dimer.agent.events import DimerEvent, EventSink, emit_event


def request_approval(
    message: str,
    event_sink: EventSink | None = None,
    default: bool = False,
) -> bool:
    emit_event(event_sink, "approval_requested", message=message)
    approved = Confirm.ask(message, default=default)
    emit_event(
        event_sink,
        "approval_accepted" if approved else "approval_denied",
        message=message,
    )
    return approved
