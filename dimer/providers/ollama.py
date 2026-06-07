"""Ollama provider."""

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


class OllamaProvider:
    name = "ollama"

    def __init__(
        self,
        config: dict[str, Any],
        default_model: str = "gemma4:e4b",
    ) -> None:
        self.base_url = config.get("base_url", "http://localhost:11434").rstrip("/")
        self.default_model = default_model
        self.use_native_tools = bool(config.get("use_native_tools", False))
        self.num_predict = int(config.get("num_predict", 2048))
        self.num_ctx = int(config.get("num_ctx", 8192))

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
                if m.content and m.content.strip().startswith('{"type": "tool_call"'):
                    try:
                        data = json.loads(m.content)
                        if data.get("type") == "tool_call":
                            entry["tool_calls"] = [{
                                "function": {
                                    "name": data["tool_name"],
                                    "arguments": data.get("arguments", {}),
                                }
                            }]
                            entry["content"] = ""
                    except json.JSONDecodeError:
                        pass
                out.append(entry)
                continue
            if m.role in ("system", "user"):
                out.append({"role": m.role, "content": m.content})
        return out

    def _parse_response(self, data: dict[str, Any]) -> ModelResponse:
        message = data.get("message", {})
        content = message.get("content", "") or ""
        tool_calls = []
        for tc in message.get("tool_calls", []) or []:
            fn = tc.get("function", {})
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            tool_calls.append(
                ModelToolCall(id=str(uuid.uuid4()), name=fn["name"], arguments=args)
            )
        if not tool_calls:
            parsed = parse_json_tool_response(content)
            if parsed:
                return parsed
        if data.get("done_reason") == "length" and len(content.strip()) < 20:
            content = (
                f"{content}\n\n[Warning: model output was truncated (done_reason=length). "
                "Try a smaller context or increase num_predict in config.]"
            ).strip()
        return ModelResponse(content=content, tool_calls=tool_calls, raw=data)

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
        payload: dict[str, Any] = {
            "model": model or self.default_model,
            "messages": self._to_ollama_messages(messages),
            "stream": False,
            "options": self._options(temperature),
        }
        if tools and self.use_native_tools:
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
        with httpx.Client(timeout=300.0) as client:
            resp = client.post(f"{self.base_url}/api/chat", json=payload)
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
