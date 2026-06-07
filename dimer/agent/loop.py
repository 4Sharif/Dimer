"""Thought-Action-Observation agent loop."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dimer.agent.compaction import compact_profile_for_context, compact_tool_result
from dimer.agent.events import EventSink, emit_event
from dimer.agent.prompts import get_system_prompt
from dimer.agent.session import AgentContext, AgentSession
from dimer.agent.tool_router import ToolRouter
from dimer.config import DimerConfig, load_config, provider_uses_native_tools
from dimer.data_context.artifact_registry import ArtifactRegistry
from dimer.data_context.assumption_log import AssumptionLog
from dimer.data_context.schema_profile import profile_dataset
from dimer.data_context.workspace_scanner import compact_workspace_summary
from dimer.providers.base import ModelMessage, ModelProvider
from dimer.storage.sessions import new_session_id, save_session


@dataclass
class AgentResult:
    content: str
    session_id: str
    artifacts: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)


class AgentLoop:
    def __init__(
        self,
        provider: ModelProvider,
        tool_router: ToolRouter,
        event_sink: EventSink | None = None,
        config: DimerConfig | None = None,
        max_iterations: int = 12,
    ) -> None:
        self.provider = provider
        self.tool_router = tool_router
        self.event_sink = event_sink
        self.config = config or load_config()
        self.max_iterations = max_iterations

    def _build_context_message(self, context: AgentContext) -> str:
        parts = [f"Workspace: {context.workspace}"]
        if context.dataset_path:
            parts.append(f"Primary dataset: {context.dataset_path}")
            try:
                profile = profile_dataset(context.dataset_path)
                parts.append("Dataset profile summary:")
                parts.append(json.dumps(compact_profile_for_context(profile.model_dump(mode="json")), indent=2))
            except Exception as e:
                parts.append(f"Could not profile dataset: {e}")
        summary = compact_workspace_summary(context.workspace)
        parts.append(f"Workspace summary: {json.dumps(summary, indent=2)}")
        return "\n".join(parts)

    def run(
        self,
        user_message: str,
        context: AgentContext,
        auto_approve: bool = True,
    ) -> AgentResult:
        session = AgentSession()
        session_id = new_session_id()
        emit_event(self.event_sink, "agent_started", message="Agent started", session_id=session_id)

        system_prompt = get_system_prompt(context.mode)
        context_msg = self._build_context_message(context)
        messages = [
            ModelMessage(role="system", content=system_prompt),
            ModelMessage(role="user", content=f"Context:\n{context_msg}\n\nQuestion: {user_message}"),
        ]

        final_content = ""
        all_tools = self.tool_router.get_schemas(context.mode)
        use_native = provider_uses_native_tools(self.config, self.provider.name)
        tools = all_tools if use_native else None

        for i in range(self.max_iterations):
            emit_event(
                self.event_sink,
                "agent_iteration",
                message=f"Agent step {i + 1}/{self.max_iterations}",
                iteration=i + 1,
            )
            emit_event(
                self.event_sink,
                "model_call_started",
                message=f"Calling {self.provider.name} ({self.config.default_model})...",
                provider=self.provider.name,
                model=self.config.default_model,
            )
            response = self.provider.generate(messages, tools=tools, model=self.config.default_model)
            emit_event(
                self.event_sink,
                "model_call_finished",
                message="Model responded",
                provider=self.provider.name,
                has_tool_calls=bool(response.tool_calls),
            )

            if response.tool_calls:
                for tc in response.tool_calls:
                    emit_event(
                        self.event_sink,
                        "tool_call_requested",
                        tool_name=tc.name,
                        arguments=tc.arguments,
                    )
                    emit_event(self.event_sink, "tool_call_started", tool_name=tc.name)
                    result = self.tool_router.execute(tc.name, tc.arguments, auto_approve=auto_approve)
                    emit_event(
                        self.event_sink,
                        "tool_call_finished" if result.get("success") else "tool_call_failed",
                        tool_name=tc.name,
                        success=result.get("success"),
                    )
                    compact = compact_tool_result(result.get("result") or result)
                    try:
                        parsed_result = json.loads(compact)
                    except json.JSONDecodeError:
                        parsed_result = compact
                    observation = {
                        "type": "tool_result",
                        "tool_name": tc.name,
                        "success": result.get("success"),
                        "result": parsed_result,
                    }
                    session.tool_results.append(observation)
                    messages.append(ModelMessage(role="assistant", content=json.dumps({
                        "type": "tool_call",
                        "tool_name": tc.name,
                        "arguments": tc.arguments,
                    })))
                    messages.append(ModelMessage(
                        role="tool",
                        content=json.dumps(observation),
                        name=tc.name,
                        tool_call_id=tc.id,
                    ))
                continue

            if response.content:
                final_content = response.content
                break

        if not final_content:
            final_content = "Agent reached iteration limit without a final response."

        emit_event(self.event_sink, "agent_finished", message="Agent finished")

        ws = context.workspace
        artifacts = [a.path for a in ArtifactRegistry(ws).list_all()]
        assumptions = [a.text for a in AssumptionLog(ws).list_all()]

        save_session(session_id, {
            "messages": [m.model_dump() for m in messages],
            "tool_results": session.tool_results,
            "final_content": final_content,
            "artifacts": artifacts,
            "assumptions": assumptions,
        }, ws)

        return AgentResult(
            content=final_content,
            session_id=session_id,
            artifacts=artifacts,
            assumptions=assumptions,
        )
