"""Privacy helpers."""

from __future__ import annotations

from dimer.config import DimerConfig, PrivacyConfig


def should_send_samples(config: DimerConfig | PrivacyConfig) -> bool:
    privacy = config.privacy if isinstance(config, DimerConfig) else config
    return privacy.send_sample_rows
