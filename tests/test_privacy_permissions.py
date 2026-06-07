"""Tests for privacy and permissions."""

from __future__ import annotations

from pathlib import Path

from dimer.safety.permissions import is_within_workspace, requires_approval_for_read
from dimer.safety.pii import redact_text


def test_privacy_redacts_email() -> None:
    text = "Contact user@example.com for details"
    redacted = redact_text(text)
    assert "user@example.com" not in redacted
    assert "[REDACTED_EMAIL]" in redacted


def test_permissions_blocks_path_escape(tmp_path: Path) -> None:
    ws = tmp_path / "workspace"
    ws.mkdir()
    inside = ws / "data.csv"
    inside.touch()
    outside = tmp_path / "outside.csv"
    outside.touch()
    assert is_within_workspace(inside, ws) is True
    assert is_within_workspace(outside, ws) is False


def test_requires_approval_for_env() -> None:
    assert requires_approval_for_read(Path(".env")) is True
    assert requires_approval_for_read(Path("data.csv")) is False
