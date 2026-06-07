"""Tool registry and execution router."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import BaseModel

from dimer.config import DimerConfig, load_config
from dimer.data_context.artifact_registry import ArtifactRegistry
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

    def execute(self, name: str, arguments: dict[str, Any], auto_approve: bool = False) -> dict[str, Any]:
        if name not in self._handlers:
            return {"success": False, "error": f"Unknown tool: {name}"}
        definition = self._definitions[name]
        if definition.risk_level == "dangerous":
            return {"success": False, "error": f"Tool {name} is blocked in MVP"}
        if definition.risk_level == "approval_required" and not auto_approve:
            pass  # MVP: allow in non-interactive ask mode with auto_approve
        try:
            result = self._handlers[name](**arguments)
            if name == "run_python" and isinstance(result, dict):
                for f in result.get("created_files", []):
                    register_chart(f, workspace=self.workspace)
            return {"success": True, "result": result}
        except Exception as e:
            return {"success": False, "error": str(e), "result": None}
