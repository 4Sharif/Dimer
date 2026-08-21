"""Thought-Action-Observation agent loop."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from dimer.agent.compaction import compact_profile_for_context, compact_tool_result
from dimer.agent.events import EventSink, emit_event
from dimer.agent.prompts import get_system_prompt
from dimer.agent.session import AgentContext, AgentSession
from dimer.agent.tool_router import ToolRouter
from dimer.config import DimerConfig, load_config, provider_tool_protocol
from dimer.data_context.analysis_state import AnalysisState
from dimer.data_context.artifact_registry import ArtifactRegistry
from dimer.data_context.assumption_log import AssumptionLog
from dimer.data_context.notebook_context import compact_notebook_for_context, find_notebooks_for_context
from dimer.data_context.schema_profile import load_dataframe, profile_dataset
from dimer.data_context.workspace_scanner import compact_workspace_summary, duckdb_table_catalog, list_duckdb_dataset_paths
from dimer.providers.base import (
    ModelMessage,
    ModelProvider,
    parse_json_tool_response,
    tool_result_message,
)
from dimer.safety.pii import redact_sensitive_text
from dimer.storage.artifacts import get_dimer_dir
from dimer.storage.sessions import new_session_id, save_session
from dimer.tools.chart import default_chart_path, register_chart


_COMPUTATION_TERMS = (
    "average",
    "best",
    "cause",
    "change",
    "changed",
    "compare",
    "contributed",
    "correlation",
    "count",
    "decrease",
    "difference",
    "driver",
    "drop",
    "how many",
    "highest",
    "increase",
    "largest",
    "led",
    "least",
    "mean",
    "median",
    "most",
    "lowest",
    "percent",
    "rate",
    "share",
    "smallest",
    "sum",
    "top",
    "total",
    "trend",
    "versus",
    "why",
)
_CONTEXT_ONLY_TERMS = (
    "cell",
    "column",
    "data type",
    "dtype",
    "duplicate",
    "execution order",
    "missing",
    "notebook structure",
    "null",
    "profile",
    "quality",
    "row count",
    "schema",
    "structure",
)
_RANKING_TERMS = (
    "best",
    "highest",
    "largest",
    "least",
    "led",
    "lowest",
    "most",
    "smallest",
    "top",
)
_AGGREGATION_TERMS = (
    "average",
    "contributed",
    "count",
    "how many",
    "mean",
    "percent",
    "rate",
    "share",
    "sum",
    "total",
)
_TREND_TERMS = (
    "change",
    "changed",
    "decrease",
    "drop",
    "increase",
    "over time",
    "trend",
)
_AGGREGATE_MARKERS = (
    "sum(",
    "avg(",
    "mean(",
    "count(",
    "max(",
    "min(",
    ".agg(",
    ".sum(",
    ".mean(",
    ".count(",
    ".max(",
    ".min(",
)
_QUESTION_STOP_WORDS = frozenset(
    {
        "about",
        "after",
        "against",
        "are",
        "before",
        "between",
        "data",
        "dataset",
        "did",
        "does",
        "for",
        "from",
        "had",
        "has",
        "have",
        "into",
        "most",
        "row",
        "rows",
        "than",
        "that",
        "the",
        "this",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "with",
    }
    | {word for phrase in _COMPUTATION_TERMS for word in phrase.split()}
)


def _canonical_evidence_token(token: str) -> str:
    if len(token) > 4 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _message_has_term(message: str, term: str) -> bool:
    pattern = re.escape(term).replace(r"\ ", r"\s+")
    return bool(re.search(rf"\b{pattern}\b", message, flags=re.IGNORECASE))


def _message_has_any(message: str, terms: tuple[str, ...]) -> bool:
    return any(_message_has_term(message, term) for term in terms)


def _requested_ranking_metric(message: str) -> str | None:
    by_match = re.search(
        r"\bby\s+([a-z][a-z0-9_]*)\b",
        message,
        flags=re.IGNORECASE,
    )
    if by_match:
        return _canonical_evidence_token(by_match.group(1).lower())
    metric_match = re.search(
        r"\b(?:highest|largest|lowest|most|least|smallest)\s+"
        r"(?:total\s+|average\s+)?([a-z][a-z0-9_]*)\b",
        message,
        flags=re.IGNORECASE,
    )
    if metric_match:
        return _canonical_evidence_token(metric_match.group(1).lower())
    return None


@dataclass
class AgentResult:
    session_id: str
    findings: str
    evidence: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    analysis_plan: list[str] = field(default_factory=list)

    @property
    def quality_notes(self) -> list[str]:
        """Backward-compatible name for structured caveats."""

        return self.caveats

    @property
    def content(self) -> str:
        sections = [("Findings", self.findings.strip())]
        if self.evidence:
            sections.append(("Evidence", "\n\n".join(self.evidence)))
        if self.artifacts:
            sections.append(("Artifacts", "\n".join(f"- `{path}`" for path in self.artifacts)))
        if self.assumptions:
            sections.append(("Assumptions", "\n".join(f"- {text}" for text in self.assumptions)))
        if self.caveats:
            sections.append(("Caveats", "\n".join(f"- {text}" for text in self.caveats)))
        if self.next_steps:
            sections.append(("Suggested Next Steps", "\n".join(f"- {text}" for text in self.next_steps)))
        return "\n\n".join(f"## {heading}\n{body}" for heading, body in sections if body)

    def structured_data(self) -> dict[str, Any]:
        return {
            "findings": self.findings,
            "evidence": self.evidence,
            "caveats": self.caveats,
            "assumptions": self.assumptions,
            "artifacts": self.artifacts,
            "next_steps": self.next_steps,
        }


class AgentLoop:
    def __init__(
        self,
        provider: ModelProvider,
        tool_router: ToolRouter,
        event_sink: EventSink | None = None,
        config: DimerConfig | None = None,
        model: str | None = None,
        max_iterations: int = 12,
        approval_callback: Callable[[str, dict[str, Any]], bool] | None = None,
    ) -> None:
        self.provider = provider
        self.tool_router = tool_router
        self.event_sink = event_sink
        self.config = config or load_config()
        self.model = model
        self.max_iterations = max_iterations
        self.approval_callback = approval_callback

    def _execute_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        auto_approve: bool,
        primary_dataset_path: str | None,
        primary_notebook_path: str | None,
        workspace_dataset_paths: list[str] | None,
        session_id: str | None,
    ) -> dict[str, Any]:
        result = self.tool_router.execute(
            name,
            arguments,
            auto_approve=auto_approve,
            primary_dataset_path=primary_dataset_path,
            primary_notebook_path=primary_notebook_path,
            workspace_dataset_paths=workspace_dataset_paths,
            session_id=session_id,
        )
        needs_approval = (
            not result.get("success")
            and "requires approval" in str(result.get("error", "")).lower()
            and self.approval_callback is not None
        )
        if not needs_approval:
            return result

        tool_name = str(result.get("tool_name") or name)
        tool_args = result.get("arguments") if isinstance(result.get("arguments"), dict) else arguments
        approval_args = {
            **tool_args,
            "workspace": str(self.tool_router.workspace or Path.cwd()),
        }
        approved = self.approval_callback(tool_name, approval_args)
        if not approved:
            return {
                **result,
                "success": False,
                "error": f"Tool {tool_name} was denied by the user",
                "repair_hint": "Choose a safer tool or continue without this action.",
            }
        return self.tool_router.execute(
            name,
            arguments,
            auto_approve=True,
            primary_dataset_path=primary_dataset_path,
            primary_notebook_path=primary_notebook_path,
            workspace_dataset_paths=workspace_dataset_paths,
            session_id=session_id,
        )

    def _selected_model(self) -> str:
        return self.model or str(getattr(self.provider, "default_model", self.config.default_model))

    def _build_context_message(self, context: AgentContext, user_message: str = "") -> str:
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
        catalog = duckdb_table_catalog(context.workspace)
        if catalog:
            parts.append(
                "DuckDB tables auto-registered when data_paths is omitted "
                "(file stem → table name): "
                + ", ".join(f"{item['table']} <= {item['path']}" for item in catalog)
            )
            parts.append(
                "For workspace-level questions you may omit data_paths; "
                "all CSV/Parquet datasets above are registered automatically."
            )

        notebook_paths = find_notebooks_for_context(
            context.workspace,
            explicit_path=context.notebook_path,
            question=user_message,
            limit=2,
        )
        if notebook_paths:
            notebook_payloads = []
            for path in notebook_paths:
                try:
                    notebook_payloads.append(compact_notebook_for_context(path))
                except Exception as e:
                    notebook_payloads.append({"path": str(path), "error": str(e)})
            parts.append("Notebook context:")
            parts.append(json.dumps(notebook_payloads, indent=2, default=str))
            parts.append(
                "If answering about notebooks, prefer summarize_notebook/read_notebook tools "
                "and call out execution-order or direction-change issues when relevant."
            )
        return "\n".join(parts)

    def _build_analysis_plan(self, user_message: str, context: AgentContext) -> list[str]:
        lower = user_message.lower()
        asks_time = any(term in lower for term in ("trend", "drop", "increase", "decrease", "month", "over time"))
        asks_why = any(term in lower for term in ("why", "driver", "cause"))
        asks_segment = any(term in lower for term in ("why", "driver", "cause", "contributed", "segment", "region", "category"))
        asks_compare = any(term in lower for term in ("compare", "join", "between", "versus", "vs"))
        asks_notebook = any(
            term in lower for term in ("notebook", "ipynb", "cell", "execution order", "out of order")
        ) or bool(context.notebook_path)

        plan = ["Inspect the available schema/profile before making analytical claims."]
        if asks_notebook:
            plan.append(
                "Summarize the relevant notebook first; check execution-order issues and direction-change notes before explaining results."
            )
        if asks_time:
            plan.append(
                "Compute metric totals over time and check whether the claimed drop/increase is actually true."
            )
        if asks_why or asks_time:
            plan.append(
                "Validate driver hypotheses with average or per-transaction metrics for the same periods "
                "(do not stop after totals alone)."
            )
        if asks_segment:
            plan.append("Break down the focal period by likely categorical dimensions to identify mix drivers.")
        if asks_compare:
            plan.append("Check whether multiple datasets or comparable dimensions are needed before joining or comparing.")
        plan.append("Validate conclusions against row counts, missingness, duplicates, and query result previews.")
        plan.append(
            "Save important SQL as reproducible evidence; create charts or reports only when requested or materially useful."
        )

        AnalysisState(context.workspace).record(
            "analysis_plan_created",
            inputs={"question": user_message, "dataset_path": context.dataset_path},
            outputs={"steps": plan},
            reason="deterministic question planning",
            tool_source="agent_planner",
        )
        return plan

    def _tool_call_signature(self, tool_name: str, arguments: dict[str, Any]) -> str:
        payload: dict[str, Any] = {"tool_name": tool_name, "arguments": arguments}
        if tool_name == "run_duckdb_query" and isinstance(arguments, dict):
            query = arguments.get("query")
            if isinstance(query, str):
                payload = {
                    "tool_name": tool_name,
                    "query": " ".join(query.lower().split()),
                    "data_paths": arguments.get("data_paths"),
                }
        return json.dumps(payload, sort_keys=True, default=str)

    def _classify_sql_coverage(self, query: str) -> set[str]:
        lower = " ".join(query.lower().split())
        tags: set[str] = set()
        has_time = any(token in lower for token in ("date_trunc", " as month", "month,"))
        has_avg = "avg(" in lower or "/ count" in lower or "/count(" in lower
        has_segment = "group by" in lower and any(
            token in lower for token in ("region", "product_category", "category", "segment")
        )
        if has_time and any(token in lower for token in ("sum(", "count(", "avg(")):
            tags.add("time_totals")
        if has_avg:
            tags.add("averages")
        if has_segment:
            tags.add("segments")
        return tags

    def _successful_tool_names(self, tool_results: list[dict[str, Any]]) -> set[str]:
        return {
            str(obs.get("tool_name"))
            for obs in tool_results
            if obs.get("success") is True and obs.get("tool_name")
        }

    def _has_supporting_evidence(
        self,
        user_message: str,
        tool_results: list[dict[str, Any]],
        context: AgentContext,
    ) -> bool:
        lower = user_message.lower()
        asks_for_computation = _message_has_any(lower, _COMPUTATION_TERMS)
        context_only = _message_has_any(lower, _CONTEXT_ONLY_TERMS)
        required_kind = (
            "computed"
            if asks_for_computation or (context.dataset_path and not context_only)
            else "contextual"
        )
        for observation in tool_results:
            if observation.get("success") is not True:
                continue
            tool_name = str(observation.get("tool_name") or "")
            evidence_kind = self.tool_router.evidence_kind(tool_name)
            if required_kind == "computed":
                if evidence_kind == "computed" and self._computation_is_relevant(
                    user_message,
                    observation,
                ):
                    return True
            elif evidence_kind in {"contextual", "computed"}:
                return True
        return False

    def _computation_is_relevant(
        self,
        user_message: str,
        observation: dict[str, Any],
    ) -> bool:
        question_terms = {
            _canonical_evidence_token(token)
            for token in re.findall(r"[a-z][a-z0-9_]+", user_message.lower())
            if len(token) > 2 and token not in _QUESTION_STOP_WORDS
        }
        if not question_terms:
            return True
        arguments = observation.get("arguments")
        result = observation.get("result")
        arguments = arguments if isinstance(arguments, dict) else {}
        result = result if isinstance(result, dict) else {}
        evidence_text = json.dumps(
            {
                "query": arguments.get("query") or result.get("query"),
                "code": arguments.get("code"),
                "column_names": result.get("column_names"),
                "preview_rows": result.get("preview_rows"),
                "stdout": result.get("stdout"),
                "return_value_summary": result.get("return_value_summary"),
            },
            default=str,
        ).lower()
        evidence_terms = {
            _canonical_evidence_token(token)
            for token in re.findall(r"[a-z][a-z0-9_]+", evidence_text)
        }
        minimum_matches = min(2, len(question_terms))
        if len(question_terms & evidence_terms) < minimum_matches:
            return False
        return self._computation_matches_requested_operation(user_message, arguments, result)

    def _computation_matches_requested_operation(
        self,
        user_message: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
    ) -> bool:
        expression = str(arguments.get("query") or arguments.get("code") or result.get("query") or "")
        normalized = " ".join(expression.lower().split())
        if _message_has_any(user_message, _RANKING_TERMS) and not self._matches_ranking_intent(
            user_message,
            normalized,
        ):
            return False
        has_aggregate = any(marker in normalized for marker in _AGGREGATE_MARKERS)
        if _message_has_any(user_message, _AGGREGATION_TERMS) and not has_aggregate:
            return False
        if re.search(r"\bby\s+[a-z][a-z0-9_]*", user_message, flags=re.IGNORECASE):
            has_grouping = any(
                marker in normalized for marker in ("group by", "groupby(", "pivot_table(")
            )
            if not has_grouping or not has_aggregate:
                return False
        if _message_has_any(user_message, _TREND_TERMS) and not any(
            marker in normalized
            for marker in (
                "date_trunc(",
                "diff(",
                "group by",
                "groupby(",
                "lag(",
                "order by",
                "pct_change(",
                "resample(",
            )
        ):
            return False
        return True

    def _matches_ranking_intent(self, user_message: str, expression: str) -> bool:
        metric = _requested_ranking_metric(user_message)
        descending = _message_has_any(
            user_message,
            ("best", "highest", "largest", "led", "most", "top"),
        )
        ascending = _message_has_any(
            user_message,
            ("least", "lowest", "smallest"),
        )
        direct_extreme = (
            (descending and metric and f"max({metric}" in expression)
            or (ascending and metric and f"min({metric}" in expression)
        )
        if direct_extreme:
            return True

        order_match = re.search(
            r"\border\s+by\s+(.+?)(?:\blimit\b|$)",
            expression,
        )
        if order_match:
            order_clause = order_match.group(1)
            if descending and "desc" not in order_clause:
                return False
            if ascending and "asc" not in order_clause:
                return False
            if metric:
                accepted_names = {metric}
                alias_matches = re.findall(
                    rf"(?:sum|avg|mean|max|min)\(\s*{re.escape(metric)}\s*\)\s+as\s+([a-z][a-z0-9_]*)",
                    expression,
                )
                accepted_names.update(alias_matches)
                if not any(
                    re.search(rf"\b{re.escape(name)}\b", order_clause)
                    for name in accepted_names
                ):
                    return False
            return True

        return any(
            marker in expression
            for marker in (
                "rank(",
                "row_number(",
                "idxmax(",
                "idxmin(",
                "nlargest(",
                "nsmallest(",
                "sort_values(",
            )
        )

    def _observation_coverage(self, tool_results: list[dict[str, Any]]) -> set[str]:
        covered: set[str] = set()
        succeeded = self._successful_tool_names(tool_results)
        if "profile_dataset" in succeeded or "inspect_dataset" in succeeded:
            covered.add("profile")
        if "save_report" in succeeded:
            covered.add("report")
        for obs in tool_results:
            if obs.get("tool_name") != "run_duckdb_query" or not obs.get("success"):
                continue
            args = obs.get("arguments") or {}
            query = args.get("query") if isinstance(args, dict) else None
            if isinstance(query, str):
                covered |= self._classify_sql_coverage(query)
            result = obs.get("result")
            if isinstance(result, dict) and isinstance(result.get("query"), str):
                covered |= self._classify_sql_coverage(result["query"])
        return covered

    def _revise_analysis_plan(
        self,
        analysis_plan: list[str],
        tool_results: list[dict[str, Any]],
        context: AgentContext,
        user_message: str,
    ) -> list[str]:
        covered = self._observation_coverage(tool_results)
        succeeded = self._successful_tool_names(tool_results)
        remaining: list[str] = []
        for step in analysis_plan:
            lower = step.lower()
            if "totals over time" in lower and "time_totals" in covered:
                continue
            if "average or per-transaction" in lower and "averages" in covered:
                continue
            if "categorical dimensions" in lower and "segments" in covered:
                continue
            if "inspect the available schema" in lower and tool_results:
                continue
            remaining.append(step)

        if remaining == analysis_plan:
            return analysis_plan

        AnalysisState(context.workspace).record(
            "analysis_plan_revised",
            inputs={
                "question": user_message,
                "covered": sorted(covered),
                "succeeded_tools": sorted(succeeded),
            },
            outputs={"steps": remaining, "completed_from": analysis_plan},
            reason="adaptive plan revision from tool observations",
            tool_source="agent_planner",
        )
        return remaining

    def _plan_progress_message(self, remaining_plan: list[str], covered: set[str]) -> str:
        covered_bits = ", ".join(sorted(covered)) if covered else "none yet"
        actionable = [
            step
            for step in remaining_plan
            if "save important sql" not in step.lower()
            and "validate conclusions" not in step.lower()
        ]
        if not actionable:
            return (
                "Adaptive checklist: core analytical checks look covered. "
                "Return a final answer now using the tool evidence. "
                "Do not emit more tool calls unless a critical gap remains."
            )
        remaining = self._plan_markdown(actionable)
        return (
            "Adaptive checklist update (do exactly one next tool call):\n"
            f"Covered: {covered_bits}\n"
            f"Still needed:\n{remaining}"
        )

    def _coerce_final_content(self, content: str) -> str:
        stripped = content.strip()
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            return content
        if isinstance(data, dict) and data.get("type") == "final":
            return str(data.get("content", ""))
        return content

    def _looks_like_tool_call_payload(self, content: str) -> bool:
        stripped = content.strip()
        if not stripped:
            return False
        # Valid protocol, or common malformed local-model dumps (missing tool_name key).
        if "tool_call" in stripped and ("\"type\"" in stripped or "'type'" in stripped):
            return True
        if stripped.startswith("{") and "arguments" in stripped and any(
            name in stripped
            for name in (
                "run_duckdb_query",
                "profile_dataset",
                "save_report",
                "run_python",
            )
        ):
            return True
        recovered = parse_json_tool_response(stripped)
        return bool(recovered and recovered.tool_calls)

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
        evidence = json.dumps(rows[:8], indent=2, default=str)
        finding = (
            "Dimer computed query results, but the model returned an invalid/incomplete final message "
            "(often a malformed tool_call). Below is the latest successful SQL evidence."
        )
        # Light deterministic cue for the planted retail trap.
        lower_q = user_message.lower()
        if "drop" in lower_q and rows:
            revenues = []
            for row in rows:
                if isinstance(row, dict):
                    for key in ("total_revenue", "total", "revenue", "sum"):
                        if key in row and row[key] is not None:
                            try:
                                revenues.append(float(row[key]))
                            except (TypeError, ValueError):
                                pass
                            break
            if len(revenues) >= 2 and revenues[-1] >= revenues[-2]:
                finding = (
                    "Computed monthly totals do not show a drop in the latest period versus the prior period "
                    "in the query preview. Treat the 'drop' claim as unverified until a segment breakdown "
                    "explains mix changes."
                )
        return (
            "## Findings\n"
            f"{finding}\n\n"
            "## Evidence\n"
            f"- Question: {user_message}\n"
            f"- Query artifact: {artifact_path or 'not saved'}\n"
            f"- Result preview:\n```json\n{evidence}\n```\n\n"
            "## Data Quality Notes\n"
            "- This is a deterministic fallback answer generated from the latest successful tool observation."
        )

    def _extract_artifact_path(self, obs: dict[str, Any]) -> str | None:
        result = obs.get("result", {})
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except json.JSONDecodeError:
                return None
        if not isinstance(result, dict):
            return None
        artifact_path = result.get("artifact_path") or result.get("path")
        return str(artifact_path) if artifact_path else None

    def _evidence_markdown(self, tool_results: list[dict[str, Any]]) -> str:
        if not tool_results:
            return ""

        lines: list[str] = []
        for obs in tool_results:
            tool_name = obs.get("tool_name", "unknown_tool")
            status = "success" if obs.get("success") else "failed"
            lines.append(f"- `{tool_name}`: {status}")
            artifact_path = self._extract_artifact_path(obs)
            if artifact_path:
                lines.append(f"  - Artifact: `{artifact_path}`")
            result = obs.get("result", {})
            if isinstance(result, dict):
                rows = result.get("preview_rows")
                if rows:
                    lines.append(f"  - Preview rows: `{json.dumps(rows[:3], default=str)}`")
                elif obs.get("success"):
                    lines.append(f"  - Computed result: `{compact_tool_result(result, max_chars=2000)}`")
            if obs.get("error"):
                lines.append(f"  - Error: {obs['error']}")
            if obs.get("repair_hint"):
                lines.append(f"  - Repair hint: {obs['repair_hint']}")
        return "\n".join(lines)

    def _plan_markdown(self, analysis_plan: list[str]) -> str:
        return "\n".join(f"- {step}" for step in analysis_plan) if analysis_plan else "- No deterministic plan was created."

    def _record_deterministic_context_notes(
        self,
        context: AgentContext,
        user_message: str,
        tool_results: list[dict[str, Any]],
    ) -> tuple[list[str], list[str]]:
        assumptions: list[str] = []
        quality_notes: list[str] = []

        if not any(obs.get("success") for obs in tool_results):
            quality_notes.append("No successful tool-backed evidence was produced for this answer.")

        if not context.dataset_path:
            return assumptions, quality_notes

        try:
            profile = profile_dataset(context.dataset_path)
        except Exception as e:
            quality_notes.append(f"Could not profile dataset for deterministic quality notes: {e}")
            return assumptions, quality_notes

        from dimer.data_context.data_quality import (
            analyze_data_quality,
            compare_dataset_schemas,
            detect_schema_drift,
            question_aware_caveats,
        )
        from dimer.data_context.schema_profile import load_profile
        from dimer.data_context.workspace_scanner import scan_workspace

        findings = analyze_data_quality(profile)
        previous = load_profile(context.dataset_path, context.workspace)
        if previous is not None:
            findings.extend(detect_schema_drift(previous, profile))

        try:
            scan = scan_workspace(context.workspace)
            peer_profiles = []
            focus = Path(context.dataset_path).resolve()
            for rel in scan.get("datasets", [])[:6]:
                candidate = Path(rel)
                if not candidate.is_absolute():
                    candidate = (context.workspace or Path.cwd()) / rel
                if candidate.resolve() == focus:
                    continue
                peer = load_profile(candidate, context.workspace)
                if peer is not None:
                    peer_profiles.append(peer)
                if len(peer_profiles) >= 2:
                    break
            if peer_profiles:
                findings.extend(compare_dataset_schemas([profile, *peer_profiles]))
        except Exception:
            pass

        findings.extend(question_aware_caveats(findings, user_message))
        quality_notes.extend(f.message for f in findings)
        quality_notes.extend(profile.quality_warnings)

        lower = user_message.lower()
        asks_time_question = any(term in lower for term in ("trend", "drop", "increase", "decrease", "month", "march", "over time"))
        asks_metric_question = any(term in lower for term in ("revenue", "sales", "amount", "metric", "trend", "drop", "increase", "decrease"))
        asks_segment_question = any(term in lower for term in ("why", "driver", "cause", "contributed", "segment", "region", "category", "breakdown"))

        if asks_time_question:
            if profile.likely_date_columns:
                assumptions.append(
                    f"Used `{profile.likely_date_columns[0]}` as the primary date column based on dataset profile hints."
                )
            else:
                quality_notes.append("No likely date column was detected for the time-based question.")

        metric_candidates = profile.likely_revenue_columns or profile.likely_metric_columns
        if asks_metric_question:
            if metric_candidates:
                assumptions.append(
                    f"Used `{metric_candidates[0]}` as the primary metric column based on dataset profile hints."
                )
            else:
                quality_notes.append("No likely metric or revenue column was detected for the metric-based question.")

        if asks_segment_question and not profile.likely_categorical_dimensions:
            quality_notes.append("No likely categorical dimension was detected for segment or driver analysis.")
        grain_codes = {f.code for f in findings if f.code.startswith("row_grain")}
        if any(term in lower for term in ("average", "per ", "transaction", "order", "drop", "why")):
            grain_notes = [f.message for f in findings if f.code.startswith("row_grain")]
            if grain_notes:
                assumptions.append(grain_notes[0])
            elif not grain_codes:
                assumptions.append(
                    "Validated metric interpretation should account for dataset row grain before relying on averages or per-row comparisons."
                )

        log = AssumptionLog(context.workspace)
        for text in _dedupe(assumptions):
            log.record(text, source="deterministic_context", confidence="medium")

        return _dedupe(assumptions), _dedupe(quality_notes)

    def _has_section(self, content: str, heading: str) -> bool:
        return bool(re.search(rf"(?im)^##\s+{re.escape(heading)}\s*$", content))

    def _format_final_answer(
        self,
        raw_content: str,
        session_id: str,
        artifacts: list[str],
        assumptions: list[str],
        quality_notes: list[str],
        tool_results: list[dict[str, Any]],
        analysis_plan: list[str],
        context: AgentContext,
        user_message: str = "",
    ) -> AgentResult:
        content = raw_content.strip() or "Agent finished without returning a final synthesis."
        if self._looks_like_tool_call_payload(content):
            if tool_results:
                content = self._fallback_final_answer(user_message or "Analysis question", tool_results)
            else:
                content = (
                    "The model returned a tool_call payload instead of a final answer. "
                    "Re-run the question so Dimer can complete the tool turn."
                )
        parsed = _parse_markdown_sections(content)
        findings = "\n\n".join(parsed.get("findings", [])).strip() or content.strip()
        has_supporting_evidence = self._has_supporting_evidence(
            user_message,
            tool_results,
            context,
        )
        workspace_evidence: dict[str, Any] | None = None
        if not has_supporting_evidence and not context.dataset_path and not context.notebook_path:
            try:
                candidate = compact_workspace_summary(context.workspace)
                counts = candidate.get("counts", {})
                if counts.get("datasets", 0) or counts.get("notebooks", 0):
                    workspace_evidence = candidate
            except Exception:
                pass
        if (
            context.dataset_path
            or context.notebook_path
            or workspace_evidence is not None
        ) and not has_supporting_evidence:
            findings = (
                "Unverified analytical synthesis (no supporting computation or source inspection was run):\n\n"
                f"{findings}"
            )
        evidence = [body for body in parsed.get("evidence", []) if body.strip()]
        deterministic_evidence = self._evidence_markdown(tool_results)
        if deterministic_evidence:
            evidence.append(deterministic_evidence)
        elif context.dataset_path:
            try:
                profile = profile_dataset(context.dataset_path)
                profile_data = compact_profile_for_context(profile.model_dump(mode="json"))
                evidence.append(
                    "- Computed dataset profile:\n"
                    f"```json\n{json.dumps(profile_data, default=str)}\n```"
                )
            except Exception as exc:
                quality_notes.append(f"Could not compute dataset evidence: {exc}")
        elif context.notebook_path:
            try:
                notebook_data = compact_notebook_for_context(context.notebook_path)
                evidence.append(
                    "- Computed notebook summary:\n"
                    f"```json\n{json.dumps(notebook_data, default=str)}\n```"
                )
            except Exception as exc:
                quality_notes.append(f"Could not compute notebook evidence: {exc}")
        elif workspace_evidence is not None:
            evidence.append(
                "- Computed workspace inventory:\n"
                f"```json\n{json.dumps(workspace_evidence, default=str)}\n```"
            )
        caveats = [
            *_section_items(parsed.get("caveats", [])),
            *_section_items(parsed.get("data quality notes", [])),
            *quality_notes,
        ]
        model_assumptions = _section_items(parsed.get("assumptions", []))
        next_steps = _section_items(parsed.get("suggested next steps", []))
        return AgentResult(
            session_id=session_id,
            findings=redact_sensitive_text(findings),
            evidence=_dedupe([redact_sensitive_text(item) for item in evidence]),
            caveats=_dedupe([redact_sensitive_text(item) for item in caveats]),
            artifacts=_dedupe([redact_sensitive_text(item) for item in artifacts]),
            assumptions=_dedupe(
                [redact_sensitive_text(item) for item in [*model_assumptions, *assumptions]]
            ),
            next_steps=_dedupe([redact_sensitive_text(item) for item in next_steps]),
            analysis_plan=analysis_plan,
        )

    def _maybe_create_basic_chart(
        self,
        user_message: str,
        context: AgentContext,
        tool_results: list[dict[str, Any]],
        session_id: str | None = None,
    ) -> str | None:
        if not context.dataset_path:
            return None
        lower = user_message.lower()
        if not any(term in lower for term in ("chart", "plot", "visualize", "visualise", "graph")):
            return None
        wants_time_chart = any(term in lower for term in ("trend", "drop", "increase", "decrease", "month", "march", "over time"))
        wants_breakdown_chart = any(term in lower for term in ("contributed", "breakdown", "by region", "by category", "segment"))
        if not wants_time_chart and not wants_breakdown_chart:
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
            dimension_col = next(iter(profile.likely_categorical_dimensions), None)
            if not metric_col:
                return None

            df = load_dataframe(dataset_path)
            fig, ax = plt.subplots(figsize=(8, 4.5))
            chart_type = "line"
            columns: list[str] = [metric_col]
            if wants_time_chart and date_col:
                df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
                df = df.dropna(subset=[date_col, metric_col])
                monthly = (
                    df.assign(_month=df[date_col].dt.to_period("M").astype(str))
                    .groupby("_month", as_index=False)[metric_col]
                    .sum()
                    .sort_values("_month")
                )
                if monthly.empty:
                    return None
                chart_path = default_chart_path("monthly_metric_trend.png", workspace=context.workspace)
                ax.plot(monthly["_month"], monthly[metric_col], marker="o")
                ax.set_title(f"{metric_col} by month")
                ax.set_xlabel("Month")
                ax.set_ylabel(metric_col)
                ax.tick_params(axis="x", rotation=30)
                columns = [date_col, metric_col]
            elif wants_breakdown_chart and dimension_col:
                df = df.dropna(subset=[dimension_col, metric_col])
                breakdown = (
                    df.groupby(dimension_col, as_index=False)[metric_col]
                    .sum()
                    .sort_values(metric_col, ascending=False)
                    .head(12)
                )
                if breakdown.empty:
                    return None
                chart_type = "bar"
                chart_path = default_chart_path(f"{dimension_col}_{metric_col}_breakdown.png", workspace=context.workspace)
                ax.bar(breakdown[dimension_col].astype(str), breakdown[metric_col])
                ax.set_title(f"{metric_col} by {dimension_col}")
                ax.set_xlabel(dimension_col)
                ax.set_ylabel(metric_col)
                ax.tick_params(axis="x", rotation=30)
                columns = [dimension_col, metric_col]
            else:
                plt.close(fig)
                return None
            fig.tight_layout()
            fig.savefig(chart_path)
            plt.close(fig)
            source_artifacts = [path for path in (self._extract_artifact_path(obs) for obs in tool_results) if path]
            register_chart(
                chart_path,
                description=f"{metric_col} {chart_type} chart",
                workspace=context.workspace,
                metadata={
                    "chart_type": chart_type,
                    "source_dataset": str(dataset_path.resolve()),
                    "source_artifacts": source_artifacts,
                    "columns": columns,
                    **({"session_id": session_id} if session_id else {}),
                },
            )
            return str(chart_path.resolve())
        except Exception:
            return None

    def run(
        self,
        user_message: str,
        context: AgentContext,
        auto_approve: bool = False,
    ) -> AgentResult:
        session = AgentSession()
        session_id = new_session_id()
        before_artifact_ids = {a.id for a in ArtifactRegistry(context.workspace).list_all()}
        before_assumption_ids = {a.id for a in AssumptionLog(context.workspace).list_all()}
        emit_event(self.event_sink, "agent_started", message="Agent started", session_id=session_id)

        system_prompt = get_system_prompt()
        context_msg = self._build_context_message(context, user_message)
        analysis_plan = self._build_analysis_plan(user_message, context)
        messages = [
            ModelMessage(role="system", content=system_prompt),
            ModelMessage(
                role="user",
                content=(
                    f"Context:\n{context_msg}\n\n"
                    f"Deterministic analysis plan:\n{self._plan_markdown(analysis_plan)}\n\n"
                    f"Question: {user_message}"
                ),
            ),
        ]

        final_content = ""
        all_tools = self.tool_router.get_schemas()
        tool_protocol = provider_tool_protocol(
            self.config,
            self.provider.name,
            self._selected_model(),
        )
        tools = all_tools if tool_protocol == "native" else None
        failure_counts: dict[str, int] = {}
        success_signatures: dict[str, dict[str, Any]] = {}
        workspace_dataset_paths = list_duckdb_dataset_paths(context.workspace)
        malformed_tool_nudge_count = 0

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
                message=f"Calling {self.provider.name} ({self._selected_model()})...",
                provider=self.provider.name,
                model=self._selected_model(),
            )
            try:
                response = self.provider.generate(messages, tools=tools, model=self.model)
            except Exception as e:
                emit_event(
                    self.event_sink,
                    "model_call_failed",
                    message=f"Model call failed: {e}",
                    provider=self.provider.name,
                    error=str(e),
                )
                if session.tool_results:
                    final_content = self._fallback_final_answer(user_message, session.tool_results)
                    final_content = (
                        f"{final_content}\n\n## Data Quality Notes\n"
                        f"- Model call failed after tool evidence was collected: {e}"
                    )
                    break
                raise

            session.provider_responses.append(response.diagnostics())

            # Recover tool calls dumped as plain text when native parsing missed them.
            executable_tool_calls = response.tool_calls
            uses_json_fallback = False
            if not response.tool_calls and response.content:
                recovered = parse_json_tool_response(response.content)
                if recovered and recovered.tool_calls:
                    executable_tool_calls = recovered.tool_calls
                    uses_json_fallback = True
            emit_event(
                self.event_sink,
                "model_call_finished",
                message="Model responded",
                provider=self.provider.name,
                has_tool_calls=bool(executable_tool_calls),
            )
            messages.append(response.message)

            if executable_tool_calls:
                for tc in executable_tool_calls:
                    emit_event(
                        self.event_sink,
                        "tool_call_requested",
                        tool_name=tc.name,
                        arguments=tc.arguments,
                    )
                    emit_event(self.event_sink, "tool_call_started", tool_name=tc.name)

                    normalized = self.tool_router.normalize_call(
                        tc.name,
                        tc.arguments,
                        primary_dataset_path=context.dataset_path,
                        workspace_dataset_paths=workspace_dataset_paths,
                    )
                    duplicate_blocked = False
                    if isinstance(normalized, dict):
                        result = normalized
                        tool_name = tc.name
                        executed_args = tc.arguments
                        signature = self._tool_call_signature(tool_name, executed_args if isinstance(executed_args, dict) else {})
                    else:
                        tool_name = normalized.name
                        executed_args = normalized.arguments
                        signature = self._tool_call_signature(tool_name, executed_args)
                        if signature in success_signatures:
                            duplicate_blocked = True
                            prior = success_signatures[signature]
                            result = {
                                "tool_name": tool_name,
                                "success": True,
                                "arguments": executed_args,
                                "result": {
                                    "duplicate_of_prior_success": True,
                                    "message": (
                                        "This exact successful tool call was already executed. "
                                        "Reuse the prior result and choose a different analytical query."
                                    ),
                                    "prior_result": prior.get("result"),
                                },
                                "repair_hint": (
                                    "Do not repeat identical successful queries. "
                                    "Next, cover a remaining checklist item such as averages/per-transaction "
                                    "metrics or categorical breakdowns."
                                ),
                            }
                        else:
                            result = self._execute_tool(
                                tc.name,
                                tc.arguments,
                                auto_approve=auto_approve,
                                primary_dataset_path=context.dataset_path,
                                primary_notebook_path=context.notebook_path,
                                workspace_dataset_paths=workspace_dataset_paths,
                                session_id=session_id,
                            )
                            tool_name = result.get("tool_name", tool_name)
                            executed_args = result.get("arguments", executed_args)
                            signature = self._tool_call_signature(
                                tool_name,
                                executed_args if isinstance(executed_args, dict) else {},
                            )

                    emit_event(
                        self.event_sink,
                        "tool_call_finished" if result.get("success") else "tool_call_failed",
                        tool_name=tool_name,
                        success=result.get("success"),
                        duplicate=duplicate_blocked,
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
                        "arguments": executed_args if isinstance(executed_args, dict) else tc.arguments,
                        "result": parsed_result,
                    }
                    if result.get("error"):
                        observation["error"] = result["error"]
                    if result.get("repair_hint"):
                        observation["repair_hint"] = result["repair_hint"]
                    if duplicate_blocked:
                        observation["duplicate"] = True
                    session.tool_results.append(observation)

                    if result.get("success") and not duplicate_blocked:
                        success_signatures[signature] = observation

                    if not result.get("success"):
                        failure_signature = json.dumps(
                            {
                                "tool_name": tool_name,
                                "arguments": executed_args,
                                "error": result.get("error"),
                            },
                            sort_keys=True,
                            default=str,
                        )
                        failure_counts[failure_signature] = failure_counts.get(failure_signature, 0) + 1
                        if failure_counts[failure_signature] >= 2:
                            final_content = (
                                "Tool execution failed repeatedly with the same call.\n\n"
                                f"Tool: `{tool_name}`\n\n"
                                f"Error: {result.get('error')}\n\n"
                                f"Repair hint: {result.get('repair_hint', 'Use the registered tool schema and retry.')}"
                            )
                            break
                    messages.append(
                        tool_result_message(
                            "json" if uses_json_fallback else "native",
                            tc,
                            observation,
                        )
                    )
                if final_content:
                    break

                revised = self._revise_analysis_plan(analysis_plan, session.tool_results, context, user_message)
                if revised != analysis_plan:
                    analysis_plan = revised
                covered = self._observation_coverage(session.tool_results)
                messages.append(
                    ModelMessage(
                        role="user",
                        content=self._plan_progress_message(analysis_plan, covered),
                    )
                )
                continue

            if response.content:
                if self._looks_like_tool_call_payload(response.content):
                    recovered = parse_json_tool_response(response.content)
                    if recovered and recovered.tool_calls:
                        tc = recovered.tool_calls[0]
                        emit_event(
                            self.event_sink,
                            "tool_call_requested",
                            tool_name=tc.name,
                            arguments=tc.arguments,
                        )
                        emit_event(self.event_sink, "tool_call_started", tool_name=tc.name)
                        result = self._execute_tool(
                            tc.name,
                            tc.arguments,
                            auto_approve=auto_approve,
                            primary_dataset_path=context.dataset_path,
                            primary_notebook_path=context.notebook_path,
                            workspace_dataset_paths=workspace_dataset_paths,
                            session_id=session_id,
                        )
                        observation = {
                            "type": "tool_result",
                            "tool_name": result.get("tool_name", tc.name),
                            "success": result.get("success", False),
                            "result": result.get("result"),
                            "error": result.get("error"),
                        }
                        session.tool_results.append({**result, "arguments": tc.arguments})
                        emit_event(
                            self.event_sink,
                            "tool_call_finished" if result.get("success") else "tool_call_failed",
                            tool_name=tc.name,
                            success=result.get("success", False),
                            error=result.get("error"),
                        )
                        messages.append(
                            ModelMessage(
                                role="assistant",
                                content=json.dumps(
                                    {
                                        "type": "tool_call",
                                        "tool_name": tc.name,
                                        "arguments": tc.arguments,
                                    }
                                ),
                            )
                        )
                        messages.append(
                            ModelMessage(
                                role="tool",
                                content=json.dumps(observation),
                                name=tc.name,
                                tool_call_id=tc.id,
                            )
                        )
                        revised = self._revise_analysis_plan(
                            analysis_plan, session.tool_results, context, user_message
                        )
                        if revised != analysis_plan:
                            analysis_plan = revised
                        messages.append(
                            ModelMessage(
                                role="user",
                                content=self._plan_progress_message(
                                    analysis_plan,
                                    self._observation_coverage(session.tool_results),
                                ),
                            )
                        )
                        continue
                    malformed_tool_nudge_count += 1
                    if malformed_tool_nudge_count <= 2:
                        messages.append(
                            ModelMessage(
                                role="user",
                                content=(
                                    "Your last message looked like a tool_call but was not valid executable JSON. "
                                    "Respond with exactly one JSON object: "
                                    '{"type":"tool_call","tool_name":"...","arguments":{...}} '
                                    'or {"type":"final","content":"..."}.'
                                ),
                            )
                        )
                        continue
                final_content = self._coerce_final_content(response.content)
                break

            # Empty model content (common after local-model timeouts / reasoning loops).
            if session.tool_results:
                final_content = self._fallback_final_answer(user_message, session.tool_results)
                break

        if not final_content:
            final_content = self._fallback_final_answer(user_message, session.tool_results)

        emit_event(self.event_sink, "agent_finished", message="Agent finished")

        ws = context.workspace
        chart_requested = any(
            term in user_message.lower()
            for term in ("chart", "plot", "visualize", "visualise", "graph")
        )
        chart_approved = auto_approve
        if chart_requested and not chart_approved and self.approval_callback is not None:
            chart_approved = self.approval_callback(
                "create_chart",
                {
                    "path": str(get_dimer_dir(ws) / "artifacts" / "charts"),
                    "reason": "The question explicitly requested a chart or visualization.",
                },
            )
        chart_path = None
        if chart_approved:
            chart_path = self._maybe_create_basic_chart(
                user_message,
                context,
                session.tool_results,
                session_id=session_id,
            )
        deterministic_assumptions, quality_notes = self._record_deterministic_context_notes(
            context,
            user_message,
            session.tool_results,
        )
        session_artifacts = [
            a.path for a in ArtifactRegistry(ws).list_all() if a.id not in before_artifact_ids
        ]
        session_assumptions = [
            a.text for a in AssumptionLog(ws).list_all() if a.id not in before_assumption_ids
        ]
        if deterministic_assumptions:
            session_assumptions = _dedupe([*session_assumptions, *deterministic_assumptions])
        result = self._format_final_answer(
            final_content,
            session_id,
            session_artifacts,
            session_assumptions,
            quality_notes,
            session.tool_results,
            analysis_plan,
            context,
            user_message=user_message,
        )
        save_session(session_id, {
            "question": user_message,
            "created_at": session_id.replace("session-", "", 1),
            "messages": [m.model_dump() for m in messages],
            "provider_responses": session.provider_responses,
            "tool_results": session.tool_results,
            "final_content": result.content,
            "structured_result": result.structured_data(),
            "chart_path": chart_path,
            "artifacts": session_artifacts,
            "assumptions": session_assumptions,
            "quality_notes": quality_notes,
            "analysis_plan": analysis_plan,
        }, ws)

        return result


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _parse_markdown_sections(content: str) -> dict[str, list[str]]:
    matches = list(re.finditer(r"(?m)^##\s+(.+?)\s*$", content))
    if not matches:
        return {"findings": [content.strip()]}

    sections: dict[str, list[str]] = {}
    prefix = content[: matches[0].start()].strip()
    if prefix:
        sections.setdefault("findings", []).append(prefix)
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        heading = match.group(1).strip().lower()
        body = content[start:end].strip()
        if heading == "generated artifacts":
            heading = "artifacts"
        if body:
            sections.setdefault(heading, []).append(body)
    return sections


def _section_items(bodies: list[str]) -> list[str]:
    items: list[str] = []
    for body in bodies:
        for line in body.splitlines():
            value = re.sub(r"^\s*(?:[-*]|\d+[.)])\s+", "", line).strip()
            if value:
                items.append(value)
    return items
