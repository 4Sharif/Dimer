"""Public-surface contract for the narrowed Dimer MVP."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import httpx
from typer.testing import CliRunner

from dimer.agent.tool_router import ToolRouter
from dimer.cli import app
from dimer.config import DimerConfig
from dimer.providers.lmstudio import LMStudioProvider
from dimer.ui.console import DimerConsole


runner = CliRunner()


def test_console_preserves_literal_provider_config_sections(capsys) -> None:
    DimerConsole().print("Check [providers.lmstudio] and retry.")

    assert "[providers.lmstudio]" in capsys.readouterr().out


def test_ask_prints_actionable_transport_error_without_traceback(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    dataset = tmp_path / "data.csv"
    dataset.write_text("value\n1\n", encoding="utf-8")
    config = DimerConfig(
        default_provider="lmstudio",
        default_model="local-model",
        providers={"lmstudio": {"base_url": "http://127.0.0.1:1234/v1"}},
    )

    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    provider = LMStudioProvider(
        {"base_url": "http://127.0.0.1:1234/v1", "model": "local-model"},
        transport=httpx.MockTransport(unreachable),
    )
    monkeypatch.setattr("dimer.cli.ensure_user_config", lambda: tmp_path / "config.toml")
    monkeypatch.setattr("dimer.cli.load_config", lambda: config)
    monkeypatch.setattr("dimer.cli.create_provider", lambda *_args, **_kwargs: provider)

    result = runner.invoke(app, ["ask", str(dataset), "Summarize the data"])

    assert result.exit_code == 1
    assert "Could not reach LM Studio" in result.output
    assert "http://127.0.0.1:1234/v1" in result.output
    assert "Start the local server" in result.output
    assert "[providers.lmstudio]" in result.output
    assert "connection refused" not in result.output
    assert "Traceback" not in result.output


def test_direct_data_commands_reject_dimerignored_paths(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    ignored = tmp_path / "private"
    ignored.mkdir()
    dataset = ignored / "data.csv"
    dataset.write_text("value\n1\n", encoding="utf-8")
    notebook = ignored / "analysis.ipynb"
    notebook.write_text(
        '{"nbformat": 4, "nbformat_minor": 5, "metadata": {}, "cells": []}',
        encoding="utf-8",
    )
    (tmp_path / ".dimerignore").write_text("private/\n", encoding="utf-8")

    results = [
        runner.invoke(app, ["profile", str(dataset)]),
        runner.invoke(app, ["sql", str(dataset), "SELECT * FROM data"]),
        runner.invoke(app, ["notebook", str(notebook)]),
    ]

    assert all(result.exit_code == 1 for result in results)
    assert all("ignored by .dimerignore" in result.output for result in results)


def test_direct_profile_rejects_an_ignored_symlink_to_an_outside_file(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    ignored = tmp_path / "private"
    ignored.mkdir()
    outside = tmp_path.parent / "outside-data.csv"
    outside.write_text("value\n1\n", encoding="utf-8")
    link = ignored / "linked.csv"
    link.symlink_to(outside)
    (tmp_path / ".dimerignore").write_text("private/\n", encoding="utf-8")

    result = runner.invoke(app, ["profile", str(link)])

    assert result.exit_code == 1
    assert "ignored by .dimerignore" in result.output


def test_direct_sql_rejects_secret_literals_before_saving(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    dataset = tmp_path / "data.csv"
    dataset.write_text("value\n1\n", encoding="utf-8")
    secret = "sk-supersecretvalue123456"

    result = runner.invoke(app, ["sql", str(dataset), f"SELECT '{secret}' AS token"])

    assert result.exit_code == 1
    assert "secret-shaped" in result.output
    persisted = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in (tmp_path / ".dimer").rglob("*")
        if path.is_file()
    )
    assert secret not in persisted


def test_public_cli_omits_tui_and_ask_mode() -> None:
    root_help = runner.invoke(app, ["--help"])
    ask_help = runner.invoke(app, ["ask", "--help"])

    assert root_help.exit_code == 0
    assert ask_help.exit_code == 0
    assert "tui" not in root_help.stdout.lower()
    assert re.search(r"--mode\b", ask_help.stdout) is None


def test_ask_requires_explicit_auto_approval() -> None:
    ask_help = runner.invoke(app, ["ask", "--help"])
    normalized_help = " ".join(ask_help.stdout.split())

    assert ask_help.exit_code == 0
    assert "default: no-auto-approve" in normalized_help
    assert "unsafe operations without" in normalized_help.lower()
    assert "prompting (advanced)" in normalized_help.lower()


def test_default_agent_tools_omit_model_training(tmp_path: Path) -> None:
    names = {tool.name for tool in ToolRouter(tmp_path).list_tools()}

    assert "train_baseline_model" not in names
    assert {"inspect_dataset", "profile_dataset", "run_duckdb_query"} <= names


def test_runtime_dependencies_omit_deferred_ui_and_ml_frameworks() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]
    dependencies = "\n".join(project["dependencies"]).lower()

    assert "textual" not in dependencies
    assert "scikit-learn" not in dependencies


def test_user_docs_label_redaction_as_best_effort() -> None:
    root = Path(__file__).parent.parent
    user_docs = "\n".join(
        [
            (root / "README.md").read_text(encoding="utf-8"),
            (root / "project-context" / "using-dimer.md").read_text(encoding="utf-8"),
        ]
    ).lower()

    assert "best-effort redaction" in user_docs
    assert "not guaranteed anonymization" in user_docs
