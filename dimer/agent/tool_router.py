"""Tool registry and execution router."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field

from dimer.config import DimerConfig, load_config
from dimer.data_context.analysis_state import AnalysisState, lineage_from_sql
from dimer.data_context.artifact_registry import ArtifactRegistry
from dimer.data_context.schema_profile import profile_dataset
from dimer.safety.permissions import enforce_workspace_path
from dimer.safety.pii import redact_sensitive_data, redact_sensitive_text
from dimer.storage.artifacts import get_dimer_dir, get_workspace_root
from dimer.tools.chart import register_chart
from dimer.tools.dataset_profile import tool_inspect_dataset, tool_profile_dataset
from dimer.tools.duckdb_exec import run_duckdb_query
from dimer.tools.files import list_files, read_file, write_file
from dimer.tools.notebook_reader import read_notebook_tool, resolve_notebook_path, summarize_notebook_tool
from dimer.tools.python_exec import run_python
from dimer.tools.report import record_assumption, save_report


RiskLevel = Literal["safe", "approval_required", "dangerous"]
EvidenceKind = Literal["none", "contextual", "computed"]


class ToolDefinition(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]
    risk_level: RiskLevel = "safe"
    evidence_kind: EvidenceKind = "none"


class NormalizedToolCall(BaseModel):
    name: str
    arguments: dict[str, Any]
    original_name: str
    original_arguments: dict[str, Any] = Field(default_factory=dict)
    changed: bool = False
    warnings: list[str] = []


TOOL_ALIASES = {
    "duckdb": "run_duckdb_query",
    "sql": "run_duckdb_query",
    "query": "run_duckdb_query",
    "query_data": "run_duckdb_query",
    "run_sql": "run_duckdb_query",
    "profile": "profile_dataset",
    "profile_data": "profile_dataset",
    "inspect": "inspect_dataset",
    "inspect_data": "inspect_dataset",
    "python": "run_python",
    "execute_python": "run_python",
    "report": "save_report",
    "save_markdown": "save_report",
    "assumption": "record_assumption",
    "record": "record_assumption",
}


ARGUMENT_ALIASES = {
    "run_duckdb_query": {
        "sql": "query",
        "statement": "query",
        "duckdb_query": "query",
        "path": "data_paths",
        "dataset_path": "data_paths",
        "dataset": "data_paths",
        "file": "data_paths",
        "files": "data_paths",
    },
    "profile_dataset": {
        "dataset_path": "path",
        "file": "path",
        "data_path": "path",
    },
    "inspect_dataset": {
        "dataset_path": "path",
        "file": "path",
        "data_path": "path",
    },
    "save_report": {
        "markdown": "markdown_content",
        "content": "markdown_content",
        "text": "markdown_content",
        "filename": "path",
    },
    "record_assumption": {
        "assumption": "text",
        "content": "text",
    },
    "run_python": {
        "python": "code",
        "script": "code",
    },
}


def _query_uses_table_function(query: str) -> bool:
    """Return whether a SQL relation source is a function call.

    This conservative lexer covers FROM/JOIN relations and comma-separated
    relation lists at every nesting depth without mistaking scalar functions
    in SELECT expressions for table sources.
    """

    tokens = _sql_relation_tokens(query)
    for index, (kind, _, depth) in enumerate(tokens[:-1]):
        next_kind, _, next_depth = tokens[index + 1]
        if kind != "identifier" or next_kind != "left_paren" or next_depth != depth:
            continue

        start = index
        while start >= 2:
            dot_kind, _, dot_depth = tokens[start - 1]
            owner_kind, _, owner_depth = tokens[start - 2]
            if (
                dot_kind == "dot"
                and owner_kind == "identifier"
                and dot_depth == depth
                and owner_depth == depth
            ):
                start -= 2
                continue
            break

        prefix = start - 1
        if (
            prefix >= 0
            and tokens[prefix][0] == "identifier"
            and tokens[prefix][1] == "LATERAL"
        ):
            prefix -= 1
        if prefix < 0 or tokens[prefix][2] != depth:
            continue
        if tokens[prefix][0] == "identifier" and tokens[prefix][1] in {"FROM", "JOIN"}:
            return True
        if (
            tokens[prefix][0] == "comma"
            and _comma_is_relation_separator(tokens, prefix, depth)
        ):
            return True
    return False


def _strip_sql_comments(query: str) -> str:
    """Remove real SQL comments while preserving quoted literal contents."""

    output: list[str] = []
    index = 0
    while index < len(query):
        char = query[index]
        if char in {"'", '"'}:
            quote = char
            output.append(char)
            index += 1
            while index < len(query):
                output.append(query[index])
                if query[index] == quote:
                    if index + 1 < len(query) and query[index + 1] == quote:
                        output.append(query[index + 1])
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            continue
        if char == "$":
            delimiter_match = re.match(
                r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$",
                query[index:],
            )
            if delimiter_match:
                delimiter = delimiter_match.group(0)
                end = query.find(delimiter, index + len(delimiter))
                if end == -1:
                    output.append(query[index:])
                    break
                end += len(delimiter)
                output.append(query[index:end])
                index = end
                continue
        if query.startswith("--", index):
            output.append(" ")
            index += 2
            while index < len(query) and query[index] not in "\r\n":
                index += 1
            continue
        if query.startswith("/*", index):
            output.append(" ")
            index += 2
            comment_depth = 1
            while index < len(query) and comment_depth:
                if query.startswith("/*", index):
                    comment_depth += 1
                    index += 2
                elif query.startswith("*/", index):
                    comment_depth -= 1
                    index += 2
                else:
                    if query[index] in "\r\n":
                        output.append(query[index])
                    index += 1
            continue
        output.append(char)
        index += 1
    return "".join(output)


def _comma_is_relation_separator(
    tokens: list[tuple[str, str, int]],
    comma_index: int,
    depth: int,
) -> bool:
    clause_boundaries = {
        "SELECT",
        "WHERE",
        "GROUP",
        "HAVING",
        "QUALIFY",
        "ORDER",
        "LIMIT",
        "UNION",
        "EXCEPT",
        "INTERSECT",
        "WINDOW",
    }
    for kind, value, token_depth in reversed(tokens[:comma_index]):
        if token_depth != depth or kind != "identifier":
            continue
        if value in {"FROM", "JOIN"}:
            return True
        if value in clause_boundaries:
            return False
    return False


def _sql_relation_tokens(query: str) -> list[tuple[str, str, int]]:
    tokens: list[tuple[str, str, int]] = []
    depth = 0
    index = 0
    while index < len(query):
        char = query[index]
        if char.isspace():
            index += 1
            continue
        if char == "'":
            index += 1
            while index < len(query):
                if (
                    query[index] == "'"
                    and index + 1 < len(query)
                    and query[index + 1] == "'"
                ):
                    index += 2
                    continue
                if query[index] == "'":
                    index += 1
                    break
                index += 1
            tokens.append(("literal", "", depth))
            continue
        if char == '"':
            index += 1
            value: list[str] = []
            while index < len(query):
                if (
                    query[index] == '"'
                    and index + 1 < len(query)
                    and query[index + 1] == '"'
                ):
                    value.append('"')
                    index += 2
                    continue
                if query[index] == '"':
                    index += 1
                    break
                value.append(query[index])
                index += 1
            tokens.append(("identifier", "".join(value).upper(), depth))
            continue
        if char.isalpha() or char == "_":
            end = index + 1
            while end < len(query) and (
                query[end].isalnum() or query[end] in {"_", "$"}
            ):
                end += 1
            tokens.append(("identifier", query[index:end].upper(), depth))
            index = end
            continue
        if char == "(":
            tokens.append(("left_paren", char, depth))
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
            tokens.append(("right_paren", char, depth))
        elif char == ",":
            tokens.append(("comma", char, depth))
        elif char == ".":
            tokens.append(("dot", char, depth))
        index += 1
    return tokens


class ToolRouter:
    def __init__(self, workspace: Path | None = None, config: DimerConfig | None = None) -> None:
        self.workspace = workspace
        self.config = config or load_config()
        self._handlers: dict[str, Callable[..., Any]] = {}
        self._definitions: dict[str, ToolDefinition] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        self.register(
            ToolDefinition(
                name="list_files",
                description="List files in a workspace directory",
                input_schema={
                    "type": "object",
                    "properties": {"path": {"type": "string", "default": "."}},
                },
                risk_level="safe",
                evidence_kind="contextual",
            ),
            lambda path=".": list_files(path, self.workspace),
        )
        self.register(
            ToolDefinition(
                name="read_file",
                description="Read a text file from the workspace",
                input_schema={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
                risk_level="safe",
                evidence_kind="contextual",
            ),
            lambda path: read_file(path, self.workspace, self.config.limits.max_output_chars),
        )
        self.register(
            ToolDefinition(
                name="write_file",
                description="Write content to a file in the workspace",
                input_schema={
                    "type": "object",
                    "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                    "required": ["path", "content"],
                },
                risk_level="approval_required",
            ),
            lambda path, content: write_file(path, content, self.workspace),
        )
        self.register(
            ToolDefinition(
                name="inspect_dataset",
                description="Quick lightweight dataset inspection",
                input_schema={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
                evidence_kind="contextual",
            ),
            lambda path: tool_inspect_dataset(path, self.workspace),
        )
        self.register(
            ToolDefinition(
                name="profile_dataset",
                description="Detailed dataset profiling with stats and quality warnings",
                input_schema={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
                evidence_kind="contextual",
            ),
            lambda path: tool_profile_dataset(path, self.workspace, self.config),
        )
        self.register(
            ToolDefinition(
                name="summarize_notebook",
                description="Summarize a Jupyter notebook: structure, datasets, variables, execution-order issues",
                input_schema={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
                evidence_kind="contextual",
            ),
            lambda path: summarize_notebook_tool(str(resolve_notebook_path(path, self.workspace))),
        )
        self.register(
            ToolDefinition(
                name="read_notebook",
                description="Read Jupyter notebook cells, outputs, and execution counts (read-only)",
                input_schema={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
                evidence_kind="contextual",
            ),
            lambda path: read_notebook_tool(str(resolve_notebook_path(path, self.workspace))),
        )
        self.register(
            ToolDefinition(
                name="run_duckdb_query",
                description="Run a DuckDB SQL query over local CSV/Parquet files",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "data_paths": {"type": "array", "items": {"type": "string"}},
                        "max_rows": {"type": "integer", "default": 50},
                    },
                    "required": ["query"],
                },
                evidence_kind="computed",
            ),
            lambda query, data_paths=None, max_rows=50: run_duckdb_query(
                query, data_paths=data_paths, max_rows=max_rows
            ),
        )
        self.register(
            ToolDefinition(
                name="run_python",
                description="Execute Python code in a persistent session with pandas/matplotlib",
                input_schema={
                    "type": "object",
                    "properties": {
                        "code": {"type": "string"},
                        "timeout_seconds": {"type": "integer", "default": 30},
                    },
                    "required": ["code"],
                },
                risk_level="approval_required",
                evidence_kind="computed",
            ),
            lambda code, timeout_seconds=None: run_python(
                code,
                workspace=self.workspace,
                timeout_seconds=self.config.limits.timeout_seconds,
                max_output_chars=self.config.limits.max_output_chars,
            ),
        )
        self.register(
            ToolDefinition(
                name="save_report",
                description="Save a markdown report as an artifact",
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "markdown_content": {"type": "string"},
                    },
                    "required": ["path", "markdown_content"],
                },
                risk_level="approval_required",
            ),
            lambda path, markdown_content: save_report(path, markdown_content, self.workspace),
        )
        self.register(
            ToolDefinition(
                name="record_assumption",
                description="Record an analytical assumption or decision",
                input_schema={
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "source": {"type": "string"},
                        "confidence": {"type": "string"},
                    },
                    "required": ["text"],
                },
            ),
            lambda text, source=None, confidence=None: record_assumption(
                text, source=source, confidence=confidence, workspace=self.workspace
            ),
        )
    def register(self, definition: ToolDefinition, handler: Callable[..., Any]) -> None:
        self._definitions[definition.name] = definition
        self._handlers[definition.name] = handler

    def list_tools(self) -> list[ToolDefinition]:
        return list(self._definitions.values())

    def evidence_kind(self, tool_name: str) -> EvidenceKind:
        definition = self._definitions.get(tool_name)
        return definition.evidence_kind if definition is not None else "none"

    def get_schemas(self) -> list:
        from dimer.providers.base import ToolSchema

        return [
            ToolSchema(name=t.name, description=t.description, input_schema=t.input_schema)
            for t in self.list_tools()
        ]

    def normalize_call(
        self,
        name: str,
        arguments: dict[str, Any] | None,
        primary_dataset_path: str | None = None,
        workspace_dataset_paths: list[str] | None = None,
    ) -> NormalizedToolCall | dict[str, Any]:
        original_name = name
        normalized_name = TOOL_ALIASES.get(name, name)
        changed = normalized_name != original_name
        warnings: list[str] = []

        if normalized_name not in self._handlers:
            valid = ", ".join(sorted(self._handlers))
            return {
                "success": False,
                "error": f"Unknown tool: {name}",
                "repair_hint": f"Use one of: {valid}",
            }

        normalized_args: dict[str, Any] = {}
        aliases = ARGUMENT_ALIASES.get(normalized_name, {})
        for key, value in (arguments or {}).items():
            normalized_key = aliases.get(key, key)
            changed = changed or normalized_key != key
            if normalized_key in normalized_args and normalized_args[normalized_key] != value:
                warnings.append(f"Ignored duplicate argument '{key}' after normalization")
                continue
            normalized_args[normalized_key] = value

        if normalized_name == "run_duckdb_query":
            data_paths = normalized_args.get("data_paths")
            if isinstance(data_paths, str):
                normalized_args["data_paths"] = [data_paths]
                changed = True
                data_paths = normalized_args["data_paths"]
            elif data_paths is None:
                if primary_dataset_path:
                    normalized_args["data_paths"] = [primary_dataset_path]
                    changed = True
                elif workspace_dataset_paths:
                    normalized_args["data_paths"] = list(workspace_dataset_paths)
                    changed = True
            if "query" not in normalized_args:
                return {
                    "success": False,
                    "error": "Missing required argument: query",
                    "repair_hint": 'Use run_duckdb_query with {"query": "SELECT ...", "data_paths": ["path/to/data.csv"]}.',
                }

        if normalized_name in {"profile_dataset", "inspect_dataset"} and "path" not in normalized_args:
            if primary_dataset_path:
                normalized_args["path"] = primary_dataset_path
                changed = True
            else:
                return {
                    "success": False,
                    "error": "Missing required argument: path",
                    "repair_hint": f'Use {normalized_name} with {{"path": "path/to/data.csv"}}.',
                }

        return NormalizedToolCall(
            name=normalized_name,
            arguments=normalized_args,
            original_name=original_name,
            original_arguments=arguments or {},
            changed=changed,
            warnings=warnings,
        )

    def _save_duckdb_artifact(
        self,
        query: str,
        result: dict[str, Any],
        arguments: dict[str, Any],
        session_id: str | None = None,
    ) -> str:
        safe_query = redact_sensitive_text(query)
        if safe_query != query:
            raise ValueError("Queries containing secret-shaped values cannot be persisted")
        ws = self.workspace
        queries_dir = get_dimer_dir(ws) / "artifacts" / "queries"
        queries_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        query_path = queries_dir / f"query-{stamp}.sql"
        query_path.write_text(safe_query, encoding="utf-8")
        data_paths = arguments.get("data_paths") or []
        metadata: dict[str, Any] = {
            "query": safe_query,
            "data_paths": data_paths,
            "row_count": result.get("row_count"),
            "columns": result.get("column_names", []),
        }
        if session_id:
            metadata["session_id"] = session_id
        artifact = ArtifactRegistry(ws).register(
            query_path,
            "query",
            description=safe_query[:120],
            metadata=metadata,
        )
        lineage = lineage_from_sql(safe_query, data_paths if isinstance(data_paths, list) else None)
        result_columns = result.get("column_names", [])
        columns = list(dict.fromkeys([*lineage["columns"], *result_columns]))
        state = AnalysisState(ws)
        parent_ids = state.find_event_ids_for_datasets(
            data_paths if isinstance(data_paths, list) else None
        )
        state.record(
            "sql_query_run",
            inputs={"query": safe_query, "data_paths": data_paths, "session_id": session_id},
            outputs={
                "artifact_id": artifact.id,
                "row_count": result.get("row_count"),
                "columns": result_columns,
                "query_artifact_path": str(query_path.resolve()),
            },
            artifact_paths=[str(query_path.resolve())],
            tool_source="run_duckdb_query",
            parent_ids=parent_ids,
            columns=columns,
            transforms=lineage["transforms"],
            session_id=session_id,
        )
        return str(query_path.resolve())

    def _duckdb_repair_hint(self, arguments: dict[str, Any], error: str) -> str:
        data_paths = arguments.get("data_paths") or []
        table_hints: list[str] = []
        column_hints: list[str] = []
        for raw_path in data_paths:
            path = Path(raw_path)
            table_name = path.stem.replace("-", "_").replace(" ", "_")
            table_hints.append(table_name)
            try:
                profile = profile_dataset(path)
            except Exception:
                continue
            cols = ", ".join(c.name for c in profile.columns)
            column_hints.append(f"{table_name}: {cols}")

        if not data_paths and self.workspace is not None:
            from dimer.data_context.workspace_scanner import duckdb_table_catalog

            catalog = duckdb_table_catalog(self.workspace)
            table_hints = [item["table"] for item in catalog]
            for item in catalog[:8]:
                try:
                    profile = profile_dataset(item["path"])
                except Exception:
                    continue
                cols = ", ".join(c.name for c in profile.columns)
                column_hints.append(f"{item['table']}: {cols}")

        hint = "Check table and column names from the dataset profile, then retry with valid DuckDB SQL."
        if table_hints:
            hint += f" Available table(s): {', '.join(table_hints)}."
        else:
            hint += " Pass data_paths with workspace CSV/Parquet files so tables are registered by file stem."
        if column_hints:
            hint += f" Available columns: {'; '.join(column_hints)}."
        if "Binder Error" in error or "Referenced column" in error:
            hint += " The query likely references a missing or misspelled column."
        if "Catalog Error" in error or "does not exist" in error:
            hint += " The query likely references a missing table or unregistered file stem."
            if not data_paths:
                hint += " Omit data_paths only when the workspace datasets can be auto-registered; otherwise include them explicitly."
        return hint

    def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        auto_approve: bool = False,
        primary_dataset_path: str | None = None,
        primary_notebook_path: str | None = None,
        workspace_dataset_paths: list[str] | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        if workspace_dataset_paths is None and self.workspace is not None:
            from dimer.data_context.workspace_scanner import list_duckdb_dataset_paths

            workspace_dataset_paths = list_duckdb_dataset_paths(self.workspace)
        normalized = self.normalize_call(
            name,
            arguments,
            primary_dataset_path=primary_dataset_path,
            workspace_dataset_paths=workspace_dataset_paths,
        )
        if isinstance(normalized, dict):
            return normalized
        name = normalized.name
        arguments = normalized.arguments
        if name not in self._handlers:
            return {"success": False, "error": f"Unknown tool: {name}"}
        definition = self._definitions[name]
        allowed_focus_paths = tuple(
            Path(path)
            for path in (primary_dataset_path, primary_notebook_path)
            if path
        )
        try:
            arguments = self._enforce_workspace_policy(
                name,
                arguments,
                allowed_focus_paths=allowed_focus_paths,
            )
        except (PermissionError, ValueError) as exc:
            return {
                "success": False,
                "error": str(exc),
                "tool_name": name,
                "arguments": redact_sensitive_data(arguments),
                "repair_hint": "Use a non-ignored path inside the workspace or the explicitly selected focus.",
            }
        if definition.risk_level == "dangerous":
            return {"success": False, "error": f"Tool {name} is blocked in MVP"}
        if definition.risk_level == "approval_required" and not auto_approve:
            return {
                "success": False,
                "error": f"Tool {name} requires approval",
                "tool_name": name,
                "arguments": arguments,
                "repair_hint": "Re-run with auto approval enabled or approve this tool in an interactive flow.",
            }
        try:
            call_args = dict(arguments)
            result = self._handlers[name](**call_args)
            result = redact_sensitive_data(result)
            if name == "run_duckdb_query" and isinstance(result, dict):
                if result.get("error"):
                    return {
                        "success": False,
                        "error": result["error"],
                        "result": result,
                        "tool_name": name,
                        "arguments": redact_sensitive_data(arguments),
                        "repair_hint": self._duckdb_repair_hint(arguments, result["error"]),
                    }
                result["artifact_path"] = self._save_duckdb_artifact(
                    arguments["query"],
                    result,
                    arguments,
                    session_id=session_id,
                )
            if name == "run_python" and isinstance(result, dict):
                if result.get("error"):
                    repair_hint = (
                        "Simplify or split the Python computation, then request approval to retry."
                        if result.get("timed_out")
                        else "Correct the Python error or use bounded DuckDB SQL instead."
                    )
                    return {
                        "success": False,
                        "error": result["error"],
                        "result": result,
                        "tool_name": name,
                        "arguments": arguments,
                        "repair_hint": repair_hint,
                    }
                for f in result.get("created_files", []):
                    register_chart(
                        f,
                        workspace=self.workspace,
                        metadata={"session_id": session_id} if session_id else None,
                    )
            response = {
                "success": True,
                "result": result,
                "tool_name": name,
                "arguments": redact_sensitive_data(arguments),
            }
            if normalized.changed:
                response["normalized_from"] = {
                    "tool_name": normalized.original_name,
                    "arguments": json.loads(json.dumps(normalized.original_arguments, default=str)),
                }
            if normalized.warnings:
                response["warnings"] = normalized.warnings
            return response
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "result": None,
                "tool_name": name,
                "arguments": redact_sensitive_data(arguments),
            }

    def _enforce_workspace_policy(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        allowed_focus_paths: tuple[Path, ...],
    ) -> dict[str, Any]:
        ws = get_workspace_root(self.workspace)
        checked = dict(arguments)
        if name in {"inspect_dataset", "profile_dataset", "summarize_notebook", "read_notebook"}:
            path = checked.get("path")
            if path:
                checked["path"] = str(
                    enforce_workspace_path(
                        path,
                        ws,
                        allowed_outside_paths=allowed_focus_paths,
                    )
                )
        elif name == "run_duckdb_query":
            self._enforce_read_only_duckdb(str(checked.get("query", "")))
            data_paths = checked.get("data_paths") or []
            checked["data_paths"] = [
                str(
                    enforce_workspace_path(
                        path,
                        ws,
                        allowed_outside_paths=allowed_focus_paths,
                    )
                )
                for path in data_paths
            ]
            requested_rows = int(checked.get("max_rows", self.config.limits.max_preview_rows))
            checked["max_rows"] = min(
                max(1, requested_rows),
                max(1, self.config.limits.max_preview_rows),
            )
        elif name == "save_report":
            path = Path(str(checked.get("path", "report.md")))
            if not path.is_absolute():
                if str(path).startswith(".dimer"):
                    path = ws / path
                else:
                    path = get_dimer_dir(ws) / "artifacts" / "reports" / path.name
            checked["path"] = str(enforce_workspace_path(path, ws))
        return checked

    def _enforce_read_only_duckdb(self, query: str) -> None:
        stripped = query.strip()
        if not stripped:
            raise ValueError("DuckDB query is empty")
        if redact_sensitive_text(query) != query:
            raise ValueError(
                "Model-visible DuckDB queries cannot contain secret-shaped values"
            )

        without_comments = _strip_sql_comments(stripped)
        without_terminal_semicolon = without_comments.rstrip().removesuffix(";")
        if ";" in without_terminal_semicolon:
            raise ValueError("Model-visible DuckDB queries must contain one read-only statement")

        without_literals = re.sub(r"'(?:''|[^'])*'", "''", without_terminal_semicolon)
        without_literals = re.sub(r'"(?:""|[^"])*"', '""', without_literals)
        tokens = set(re.findall(r"\b[A-Za-z_]+\b", without_literals.upper()))
        blocked = {
            "ALTER",
            "ATTACH",
            "CALL",
            "CHECKPOINT",
            "COPY",
            "CREATE",
            "DELETE",
            "DETACH",
            "DROP",
            "EXPORT",
            "IMPORT",
            "INSERT",
            "INSTALL",
            "LOAD",
            "PRAGMA",
            "RESET",
            "SET",
            "TRUNCATE",
            "UPDATE",
            "VACUUM",
        }
        if tokens & blocked:
            raise ValueError("Model-visible DuckDB queries must be read-only")

        first_token = next(iter(re.findall(r"\b[A-Za-z_]+\b", without_literals.upper())), "")
        if first_token not in {"SELECT", "WITH", "EXPLAIN", "DESCRIBE", "SHOW"}:
            raise ValueError("Model-visible DuckDB queries must be read-only SELECT statements")

        external_readers = (
            "read_blob",
            "read_csv",
            "read_csv_auto",
            "read_json",
            "read_parquet",
            "read_text",
            "glob",
            "httpfs",
            "iceberg_scan",
            "delta_scan",
            "mysql_scan",
            "postgres_scan",
            "sqlite_scan",
        )
        lowered = without_literals.lower()
        if any(re.search(rf"\b{re.escape(name)}\s*\(", lowered) for name in external_readers):
            raise ValueError(
                "Model-visible DuckDB queries must use registered workspace tables, not external file readers"
            )
        if _query_uses_table_function(without_comments):
            raise ValueError(
                "Model-visible DuckDB queries must use registered workspace tables, not table functions"
            )
        file_literals = re.findall(r"'((?:''|[^'])*)'", without_terminal_semicolon)
        if any(re.search(r"(?i)(?:^|[/\\]).+\.(?:csv|parquet|json|db)$", value) for value in file_literals):
            raise ValueError(
                "Model-visible DuckDB queries must use registered workspace tables, not file path literals"
            )
