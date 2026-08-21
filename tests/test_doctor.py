"""Application and CLI contracts for provider diagnostics."""

from __future__ import annotations

import json

import httpx
from typer.testing import CliRunner

from dimer.application.doctor import run_doctor
from dimer.cli import app
from dimer.config import DimerConfig
from dimer.providers.lmstudio import LMStudioProvider
from dimer.providers.ollama import OllamaProvider


runner = CliRunner()


def test_doctor_reports_a_missing_tool_call_after_basic_completion() -> None:
    def complete(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["model"] == "local-model"
        assert "tools" not in payload
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "OK"},
                    }
                ]
            },
        )

    config = DimerConfig(
        default_provider="lmstudio",
        default_model="local-model",
        providers={
            "lmstudio": {
                "base_url": "http://127.0.0.1:1234/v1",
                "model": "local-model",
            }
        },
    )
    provider = LMStudioProvider(
        config.providers["lmstudio"],
        transport=httpx.MockTransport(complete),
    )

    report = run_doctor(config, provider=provider)

    assert report.provider == "lmstudio"
    assert report.model == "local-model"
    assert report.endpoint == "http://127.0.0.1:1234/v1"
    assert report.data_locality == "local"
    assert [(check.name, check.status) for check in report.checks] == [
        ("configuration", "pass"),
        ("basic completion", "pass"),
        ("tool call", "fail"),
        ("tool result", "not checked"),
    ]
    assert "exactly one diagnostic tool call" in report.checks[2].detail
    assert report.ok is False


def test_doctor_confirms_a_native_tool_call_and_result_round_trip() -> None:
    requests: list[dict] = []

    def complete(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append(payload)
        if len(requests) == 1:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": "OK"},
                        }
                    ]
                },
            )
        if len(requests) == 2:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "tool_calls",
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "doctor-call-1",
                                        "type": "function",
                                        "function": {
                                            "name": "dimer_doctor_echo",
                                            "arguments": '{"value":"DIMER_DOCTOR_PROBE"}',
                                        },
                                    }
                                ],
                            },
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": "DIMER_DOCTOR_RESULT_7F3A",
                        },
                    }
                ]
            },
        )

    config = DimerConfig(
        default_provider="lmstudio",
        default_model="local-model",
        providers={
            "lmstudio": {
                "base_url": "http://127.0.0.1:1234/v1",
                "model": "local-model",
                "models": {"local-model": {"tool_protocol": "native"}},
            }
        },
    )
    provider = LMStudioProvider(
        config.providers["lmstudio"],
        transport=httpx.MockTransport(complete),
    )

    report = run_doctor(config, provider=provider)

    assert [(check.name, check.status) for check in report.checks] == [
        ("configuration", "pass"),
        ("basic completion", "pass"),
        ("tool call", "pass"),
        ("tool result", "pass"),
    ]
    assert requests[1]["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "dimer_doctor_echo",
                "description": "Return the supplied diagnostic value unchanged.",
                "parameters": {
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                    "additionalProperties": False,
                },
            },
        }
    ]
    assert requests[2]["messages"][-2:] == [
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "doctor-call-1",
                    "type": "function",
                    "function": {
                        "name": "dimer_doctor_echo",
                        "arguments": '{"value": "DIMER_DOCTOR_PROBE"}',
                    },
                }
            ],
        },
        {
            "role": "tool",
            "content": (
                '{"type": "tool_result", "tool_name": "dimer_doctor_echo", '
                '"success": true, "result": {"value": "DIMER_DOCTOR_RESULT_7F3A"}}'
            ),
            "tool_call_id": "doctor-call-1",
            "name": "dimer_doctor_echo",
        },
    ]
    assert "DIMER_DOCTOR_RESULT_7F3A" not in json.dumps(requests[:2])
    assert report.ok is True


def test_doctor_confirms_a_json_fallback_tool_call_and_result_round_trip() -> None:
    requests: list[dict] = []

    def complete(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append(payload)
        if len(requests) == 1:
            content = "OK"
        elif len(requests) == 2:
            content = (
                '{"type":"tool_call","tool_name":"dimer_doctor_echo",'
                '"arguments":{"value":"DIMER_DOCTOR_PROBE"}}'
            )
        else:
            content = '{"type":"final","content":"DIMER_DOCTOR_RESULT_7F3A"}'
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": content},
                    }
                ]
            },
        )

    config = DimerConfig(
        default_provider="lmstudio",
        default_model="local-model",
        providers={
            "lmstudio": {
                "base_url": "http://127.0.0.1:1234/v1",
                "model": "local-model",
            }
        },
    )
    provider = LMStudioProvider(
        config.providers["lmstudio"],
        transport=httpx.MockTransport(complete),
    )

    report = run_doctor(config, provider=provider)

    assert [(check.name, check.status) for check in report.checks] == [
        ("configuration", "pass"),
        ("basic completion", "pass"),
        ("tool call", "pass"),
        ("tool result", "pass"),
    ]
    assert "tools" not in requests[1]
    assert requests[2]["messages"][-2] == {
        "role": "assistant",
        "content": (
            '{"type":"tool_call","tool_name":"dimer_doctor_echo",'
            '"arguments":{"value":"DIMER_DOCTOR_PROBE"}}'
        ),
    }
    observation = requests[2]["messages"][-1]
    assert observation["role"] == "user"
    assert json.loads(observation["content"]) == {
        "type": "tool_result",
        "tool_name": "dimer_doctor_echo",
        "success": True,
        "result": {"value": "DIMER_DOCTOR_RESULT_7F3A"},
    }
    assert "DIMER_DOCTOR_RESULT_7F3A" not in json.dumps(requests[:2])
    assert report.ok is True


