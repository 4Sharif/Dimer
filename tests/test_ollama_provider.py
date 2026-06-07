"""Tests for Ollama message serialization."""

from __future__ import annotations

import json

from dimer.providers.base import ModelMessage
from dimer.providers.ollama import OllamaProvider


def test_ollama_includes_tool_messages() -> None:
    provider = OllamaProvider({"use_native_tools": False})
    messages = [
        ModelMessage(role="user", content="hi"),
        ModelMessage(role="assistant", content=json.dumps({
            "type": "tool_call",
            "tool_name": "inspect_dataset",
            "arguments": {"path": "sales.csv"},
        })),
        ModelMessage(role="tool", content='{"success": true}', name="inspect_dataset"),
    ]
    ollama_msgs = provider._to_ollama_messages(messages)
    roles = [m["role"] for m in ollama_msgs]
    assert "tool" in roles
    assert any(m.get("tool_calls") for m in ollama_msgs if m["role"] == "assistant")
