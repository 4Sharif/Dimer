"""Thought-Action-Observation agent loop."""

from __future__ import annotations

import json
import re
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
from dimer.data_context.schema_profile import load_dataframe, profile_dataset
from dimer.data_context.workspace_scanner import compact_workspace_summary
from dimer.providers.base import ModelMessage, ModelProvider
from dimer.storage.sessions import new_session_id, save_session
from dimer.tools.chart import default_chart_path, register_chart
from dimer.tools.report import save_report


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

    def _coerce_final_content(self, content: str) -> str:
        stripped = content.strip()
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            return content
        if isinstance(data, dict) and data.get("type") == "final":
            return str(data.get("content", ""))
        return content

    def _successful_sql_observations(self, tool_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            obs
            for obs in tool_results
            if obs.get("tool_name") == "run_duckdb_query" and obs.get("success") is True
        ]

    def _fallback_final_answer(self, user_message: str, tool_results: list[dict[str, Any]]) -> str:
        sql_observations = self._successful_sql_observations(tool_results)
        if not sql_observations:
            return "Agent reached iteration limit without a final response."

        latest = sql_observations[-1].get("result", {})
        if isinstance(latest, str):
            try:
                latest = json.loads(latest)
            except json.JSONDecodeError:
                latest = {}
        rows = latest.get("preview_rows", []) if isinstance(latest, dict) else []
        artifact_path = latest.get("artifact_path") if isinstance(latest, dict) else None
        evidence = json.dumps(rows[:5], indent=2, default=str)
        return (
            "## Findings\n"
            "Dimer computed the query result, but the model did not return a final synthesis before the iteration limit.\n\n"
            "## Evidence\n"
            f"- Question: {user_message}\n"
            f"- Query artifact: {artifact_path or 'not saved'}\n"
            f"- Result preview:\n```json\n{evidence}\n```\n\n"
            "## Caveats\n"
            "- This is a deterministic fallback answer generated from the latest successful SQL observation."
        )

    def _report_path_name(self, user_message: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", user_message.lower()).strip("-")
        return f"{(slug or 'analysis')[:60]}.md"

    def _tool_summary_markdown(self, tool_results: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for obs in tool_results:
            result = obs.get("result", {})
            if isinstance(result, str):
                try:
                    result = json.loads(result)
                except json.JSONDecodeError:
                    result = {"content": result}
            status = "success" if obs.get("success") else "failed"
            lines.append(f"- `{obs.get('tool_name')}`: {status}")
            if isinstance(result, dict):
                artifact_path = result.get("artifact_path") or result.get("path")
                if artifact_path:
                    lines.append(f"  Artifact: `{artifact_path}`")
                if result.get("error"):
                    lines.append(f"  Error: {result['error']}")
        return "\n".join(lines) if lines else "- No tools were executed."

    def _save_deterministic_report(
        self,
        user_message: str,
        context: AgentContext,
        final_content: str,
        session_id: str,
        tool_results: list[dict[str, Any]],
    ) -> str | None:
        if not tool_results or not final_content.strip():
            return None
        markdown = (
            f"# Dimer Analysis Report\n\n"
            f"## Question\n{user_message}\n\n"
            f"## Dataset\n`{context.dataset_path or context.workspace}`\n\n"
            f"## Answer\n{final_content}\n\n"
            f"## Methods And Artifacts\n{self._tool_summary_markdown(tool_results)}\n\n"
            f"## Session\n`{session_id}`\n"
        )
        result = save_report(self._report_path_name(user_message), markdown, workspace=context.workspace)
        return result.get("path")

    def _maybe_create_basic_chart(self, user_message: str, context: AgentContext) -> str | None:
        if not context.dataset_path:
            return None
        lower = user_message.lower()
        if not any(term in lower for term in ("trend", "drop", "increase", "decrease", "month", "march", "over time")):
            return None

        try:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            import pandas as pd

            dataset_path = Path(context.dataset_path)
            profile = profile_dataset(dataset_path)
            date_col = next(iter(profile.likely_date_columns), None)
            metric_col = next(iter(profile.likely_revenue_columns or profile.likely_metric_columns), None)
            if not date_col or not metric_col:
                return None

            df = load_dataframe(dataset_path)
            df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
            df = df.dropna(subset=[date_col, metric_col])
            if df.empty:
                return None

            monthly = (
                df.assign(_month=df[date_col].dt.to_period("M").astype(str))
                .groupby("_month", as_index=False)[metric_col]
                .sum()
                .sort_values("_month")
            )
            if monthly.empty:
                return None

            chart_path = default_chart_path("monthly_metric_trend.png", workspace=context.workspace)
            fig, ax = plt.subplots(figsize=(8, 4.5))
            ax.plot(monthly["_month"], monthly[metric_col], marker="o")
            ax.set_title(f"{metric_col} by month")
            ax.set_xlabel("Month")
            ax.set_ylabel(metric_col)
            ax.tick_params(axis="x", rotation=30)
            fig.tight_layout()
            fig.savefig(chart_path)
            plt.close(fig)
            register_chart(chart_path, description=f"{metric_col} by month", workspace=context.workspace)
            return str(chart_path.resolve())
        except Exception:
            return None

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
        failure_counts: dict[str, int] = {}

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
                    result = self.tool_router.execute(
                        tc.name,
                        tc.arguments,
                        auto_approve=auto_approve,
                        primary_dataset_path=context.dataset_path,
                    )
                    tool_name = result.get("tool_name", tc.name)
                    emit_event(
                        self.event_sink,
                        "tool_call_finished" if result.get("success") else "tool_call_failed",
                        tool_name=tool_name,
                        success=result.get("success"),
                    )
                    compact = compact_tool_result(result.get("result") or result)
                    try:
                        parsed_result = json.loads(compact)
                    except json.JSONDecodeError:
                        parsed_result = compact
                    observation = {
                        "type": "tool_result",
                        "tool_name": tool_name,
                        "success": result.get("success"),
                        "result": parsed_result,
                    }
                    if result.get("error"):
                        observation["error"] = result["error"]
                    if result.get("repair_hint"):
                        observation["repair_hint"] = result["repair_hint"]
                    session.tool_results.append(observation)
                    if not result.get("success"):
                        signature = json.dumps(
                            {
                                "tool_name": tool_name,
                                "arguments": result.get("arguments", tc.arguments),
                                "error": result.get("error"),
                            },
                            sort_keys=True,
                            default=str,
                        )
                        failure_counts[signature] = failure_counts.get(signature, 0) + 1
                        if failure_counts[signature] >= 2:
                            final_content = (
                                "Tool execution failed repeatedly with the same call.\n\n"
                                f"Tool: `{tool_name}`\n\n"
                                f"Error: {result.get('error')}\n\n"
                                f"Repair hint: {result.get('repair_hint', 'Use the registered tool schema and retry.')}"
                            )
                            break
                    messages.append(ModelMessage(role="assistant", content=json.dumps({
                        "type": "tool_call",
                        "tool_name": tool_name,
                        "arguments": result.get("arguments", tc.arguments),
                    })))
                    messages.append(ModelMessage(
                        role="tool",
                        content=json.dumps(observation),
                        name=tool_name,
                        tool_call_id=tc.id,
                    ))
                if final_content:
                    break
                continue

            if response.content:
                final_content = self._coerce_final_content(response.content)
                break

        if not final_content:
            final_content = self._fallback_final_answer(user_message, session.tool_results)

        emit_event(self.event_sink, "agent_finished", message="Agent finished")

        ws = context.workspace
        report_path = self._save_deterministic_report(
            user_message,
            context,
            final_content,
            session_id,
            session.tool_results,
        )
        chart_path = self._maybe_create_basic_chart(user_message, context)
        artifacts = [a.path for a in ArtifactRegistry(ws).list_all()]
        assumptions = [a.text for a in AssumptionLog(ws).list_all()]

        save_session(session_id, {
            "messages": [m.model_dump() for m in messages],
            "tool_results": session.tool_results,
            "final_content": final_content,
            "report_path": report_path,
            "chart_path": chart_path,
            "artifacts": artifacts,
            "assumptions": assumptions,
        }, ws)

        return AgentResult(
            content=final_content,
            session_id=session_id,
            artifacts=artifacts,
            assumptions=assumptions,
        )
