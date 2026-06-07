"""Provider interface and shared types."""

from __future__ import annotations

import json
import re
from typing import Any, Iterator, Literal, Protocol

from pydantic import BaseModel, Field

from dimer.config import DimerConfig, get_provider_config, load_config, resolve_api_key


class ModelMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_call_id: str | None = None
    name: str | None = None


class ModelToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]


class ModelResponse(BaseModel):
    content: str | None = None
    tool_calls: list[ModelToolCall] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class ModelStreamEvent(BaseModel):
    type: Literal["delta", "done"]
    content: str | None = None
    response: ModelResponse | None = None


class ToolSchema(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]


class ModelProvider(Protocol):
    name: str

    def generate(
        self,
        messages: list[ModelMessage],
        tools: list[ToolSchema] | None = None,
        model: str | None = None,
        temperature: float = 0.2,
    ) -> ModelResponse: ...

    def stream(
        self,
        messages: list[ModelMessage],
        tools: list[ToolSchema] | None = None,
        model: str | None = None,
        temperature: float = 0.2,
    ) -> Iterator[ModelStreamEvent]: ...


def parse_json_tool_response(text: str) -> ModelResponse | None:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return None
        else:
            return None

    if data.get("type") == "final":
        return ModelResponse(content=data.get("content", ""))
    if data.get("type") == "tool_call":
        return ModelResponse(
            tool_calls=[
                ModelToolCall(
                    id="json-fallback-1",
                    name=data["tool_name"],
                    arguments=data.get("arguments", {}),
                )
            ]
        )
    return None


def create_provider(name: str | None = None, config: DimerConfig | None = None) -> ModelProvider:
    cfg = config or load_config()
    provider_name = name or cfg.default_provider
    provider_cfg = get_provider_config(cfg, provider_name)

    if provider_name == "ollama":
        from dimer.providers.ollama import OllamaProvider

        return OllamaProvider(provider_cfg, default_model=cfg.default_model)
    if provider_name == "lmstudio":
        from dimer.providers.lmstudio import LMStudioProvider

        return LMStudioProvider(provider_cfg, default_model=cfg.default_model)
    if provider_name in ("openai", "anthropic", "gemini"):
        from dimer.providers.openai_compatible import OpenAICompatibleProvider

        base_url = provider_cfg.get("base_url")
        if provider_name == "openai" and not base_url:
            base_url = "https://api.openai.com/v1"
        elif provider_name == "anthropic" and not base_url:
            base_url = "https://api.anthropic.com/v1"
        elif provider_name == "gemini" and not base_url:
            base_url = "https://generativeai.googleapis.com/v1beta/openai"
        return OpenAICompatibleProvider(
            name=provider_name,
            base_url=base_url or "http://localhost:1234/v1",
            api_key=resolve_api_key(provider_cfg),
            default_model=provider_cfg.get("model", cfg.default_model),
        )
    from dimer.providers.openai_compatible import OpenAICompatibleProvider

    return OpenAICompatibleProvider(
        name=provider_name,
        base_url=provider_cfg.get("base_url", "http://localhost:1234/v1"),
        api_key=resolve_api_key(provider_cfg),
        default_model=provider_cfg.get("model", cfg.default_model),
    )
