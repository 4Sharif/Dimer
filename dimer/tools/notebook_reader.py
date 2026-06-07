"""Notebook reader tool."""

from __future__ import annotations

from dimer.data_context.notebook_context import read_notebook


def read_notebook_tool(path: str) -> dict:
    return read_notebook(path)
