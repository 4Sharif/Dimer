"""OpenAI-compatible API provider."""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx

from dimer.providers.base import (
    ModelMessage,
    ModelResponse,
    ModelToolCall,
    ModelUsage,
    ProviderError,
    ToolSchema,
)
from dimer.providers.transport import (
    ProviderRequestContext,
    decode_tool_function,
    invalid_response_error,
    post_provider_json,
)


class OpenAICompatibleProvider:
    name: str

    def __init__(
        self,
        name: str = "openai_compatible",
        base_url: str = "http://localhost:1234/v1",
        api_key: str | None = None,
        default_model: str = "local-model",
        transport: httpx.BaseTransport | None = None,
        include_raw_diagnostics: bool = False,
    ) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or "not-needed"
        self.default_model = default_model
        self.transport = transport
        self.include_raw_diagnostics = include_raw_diagnostics

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _payload(
        self,
        messages: list[ModelMessage],
        tools: list[ToolSchema] | None,
        model: str | None,
        temperature: float,
        stream: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model or self.default_model,
            "messages": [self._serialize_message(message) for message in messages],
            "temperature": temperature,
            "stream": stream,
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.input_schema,
                    },
                }
                for t in tools
            ]
        return payload

    @staticmethod
    def _serialize_message(message: ModelMessage) -> dict[str, Any]:
        serialized: dict[str, Any] = {"role": message.role}
        if message.content is not None:
            serialized["content"] = message.content
        if message.tool_calls:
            serialized["tool_calls"] = [
                {
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": tool_call.name,
                        "arguments": json.dumps(tool_call.arguments),
                    },
                }
                for tool_call in message.tool_calls
            ]
        if message.tool_call_id is not None:
            serialized["tool_call_id"] = message.tool_call_id
        if message.name is not None:
            serialized["name"] = message.name
        return serialized

    def _parse_response(
        self,
        data: dict[str, Any],
        *,
        request_id: str | None = None,
        context: ProviderRequestContext,
    ) -> ModelResponse:
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ValueError("missing first response choice")
        choice = choices[0]
        message = choice.get("message")
        if not isinstance(message, dict):
            raise ValueError("assistant message is not an object")
        content = message.get("content")
        tool_calls = []
        tool_calls_data = message.get("tool_calls", []) or []
        if not isinstance(tool_calls_data, list):
            raise ValueError("assistant tool_calls is not a list")
        for tool_call_data in tool_calls_data:
            tool_name, arguments = decode_tool_function(tool_call_data, context)
            tool_calls.append(
                ModelToolCall(
                    id=tool_call_data.get("id", str(uuid.uuid4())),
                    name=tool_name,
                    arguments=arguments,
                )
            )
        usage_data = data.get("usage")
        usage = None
        if isinstance(usage_data, dict):
            usage = ModelUsage(
                input_tokens=usage_data.get("prompt_tokens"),
                output_tokens=usage_data.get("completion_tokens"),
                total_tokens=usage_data.get("total_tokens"),
            )
        response_id = data.get("id")
        if not isinstance(response_id, str) or not response_id.strip():
            response_id = None
        return ModelResponse(
            message=ModelMessage(
                role="assistant",
                content=content,
                tool_calls=tool_calls,
            ),
            finish_reason=choice.get("finish_reason"),
            usage=usage,
            request_id=request_id,
            response_id=response_id,
            raw=data if self.include_raw_diagnostics else None,
        )

    def generate(
        self,
        messages: list[ModelMessage],
        tools: list[ToolSchema] | None = None,
        model: str | None = None,
        temperature: float = 0.2,
    ) -> ModelResponse:
        payload = self._payload(messages, tools, model, temperature, stream=False)
        selected_model = model or self.default_model
        context = ProviderRequestContext(self.name, self.base_url, selected_model)
        data, request_id = post_provider_json(
            context=context,
            path="/chat/completions",
            payload=payload,
            headers=self._headers(),
            transport=self.transport,
        )
        try:
            return self._parse_response(
                data,
                request_id=request_id,
                context=context,
            )
        except ProviderError:
            raise
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            raise invalid_response_error(
                context,
                "Response did not match the expected response schema.",
            ) from exc
