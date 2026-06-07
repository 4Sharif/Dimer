"""LM Studio provider (OpenAI-compatible)."""

from __future__ import annotations

from typing import Any

from dimer.providers.openai_compatible import OpenAICompatibleProvider


class LMStudioProvider(OpenAICompatibleProvider):
    name = "lmstudio"

    def __init__(
        self, config: dict[str, Any], default_model: str = "local-model"
    ) -> None:
        base_url = config.get("base_url", "http://127.0.0.1:1234/v1").rstrip("/")
        if not base_url.endswith("/v1"):
            base_url = f"{base_url}/v1"
        super().__init__(
            name="lmstudio",
            base_url=base_url,
            api_key=config.get("api_key", "lm-studio"),
            default_model=default_model,
        )
