"""Agent loop tests with mocked provider."""

from __future__ import annotations

from pathlib import Path

import pytest

from dimer.agent.loop import AgentLoop
from dimer.agent.session import AgentContext
from dimer.agent.tool_router import ToolRouter
from dimer.providers.base import ModelMessage, ModelResponse, ModelToolCall, ToolSchema
from dimer.storage.artifacts import ensure_workspace_dirs


class MockProvider:
    name = "mock"
    calls = 0

    def generate(self, messages, tools=None, model=None, temperature=0.2):
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                tool_calls=[
                    ModelToolCall(
                        id="1",
                        name="inspect_dataset",
                        arguments={"path": str(Path(__file__).parent.parent / "examples" / "sales" / "sales.csv")},
                    )
                ]
            )
        return ModelResponse(content="## Findings\nRevenue trends analyzed.")

    def stream(self, messages, tools=None, model=None, temperature=0.2):
        yield from ()


def test_agent_loop_with_mock(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)
    provider = MockProvider()
    router = ToolRouter(tmp_path)
    loop = AgentLoop(provider, router, max_iterations=3)
    ctx = AgentContext(
        workspace=tmp_path,
        dataset_path=str(Path(__file__).parent.parent / "examples" / "sales" / "sales.csv"),
    )
    result = loop.run("What are the trends?", ctx)
    assert "Findings" in result.content
    assert provider.calls == 2
