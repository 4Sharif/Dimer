"""Provider interface and shared types."""

from __future__ import annotations

import json
import re
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field, model_validator

from dimer.config import (
    DimerConfig,
    ToolProtocol,
    get_provider_config,
    load_config,
    provider_data_locality,
    resolve_api_key,
)


class ProviderError(RuntimeError):
    """Actionable failure at a model-provider boundary."""


class ModelToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]


class ModelMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: list[ModelToolCall] = Field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None


class ModelUsage(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class ModelResponse(BaseModel):
    message: ModelMessage = Field(
        default_factory=lambda: ModelMessage(role="assistant")
    )
    finish_reason: str | None = None
    usage: ModelUsage | None = None
    request_id: str | None = None
    response_id: str | None = None
    raw: dict[str, Any] | None = None

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_content_and_tool_calls(cls, data: Any) -> Any:
        """Keep existing in-process test providers source-compatible."""
        if not isinstance(data, dict) or "message" in data:
            return data
        legacy_data = dict(data)
        content = legacy_data.pop("content", None)
        tool_calls = legacy_data.pop("tool_calls", [])
        return {
            **legacy_data,
            "message": ModelMessage(
                role="assistant",
                content=content,
                tool_calls=tool_calls,
            ),
        }

    @property
    def content(self) -> str | None:
        return self.message.content

    @property
    def tool_calls(self) -> list[ModelToolCall]:
        return self.message.tool_calls

    def diagnostics(self) -> dict[str, Any]:
        """Return provider metadata suitable for redacted session persistence."""
        return {
            "finish_reason": self.finish_reason,
            "usage": self.usage.model_dump() if self.usage is not None else None,
            "request_id": self.request_id,
            "response_id": self.response_id,
            "raw": self.raw,
        }


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


def tool_result_message(
    tool_protocol: ToolProtocol,
    tool_call: ModelToolCall,
    observation: dict[str, Any],
) -> ModelMessage:
    """Build the next provider message for a completed Dimer tool call."""
    if tool_protocol == "json":
        return ModelMessage(role="user", content=json.dumps(observation))
    return ModelMessage(
        role="tool",
        content=json.dumps(observation),
        name=tool_call.name,
        tool_call_id=tool_call.id,
    )


def _iter_json_objects(text: str) -> list[dict[str, Any]]:
    """Extract top-level JSON objects from free-form model text."""
    decoder = json.JSONDecoder()
    objects: list[dict[str, Any]] = []
    idx = 0
    while idx < len(text):
        start = text.find("{", idx)
        if start < 0:
            break
        try:
            obj, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            idx = start + 1
            continue
        if isinstance(obj, dict):
            objects.append(obj)
        idx = end
    return objects


def parse_json_tool_response(text: str) -> ModelResponse | None:
    """Parse JSON tool-call / final protocol from model content.

    Handles:
    - a single JSON object
    - fenced ```json``` blocks
    - prose mixed with one or more {"type":"tool_call",...} objects
    """
    text = text.strip()
    if not text:
        return None

    fenced_blocks = re.findall(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    scan_text = "\n".join(fenced_blocks) if fenced_blocks else text
    objects = _iter_json_objects(scan_text)
    if not objects and fenced_blocks:
        objects = _iter_json_objects(text)

    tool_calls: list[ModelToolCall] = []
    final_content: str | None = None
    for i, data in enumerate(objects):
        obj_type = data.get("type")
        if obj_type == "tool_call" and data.get("tool_name"):
            args = data.get("arguments", {})
            if not isinstance(args, dict):
                args = {}
            tool_calls.append(
                ModelToolCall(
                    id=f"json-fallback-{i + 1}",
                    name=str(data["tool_name"]),
                    arguments=args,
                )
            )
        elif obj_type == "final":
            final_content = str(data.get("content", ""))

    # Prefer executable tool calls over a premature final answer.
    if tool_calls:
        # Local models often dump many calls at once; keep one per turn.
        return ModelResponse(content=None, tool_calls=tool_calls[:1])
    if final_content is not None:
        return ModelResponse(content=final_content)
    return None


def create_provider(name: str | None = None, config: DimerConfig | None = None) -> ModelProvider:
    cfg = config or load_config()
    provider_name = name or cfg.default_provider
    provider_cfg = get_provider_config(cfg, provider_name)

    if provider_name == "anthropic":
        raise ValueError(
            "Anthropic is unsupported: Dimer does not implement the Anthropic "
            "Messages API. Choose openai, lmstudio, ollama, gemini, or a custom "
            "OpenAI-compatible endpoint."
        )
    if (
        provider_data_locality(cfg, provider_name) == "cloud"
        and not cfg.privacy.allow_cloud_llm
    ):
        raise ValueError(
            f"Cloud provider '{provider_name}' is disabled by privacy policy. "
            "Review what context will be shared, then set allow_cloud_llm = true "
            "under [privacy] to opt in."
        )
    if provider_name == "ollama":
        from dimer.providers.ollama import OllamaProvider

        return OllamaProvider(provider_cfg, default_model=cfg.default_model)
    if provider_name == "lmstudio":
        from dimer.providers.lmstudio import LMStudioProvider

        return LMStudioProvider(provider_cfg, default_model=cfg.default_model)
    if provider_name in ("openai", "gemini"):
        from dimer.providers.openai_compatible import OpenAICompatibleProvider

        base_url = provider_cfg.get("base_url")
        if provider_name == "openai" and not base_url:
            base_url = "https://api.openai.com/v1"
        elif provider_name == "gemini" and not base_url:
            base_url = "https://generativelanguage.googleapis.com/v1beta/openai"
        api_key = resolve_api_key(provider_cfg)
        if not api_key:
            configured_env = provider_cfg.get("api_key_env")
            if configured_env:
                raise ValueError(
                    f"No API key found for provider '{provider_name}'. "
                    f"Set ${configured_env} or use api_key in the provider config."
                )
            raise ValueError(
                f"No API key configured for provider '{provider_name}'. "
                "Set api_key_env or api_key in the provider config."
            )
        return OpenAICompatibleProvider(
            name=provider_name,
            base_url=base_url or "http://localhost:1234/v1",
            api_key=api_key,
            default_model=provider_cfg.get("model", cfg.default_model),
            include_raw_diagnostics=bool(
                provider_cfg.get("include_raw_diagnostics", False)
            ),
        )
    from dimer.providers.openai_compatible import OpenAICompatibleProvider

    return OpenAICompatibleProvider(
        name=provider_name,
        base_url=provider_cfg.get("base_url", "http://localhost:1234/v1"),
        api_key=resolve_api_key(provider_cfg),
        default_model=provider_cfg.get("model", cfg.default_model),
        include_raw_diagnostics=bool(
            provider_cfg.get("include_raw_diagnostics", False)
        ),
    )
