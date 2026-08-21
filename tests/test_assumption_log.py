"""Tests for assumption log."""

from __future__ import annotations

from dimer.data_context.assumption_log import AssumptionLog
from dimer.storage.artifacts import ensure_workspace_dirs


def test_assumption_log_write_read(tmp_path) -> None:
    ensure_workspace_dirs(tmp_path)
    log = AssumptionLog(tmp_path)
    a1 = log.record("Revenue includes refunds as negative values.", source="analysis")
    a2 = log.record("March compared to February.", confidence="high")
    items = log.list_all()
    assert len(items) == 2
    assert items[0].text == a1.text
    assert items[1].confidence == "high"
