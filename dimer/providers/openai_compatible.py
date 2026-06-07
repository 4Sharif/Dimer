"""OpenAI-compatible API provider."""

from __future__ import annotations

import json
import uuid
from typing import Any, Iterator

import httpx

from dimer.providers.base import (
    ModelMessage,
    ModelResponse,
    ModelStreamEvent,
    ModelToolCall,
    ToolSchema,
    parse_json_tool_response,
)


class OpenAICompatibleProvider:
    name: str

    def __init__(
        self,
        name: str = "openai_compatible",
        base_url: str = "http://localhost:1234/v1",
        api_key: str | None = None,
        default_model: str = "local-model",
    ) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or "not-needed"
        self.default_model = default_model

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

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
            "messages": [m.model_dump(exclude_none=True) for m in messages],
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

    def _parse_response(self, data: dict[str, Any]) -> ModelResponse:
        choice = data.get("choices", [{}])[0]
        message = choice.get("message", {})
        content = message.get("content")
        tool_calls = []
        for tc in message.get("tool_calls", []) or []:
            fn = tc.get("function", {})
            args = fn.get("arguments", "{}")
            if isinstance(args, str):
                args = json.loads(args)
            tool_calls.append(ModelToolCall(id=tc.get("id", str(uuid.uuid4())), name=fn["name"], arguments=args))
        if not tool_calls and content:
            parsed = parse_json_tool_response(content)
            if parsed:
                return parsed
        return ModelResponse(content=content, tool_calls=tool_calls, raw=data)

    def generate(
        self,
        messages: list[ModelMessage],
        tools: list[ToolSchema] | None = None,
        model: str | None = None,
        temperature: float = 0.2,
    ) -> ModelResponse:
        payload = self._payload(messages, tools, model, temperature, stream=False)
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(f"{self.base_url}/chat/completions", headers=self._headers(), json=payload)
            resp.raise_for_status()
            return self._parse_response(resp.json())

    def stream(
        self,
        messages: list[ModelMessage],
        tools: list[ToolSchema] | None = None,
        model: str | None = None,
        temperature: float = 0.2,
    ) -> Iterator[ModelStreamEvent]:
        response = self.generate(messages, tools, model, temperature)
        if response.content:
            yield ModelStreamEvent(type="delta", content=response.content)
        yield ModelStreamEvent(type="done", response=response)
