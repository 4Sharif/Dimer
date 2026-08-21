"""Deterministic contracts for the opt-in live-provider harness."""

from __future__ import annotations

import httpx
import pytest

from dimer.config import DimerConfig
from dimer.providers.base import create_provider
from tests.test_live_provider_conformance import (
    _assert_live_doctor_passes,
    _assert_ollama_memory_preflight,
    _live_config,
)


@pytest.fixture
def ollama_config() -> DimerConfig:
    return DimerConfig(
        default_provider="ollama",
        default_model="granite4.1:8b",
        providers={
            "ollama": {
                "base_url": "http://localhost:11434",
                "model": "granite4.1:8b",
            }
        },
    )


def _runtime_transport(
    *,
    lmstudio_models: list[dict[str, object]] | None = None,
    ollama_models: list[dict[str, object]] | None = None,
) -> httpx.MockTransport:
    def runtime_state(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/models":
            return httpx.Response(200, json={"models": lmstudio_models or []})
        if request.url.path == "/api/ps":
            return httpx.Response(200, json={"models": ollama_models or []})
        raise AssertionError(f"unexpected preflight request: {request.url}")

    return httpx.MockTransport(runtime_state)


def test_live_ollama_config_applies_low_memory_generation_limits(monkeypatch) -> None:
    monkeypatch.setenv("DIMER_RUN_LIVE_PROVIDER_TESTS", "1")
    monkeypatch.setenv("DIMER_LIVE_OLLAMA_MODEL", "granite4.1:8b")
    monkeypatch.setenv("DIMER_LIVE_OLLAMA_TOOL_PROTOCOL", "native")

    config = _live_config(
        "ollama",
        default_base_url="http://localhost:11434",
    )

    provider = create_provider(config=config)

    assert (provider.num_ctx, provider.num_predict) == (4096, 512)


def test_ollama_preflight_refuses_a_loaded_lmstudio_model(
    ollama_config: DimerConfig,
) -> None:
    transport = _runtime_transport(
        lmstudio_models=[
            {
                "key": "qwen/qwen3.5-9b",
                "loaded_instances": [{"id": "qwen-loaded"}],
            }
        ]
    )

    with pytest.raises(
        AssertionError,
        match="Unload every model from LM Studio before testing Ollama",
    ):
        _assert_ollama_memory_preflight(ollama_config, transport=transport)


def test_ollama_preflight_refuses_a_different_resident_ollama_model(
    ollama_config: DimerConfig,
) -> None:
    transport = _runtime_transport(
        ollama_models=[{"name": "qwen3.5:9b", "model": "qwen3.5:9b"}]
    )

    with pytest.raises(
        AssertionError,
        match="Unload other Ollama models before testing granite4.1:8b",
    ):
        _assert_ollama_memory_preflight(ollama_config, transport=transport)


def test_ollama_preflight_allows_only_the_selected_model_to_be_resident(
    ollama_config: DimerConfig,
) -> None:
    transport = _runtime_transport(
        ollama_models=[{"name": "granite4.1:8b", "model": "granite4.1:8b"}]
    )

    _assert_ollama_memory_preflight(ollama_config, transport=transport)


def test_live_ollama_preflight_runs_before_doctor_generation(monkeypatch) -> None:
    monkeypatch.setenv("DIMER_RUN_LIVE_PROVIDER_TESTS", "1")
    monkeypatch.setenv("DIMER_LIVE_OLLAMA_MODEL", "granite4.1:8b")
    monkeypatch.setenv("DIMER_LIVE_OLLAMA_TOOL_PROTOCOL", "native")
    monkeypatch.setenv("DIMER_LIVE_OLLAMA_RUNTIME_VERSION", "Ollama test")
    monkeypatch.setenv(
        "DIMER_LIVE_OLLAMA_CONTEXT_SETTINGS",
        "num_ctx=4096, num_predict=512",
    )
    monkeypatch.setenv("DIMER_LIVE_OLLAMA_HARDWARE", "test hardware")
    config = _live_config(
        "ollama",
        default_base_url="http://localhost:11434",
    )
    transport = _runtime_transport(
        lmstudio_models=[
            {
                "key": "qwen/qwen3.5-9b",
                "loaded_instances": [{"id": "qwen-loaded"}],
            }
        ]
    )
    monkeypatch.setattr(
        "tests.test_live_provider_conformance.run_doctor",
        lambda _config: pytest.fail("generation started before memory preflight"),
    )

    with pytest.raises(
        AssertionError,
        match="Unload every model from LM Studio before testing Ollama",
    ):
        _assert_live_doctor_passes(config, preflight_transport=transport)
