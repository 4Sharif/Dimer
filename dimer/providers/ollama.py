"""Ollama provider."""

from __future__ import annotations

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


class OllamaProvider:
    name = "ollama"

    def __init__(
        self,
        config: dict[str, Any],
        default_model: str = "gemma4:e4b",
        transport: httpx.BaseTransport | None = None,
        include_raw_diagnostics: bool | None = None,
    ) -> None:
        self.base_url = config.get("base_url", "http://localhost:11434").rstrip("/")
        self.default_model = str(config.get("model", default_model))
        self.num_predict = int(config.get("num_predict", 2048))
        self.num_ctx = int(config.get("num_ctx", 8192))
        self.transport = transport
        self.include_raw_diagnostics = (
            bool(config.get("include_raw_diagnostics", False))
            if include_raw_diagnostics is None
            else include_raw_diagnostics
        )

    def _to_ollama_messages(self, messages: list[ModelMessage]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "tool":
                out.append({
                    "role": "tool",
                    "content": m.content,
                })
                continue
            if m.role == "assistant":
                entry: dict[str, Any] = {"role": "assistant", "content": m.content or ""}
                if m.tool_calls:
                    entry["tool_calls"] = [
                        {
                            "function": {
                                "name": tool_call.name,
                                "arguments": tool_call.arguments,
                            }
                        }
                        for tool_call in m.tool_calls
                    ]
                out.append(entry)
                continue
            if m.role in ("system", "user"):
                out.append({"role": m.role, "content": m.content})
        return out

    def _parse_response(
        self,
        data: dict[str, Any],
        *,
        context: ProviderRequestContext,
    ) -> ModelResponse:
        message = data.get("message")
        if not isinstance(message, dict):
            raise ValueError("assistant message is not an object")
        content = message.get("content", "") or ""
        tool_calls = []
        tool_calls_data = message.get("tool_calls", []) or []
        if not isinstance(tool_calls_data, list):
            raise ValueError("assistant tool_calls is not a list")
        for tool_call_data in tool_calls_data:
            tool_name, arguments = decode_tool_function(tool_call_data, context)
            tool_calls.append(
                ModelToolCall(
                    id=str(uuid.uuid4()),
                    name=tool_name,
                    arguments=arguments,
                )
            )
        if data.get("done_reason") == "length" and len(content.strip()) < 20:
            content = (
                f"{content}\n\n[Warning: model output was truncated (done_reason=length). "
                "Try a smaller context or increase num_predict in config.]"
            ).strip()
        input_tokens = data.get("prompt_eval_count")
        output_tokens = data.get("eval_count")
        total_tokens = None
        if isinstance(input_tokens, int) and isinstance(output_tokens, int):
            total_tokens = input_tokens + output_tokens
        usage = None
        if input_tokens is not None or output_tokens is not None:
            usage = ModelUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
            )
        return ModelResponse(
            message=ModelMessage(
                role="assistant",
                content=content,
                tool_calls=tool_calls,
            ),
            finish_reason=data.get("done_reason"),
            usage=usage,
            raw=data if self.include_raw_diagnostics else None,
        )

    def _options(self, temperature: float) -> dict[str, Any]:
        return {
            "temperature": temperature,
            "num_predict": self.num_predict,
            "num_ctx": self.num_ctx,
        }

    def generate(
        self,
        messages: list[ModelMessage],
        tools: list[ToolSchema] | None = None,
        model: str | None = None,
        temperature: float = 0.2,
    ) -> ModelResponse:
        selected_model = model or self.default_model
        payload: dict[str, Any] = {
            "model": selected_model,
            "messages": self._to_ollama_messages(messages),
            "stream": False,
            "options": self._options(temperature),
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
        context = ProviderRequestContext(self.name, self.base_url, selected_model)
        data, _request_id = post_provider_json(
            context=context,
            path="/api/chat",
            payload=payload,
            transport=self.transport,
        )
        try:
            return self._parse_response(data, context=context)
        except ProviderError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise invalid_response_error(
                context,
                "Response did not match the expected response schema.",
            ) from exc
