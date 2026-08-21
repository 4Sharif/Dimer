"""Analysis state event tracking with lineage edges."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from dimer.data_context.sql_lineage import extract_sql_lineage
from dimer.safety.pii import redact_sensitive_data
from dimer.storage.artifacts import get_dimer_dir

_DATASET_EVENT_TYPES = frozenset({"dataset_inspected", "dataset_profiled"})
_LEAF_EVENT_TYPES = ("chart_created", "report_created", "assumption_added")
_IDENT_RE = re.compile(r"^[A-Za-z_][\w]*$")


class AnalysisEvent(BaseModel):
    id: str
    event_type: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = None
    tool_source: str | None = None
    artifact_paths: list[str] = Field(default_factory=list)
    parent_ids: list[str] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    transforms: list[dict[str, Any]] = Field(default_factory=list)
    session_id: str | None = None


class AnalysisState:
    def __init__(self, workspace: Path | None = None) -> None:
        self.workspace = workspace
        self._path = get_dimer_dir(workspace) / "analysis_state.jsonl"

    def record(
        self,
        event_type: str,
        inputs: dict[str, Any] | None = None,
        outputs: dict[str, Any] | None = None,
        reason: str | None = None,
        tool_source: str | None = None,
        artifact_paths: list[str] | None = None,
        parent_ids: list[str] | None = None,
        columns: list[str] | None = None,
        transforms: list[dict[str, Any]] | None = None,
        session_id: str | None = None,
    ) -> AnalysisEvent:
        payload = redact_sensitive_data(inputs or {})
        resolved_session = session_id or _session_from_payload(payload)
        event = AnalysisEvent(
            id=f"evt-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}",
            event_type=event_type,
            inputs=payload,
            outputs=redact_sensitive_data(outputs or {}),
            reason=redact_sensitive_data(reason),
            tool_source=redact_sensitive_data(tool_source),
            artifact_paths=redact_sensitive_data(artifact_paths or []),
            parent_ids=redact_sensitive_data(parent_ids or []),
            columns=redact_sensitive_data(columns or []),
            transforms=redact_sensitive_data(transforms or []),
            session_id=redact_sensitive_data(resolved_session),
        )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as f:
            f.write(event.model_dump_json() + "\n")
        return event

    def list_events(self) -> list[AnalysisEvent]:
        if not self._path.exists():
            return []
        events = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(AnalysisEvent.model_validate_json(line))
        return events

    def find_event_ids_for_artifacts(
        self,
        artifact_paths: list[str] | None,
        session_id: str | None = None,
    ) -> list[str]:
        """Return event ids whose artifact_paths overlap the given paths.

        When session_id is set, only same-session matches are returned so reused
        artifact filenames from older runs do not become false parents.
        """
        if not artifact_paths:
            return []
        needles = {_norm_path(path) for path in artifact_paths if path}
        if not needles:
            return []
        matched: list[str] = []
        seen: set[str] = set()
        for event in self.list_events():
            if session_id and event_session_id(event) != session_id:
                continue
            event_paths = {_norm_path(path) for path in event.artifact_paths}
            if event_paths & needles and event.id not in seen:
                matched.append(event.id)
                seen.add(event.id)
        return matched
    def find_event_ids_for_datasets(self, data_paths: list[str] | None) -> list[str]:
        """Return the newest inspect/profile event id per dataset path."""
        if not data_paths:
            return []
        needles = {_norm_path(path) for path in data_paths if path}
        if not needles:
            return []

        matched: list[str] = []
        claimed: set[str] = set()
        for event in reversed(self.list_events()):
            if event.event_type not in _DATASET_EVENT_TYPES:
                continue
            candidates = []
            path = event.inputs.get("path")
            if isinstance(path, str) and path:
                candidates.append(path)
            candidates.extend(event.artifact_paths)
            for candidate in candidates:
                normalized = _norm_path(candidate)
                if normalized in needles and normalized not in claimed:
                    matched.append(event.id)
                    claimed.add(normalized)
                    break
            if claimed >= needles:
                break
        return matched

    def trace(
        self,
        target: str,
        limit: int = 10,
        session_id: str | None = None,
    ) -> list[AnalysisEvent]:
        """Return lineage-related events for an artifact path, id, column, or free-text target.

        Column targets prefer exact column matches as seeds. When session_id is set,
        seeds and descendants stay in-session; ancestors (e.g. dataset profile events)
        are still included so chains remain intact without pulling sibling sessions.
        """
        events = self.list_events()
        if not events:
            return []

        by_id = {event.id: event for event in events}
        children: dict[str, list[str]] = {}
        for event in events:
            for parent_id in event.parent_ids:
                children.setdefault(parent_id, []).append(event.id)

        needle = target.lower().strip()
        scoped_events = (
            [event for event in events if event_session_id(event) == session_id]
            if session_id
            else events
        )
        column_mode = is_column_target(target, scoped_events or events)
        seed_ids: list[str] = []

        if column_mode:
            for event in reversed(scoped_events):
                if event_uses_column(event, needle):
                    seed_ids.append(event.id)
        if not seed_ids:
            for event in reversed(scoped_events):
                if self._event_matches(event, needle):
                    seed_ids.append(event.id)

        if not seed_ids:
            return []

        related_ids: set[str] = set(seed_ids)

        # Walk ancestors freely (dataset links, etc.).
        up_queue = list(seed_ids)
        seen_up: set[str] = set()
        while up_queue:
            event_id = up_queue.pop(0)
            if event_id in seen_up:
                continue
            seen_up.add(event_id)
            event = by_id.get(event_id)
            if event is None:
                continue
            for parent_id in event.parent_ids:
                if parent_id not in related_ids:
                    related_ids.add(parent_id)
                    up_queue.append(parent_id)

        # Walk descendants; keep session scope when requested.
        down_queue = list(seed_ids)
        seen_down: set[str] = set()
        while down_queue:
            event_id = down_queue.pop(0)
            if event_id in seen_down:
                continue
            seen_down.add(event_id)
            for child_id in children.get(event_id, []):
                child = by_id.get(child_id)
                if child is None:
                    continue
                child_session = event_session_id(child)
                if session_id and child_session and child_session != session_id:
                    continue
                if child_id not in related_ids:
                    related_ids.add(child_id)
                    down_queue.append(child_id)

        # Without session scope, expand the full connected component.
        if not session_id:
            queue = list(related_ids)
            while queue:
                event_id = queue.pop(0)
                event = by_id.get(event_id)
                if event is None:
                    continue
                for parent_id in event.parent_ids:
                    if parent_id not in related_ids and parent_id in by_id:
                        related_ids.add(parent_id)
                        queue.append(parent_id)
                for child_id in children.get(event_id, []):
                    if child_id not in related_ids and child_id in by_id:
                        related_ids.add(child_id)
                        queue.append(child_id)

        related = [event for event in events if event.id in related_ids]
        if column_mode:
            related.sort(
                key=lambda event: (
                    0 if event_uses_column(event, needle) else 1,
                    -event.timestamp.timestamp(),
                )
            )
        else:
            related.sort(key=lambda event: event.timestamp, reverse=True)
        return related[:limit]

    def _event_matches(self, event: AnalysisEvent, needle: str) -> bool:
        if not needle:
            return False
        haystacks = [
            event.id,
            event.event_type,
            event.reason or "",
            event.tool_source or "",
            *event.artifact_paths,
            *event.parent_ids,
            *event.columns,
            *[str(t.get("op", "")) for t in event.transforms],
            *[str(t.get("expr", "")) for t in event.transforms],
            *[str(p) for t in event.transforms for p in (t.get("paths") or [])],
            _safe_json(event.inputs),
            _safe_json(event.outputs),
        ]
        return any(needle in str(value).lower() for value in haystacks)


def format_trace(
    events: list[AnalysisEvent],
    target: str | None = None,
    session_id: str | None = None,
) -> str:
    if not events:
        if session_id:
            return (
                f"No analysis events matched that trace target in session `{session_id}`.\n"
                "Try `dimer trace --all <target>` for full history, "
                "or `dimer trace --session <id> <target>` for another session."
            )
        return "No analysis events matched that trace target."

    lines: list[str] = []
    if session_id:
        lines.append(f"Scope: session `{session_id}`")
        lines.append("")
    column = target.strip() if target and is_column_target(target, events) else None
    if column:
        usage = column_usage_summaries(events, column)
        if usage:
            lines.append(f"Column `{column}`:")
            for item in usage:
                lines.append(f"  - {item}")
            lines.append("")

    chains = lineage_chain_summaries(events)
    if chains:
        lines.append("Lineage:")
        for chain in chains:
            lines.append(f"  {chain}")
        lines.append("")
        lines.append("Events:")

    for event in events:
        lines.append(f"- `{event.event_type}` (`{event.id}`)")
        if column and event_uses_column(event, column):
            roles = column_roles(event, column)
            if roles:
                lines.append(f"  - Column use: {', '.join(roles)}")
        sid = event_session_id(event)
        if sid:
            lines.append(f"  - Session: `{sid}`")
        if event.tool_source:
            lines.append(f"  - Tool: `{event.tool_source}`")
        if event.reason:
            lines.append(f"  - Reason: {event.reason}")
        if event.parent_ids:
            lines.append("  - Parents:")
            for parent_id in event.parent_ids:
                lines.append(f"    - `{parent_id}`")
        if event.columns:
            lines.append(f"  - Columns: {', '.join(f'`{c}`' for c in event.columns)}")
        if event.transforms:
            lines.append("  - Transforms:")
            for transform in event.transforms:
                op = transform.get("op", "op")
                if op == "source" and transform.get("paths"):
                    paths = ", ".join(f"`{_short_path(p)}`" for p in transform["paths"])
                    lines.append(f"    - `source`: {paths}")
                    continue
                expr = transform.get("expr")
                if expr:
                    lines.append(f"    - `{op}`: `{_compact_text(str(expr))}`")
                else:
                    lines.append(f"    - `{op}`")
        if event.artifact_paths:
            lines.append("  - Artifacts:")
            for path in event.artifact_paths:
                lines.append(f"    - `{path}`")
        if event.inputs:
            lines.append(f"  - Inputs: `{_compact_json(event.inputs)}`")
        if event.outputs:
            lines.append(f"  - Outputs: `{_compact_json(event.outputs)}`")
    return "\n".join(lines)


def event_session_id(event: AnalysisEvent) -> str | None:
    if event.session_id:
        return event.session_id
    return _session_from_payload(event.inputs)


def _session_from_payload(payload: dict[str, Any] | None) -> str | None:
    if not payload:
        return None
    value = payload.get("session_id")
    return value if isinstance(value, str) and value else None


def resolve_trace_session(
    workspace: Path | None,
    session: str | None = None,
    all_sessions: bool = False,
) -> str | None:
    """Resolve which session_id to use for tracing.

    Default (no flags): latest saved session when one exists.
    `--all` / all_sessions: no session filter.
    Explicit session id: that session.
    """
    if all_sessions:
        return None
    if session:
        return session
    from dimer.storage.sessions import list_sessions

    summaries = list_sessions(workspace, limit=1)
    if summaries:
        return summaries[0]["session_id"]
    return None


def is_column_target(target: str, events: list[AnalysisEvent]) -> bool:
    """True when target looks like a column/variable name present in lineage."""
    raw = target.strip()
    if not raw or not _IDENT_RE.match(raw):
        return False
    if raw.lower().startswith("evt-"):
        return False
    needle = raw.lower()
    return any(event_uses_column(event, needle) for event in events)


def event_uses_column(event: AnalysisEvent, column: str) -> bool:
    needle = column.lower().strip()
    if not needle:
        return False
    if any(str(col).lower() == needle for col in event.columns):
        return True
    for transform in event.transforms:
        cols = transform.get("columns") or []
        if any(str(col).lower() == needle for col in cols):
            return True
        expr = transform.get("expr")
        if isinstance(expr, str) and _token_in_expr(needle, expr):
            return True
    return False


def column_roles(event: AnalysisEvent, column: str) -> list[str]:
    """How a column appears in an event (schema, filter, aggregate, chart, ...)."""
    needle = column.lower().strip()
    roles: list[str] = []
    if event.event_type in _DATASET_EVENT_TYPES and any(c.lower() == needle for c in event.columns):
        roles.append("schema")
    for transform in event.transforms:
        op = str(transform.get("op") or "transform")
        if op == "source":
            continue
        cols = transform.get("columns") or []
        expr = transform.get("expr")
        hit = any(str(col).lower() == needle for col in cols)
        if not hit and isinstance(expr, str):
            hit = _token_in_expr(needle, expr)
        if hit and op not in roles:
            roles.append(op)
    if event.event_type == "sql_query_run" and any(c.lower() == needle for c in event.columns):
        if "select" not in roles and not roles:
            roles.append("select")
        elif "select" not in roles and any(
            op in roles for op in ("aggregate", "filter", "group_by", "order_by", "having")
        ):
            pass
        elif "select" not in roles:
            roles.append("select")
    if event.event_type == "chart_created" and any(c.lower() == needle for c in event.columns):
        roles.append("plotted")
    if event.event_type == "report_created" and event_uses_column(event, needle):
        roles.append("reported")
    if not roles and event_uses_column(event, needle):
        roles.append("referenced")
    return roles


def column_usage_summaries(events: list[AnalysisEvent], column: str) -> list[str]:
    """Short per-step usage lines for a column-centric trace."""
    lines: list[str] = []
    seen: set[str] = set()
    for event in events:
        if not event_uses_column(event, column):
            continue
        roles = column_roles(event, column)
        if not roles:
            continue
        label = _event_label(event)
        key = f"{label}|{','.join(roles)}"
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"{label}: {', '.join(roles)}")
    return lines


def lineage_chain_summaries(events: list[AnalysisEvent], limit: int = 5) -> list[str]:
    """Build short root→leaf chain strings from a related event set."""
    if not events:
        return []

    by_id = {event.id: event for event in events}
    related_ids = set(by_id)
    parent_ids_in_set = {
        parent_id
        for event in events
        for parent_id in event.parent_ids
        if parent_id in related_ids
    }
    leaves = [event for event in events if event.id not in parent_ids_in_set]
    leaves.sort(
        key=lambda event: (
            0 if event.event_type in _LEAF_EVENT_TYPES else 1,
            -event.timestamp.timestamp(),
        )
    )

    chains: list[str] = []
    seen: set[tuple[str, ...]] = set()
    for leaf in leaves:
        path_ids = _walk_to_roots(leaf, by_id)
        if not path_ids:
            continue
        key = tuple(path_ids)
        if key in seen:
            continue
        seen.add(key)
        labels: list[str] = []
        for event_id in path_ids:
            event = by_id[event_id]
            label = _event_label(event)
            if labels and labels[-1] == label:
                continue
            labels.append(label)
        # If SQL has source paths but no dataset parent event, prepend dataset labels.
        root = by_id[path_ids[0]]
        if root.event_type == "sql_query_run":
            for transform in root.transforms:
                if transform.get("op") != "source":
                    continue
                for path in transform.get("paths") or []:
                    labels.insert(0, f"dataset `{_short_path(str(path))}`")
        chains.append(" → ".join(labels))
        if len(chains) >= limit:
            break
    return chains


def lineage_from_sql(query: str, data_paths: list[str] | None = None) -> dict[str, Any]:
    """Extract columns/transforms from SQL and attach source dataset transforms."""
    lineage = extract_sql_lineage(query)
    transforms = list(lineage["transforms"])
    if data_paths:
        transforms.insert(0, {"op": "source", "paths": list(data_paths)})
    return {"columns": lineage["columns"], "transforms": transforms}


def _token_in_expr(token: str, expr: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(token)}(?![A-Za-z0-9_])", expr, flags=re.IGNORECASE) is not None


def _walk_to_roots(leaf: AnalysisEvent, by_id: dict[str, AnalysisEvent]) -> list[str]:
    """Return one root→leaf path (prefer first parent when branching)."""
    path = [leaf.id]
    current = leaf
    seen = {leaf.id}
    while current.parent_ids:
        parent_id = next((pid for pid in current.parent_ids if pid in by_id and pid not in seen), None)
        if parent_id is None:
            break
        path.append(parent_id)
        seen.add(parent_id)
        current = by_id[parent_id]
    path.reverse()
    return path


def _event_label(event: AnalysisEvent) -> str:
    if event.event_type in _DATASET_EVENT_TYPES:
        path = event.inputs.get("path")
        if not path and event.artifact_paths:
            path = event.artifact_paths[0]
        return f"dataset `{_short_path(str(path) if path else 'unknown')}`"
    if event.event_type == "sql_query_run":
        ops = [str(t.get("op")) for t in event.transforms if t.get("op") and t.get("op") != "source"]
        if ops:
            return f"sql ({', '.join(ops)})"
        return "sql"
    if event.event_type == "chart_created":
        name = Path(event.artifact_paths[0]).name if event.artifact_paths else "chart"
        return f"chart `{name}`"
    if event.event_type == "report_created":
        name = Path(event.artifact_paths[0]).name if event.artifact_paths else "report"
        return f"report `{name}`"
    if event.event_type == "assumption_added":
        return "assumption"
    return event.event_type


def _short_path(path: str) -> str:
    try:
        return Path(path).name or path
    except Exception:
        return path


def _norm_path(path: str) -> str:
    try:
        return str(Path(path).resolve())
    except OSError:
        return path.replace("\\", "/").rstrip("/").lower()


def _safe_json(value: dict[str, Any]) -> str:
    try:
        return json.dumps(value, sort_keys=True, default=str)
    except TypeError:
        return str(value)


def _compact_json(value: dict[str, Any], max_chars: int = 500) -> str:
    text = _safe_json(value)
    return text if len(text) <= max_chars else f"{text[:max_chars]}..."


def _compact_text(value: str, max_chars: int = 160) -> str:
    text = " ".join(value.split())
    return text if len(text) <= max_chars else f"{text[:max_chars]}..."
