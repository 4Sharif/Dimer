"""Provider configuration tests."""

from __future__ import annotations

import tomllib

import pytest

from dimer.config import (
    DEFAULT_CONFIG,
    DimerConfig,
    PrivacyConfig,
    provider_data_locality,
    provider_tool_protocol,
    resolve_api_key,
)
from dimer.providers.base import create_provider
from dimer.providers.openai_compatible import OpenAICompatibleProvider


def test_generated_config_is_local_first() -> None:
    generated = tomllib.loads(DEFAULT_CONFIG)

    assert set(generated["providers"]) == {"ollama", "lmstudio"}
    assert generated["privacy"]["allow_cloud_llm"] is False
    assert "use_native_tools" not in generated["providers"]["ollama"]


def test_custom_loopback_endpoint_is_local() -> None:
    config = DimerConfig(
        default_provider="llama-cpp",
        providers={
            "llama-cpp": {"base_url": "http://localhost:8080/v1"},
        },
    )

    assert provider_data_locality(config, "llama-cpp") == "local"


def test_cloud_provider_requires_explicit_privacy_opt_in() -> None:
    config = DimerConfig(
        default_provider="remote-compatible",
        providers={
            "remote-compatible": {"base_url": "https://models.example/v1"},
        },
    )

    with pytest.raises(
        ValueError,
        match=r"Cloud provider 'remote-compatible' is disabled.*allow_cloud_llm = true",
    ):
        create_provider(config=config)


def test_remote_ollama_requires_explicit_privacy_opt_in() -> None:
    config = DimerConfig(
        default_provider="ollama",
        providers={
            "ollama": {"base_url": "https://ollama.example"},
        },
    )

    with pytest.raises(
        ValueError,
        match=r"Cloud provider 'ollama' is disabled.*allow_cloud_llm = true",
    ):
        create_provider(config=config)


def test_invalid_model_tool_protocol_is_rejected() -> None:
    config = DimerConfig(
        default_provider="ollama",
        providers={
            "ollama": {
                "model": "qwen-test",
                "models": {"qwen-test": {"tool_protocol": "automatic"}},
            }
        },
    )

    with pytest.raises(
        ValueError,
        match=r"Invalid tool_protocol.*automatic.*Use 'native' or 'json'",
    ):
        provider_tool_protocol(config, "ollama", "qwen-test")


def test_gemini_uses_google_openai_compatible_base_url() -> None:
    config = DimerConfig(
        default_provider="gemini",
        providers={"gemini": {"api_key": "test-key", "model": "gemini-2.0-flash"}},
        privacy=PrivacyConfig(allow_cloud_llm=True),
    )

    provider = create_provider(config=config)

    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.base_url == "https://generativelanguage.googleapis.com/v1beta/openai"
    assert provider.default_model == "gemini-2.0-flash"


def test_resolve_api_key_prefers_direct_config_key() -> None:
    assert resolve_api_key({"api_key": "direct-key", "api_key_env": "MISSING_ENV"}) == "direct-key"


def test_cloud_provider_requires_api_key() -> None:
    config = DimerConfig(
        default_provider="gemini",
        providers={"gemini": {"api_key_env": "MISSING_DIMER_TEST_GEMINI_KEY"}},
        privacy=PrivacyConfig(allow_cloud_llm=True),
    )

    with pytest.raises(ValueError, match="No API key found"):
        create_provider(config=config)


def test_local_providers_use_their_provider_level_models() -> None:
    config = DimerConfig(
        default_provider="ollama",
        default_model="global-model",
        providers={
            "ollama": {"model": "ollama-model", "include_raw_diagnostics": True},
            "lmstudio": {"model": "lmstudio-model", "include_raw_diagnostics": True},
        },
    )

    ollama = create_provider("ollama", config)
    lmstudio = create_provider("lmstudio", config)

    assert ollama.default_model == "ollama-model"
    assert lmstudio.default_model == "lmstudio-model"
    assert ollama.include_raw_diagnostics is True
    assert lmstudio.include_raw_diagnostics is True


def test_anthropic_is_not_routed_through_openai_chat_completions() -> None:
    config = DimerConfig(
        default_provider="anthropic",
        providers={"anthropic": {"api_key": "test-key", "model": "claude-test"}},
    )

    with pytest.raises(
        ValueError,
        match="Anthropic is unsupported.*Messages API",
    ):
        create_provider(config=config)
