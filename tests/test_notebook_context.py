"""Tests for notebook summarization and execution-order detection."""

from __future__ import annotations

import json
from pathlib import Path

from dimer.agent.loop import AgentLoop
from dimer.agent.session import AgentContext
from dimer.agent.tool_router import ToolRouter
from dimer.data_context.notebook_context import (
    compact_notebook_for_context,
    detect_execution_order_issues,
    find_notebooks_for_context,
    format_notebook_summary,
    summarize_notebook,
)
from dimer.providers.base import ModelResponse
from dimer.storage.artifacts import ensure_workspace_dirs
from dimer.tools.notebook_reader import summarize_notebook_tool


def _write_notebook(path: Path, cells: list[dict]) -> None:
    nb = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {},
        "cells": cells,
    }
    path.write_text(json.dumps(nb), encoding="utf-8")


def test_summarize_notebook_detects_datasets_and_out_of_order(tmp_path: Path) -> None:
    nb_path = tmp_path / "analysis.ipynb"
    _write_notebook(
        nb_path,
        [
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": ["# Analysis\n", "Instead of totals, we pivot to monthly trends."],
            },
            {
                "cell_type": "code",
                "execution_count": 1,
                "metadata": {},
                "outputs": [],
                "source": ["import pandas as pd\n", "sales = pd.read_csv('data/sales.csv')\n"],
            },
            {
                "cell_type": "code",
                "execution_count": 3,
                "metadata": {},
                "outputs": [
                    {
                        "output_type": "execute_result",
                        "data": {"text/plain": ["42"]},
                        "metadata": {},
                        "execution_count": 3,
                    }
                ],
                "source": ["total = sales['revenue'].sum()\n", "total\n"],
            },
            {
                "cell_type": "code",
                "execution_count": 2,
                "metadata": {},
                "outputs": [],
                "source": ["monthly = sales.groupby('month')['revenue'].sum()\n"],
            },
        ],
    )

    summary = summarize_notebook(nb_path)

    assert summary["code_cells"] == 3
    assert "data/sales.csv" in summary["datasets_referenced"]
    assert "sales" in summary["variables"]
    assert "monthly" in summary["variables"]
    assert any(i["type"] == "out_of_order_execution" for i in summary["execution_order_issues"])
    assert summary["direction_changes"]
    markdown = format_notebook_summary(summary)
    assert "Execution-order issues" in markdown
    assert "Direction-change hints" in markdown

    tool_result = summarize_notebook_tool(str(nb_path))
    assert "markdown" in tool_result
    assert tool_result["cell_count"] == 4


def test_detect_output_without_execution_count() -> None:
    issues = detect_execution_order_issues(
        [
            {
                "index": 0,
                "type": "code",
                "execution_count": None,
                "outputs": [{"type": "stream", "text": "hi"}],
                "has_error": False,
                "source": "print('hi')",
            }
        ]
    )
    assert issues
    assert issues[0]["type"] == "output_without_execution_count"


def test_example_sales_notebook_summarizes() -> None:
    path = Path(__file__).parent / "fixtures" / "sales_exploration.ipynb"
    summary = summarize_notebook(path)
    assert summary["cell_count"] >= 4
    assert any("sales.csv" in d for d in summary["datasets_referenced"])
    assert any(i["type"] == "out_of_order_execution" for i in summary["execution_order_issues"])
    assert any(o["kind"] in {"dataframe", "image"} for o in summary["notable_outputs"])
    compact = compact_notebook_for_context(path)
    assert compact["summary"]
    assert "outline" in compact


def test_find_notebooks_for_context(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)
    nb = tmp_path / "sales_notes.ipynb"
    _write_notebook(
        nb,
        [{"cell_type": "markdown", "metadata": {}, "source": ["# hi"]}],
    )
    found = find_notebooks_for_context(tmp_path, question="Explain this notebook sales analysis")
    assert found
    assert found[0].name == "sales_notes.ipynb"


def test_agent_loop_includes_notebook_plan_and_context(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)
    nb = tmp_path / "explore.ipynb"
    _write_notebook(
        nb,
        [
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": ["Instead of regional totals, we changed direction."],
            },
            {
                "cell_type": "code",
                "execution_count": 1,
                "metadata": {},
                "outputs": [],
                "source": ["sales = pd.read_csv('sales.csv')\n"],
            },
        ],
    )

    class Provider:
        name = "mock"

        def __init__(self) -> None:
            self.messages = None

        def generate(self, messages, tools=None, model=None, temperature=0.2):
            self.messages = messages
            return ModelResponse(content="## Findings\nNotebook summarized.")

        def stream(self, messages, tools=None, model=None, temperature=0.2):
            yield from ()

    provider = Provider()
    loop = AgentLoop(provider, ToolRouter(tmp_path), max_iterations=2)
    ctx = AgentContext(workspace=tmp_path, notebook_path=str(nb))
    result = loop.run("What changed in this notebook?", ctx)

    assert any("notebook" in step.lower() or "execution-order" in step.lower() for step in result.analysis_plan)
    assert provider.messages is not None
    joined = "\n".join(m.content or "" for m in provider.messages)
    assert "Notebook context" in joined
    assert "explore.ipynb" in joined
