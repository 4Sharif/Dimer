"""Tests for session listing and replay formatting."""

from __future__ import annotations

from pathlib import Path

from dimer.storage.artifacts import ensure_workspace_dirs
from dimer.storage.sessions import (
    format_session_list,
    format_session_replay,
    list_sessions,
    save_session,
)


def test_list_and_replay_sessions(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)
    save_session(
        "session-20260711-120000",
        {
            "question": "Why did revenue drop in March?",
            "tool_results": [{"tool_name": "run_duckdb_query", "success": True}],
            "artifacts": ["/tmp/q.sql"],
            "assumptions": ["Used revenue"],
            "final_content": "## Findings\nMarch totals rose.",
        },
        tmp_path,
    )
    save_session(
        "session-20260711-130000",
        {
            "question": "Which region contributed most revenue?",
            "tool_results": [],
            "artifacts": [],
            "final_content": "## Findings\nWest.",
        },
        tmp_path,
    )

    summaries = list_sessions(tmp_path, limit=10)
    assert [s["session_id"] for s in summaries] == [
        "session-20260711-130000",
        "session-20260711-120000",
    ]
    listing = format_session_list(summaries)
    assert "session-20260711-130000" in listing
    assert "Which region contributed most revenue?" in listing
    assert "mode=" not in listing

    replay = format_session_replay(
        "session-20260711-120000",
        {
            "question": "Why did revenue drop in March?",
            "tool_results": [{"tool_name": "run_duckdb_query", "success": True}],
            "artifacts": ["/tmp/q.sql"],
            "assumptions": ["Used revenue"],
            "final_content": "## Findings\nMarch totals rose.",
        },
    )
    assert "Session replay: session-20260711-120000" in replay
    assert "Mode:" not in replay
    assert "`run_duckdb_query`: ok" in replay
    assert "March totals rose." in replay


def test_session_persistence_redacts_secrets_recursively(tmp_path: Path) -> None:
    ensure_workspace_dirs(tmp_path)

    path = save_session(
        "session-20260711-140000",
        {
            "question": "Use token=secret-session-token for this request",
            "tool_results": [
                {
                    "stdout": "Authorization: Bearer secret-bearer-token",
                    "arguments": {"code": "print('sk-sessionsecret123456789')"},
                }
            ],
            "final_content": "The credential was sk-sessionsecret123456789",
        },
        tmp_path,
    )

    persisted = path.read_text(encoding="utf-8")
    assert "secret-session-token" not in persisted
    assert "secret-bearer-token" not in persisted
    assert "sk-sessionsecret123456789" not in persisted
    assert "[REDACTED_SECRET]" in persisted
