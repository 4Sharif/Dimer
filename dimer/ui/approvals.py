"""Approval prompts for risky actions."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from rich.prompt import Confirm

from dimer.agent.events import EventSink, emit_event
from dimer.safety.pii import redact_sensitive_text

TOOL_RISK_DETAILS = {
    "run_python": (
        "execute Python code",
        "isolated child process in the current workspace",
        "perform analysis that is not available through bounded SQL",
        "code can consume resources and create workspace artifacts",
    ),
    "write_file": (
        "write a file",
        "the requested workspace path",
        "create or update a user-requested output",
        "existing content at the target may be overwritten",
    ),
    "save_report": (
        "save a Markdown report",
        "the requested workspace artifact path",
        "preserve a user-requested analysis report",
        "a new artifact is written and existing content may be overwritten",
    ),
    "create_chart": (
        "create a chart",
        "the workspace chart-artifact directory",
        "fulfill the explicit visualization request",
        "a new image file is written inside the workspace",
    ),
    "read_file": (
        "read a text file",
        "the requested workspace path",
        "inspect source context needed for the analysis",
        "file contents may be sent to the configured model provider",
    ),
}


def describe_tool_risk(tool_name: str, arguments: dict[str, Any] | None = None) -> str:
    args = arguments or {}
    operation, target, reason, consequence = TOOL_RISK_DETAILS.get(
        tool_name,
        (
            f"run {tool_name}",
            "the current workspace",
            "complete the requested analysis",
            "the operation may change workspace state",
        ),
    )
    if tool_name == "run_python" and args.get("workspace"):
        target = f"isolated child process rooted at {args['workspace']}"
    details: list[str] = []
    if tool_name == "run_python" and isinstance(args.get("code"), str):
        preview = " ".join(args["code"].strip().split())
        details.append(f"code preview: {preview[:160]}")
    if tool_name in {"write_file", "save_report", "create_chart"} and args.get("path"):
        details.append(f"path: {args['path']}")
    if tool_name == "read_file" and args.get("path"):
        details.append(f"path: {args['path']}")
    detail_text = f"; {'; '.join(details)}" if details else ""
    return redact_sensitive_text(
        f"Operation: {operation}; Target: {target}; Why: {reason}; "
        f"Consequence: {consequence}{detail_text}."
    )


def request_approval(
    message: str,
    event_sink: EventSink | None = None,
    default: bool = False,
    ask: Callable[[str], bool] | None = None,
) -> bool:
    emit_event(event_sink, "approval_requested", message=message)
    if ask is not None:
        approved = ask(message)
    else:
        approved = Confirm.ask(message, default=default)
    emit_event(
        event_sink,
        "approval_accepted" if approved else "approval_denied",
        message=message,
    )
    return approved


def request_tool_approval(
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    event_sink: EventSink | None = None,
    default: bool = False,
    ask: Callable[[str], bool] | None = None,
) -> bool:
    risk = describe_tool_risk(tool_name, arguments)
    message = f"Approve `{tool_name}`? {risk}"
    return request_approval(message, event_sink=event_sink, default=default, ask=ask)
