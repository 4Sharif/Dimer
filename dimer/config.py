"""Configuration loading for Dimer."""

from __future__ import annotations

import os
import tomllib
from ipaddress import ip_address
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field


DEFAULT_CONFIG_PATH = Path.home() / ".config" / "dimer" / "config.toml"

DataLocality = Literal["local", "cloud"]
ToolProtocol = Literal["native", "json"]

DEFAULT_CONFIG = """\
default_provider = "ollama"
default_model = "qwen2.5-coder:7b"

[providers.ollama]
base_url = "http://localhost:11434"
num_predict = 2048
num_ctx = 8192

[providers.ollama.models."qwen2.5-coder:7b"]
tool_protocol = "json"

[providers.lmstudio]
base_url = "http://127.0.0.1:1234/v1"
api_key = "lm-studio"
model = "local-model"

[privacy]
send_sample_rows = false
max_sample_rows = 5
redact_pii = true
allow_cloud_llm = false

[limits]
timeout_seconds = 30
max_output_chars = 20000
max_preview_rows = 50
"""


class PrivacyConfig(BaseModel):
    send_sample_rows: bool = False
    max_sample_rows: int = 5
    redact_pii: bool = True
    allow_cloud_llm: bool = False


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
    direct_key = provider_cfg.get("api_key")
    if direct_key:
        return direct_key

    env_var = provider_cfg.get("api_key_env")
    if env_var:
        if str(env_var).startswith("AIza"):
            return str(env_var)
        return os.environ.get(env_var)
    return None


def provider_data_locality(
    config: DimerConfig,
    provider_name: str,
) -> DataLocality:
    """Classify whether model context stays on this machine or leaves it."""
    provider_cfg = get_provider_config(config, provider_name)
    configured = provider_cfg.get("data_locality")
    if configured == "local":
        return "local"
    if configured == "cloud":
        return "cloud"
    if configured is not None:
        raise ValueError(
            f"Invalid data_locality for provider '{provider_name}': {configured!r}. "
            "Use 'local' or 'cloud'."
        )

    base_url = provider_cfg.get("base_url")
    if base_url:
        hostname = urlparse(str(base_url)).hostname
        if hostname == "localhost" or (hostname and hostname.endswith(".localhost")):
            return "local"
        if hostname:
            try:
                if ip_address(hostname).is_loopback:
                    return "local"
            except ValueError:
                pass
        return "cloud"

    if provider_name in {"ollama", "lmstudio"}:
        return "local"

    return "cloud"


def provider_tool_protocol(
    config: DimerConfig,
    provider_name: str,
    model: str,
) -> ToolProtocol:
    provider_cfg = get_provider_config(config, provider_name)
    models = provider_cfg.get("models", {})
    if not isinstance(models, dict):
        return "json"
    model_capabilities = models.get(model, {})
    if not isinstance(model_capabilities, dict):
        return "json"
    configured = model_capabilities.get("tool_protocol", "json")
    if configured == "native":
        return "native"
    if configured == "json":
        return "json"
    raise ValueError(
        f"Invalid tool_protocol for provider '{provider_name}' model '{model}': "
        f"{configured!r}. Use 'native' or 'json'."
    )
