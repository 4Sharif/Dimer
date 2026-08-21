"""Process execution limits."""

from __future__ import annotations

from dimer.config import DimerConfig, LimitsConfig


def truncate_output(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars] + "\n... [truncated]", True


def get_limits(config: DimerConfig | None = None) -> LimitsConfig:
    if config:
        return config.limits
    return LimitsConfig()
