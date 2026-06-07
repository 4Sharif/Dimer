"""Agent session state."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dimer.providers.base import ModelMessage


@dataclass
class AgentContext:
    workspace: Path
    dataset_path: str | None = None
    mode: str = "analysis"
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentSession:
    messages: list[ModelMessage] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