def test_doctor_rejects_a_bare_json_fallback_summary() -> None:
    calls = 0

    def complete(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            content = "OK"
        elif calls == 2:
            content = (
                '{"type":"tool_call","tool_name":"dimer_doctor_echo",'
                '"arguments":{"value":"DIMER_DOCTOR_PROBE"}}'
            )
        else:
            content = "DIMER_DOCTOR_RESULT_7F3A"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": content},
                    }
                ]
            },
        )

    config = DimerConfig(
        default_provider="lmstudio",
        default_model="local-model",
        providers={
            "lmstudio": {
                "base_url": "http://127.0.0.1:1234/v1",
                "model": "local-model",
            }
        },
    )
    provider = LMStudioProvider(
        config.providers["lmstudio"],
        transport=httpx.MockTransport(complete),
    )

    report = run_doctor(config, provider=provider)

    assert report.checks[2].status == "pass"
    assert report.checks[3].status == "fail"
    assert "did not return the required JSON final envelope" in report.checks[3].detail
    assert report.ok is False


def test_doctor_cli_reports_basic_local_provider_health(tmp_path, monkeypatch) -> None:
    config = DimerConfig(
        default_provider="lmstudio",
        default_model="local-model",
        providers={
            "lmstudio": {
                "base_url": "http://127.0.0.1:1234/v1",
                "model": "local-model",
            }
        },
    )

    calls = 0

    def complete(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            content = "OK"
        elif calls == 2:
            content = (
                '{"type":"tool_call","tool_name":"dimer_doctor_echo",'
                '"arguments":{"value":"DIMER_DOCTOR_PROBE"}}'
            )
        else:
            content = '{"type":"final","content":"DIMER_DOCTOR_RESULT_7F3A"}'
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": content},
                    }
                ]
            },
        )

    provider = LMStudioProvider(
        config.providers["lmstudio"],
        transport=httpx.MockTransport(complete),
    )
    monkeypatch.setattr("dimer.cli.ensure_user_config", lambda: tmp_path / "config.toml")
    monkeypatch.setattr("dimer.cli.load_config", lambda: config)
    monkeypatch.setattr("dimer.application.doctor.create_provider", lambda *_args: provider)

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "Provider: lmstudio" in result.output
    assert "Model: local-model" in result.output
    assert "Endpoint: http://127.0.0.1:1234/v1" in result.output
    assert "Data handling: local" in result.output
    assert "model context stays on this machine" in result.output
    assert "configuration: pass" in result.output.lower()
    assert "basic completion: pass" in result.output.lower()
    assert "tool call: pass" in result.output.lower()
    assert "tool result: pass" in result.output.lower()


def test_doctor_stops_after_an_actionable_basic_completion_failure() -> None:
    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    config = DimerConfig(
        default_provider="ollama",
        default_model="qwen-local",
        providers={
            "ollama": {
                "base_url": "http://localhost:11434",
                "model": "qwen-local",
            }
        },
    )
    provider = OllamaProvider(
        config.providers["ollama"],
        transport=httpx.MockTransport(unreachable),
    )

    report = run_doctor(config, provider=provider)

    assert report.ok is False
    assert report.checks[1].status == "fail"
    assert "Could not reach Ollama" in report.checks[1].detail
    assert "Start the local server" in report.checks[1].detail
    assert report.checks[2].status == "not checked"
    assert report.checks[2].detail == (
        "Fix basic completion before testing tool calling."
    )
    assert report.checks[3].status == "not checked"


def test_doctor_cli_returns_failure_for_an_unreachable_provider(
    tmp_path,
    monkeypatch,
) -> None:
    config = DimerConfig(
        default_provider="ollama",
        default_model="qwen-local",
        providers={
            "ollama": {
                "base_url": "http://localhost:11434",
                "model": "qwen-local",
            }
        },
    )

    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    provider = OllamaProvider(
        config.providers["ollama"],
        transport=httpx.MockTransport(unreachable),
    )
    monkeypatch.setattr("dimer.cli.ensure_user_config", lambda: tmp_path / "config.toml")
    monkeypatch.setattr("dimer.cli.load_config", lambda: config)
    monkeypatch.setattr("dimer.application.doctor.create_provider", lambda *_args: provider)

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 1
    assert "basic completion: fail" in result.output.lower()
    assert "Could not reach Ollama" in result.output
    assert "Start the local server" in result.output
    assert "tool call: not checked" in result.output.lower()
    assert "tool result: not checked" in result.output.lower()
    assert "Traceback" not in result.output
