"""Opt-in live conformance checks for the two local MVP provider paths."""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest

from dimer.application.capability_evidence import (
    CapabilityEnvironment,
    record_capability_evidence,
)
from dimer.application.doctor import run_doctor
from dimer.config import DimerConfig, provider_data_locality, provider_tool_protocol


_LIVE_OPT_IN = "DIMER_RUN_LIVE_PROVIDER_TESTS"
_DEFAULT_EVIDENCE_PATH = Path("project-context/provider-capability-evidence.jsonl")
_OLLAMA_NUM_CTX = 4096
_OLLAMA_NUM_PREDICT = 512


def _assert_ollama_memory_preflight(
    config: DimerConfig,
    *,
    transport: httpx.BaseTransport | None = None,
) -> None:
    """Refuse Ollama generation while another local runtime owns model memory."""
    lmstudio_base_url = os.environ.get(
        "DIMER_LIVE_LMSTUDIO_BASE_URL",
        "http://127.0.0.1:1234/v1",
    ).rstrip("/")
    if lmstudio_base_url.endswith("/v1"):
        lmstudio_base_url = lmstudio_base_url[:-3]

    try:
        with httpx.Client(transport=transport, timeout=5.0) as client:
            response = client.get(f"{lmstudio_base_url}/api/v1/models")
    except httpx.ConnectError:
        pass
    else:
        assert response.status_code == 200, (
            "Could not confirm that LM Studio has no loaded model; "
            f"its model-state endpoint returned HTTP {response.status_code}."
        )
        payload = response.json()
        models = payload.get("models") if isinstance(payload, dict) else None
        assert isinstance(models, list), (
            "Could not confirm that LM Studio has no loaded model because its "
            "model-state response was invalid."
        )
        loaded = [
            str(model.get("key", "unknown"))
            for model in models
            if isinstance(model, dict) and model.get("loaded_instances")
        ]
        assert not loaded, (
            "Unload every model from LM Studio before testing Ollama. "
            f"Loaded LM Studio model(s): {', '.join(loaded)}."
        )

    ollama_config = config.providers["ollama"]
    ollama_base_url = str(
        ollama_config.get("base_url", "http://localhost:11434")
    ).rstrip("/")
    with httpx.Client(transport=transport, timeout=5.0) as client:
        response = client.get(f"{ollama_base_url}/api/ps")
    assert response.status_code == 200, (
        "Could not confirm Ollama's resident models; "
        f"its process endpoint returned HTTP {response.status_code}."
    )
    payload = response.json()
    models = payload.get("models") if isinstance(payload, dict) else None
    assert isinstance(models, list), (
        "Could not confirm Ollama's resident models because its process response "
        "was invalid."
    )
    selected_model = str(ollama_config.get("model", config.default_model))
    other_models = [
        str(model.get("model") or model.get("name") or "unknown")
        for model in models
        if isinstance(model, dict)
        and str(model.get("model") or model.get("name") or "unknown")
        != selected_model
    ]
    assert not other_models, (
        f"Unload other Ollama models before testing {selected_model}. "
        f"Resident Ollama model(s): {', '.join(other_models)}."
    )


def _required_live_value(env_prefix: str, field: str) -> str:
    variable = f"{env_prefix}_{field}"
    value = os.environ.get(variable)
    if not value or not value.strip():
        pytest.skip(f"set {variable} to record complete live capability evidence")
    return value


def _live_config(
    provider_name: str,
    *,
    default_base_url: str,
    api_key: str | None = None,
) -> DimerConfig:
    if os.environ.get(_LIVE_OPT_IN) != "1":
        pytest.skip(f"set {_LIVE_OPT_IN}=1 to contact a local model provider")

    env_prefix = f"DIMER_LIVE_{provider_name.upper()}"
    model = os.environ.get(f"{env_prefix}_MODEL")
    if not model:
        pytest.skip(f"set {env_prefix}_MODEL to select the live model")
    tool_protocol = os.environ.get(f"{env_prefix}_TOOL_PROTOCOL")
    if not tool_protocol:
        pytest.skip(
            f"set {env_prefix}_TOOL_PROTOCOL to the model's native or json protocol"
        )

    provider_config: dict[str, object] = {
        "base_url": os.environ.get(f"{env_prefix}_BASE_URL", default_base_url),
        "model": model,
        "models": {model: {"tool_protocol": tool_protocol}},
    }
    if provider_name == "ollama":
        provider_config.update({
            "num_ctx": _OLLAMA_NUM_CTX,
            "num_predict": _OLLAMA_NUM_PREDICT,
        })
    if api_key is not None:
        provider_config["api_key"] = api_key

    return DimerConfig(
        default_provider=provider_name,
        default_model=model,
        providers={provider_name: provider_config},
    )


def _assert_live_doctor_passes(
    config: DimerConfig,
    *,
    preflight_transport: httpx.BaseTransport | None = None,
) -> None:
    assert provider_data_locality(config, config.default_provider) == "local", (
        "live provider conformance is restricted to loopback endpoints"
    )
    env_prefix = f"DIMER_LIVE_{config.default_provider.upper()}"
    environment = CapabilityEnvironment(
        runtime_version=_required_live_value(env_prefix, "RUNTIME_VERSION"),
        context_settings=_required_live_value(env_prefix, "CONTEXT_SETTINGS"),
        hardware=_required_live_value(env_prefix, "HARDWARE"),
    )
    if config.default_provider == "ollama":
        _assert_ollama_memory_preflight(
            config,
            transport=preflight_transport,
        )

    report = run_doctor(config)

    assert report.data_locality == "local"
    assert report.ok, "\n".join(
        f"{check.name}: {check.status} - {check.detail}" for check in report.checks
    )
    assert [check.status for check in report.checks] == [
        "pass",
        "pass",
        "pass",
        "pass",
    ]
    record_capability_evidence(
        report,
        tool_protocol=provider_tool_protocol(
            config,
            report.provider,
            report.model,
        ),
        environment=environment,
        destination=Path(
            os.environ.get("DIMER_LIVE_EVIDENCE_PATH", _DEFAULT_EVIDENCE_PATH)
        ),
    )


@pytest.mark.live_provider
def test_live_ollama_completes_the_doctor_tool_round_trip() -> None:
    config = _live_config(
        "ollama",
        default_base_url="http://localhost:11434",
    )

    _assert_live_doctor_passes(config)


@pytest.mark.live_provider
def test_live_lmstudio_completes_the_doctor_tool_round_trip() -> None:
    config = _live_config(
        "lmstudio",
        default_base_url="http://127.0.0.1:1234/v1",
        api_key="lm-studio",
    )

    _assert_live_doctor_passes(config)
