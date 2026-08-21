"""Mocked conformance tests for provider transports."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from dimer.agent.loop import AgentLoop
from dimer.agent.events import ListEventSink
from dimer.agent.session import AgentContext
from dimer.agent.tool_router import ToolRouter
from dimer.config import DimerConfig
from dimer.providers.base import (
    ModelMessage,
    ProviderError,
    ModelResponse,
    ModelToolCall,
    ModelUsage,
    ToolSchema,
)
from dimer.providers.ollama import OllamaProvider
from dimer.providers.lmstudio import LMStudioProvider
from dimer.providers.openai_compatible import OpenAICompatibleProvider
from dimer.storage.sessions import load_session


def test_lmstudio_connection_failure_names_endpoint_model_and_remedy() -> None:
    endpoint = "http://127.0.0.1:1234/v1"

    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    provider = LMStudioProvider(
        {"base_url": endpoint, "model": "local-model"},
        transport=httpx.MockTransport(unreachable),
    )

    with pytest.raises(ProviderError) as exc_info:
        provider.generate([ModelMessage(role="user", content="Hello")])

    message = str(exc_info.value)
    assert "Could not reach LM Studio" in message
    assert endpoint in message
    assert "local-model" in message
    assert "Start the local server" in message
    assert "base_url" in message
    assert isinstance(exc_info.value.__cause__, httpx.ConnectError)


def test_transport_error_redacts_credentials_embedded_in_endpoint() -> None:
    secret = "sk-supersecretvalue123456"

    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    provider = OpenAICompatibleProvider(
        name="custom-hosted",
        base_url=f"https://user:{secret}@models.test/v1",
        default_model="hosted-model",
        transport=httpx.MockTransport(unreachable),
    )

    with pytest.raises(ProviderError) as exc_info:
        provider.generate([ModelMessage(role="user", content="Hello")])

    message = str(exc_info.value)
    assert secret not in message
    assert "[REDACTED_" in message


def test_ollama_timeout_names_endpoint_model_and_remedy() -> None:
    endpoint = "http://localhost:11434"

    def times_out(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    provider = OllamaProvider(
        {"base_url": endpoint, "model": "qwen-local"},
        transport=httpx.MockTransport(times_out),
    )

    with pytest.raises(ProviderError) as exc_info:
        provider.generate([ModelMessage(role="user", content="Hello")])

    message = str(exc_info.value)
    assert "Ollama timed out after 300 seconds" in message
    assert endpoint in message
    assert "qwen-local" in message
    assert "server load" in message
    assert "smaller model" in message
    assert isinstance(exc_info.value.__cause__, httpx.ReadTimeout)


def test_ollama_unknown_model_error_gives_install_and_config_remedies() -> None:
    def missing_model(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={"error": "model 'missing-model' not found"},
        )

    provider = OllamaProvider(
        {"model": "missing-model"},
        transport=httpx.MockTransport(missing_model),
    )

    with pytest.raises(ProviderError) as exc_info:
        provider.generate([ModelMessage(role="user", content="Hello")])

    message = str(exc_info.value)
    assert "Ollama rejected model 'missing-model' (HTTP 404)" in message
    assert "model 'missing-model' not found" in message
    assert "ollama list" in message
    assert "ollama pull missing-model" in message
    assert "[providers.ollama]" in message
    assert isinstance(exc_info.value.__cause__, httpx.HTTPStatusError)


def test_lmstudio_unknown_model_error_gives_load_and_config_remedies() -> None:
    def missing_model(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={"error": {"message": "Model local-missing not found"}},
        )

    provider = LMStudioProvider(
        {"model": "local-missing"},
        transport=httpx.MockTransport(missing_model),
    )

    with pytest.raises(ProviderError) as exc_info:
        provider.generate([ModelMessage(role="user", content="Hello")])

    message = str(exc_info.value)
    assert "LM Studio rejected model 'local-missing' (HTTP 404)" in message
    assert "Confirm the model is loaded in LM Studio" in message
    assert "[providers.lmstudio]" in message


def test_openai_compatible_rate_limit_preserves_safe_detail_and_request_id() -> None:
    def rate_limited(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            headers={"x-request-id": "req-rate-1"},
            json={
                "error": {
                    "message": "Quota exhausted for sk-supersecretvalue123456",
                }
            },
        )

    provider = OpenAICompatibleProvider(
        name="openai",
        base_url="https://api.openai.test/v1",
        api_key="test-key",
        default_model="hosted-model",
        transport=httpx.MockTransport(rate_limited),
    )

    with pytest.raises(ProviderError) as exc_info:
        provider.generate([ModelMessage(role="user", content="Hello")])

    message = str(exc_info.value)
    assert "openai request for model 'hosted-model' failed (HTTP 429)" in message
    assert "hosted-model" in message
    assert "Quota exhausted for [REDACTED_SECRET]" in message
    assert "request ID req-rate-1" in message
    assert "Wait and retry" in message
    assert "rate limit and quota" in message
    assert "sk-supersecretvalue123456" not in message


def test_openai_compatible_server_failure_points_to_provider_health() -> None:
    def unavailable(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503,
            headers={"x-request-id": "req-server-1"},
            json={"error": {"message": "Model worker unavailable"}},
        )

    provider = OpenAICompatibleProvider(
        name="custom-local",
        base_url="http://localhost:8080/v1",
        default_model="custom-model",
        transport=httpx.MockTransport(unavailable),
    )

    with pytest.raises(ProviderError) as exc_info:
        provider.generate([ModelMessage(role="user", content="Hello")])

    message = str(exc_info.value)
    assert "custom-local request for model 'custom-model' failed (HTTP 503)" in message
    assert "Provider message: Model worker unavailable" in message
    assert "Provider request ID req-server-1" in message
    assert "Check the provider server logs and health" in message


def test_openai_compatible_distinguishes_response_id_from_request_id() -> None:
    def complete(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-lmstudio-1",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "OK"},
                    }
                ],
            },
        )

    provider = LMStudioProvider(
        {"model": "local-model"},
        transport=httpx.MockTransport(complete),
    )

    response = provider.generate([ModelMessage(role="user", content="Hello")])

    assert response.response_id == "chatcmpl-lmstudio-1"
    assert response.request_id is None


def test_lmstudio_auth_rejection_names_credential_remedy_and_endpoint() -> None:
    endpoint = "http://127.0.0.1:1234/v1"

    def reject(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == f"{endpoint}/chat/completions"
        assert request.headers["authorization"] == "Bearer lm-studio-test"
        return httpx.Response(
            401,
            headers={"x-request-id": "req-auth-1"},
            json={"error": {"message": "Invalid API key"}},
        )

    provider = LMStudioProvider(
        {
            "base_url": "http://127.0.0.1:1234",
            "api_key": "lm-studio-test",
            "model": "local-model",
        },
        transport=httpx.MockTransport(reject),
    )

    with pytest.raises(ProviderError) as exc_info:
        provider.generate([ModelMessage(role="user", content="Hello")])

    message = str(exc_info.value)
    assert "LM Studio request for model 'local-model' failed (HTTP 401)" in message
    assert endpoint in message
    assert "Provider request ID req-auth-1" in message
    assert "Check the API credential and permissions" in message


def test_lmstudio_non_json_response_explains_protocol_remedy() -> None:
    def invalid_response(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not the chat API</html>")

    provider = LMStudioProvider(
        {"base_url": "http://127.0.0.1:1234/v1", "model": "local-model"},
        transport=httpx.MockTransport(invalid_response),
    )

    with pytest.raises(ProviderError) as exc_info:
        provider.generate([ModelMessage(role="user", content="Hello")])

    message = str(exc_info.value)
    assert "LM Studio returned an invalid response" in message
    assert "http://127.0.0.1:1234/v1" in message
    assert "local-model" in message
    assert "not valid JSON" in message
    assert "OpenAI-compatible Chat Completions" in message
    assert "<html>" not in message
    assert isinstance(exc_info.value.__cause__, json.JSONDecodeError)


def test_lmstudio_malformed_tool_arguments_explain_json_fallback() -> None:
    def malformed_arguments(_request: httpx.Request) -> httpx.Response:
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
                                    "id": "call-bad-args",
                                    "type": "function",
                                    "function": {
                                        "name": "inspect_dataset",
                                        "arguments": "{not-json",
                                    },
                                }
                            ],
                        },
                    }
                ]
            },
        )

    provider = LMStudioProvider(
        {"base_url": "http://127.0.0.1:1234/v1", "model": "local-model"},
        transport=httpx.MockTransport(malformed_arguments),
    )

    with pytest.raises(ProviderError) as exc_info:
        provider.generate([ModelMessage(role="user", content="Inspect data")])

    message = str(exc_info.value)
    assert "malformed tool arguments for 'inspect_dataset'" in message
    assert 'tool_protocol = "json"' in message
    assert "provider/model" in message
    assert isinstance(exc_info.value.__cause__, json.JSONDecodeError)


def test_lmstudio_non_object_tool_arguments_explain_json_fallback() -> None:
    def malformed_arguments(_request: httpx.Request) -> httpx.Response:
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
                                    "id": "call-bad-args",
                                    "type": "function",
                                    "function": {
                                        "name": "inspect_dataset",
                                        "arguments": [],
                                    },
                                }
                            ],
                        },
                    }
                ]
            },
        )

    provider = LMStudioProvider(
        {"base_url": "http://127.0.0.1:1234/v1", "model": "local-model"},
        transport=httpx.MockTransport(malformed_arguments),
    )

    with pytest.raises(ProviderError) as exc_info:
        provider.generate([ModelMessage(role="user", content="Inspect data")])

    assert 'tool_protocol = "json"' in str(exc_info.value)


def test_ollama_malformed_tool_arguments_explain_json_fallback() -> None:
    def malformed_arguments(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "inspect_dataset",
                                "arguments": "{not-json",
                            }
                        }
                    ],
                },
                "done": True,
                "done_reason": "stop",
            },
        )

    provider = OllamaProvider(
        {"model": "qwen-local"},
        transport=httpx.MockTransport(malformed_arguments),
    )

    with pytest.raises(ProviderError) as exc_info:
        provider.generate([ModelMessage(role="user", content="Inspect data")])

    message = str(exc_info.value)
    assert "Ollama returned malformed tool arguments for 'inspect_dataset'" in message
    assert 'tool_protocol = "json"' in message
    assert isinstance(exc_info.value.__cause__, json.JSONDecodeError)


def test_openai_compatible_invalid_response_shape_names_expected_protocol() -> None:
    def missing_choices(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})

    provider = LMStudioProvider(
        {"base_url": "http://127.0.0.1:1234/v1", "model": "local-model"},
        transport=httpx.MockTransport(missing_choices),
    )

    with pytest.raises(ProviderError) as exc_info:
        provider.generate([ModelMessage(role="user", content="Hello")])

    message = str(exc_info.value)
    assert "LM Studio returned an invalid response" in message
    assert "did not match the expected response schema" in message
    assert "OpenAI-compatible Chat Completions" in message


def test_openai_compatible_missing_assistant_message_is_actionable() -> None:
    def missing_message(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{}]})

    provider = LMStudioProvider(
        {"base_url": "http://127.0.0.1:1234/v1", "model": "local-model"},
        transport=httpx.MockTransport(missing_message),
    )

    with pytest.raises(ProviderError) as exc_info:
        provider.generate([ModelMessage(role="user", content="Hello")])

    message = str(exc_info.value)
    assert "LM Studio returned an invalid response" in message
    assert "did not match the expected response schema" in message


def test_openai_compatible_invalid_nested_tool_call_is_actionable() -> None:
    def null_tool_call(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [None],
                        },
                    }
                ]
            },
        )

    provider = OpenAICompatibleProvider(
        name="custom-local",
        base_url="http://localhost:8080/v1",
        default_model="custom-model",
        transport=httpx.MockTransport(null_tool_call),
    )

    with pytest.raises(ProviderError) as exc_info:
        provider.generate([ModelMessage(role="user", content="Inspect data")])

    message = str(exc_info.value)
    assert "custom-local returned an invalid response" in message
    assert "did not match the expected response schema" in message
    assert "NoneType" not in message


def test_ollama_invalid_response_shape_names_server_remedy() -> None:
    def missing_message(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"done": True, "done_reason": "stop"})

    provider = OllamaProvider(
        {"model": "qwen-local"},
        transport=httpx.MockTransport(missing_message),
    )

    with pytest.raises(ProviderError) as exc_info:
        provider.generate([ModelMessage(role="user", content="Hello")])

    message = str(exc_info.value)
    assert "Ollama returned an invalid response" in message
    assert "did not match the expected response schema" in message
    assert "Ollama server is current" in message


def test_openai_compatible_protocol_error_gives_transport_remedy() -> None:
    def broken_protocol(request: httpx.Request) -> httpx.Response:
        raise httpx.RemoteProtocolError("server disconnected", request=request)

    provider = OpenAICompatibleProvider(
        name="custom-local",
        base_url="http://localhost:8080/v1",
        default_model="custom-model",
        transport=httpx.MockTransport(broken_protocol),
    )

    with pytest.raises(ProviderError) as exc_info:
        provider.generate([ModelMessage(role="user", content="Hello")])

    message = str(exc_info.value)
    assert "Transport error while contacting custom-local" in message
    assert "http://localhost:8080/v1" in message
    assert "custom-model" in message
    assert "server logs" in message
    assert "network or proxy settings" in message
    assert isinstance(exc_info.value.__cause__, httpx.RemoteProtocolError)


def test_openai_compatible_preserves_a_native_tool_round_trip() -> None:
    requests: list[dict] = []

    def handle(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://provider.test/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer test-key"
        payload = json.loads(request.content)
        requests.append(payload)
        if len(requests) == 1:
            return httpx.Response(
                200,
                headers={"x-request-id": "req-tool-call"},
                json={
                    "id": "chatcmpl-tool-call",
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "tool_calls",
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "call_inspect_1",
                                        "type": "function",
                                        "function": {
                                            "name": "inspect_dataset",
                                            "arguments": '{"path":"sales.csv"}',
                                        },
                                    }
                                ],
                            },
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 41,
                        "completion_tokens": 12,
                        "total_tokens": 53,
                    },
                },
            )
        return httpx.Response(
            200,
            headers={"x-request-id": "req-final"},
            json={
                "id": "chatcmpl-final",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "The dataset has 12 rows."},
                    }
                ],
                "usage": {
                    "prompt_tokens": 68,
                    "completion_tokens": 9,
                    "total_tokens": 77,
                },
            },
        )

    provider = OpenAICompatibleProvider(
        base_url="https://provider.test/v1",
        api_key="test-key",
        default_model="configured-model",
        transport=httpx.MockTransport(handle),
        include_raw_diagnostics=True,
    )
    tools = [
        ToolSchema(
            name="inspect_dataset",
            description="Inspect a dataset",
            input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
        )
    ]

    first = provider.generate(
        [ModelMessage(role="user", content="Inspect sales.csv")],
        tools=tools,
        model="run-model",
    )

    assert first.message == ModelMessage(
        role="assistant",
        content=None,
        tool_calls=[
            ModelToolCall(
                id="call_inspect_1",
                name="inspect_dataset",
                arguments={"path": "sales.csv"},
            )
        ],
    )
    assert first.finish_reason == "tool_calls"
    assert first.usage is not None
    assert first.usage.model_dump() == {
        "input_tokens": 41,
        "output_tokens": 12,
        "total_tokens": 53,
    }
    assert first.request_id == "req-tool-call"
    assert first.raw is not None
    assert requests[0]["tools"][0]["function"]["name"] == "inspect_dataset"

    second = provider.generate(
        [
            ModelMessage(role="user", content="Inspect sales.csv"),
            first.message,
            ModelMessage(
                role="tool",
                content='{"row_count":12}',
                name="inspect_dataset",
                tool_call_id="call_inspect_1",
            ),
        ],
        tools=tools,
        model="run-model",
    )

    assert requests[0]["model"] == "run-model"
    assert requests[1]["messages"][1] == {
        "role": "assistant",
        "tool_calls": [
            {
                "id": "call_inspect_1",
                "type": "function",
                "function": {
                    "name": "inspect_dataset",
                    "arguments": '{"path": "sales.csv"}',
                },
            }
        ],
    }
    assert requests[1]["messages"][2]["tool_call_id"] == "call_inspect_1"
    assert second.message.content == "The dataset has 12 rows."
    assert second.finish_reason == "stop"
    assert second.request_id == "req-final"


def test_transport_leaves_json_fallback_content_to_agent_policy() -> None:
    fallback = (
        '{"type":"tool_call","tool_name":"inspect_dataset",'
        '"arguments":{"path":"sales.csv"}}'
    )

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": fallback},
                    }
                ]
            },
        )

    provider = OpenAICompatibleProvider(
        base_url="https://provider.test/v1",
        transport=httpx.MockTransport(handle),
    )

    response = provider.generate([ModelMessage(role="user", content="Inspect data")])

    assert response.message.content == fallback
    assert response.message.tool_calls == []


def test_agent_keeps_the_json_fallback_protocol_for_the_next_transport_turn(
    tmp_path: Path,
) -> None:
    requests: list[dict] = []
    fallback = (
        '{"type":"tool_call","tool_name":"inspect_dataset",'
        '"arguments":{}}'
    )

    def handle(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append(payload)
        if len(requests) == 1:
            assert "tools" not in payload
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": fallback},
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
                            "content": '{"type":"final","content":"## Findings\\nDataset inspected."}',
                        },
                    }
                ]
            },
        )

    provider = OpenAICompatibleProvider(
        name="fallback-test",
        base_url="https://provider.test/v1",
        transport=httpx.MockTransport(handle),
    )
    config = DimerConfig(
        default_provider=provider.name,
        providers={
            provider.name: {
                "models": {"local-model": {"tool_protocol": "json"}},
            }
        },
    )
    dataset = Path(__file__).parent.parent / "examples" / "sales" / "sales.csv"
    loop = AgentLoop(
        provider,
        ToolRouter(tmp_path, config),
        config=config,
        max_iterations=3,
    )

    result = loop.run(
        "Inspect this dataset.",
        AgentContext(workspace=tmp_path, dataset_path=str(dataset)),
    )

    assert len(requests) == 2
    assistant = next(
        message for message in requests[1]["messages"] if message["role"] == "assistant"
    )
    observation = next(
        message
        for message in requests[1]["messages"]
        if message["role"] == "user"
        and '"type": "tool_result"' in message.get("content", "")
    )
    assert assistant == {"role": "assistant", "content": fallback}
    assert "tool_calls" not in assistant
    assert json.loads(observation["content"])["type"] == "tool_result"
    assert "Dataset inspected." in result.findings


def test_ollama_preserves_a_native_tool_round_trip_and_usage() -> None:
    requests: list[dict] = []

    def handle(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://localhost:11434/api/chat"
        payload = json.loads(request.content)
        requests.append(payload)
        if len(requests) == 1:
            return httpx.Response(
                200,
                json={
                    "model": "configured-ollama-model",
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "inspect_dataset",
                                    "arguments": {"path": "sales.csv"},
                                }
                            }
                        ],
                    },
                    "done": True,
                    "done_reason": "stop",
                    "prompt_eval_count": 31,
                    "eval_count": 8,
                },
            )
        return httpx.Response(
            200,
            json={
                "model": "configured-ollama-model",
                "message": {
                    "role": "assistant",
                    "content": "The dataset has 12 rows.",
                },
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 52,
                "eval_count": 7,
            },
        )

    provider = OllamaProvider(
        {
            "model": "configured-ollama-model",
        },
        transport=httpx.MockTransport(handle),
        include_raw_diagnostics=True,
    )
    tools = [
        ToolSchema(
            name="inspect_dataset",
            description="Inspect a dataset",
            input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
        )
    ]

    first = provider.generate(
        [ModelMessage(role="user", content="Inspect sales.csv")],
        tools=tools,
    )

    assert first.message.role == "assistant"
    assert first.message.content == ""
    assert len(first.message.tool_calls) == 1
    assert first.message.tool_calls[0].id
    assert first.message.tool_calls[0].name == "inspect_dataset"
    assert first.message.tool_calls[0].arguments == {"path": "sales.csv"}
    assert first.finish_reason == "stop"
    assert first.usage is not None
    assert first.usage.model_dump() == {
        "input_tokens": 31,
        "output_tokens": 8,
        "total_tokens": 39,
    }
    assert first.request_id is None
    assert first.raw is not None
    assert requests[0]["tools"][0]["function"]["name"] == "inspect_dataset"

    second = provider.generate(
        [
            ModelMessage(role="user", content="Inspect sales.csv"),
            first.message,
            ModelMessage(
                role="tool",
                content='{"row_count":12}',
                name="inspect_dataset",
                tool_call_id=first.message.tool_calls[0].id,
            ),
        ],
        tools=tools,
    )

    assert requests[0]["model"] == "configured-ollama-model"
    assert requests[1]["messages"][1]["tool_calls"] == [
        {
            "function": {
                "name": "inspect_dataset",
                "arguments": {"path": "sales.csv"},
            }
        }
    ]
    assert requests[1]["messages"][2] == {
        "role": "tool",
        "content": '{"row_count":12}',
    }
    assert second.message.content == "The dataset has 12 rows."


def test_ollama_uses_a_per_request_model_override() -> None:
    def complete(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["model"] == "override-model"
        return httpx.Response(
            200,
            json={
                "message": {"role": "assistant", "content": "OK"},
                "done": True,
                "done_reason": "stop",
            },
        )

    provider = OllamaProvider(
        {"model": "configured-model"},
        transport=httpx.MockTransport(complete),
    )

    response = provider.generate(
        [ModelMessage(role="user", content="Hello")],
        model="override-model",
    )

    assert response.content == "OK"


class MetadataProvider:
    name = "metadata-test"

    def __init__(self) -> None:
        self.messages_seen: list[list[ModelMessage]] = []

    def generate(self, messages, tools=None, model=None, temperature=0.2):
        self.messages_seen.append(messages)
        if len(self.messages_seen) == 1:
            return ModelResponse(
                message=ModelMessage(
                    role="assistant",
                    tool_calls=[
                        ModelToolCall(
                            id="call-profile-1",
                            name="inspect_dataset",
                            arguments={},
                        )
                    ],
                ),
                finish_reason="tool_calls",
                usage=ModelUsage(input_tokens=20, output_tokens=5, total_tokens=25),
                request_id="req-profile-1",
                response_id="chatcmpl-profile-1",
                raw={"diagnostic": "first turn"},
            )
        return ModelResponse(
            message=ModelMessage(role="assistant", content="## Findings\nDataset inspected."),
            finish_reason="stop",
            usage=ModelUsage(input_tokens=35, output_tokens=7, total_tokens=42),
            request_id="req-final-1",
            response_id="chatcmpl-final-1",
            raw={"diagnostic": "final turn"},
        )


class ToolPolicyProvider:
    name = "tool-policy-test"
    default_model = "native-model"

    def __init__(self) -> None:
        self.tools_seen: list[list[ToolSchema] | None] = []

    def generate(self, messages, tools=None, model=None, temperature=0.2):
        self.tools_seen.append(tools)
        return ModelResponse(content="## Findings\nNo analysis requested.")


def native_tool_policy_config(provider: ToolPolicyProvider) -> DimerConfig:
    return DimerConfig(
        default_provider=provider.name,
        default_model=provider.default_model,
        providers={
            provider.name: {
                "models": {
                    provider.default_model: {"tool_protocol": "native"},
                }
            }
        },
    )


def test_agent_sends_tool_schemas_for_a_model_with_native_capability(
    tmp_path: Path,
) -> None:
    provider = ToolPolicyProvider()
    config = native_tool_policy_config(provider)
    loop = AgentLoop(provider, ToolRouter(tmp_path, config), config=config)

    loop.run("Say hello.", AgentContext(workspace=tmp_path))

    assert provider.tools_seen
    assert provider.tools_seen[0]


def test_agent_uses_json_fallback_for_an_unverified_model_override(
    tmp_path: Path,
) -> None:
    provider = ToolPolicyProvider()
    config = native_tool_policy_config(provider)
    loop = AgentLoop(
        provider,
        ToolRouter(tmp_path, config),
        config=config,
        model="unverified-model",
    )

    loop.run("Say hello.", AgentContext(workspace=tmp_path))

    assert provider.tools_seen == [None]


def test_agent_preserves_structured_provider_turns_and_metadata(tmp_path: Path) -> None:
    provider = MetadataProvider()
    config = DimerConfig(
        default_provider=provider.name,
        providers={
            provider.name: {
                "models": {
                    "qwen2.5-coder:7b": {"tool_protocol": "native"},
                }
            }
        },
    )
    dataset = Path(__file__).parent.parent / "examples" / "sales" / "sales.csv"
    loop = AgentLoop(
        provider,
        ToolRouter(tmp_path, config),
        config=config,
        max_iterations=3,
    )

    result = loop.run(
        "Inspect this dataset.",
        AgentContext(workspace=tmp_path, dataset_path=str(dataset)),
    )

    second_turn = provider.messages_seen[1]
    assistant = next(message for message in second_turn if message.role == "assistant")
    tool_result = next(message for message in second_turn if message.role == "tool")
    assert assistant.content is None
    assert assistant.tool_calls[0].id == "call-profile-1"
    assert tool_result.tool_call_id == "call-profile-1"

    saved = load_session(result.session_id, tmp_path)
    assert saved["provider_responses"] == [
        {
            "finish_reason": "tool_calls",
            "usage": {"input_tokens": 20, "output_tokens": 5, "total_tokens": 25},
            "request_id": "req-profile-1",
            "response_id": "chatcmpl-profile-1",
            "raw": {"diagnostic": "first turn"},
        },
        {
            "finish_reason": "stop",
            "usage": {"input_tokens": 35, "output_tokens": 7, "total_tokens": 42},
            "request_id": "req-final-1",
            "response_id": "chatcmpl-final-1",
            "raw": {"diagnostic": "final turn"},
        },
    ]


def test_agent_preserves_actionable_provider_error_after_tool_evidence(
    tmp_path: Path,
) -> None:
    calls = 0

    def tool_then_timeout(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
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
                                        "id": "call-sql-1",
                                        "type": "function",
                                        "function": {
                                            "name": "run_duckdb_query",
                                            "arguments": json.dumps(
                                                {
                                                    "query": (
                                                        "SELECT region, SUM(revenue) AS total "
                                                        "FROM sales GROUP BY region "
                                                        "ORDER BY total DESC"
                                                    )
                                                }
                                            ),
                                        },
                                    }
                                ],
                            },
                        }
                    ]
                },
            )
        raise httpx.ReadTimeout("timed out", request=request)

    provider = LMStudioProvider(
        {"base_url": "http://127.0.0.1:1234/v1", "model": "local-model"},
        transport=httpx.MockTransport(tool_then_timeout),
    )
    config = DimerConfig(
        default_provider="lmstudio",
        default_model="local-model",
        providers={
            "lmstudio": {
                "models": {"local-model": {"tool_protocol": "native"}},
            }
        },
    )
    events = ListEventSink()
    dataset = Path(__file__).parent.parent / "examples" / "sales" / "sales.csv"
    loop = AgentLoop(
        provider,
        ToolRouter(tmp_path, config),
        config=config,
        event_sink=events,
        max_iterations=3,
    )

    result = loop.run(
        "Which region contributed the most revenue?",
        AgentContext(workspace=tmp_path, dataset_path=str(dataset)),
    )

    assert "latest successful SQL evidence" in result.findings
    assert any("LM Studio timed out after 300 seconds" in note for note in result.caveats)
    failed = [event for event in events.events if event.type == "model_call_failed"]
    assert len(failed) == 1
    assert "Check server load" in (failed[0].message or "")
    saved = load_session(result.session_id, tmp_path)
    assert "LM Studio timed out after 300 seconds" in saved["final_content"]
