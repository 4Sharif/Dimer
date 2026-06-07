"""Structured event system for agent and tool activity."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Protocol

from pydantic import BaseModel, Field


class DimerEvent(BaseModel):
    type: str
    message: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class EventSink(Protocol):
    def emit(self, event: DimerEvent) -> None: ...


class ListEventSink:
    def __init__(self) -> None:
        self.events: list[DimerEvent] = []

    def emit(self, event: DimerEvent) -> None:
        self.events.append(event)


class CallbackEventSink:
    def __init__(self, callback: Callable[[DimerEvent], None]) -> None:
        self._callback = callback

    def emit(self, event: DimerEvent) -> None:
        self._callback(event)


def emit_event(sink: EventSink | None, event_type: str, message: str | None = None, **payload: Any) -> DimerEvent:
    event = DimerEvent(type=event_type, message=message, payload=payload)
    if sink:
        sink.emit(event)
    return event
