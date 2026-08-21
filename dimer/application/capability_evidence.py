"""Durable records for explicitly authorized provider conformance runs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from dimer.application.doctor import DoctorReport
from dimer.config import ToolProtocol
from dimer.safety.pii import redact_sensitive_text


_CONFORMANCE_CHECKS = (
    "configuration",
    "basic completion",
    "tool call",
    "tool result",
)


@dataclass(frozen=True)
class CapabilityEnvironment:
    """Operator-supplied environment metadata for one live conformance run."""

    runtime_version: str
    context_settings: str
    hardware: str

    def as_redacted_record(self) -> dict[str, str]:
        values = {
            "runtime_version": self.runtime_version,
            "context_settings": self.context_settings,
            "hardware": self.hardware,
        }
        missing = [name for name, value in values.items() if not value.strip()]
        if missing:
            raise ValueError(
                "Capability evidence requires non-empty metadata: "
                + ", ".join(missing)
            )
        return {name: redact_sensitive_text(value) for name, value in values.items()}


def record_capability_evidence(
    report: DoctorReport,
    *,
    tool_protocol: ToolProtocol,
    environment: CapabilityEnvironment,
    destination: Path,
    recorded_at: datetime | None = None,
) -> Path:
    """Append one complete, passing doctor result as redacted JSONL evidence."""
    if tuple(check.name for check in report.checks) != _CONFORMANCE_CHECKS:
        raise ValueError("Capability evidence requires all four doctor checks.")
    if any(check.status != "pass" for check in report.checks):
        raise ValueError("Capability evidence requires every doctor check to pass.")

    timestamp = recorded_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        raise ValueError("Capability evidence timestamps must include a timezone.")

    record = {
        "schema_version": 1,
        "recorded_at": timestamp.isoformat(),
        "provider": redact_sensitive_text(report.provider),
        "model": redact_sensitive_text(report.model),
        "endpoint": redact_sensitive_text(report.endpoint),
        "data_locality": report.data_locality,
        "tool_protocol": tool_protocol,
        **environment.as_redacted_record(),
        "checks": [
            {"name": check.name, "status": check.status} for check in report.checks
        ],
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("a", encoding="utf-8") as evidence_file:
        evidence_file.write(json.dumps(record, sort_keys=True) + "\n")
    return destination
