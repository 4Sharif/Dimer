"""Configuration loading for Dimer."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


DEFAULT_CONFIG_PATH = Path.home() / ".config" / "dimer" / "config.toml"

DEFAULT_CONFIG = """\
default_provider = "ollama"
default_model = "qwen2.5-coder:7b"

[providers.ollama]
base_url = "http://localhost:11434"
use_native_tools = false
num_predict = 2048
num_ctx = 8192

[providers.lmstudio]
base_url = "http://127.0.0.1:1234/v1"
api_key = "lm-studio"

[providers.openai]
api_key_env = "OPENAI_API_KEY"
model = "gpt-4o"

[providers.anthropic]
api_key_env = "ANTHROPIC_API_KEY"
model = "claude-sonnet-4-20250514"

[providers.gemini]
api_key_env = "GEMINI_API_KEY"
model = "gemini-2.0-flash"

[privacy]
send_sample_rows = false
max_sample_rows = 5
redact_pii = true
allow_cloud_llm = true

[limits]
timeout_seconds = 30
max_output_chars = 20000
max_preview_rows = 50
"""


class PrivacyConfig(BaseModel):
    send_sample_rows: bool = False
    max_sample_rows: int = 5
    redact_pii: bool = True
    allow_cloud_llm: bool = True


class LimitsConfig(BaseModel):
    timeout_seconds: int = 30
    max_output_chars: int = 20000
    max_preview_rows: int = 50


class DimerConfig(BaseModel):
    default_provider: str = "ollama"
    default_model: str = "qwen2.5-coder:7b"
    providers: dict[str, dict[str, Any]] = Field(default_factory=dict)
    privacy: PrivacyConfig = Field(default_factory=PrivacyConfig)
    limits: LimitsConfig = Field(default_factory=LimitsConfig)


def ensure_user_config() -> Path:
    path = DEFAULT_CONFIG_PATH
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(DEFAULT_CONFIG, encoding="utf-8")
    return path


def load_config(config_path: Path | None = None) -> DimerConfig:
    path = config_path or DEFAULT_CONFIG_PATH
    if not path.exists():
        ensure_user_config()
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    return DimerConfig.model_validate(raw)


def get_provider_config(config: DimerConfig, provider_name: str) -> dict[str, Any]:
    return config.providers.get(provider_name, {})


def resolve_api_key(provider_cfg: dict[str, Any]) -> str | None:
    env_var = provider_cfg.get("api_key_env")
    if env_var:
        return os.environ.get(env_var)
    return provider_cfg.get("api_key")


def provider_uses_native_tools(config: DimerConfig, provider_name: str) -> bool:
    provider_cfg = get_provider_config(config, provider_name)
    return bool(provider_cfg.get("use_native_tools", False))
