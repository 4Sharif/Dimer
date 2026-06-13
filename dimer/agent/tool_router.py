"""Tool registry and execution router."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field

from dimer.config import DimerConfig, load_config
from dimer.data_context.analysis_state import AnalysisState
from dimer.data_context.artifact_registry import ArtifactRegistry
from dimer.storage.artifacts import get_dimer_dir
from dimer.tools.chart import register_chart
from dimer.tools.dataset_profile import tool_inspect_dataset, tool_profile_dataset
from dimer.tools.duckdb_exec import run_duckdb_query
from dimer.tools.files import list_files, read_file, write_file
from dimer.tools.python_exec import run_python
from dimer.tools.report import record_assumption, save_report


RiskLevel = Literal["safe", "approval_required", "dangerous"]


class ToolDefinition(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]
    risk_level: RiskLevel = "safe"


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
            ),
            lambda path: tool_profile_dataset(path, self.workspace, self.config),
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
            ),
            lambda code, timeout_seconds=30: run_python(
                code,
                workspace=self.workspace,
                timeout_seconds=timeout_seconds,
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

    def list_tools(self, mode: str = "analysis") -> list[ToolDefinition]:
        tools = list(self._definitions.values())
        if mode == "sql":
            preferred = {"profile_dataset", "inspect_dataset", "run_duckdb_query", "save_report", "record_assumption"}
            return [t for t in tools if t.name in preferred or t.name in ("list_files", "read_file")]
        return tools

    def get_schemas(self, mode: str = "analysis") -> list:
        from dimer.providers.base import ToolSchema

        return [
            ToolSchema(name=t.name, description=t.description, input_schema=t.input_schema)
            for t in self.list_tools(mode)
        ]

    def normalize_call(
        self,
        name: str,
        arguments: dict[str, Any] | None,
        primary_dataset_path: str | None = None,
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
            elif data_paths is None and primary_dataset_path:
                normalized_args["data_paths"] = [primary_dataset_path]
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

    def _save_duckdb_artifact(self, query: str, result: dict[str, Any]) -> str:
        ws = self.workspace
        queries_dir = get_dimer_dir(ws) / "artifacts" / "queries"
        queries_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        query_path = queries_dir / f"query-{stamp}.sql"
        query_path.write_text(query, encoding="utf-8")
        artifact = ArtifactRegistry(ws).register(
            query_path,
            "query",
            description=query[:120],
            metadata={
                "row_count": result.get("row_count"),
                "columns": result.get("column_names", []),
            },
        )
        AnalysisState(ws).record(
            "sql_query_run",
            inputs={"query": query},
            outputs={"artifact_id": artifact.id, "row_count": result.get("row_count")},
            artifact_paths=[str(query_path.resolve())],
            tool_source="run_duckdb_query",
        )
        return str(query_path.resolve())

    def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        auto_approve: bool = False,
        primary_dataset_path: str | None = None,
    ) -> dict[str, Any]:
        normalized = self.normalize_call(name, arguments, primary_dataset_path=primary_dataset_path)
        if isinstance(normalized, dict):
            return normalized
        name = normalized.name
        arguments = normalized.arguments
        if name not in self._handlers:
            return {"success": False, "error": f"Unknown tool: {name}"}
        definition = self._definitions[name]
        if definition.risk_level == "dangerous":
            return {"success": False, "error": f"Tool {name} is blocked in MVP"}
        if definition.risk_level == "approval_required" and not auto_approve:
            pass  # MVP: allow in non-interactive ask mode with auto_approve
        try:
            result = self._handlers[name](**arguments)
            if name == "run_duckdb_query" and isinstance(result, dict):
                if result.get("error"):
                    return {
                        "success": False,
                        "error": result["error"],
                        "result": result,
                        "tool_name": name,
                        "arguments": arguments,
                        "repair_hint": "Check table and column names from the dataset profile, then retry with valid DuckDB SQL.",
                    }
                result["artifact_path"] = self._save_duckdb_artifact(arguments["query"], result)
            if name == "run_python" and isinstance(result, dict):
                for f in result.get("created_files", []):
                    register_chart(f, workspace=self.workspace)
            response = {
                "success": True,
                "result": result,
                "tool_name": name,
                "arguments": arguments,
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
                "arguments": arguments,
            }
