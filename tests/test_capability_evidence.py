"""Durable evidence contracts for authorized provider conformance runs."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import pytest

from dimer.application.capability_evidence import (
    CapabilityEnvironment,
    record_capability_evidence,
)
from dimer.application.doctor import DoctorCheck, DoctorReport
from dimer.config import DimerConfig
from tests.test_live_provider_conformance import _assert_live_doctor_passes


def test_passing_doctor_report_records_exact_live_capability_evidence(tmp_path) -> None:
    report = DoctorReport(
        provider="lmstudio",
        model="qwen-local",
        endpoint="http://127.0.0.1:1234/v1",
        data_locality="local",
        checks=(
            DoctorCheck("configuration", "pass", "Selected provider and model."),
            DoctorCheck("basic completion", "pass", "Completion succeeded."),
            DoctorCheck("tool call", "pass", "Native tool call succeeded."),
            DoctorCheck("tool result", "pass", "Tool result succeeded."),
        ),
    )
    destination = tmp_path / "provider-capabilities.jsonl"

    recorded_path = record_capability_evidence(
        report,
        tool_protocol="native",
        environment=CapabilityEnvironment(
            runtime_version="LM Studio 0.3.24",
            context_settings="context_length=8192",
            hardware="Apple M2 Pro, 32 GB",
        ),
        destination=destination,
        recorded_at=datetime(2026, 8, 20, 14, 30, tzinfo=timezone.utc),
    )

    assert recorded_path == destination
    assert json.loads(destination.read_text(encoding="utf-8")) == {
        "schema_version": 1,
        "recorded_at": "2026-08-20T14:30:00+00:00",
        "provider": "lmstudio",
        "model": "qwen-local",
        "endpoint": "http://127.0.0.1:1234/v1",
        "data_locality": "local",
        "tool_protocol": "native",
        "runtime_version": "LM Studio 0.3.24",
        "context_settings": "context_length=8192",
        "hardware": "Apple M2 Pro, 32 GB",
        "checks": [
            {"name": "configuration", "status": "pass"},
            {"name": "basic completion", "status": "pass"},
            {"name": "tool call", "status": "pass"},
            {"name": "tool result", "status": "pass"},
        ],
    }


def test_partial_doctor_report_is_not_recorded_as_capability_evidence(tmp_path) -> None:
    report = DoctorReport(
        provider="ollama",
        model="qwen-local",
        endpoint="http://localhost:11434",
        data_locality="local",
        checks=(
            DoctorCheck("configuration", "pass", "Selected provider and model."),
            DoctorCheck("basic completion", "pass", "Completion succeeded."),
            DoctorCheck("tool call", "fail", "Wrong tool call."),
            DoctorCheck("tool result", "not checked", "Fix tool calling first."),
        ),
    )
    destination = tmp_path / "provider-capabilities.jsonl"

    with pytest.raises(ValueError, match="every doctor check to pass"):
        record_capability_evidence(
            report,
            tool_protocol="json",
            environment=CapabilityEnvironment(
                runtime_version="Ollama 0.11.4",
                context_settings="num_ctx=8192",
                hardware="Apple M2 Pro, 32 GB",
            ),
            destination=destination,
        )

    assert not destination.exists()


def test_incomplete_all_pass_report_is_not_recorded_as_conformance(tmp_path) -> None:
    report = DoctorReport(
        provider="ollama",
        model="qwen-local",
        endpoint="http://localhost:11434",
        data_locality="local",
        checks=(DoctorCheck("configuration", "pass", "Configured."),),
    )
    destination = tmp_path / "provider-capabilities.jsonl"

    with pytest.raises(ValueError, match="all four doctor checks"):
        record_capability_evidence(
            report,
            tool_protocol="json",
            environment=CapabilityEnvironment(
                runtime_version="Ollama 0.11.4",
                context_settings="num_ctx=8192",
                hardware="Apple M2 Pro, 32 GB",
            ),
            destination=destination,
        )

    assert not destination.exists()


def test_authorized_live_pass_automatically_records_operator_evidence(
    tmp_path,
    monkeypatch,
) -> None:
    report = DoctorReport(
        provider="ollama",
        model="qwen-local",
        endpoint="http://localhost:11434",
        data_locality="local",
        checks=tuple(
            DoctorCheck(name, "pass", "Passed.")
            for name in ("configuration", "basic completion", "tool call", "tool result")
        ),
    )
    config = DimerConfig(
        default_provider="ollama",
        default_model="qwen-local",
        providers={
            "ollama": {
                "base_url": "http://localhost:11434",
                "model": "qwen-local",
                "models": {"qwen-local": {"tool_protocol": "json"}},
            }
        },
    )
    destination = tmp_path / "live-evidence.jsonl"
    monkeypatch.setenv("DIMER_LIVE_OLLAMA_RUNTIME_VERSION", "Ollama 0.11.4")
    monkeypatch.setenv("DIMER_LIVE_OLLAMA_CONTEXT_SETTINGS", "num_ctx=8192")
    monkeypatch.setenv("DIMER_LIVE_OLLAMA_HARDWARE", "Apple M2 Pro, 32 GB")
    monkeypatch.setenv("DIMER_LIVE_EVIDENCE_PATH", str(destination))
    monkeypatch.setattr(
        "tests.test_live_provider_conformance.run_doctor",
        lambda _config: report,
    )

    def no_other_resident_models(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/models":
            return httpx.Response(200, json={"models": []})
        if request.url.path == "/api/ps":
            return httpx.Response(200, json={"models": []})
        raise AssertionError(f"unexpected preflight request: {request.url}")

    _assert_live_doctor_passes(
        config,
        preflight_transport=httpx.MockTransport(no_other_resident_models),
    )

    record = json.loads(destination.read_text(encoding="utf-8"))
    assert record["provider"] == "ollama"
    assert record["model"] == "qwen-local"
    assert record["tool_protocol"] == "json"
    assert record["runtime_version"] == "Ollama 0.11.4"
    assert record["context_settings"] == "num_ctx=8192"
    assert record["hardware"] == "Apple M2 Pro, 32 GB"


def test_live_evidence_metadata_is_required_before_provider_contact(
    monkeypatch,
) -> None:
    config = DimerConfig(
        default_provider="ollama",
        default_model="qwen-local",
        providers={
            "ollama": {
                "base_url": "http://localhost:11434",
                "model": "qwen-local",
                "models": {"qwen-local": {"tool_protocol": "json"}},
            }
        },
    )
    for field in ("RUNTIME_VERSION", "CONTEXT_SETTINGS", "HARDWARE"):
        monkeypatch.delenv(f"DIMER_LIVE_OLLAMA_{field}", raising=False)
    monkeypatch.setattr(
        "tests.test_live_provider_conformance.run_doctor",
        lambda _config: pytest.fail("provider was contacted before metadata validation"),
    )

    with pytest.raises(pytest.skip.Exception, match="RUNTIME_VERSION"):
        _assert_live_doctor_passes(config)


def test_blank_live_evidence_metadata_is_rejected_before_provider_contact(
    monkeypatch,
) -> None:
    config = DimerConfig(
        default_provider="ollama",
        default_model="qwen-local",
        providers={
            "ollama": {
                "base_url": "http://localhost:11434",
                "model": "qwen-local",
                "models": {"qwen-local": {"tool_protocol": "json"}},
            }
        },
    )
    monkeypatch.setenv("DIMER_LIVE_OLLAMA_RUNTIME_VERSION", "   ")
    monkeypatch.setenv("DIMER_LIVE_OLLAMA_CONTEXT_SETTINGS", "num_ctx=8192")
    monkeypatch.setenv("DIMER_LIVE_OLLAMA_HARDWARE", "Apple M2 Pro, 32 GB")
    monkeypatch.setattr(
        "tests.test_live_provider_conformance.run_doctor",
        lambda _config: pytest.fail("provider was contacted before metadata validation"),
    )

    with pytest.raises(pytest.skip.Exception, match="RUNTIME_VERSION"):
        _assert_live_doctor_passes(config)
