"""Tests for approval helpers and agent approval callback."""

from __future__ import annotations

from pathlib import Path

from dimer.agent.loop import AgentLoop
from dimer.agent.session import AgentContext
from dimer.agent.tool_router import ToolRouter
from dimer.providers.base import ModelResponse, ModelToolCall
from dimer.storage.artifacts import ensure_workspace_dirs
from dimer.storage.sessions import load_session
from dimer.ui.approvals import describe_tool_risk


def test_describe_tool_risk_explains_operation_target_reason_and_consequence() -> None:
    text = describe_tool_risk("run_python", {"code": "print(1)\nprint(2)"})
    assert "Operation: execute Python code" in text
    assert "Target: isolated child process in the current workspace" in text
    assert "Why: perform analysis that is not available through bounded SQL" in text
    assert "Consequence: code can consume resources and create workspace artifacts" in text
    assert "print(1)" in text


def test_describe_tool_risk_redacts_secrets_from_code_preview() -> None:
    secret = "sk-supersecretvalue123456"

    text = describe_tool_risk("run_python", {"code": f"print('{secret}')"})

    assert secret not in text
    assert "[REDACTED_SECRET]" in text


def test_model_visible_tools_have_explicit_mvp_risk_levels(tmp_path: Path) -> None:
    definitions = {tool.name: tool.risk_level for tool in ToolRouter(tmp_path).list_tools()}

    assert definitions["inspect_dataset"] == "safe"
    assert definitions["profile_dataset"] == "safe"
    assert definitions["run_duckdb_query"] == "safe"
    assert definitions["run_python"] == "approval_required"
    assert definitions["write_file"] == "approval_required"
    assert definitions["save_report"] == "approval_required"
    assert "run_shell" not in definitions


class ApprovalPythonProvider:
    name = "mock"

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, messages, tools=None, model=None, temperature=0.2):
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                tool_calls=[
                    ModelToolCall(
                        id="1",
                        name="run_python",
                        arguments={"code": "result = 1 + 1"},
                    )
                ]
            )
        return ModelResponse(content="## Findings\nPython ran.")

    def stream(self, messages, tools=None, model=None, temperature=0.2):
        yield from ()


class EvidencePythonProvider(ApprovalPythonProvider):
    def generate(self, messages, tools=None, model=None, temperature=0.2):
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                tool_calls=[
                    ModelToolCall(
                        id="1",
                        name="run_python",
                        arguments={"code": "print(42)"},
                    )
                ]
            )
        return ModelResponse(content="## Findings\nThe computed answer is 42.")


def test_python_factual_answer_exposes_computed_result(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)
    loop = AgentLoop(EvidencePythonProvider(), ToolRouter(tmp_path), max_iterations=3)

    result = loop.run(
        "Compute something in python",
        AgentContext(workspace=tmp_path),
        auto_approve=True,
    )

    assert "42" in "\n".join(result.evidence)


def test_agent_loop_approval_callback_can_allow(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)
    seen: list[str] = []
    approval_arguments: list[dict] = []

    def approve(tool_name: str, arguments: dict) -> bool:
        seen.append(tool_name)
        approval_arguments.append(arguments)
        return True

    provider = ApprovalPythonProvider()
    router = ToolRouter(tmp_path)
    loop = AgentLoop(provider, router, max_iterations=3, approval_callback=approve)
    ctx = AgentContext(workspace=tmp_path)

    result = loop.run("Compute something in python", ctx, auto_approve=False)

    assert seen == ["run_python"]
    assert approval_arguments[0]["workspace"] == str(tmp_path)
    assert "Python ran" in result.content


def test_agent_loop_approval_callback_can_deny(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)

    def deny(tool_name: str, arguments: dict) -> bool:
        return False

    provider = ApprovalPythonProvider()
    router = ToolRouter(tmp_path)
    loop = AgentLoop(provider, router, max_iterations=3, approval_callback=deny)
    ctx = AgentContext(workspace=tmp_path)

    result = loop.run("Compute something in python", ctx, auto_approve=False)

    assert "denied by the user" in result.content


def test_agent_loop_requires_opt_in_for_python_by_default(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)
    provider = ApprovalPythonProvider()
    loop = AgentLoop(provider, ToolRouter(tmp_path), max_iterations=3)
    ctx = AgentContext(workspace=tmp_path)

    result = loop.run("Compute something in python", ctx)

    saved = load_session(result.session_id, tmp_path)
    assert saved["tool_results"][0]["success"] is False
    assert saved["tool_results"][0]["error"] == "Tool run_python requires approval"
