"""Session persistence."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dimer.storage.artifacts import get_dimer_dir
from dimer.safety.pii import redact_sensitive_data


def _sessions_dir(workspace: Path | None = None) -> Path:
    return get_dimer_dir(workspace) / "sessions"


def _session_path(session_id: str, workspace: Path | None = None) -> Path:
    return _sessions_dir(workspace) / f"{session_id}.json"


def new_session_id() -> str:
    return datetime.now(timezone.utc).strftime("session-%Y%m%d-%H%M%S")


def save_session(session_id: str, data: dict[str, Any], workspace: Path | None = None) -> Path:
    path = _session_path(session_id, workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_data = redact_sensitive_data(data)
    path.write_text(json.dumps(safe_data, indent=2, default=str), encoding="utf-8")
    return path


def load_session(session_id: str, workspace: Path | None = None) -> dict[str, Any]:
    path = _session_path(session_id, workspace)
    if not path.exists():
        raise FileNotFoundError(f"Session not found: {session_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def list_sessions(workspace: Path | None = None, limit: int = 20) -> list[dict[str, Any]]:
    directory = _sessions_dir(workspace)
    if not directory.exists():
        return []
    paths = sorted(directory.glob("session-*.json"), reverse=True)
    if limit is not None and limit >= 0:
        paths = paths[:limit]
    summaries: list[dict[str, Any]] = []
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        session_id = path.stem
        tool_results = data.get("tool_results") or []
        summaries.append(
            {
                "session_id": session_id,
                "question": data.get("question") or _question_from_messages(data.get("messages") or []),
                "artifact_count": len(data.get("artifacts") or []),
                "tool_count": len(tool_results),
                "created_at": data.get("created_at") or _stamp_from_session_id(session_id),
                "path": str(path),
            }
        )
    return summaries


def format_session_list(summaries: list[dict[str, Any]]) -> str:
    if not summaries:
        return "No sessions saved yet."
    lines: list[str] = []
    for item in summaries:
        question = (item.get("question") or "(no question recorded)").strip().replace("\n", " ")
        if len(question) > 80:
            question = question[:77] + "..."
        lines.append(
            f"- {item['session_id']} | tools={item.get('tool_count', 0)} | "
            f"artifacts={item.get('artifact_count', 0)} | {question}"
        )
    return "\n".join(lines)


def format_session_replay(session_id: str, data: dict[str, Any]) -> str:
    question = data.get("question") or _question_from_messages(data.get("messages") or []) or "(no question recorded)"
    tool_results = data.get("tool_results") or []
    artifacts = data.get("artifacts") or []
    assumptions = data.get("assumptions") or []
    final_content = (data.get("final_content") or "").strip() or "(no final answer)"

    lines = [
        f"# Session replay: {session_id}",
        "",
        f"Question: {question}",
        "",
        "## Tool log",
    ]
    if not tool_results:
        lines.append("- No tools were executed.")
    else:
        for obs in tool_results:
            name = obs.get("tool_name", "unknown")
            status = "ok" if obs.get("success") else "failed"
            lines.append(f"- `{name}`: {status}")
            if obs.get("duplicate"):
                lines.append("  - duplicate blocked")
            if obs.get("error"):
                lines.append(f"  - error: {obs['error']}")

    lines.extend(["", "## Artifacts"])
    if artifacts:
        for path in artifacts:
            lines.append(f"- `{path}`")
    else:
        lines.append("- None")

    lines.extend(["", "## Assumptions"])
    if assumptions:
        for text in assumptions:
            lines.append(f"- {text}")
    else:
        lines.append("- None")

    lines.extend(["", "## Final answer", final_content])
    return "\n".join(lines)


def _question_from_messages(messages: list[dict[str, Any]]) -> str | None:
    for message in messages:
        if message.get("role") != "user":
            continue
        content = str(message.get("content") or "")
        marker = "Question: "
        if marker in content:
            return content.split(marker, 1)[1].strip()
    return None


def _stamp_from_session_id(session_id: str) -> str | None:
    # session-YYYYMMDD-HHMMSS
    parts = session_id.split("-")
    if len(parts) >= 3 and parts[0] == "session":
        return f"{parts[1]}-{parts[2]}"
    return None
