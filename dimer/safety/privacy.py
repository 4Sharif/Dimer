"""Privacy helpers."""

from __future__ import annotations

from dimer.config import DimerConfig, PrivacyConfig, provider_data_locality


CLOUD_CONTEXT_WARNING = (
    "Cloud provider selected. Dimer sends compact profiles, summaries, and tool "
    "results by default; avoid exposing raw rows unless explicitly approved."
)


def should_send_samples(config: DimerConfig | PrivacyConfig) -> bool:
    privacy = config.privacy if isinstance(config, DimerConfig) else config
    return privacy.send_sample_rows


def provider_context_warning(
    config: DimerConfig,
    provider_name: str,
) -> str | None:
    """Explain when model-visible context will leave the local machine."""
    if provider_data_locality(config, provider_name) == "cloud":
        return CLOUD_CONTEXT_WARNING
    return None
