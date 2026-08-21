"""Heuristic SQL lineage extraction for analysis-state edges."""

from __future__ import annotations

import re
from typing import Any

_SQL_KEYWORDS = {
    "select",
    "from",
    "where",
    "group",
    "by",
    "order",
    "having",
    "join",
    "left",
    "right",
    "inner",
    "outer",
    "on",
    "as",
    "and",
    "or",
    "not",
    "in",
    "is",
    "null",
    "like",
    "between",
    "case",
    "when",
    "then",
    "else",
    "end",
    "distinct",
    "limit",
    "offset",
    "union",
    "all",
    "with",
    "asc",
    "desc",
    "over",
    "partition",
    "count",
    "sum",
    "avg",
    "min",
    "max",
    "cast",
    "date_trunc",
    "extract",
}


def extract_sql_lineage(query: str) -> dict[str, Any]:
    """Return columns and transforms inferred from a SQL string.

    Best-effort only — not a full SQL parser. Good enough for provenance hints.
    """
    text = " ".join((query or "").split())
    lower = text.lower()
    transforms: list[dict[str, Any]] = []
    columns: list[str] = []

    where = _clause_after(lower, text, r"\bwhere\b", ("group by", "order by", "having", "limit", "offset"))
    if where:
        transforms.append({"op": "filter", "expr": where})

    group_by = _clause_after(lower, text, r"\bgroup\s+by\b", ("order by", "having", "limit", "offset"))
    if group_by:
        transforms.append({"op": "group_by", "expr": group_by, "columns": _split_idents(group_by)})

    having = _clause_after(lower, text, r"\bhaving\b", ("order by", "limit", "offset"))
    if having:
        transforms.append({"op": "having", "expr": having})

    order_by = _clause_after(lower, text, r"\border\s+by\b", ("limit", "offset"))
    if order_by:
        transforms.append({"op": "order_by", "expr": order_by})

    for match in re.finditer(
        r"\b((?:left|right|inner|full|cross)\s+)?join\b",
        lower,
        flags=re.IGNORECASE,
    ):
        start = match.start()
        snippet = text[start : start + 120].strip()
        transforms.append({"op": "join", "expr": snippet})

    select_list = _select_list(lower, text)
    if select_list:
        columns.extend(_columns_from_select(select_list))
        if re.search(r"\b(sum|avg|count|min|max)\s*\(", select_list, flags=re.IGNORECASE):
            transforms.append({"op": "aggregate", "expr": select_list})

    for transform in transforms:
        expr = transform.get("expr")
        if isinstance(expr, str):
            columns.extend(_idents(expr))
        cols = transform.get("columns")
        if isinstance(cols, list):
            columns.extend(str(c) for c in cols)

    return {
        "columns": _unique(columns),
        "transforms": transforms,
    }


def _select_list(lower: str, original: str) -> str | None:
    match = re.search(r"\bselect\b", lower)
    if not match:
        return None
    start = match.end()
    from_match = re.search(r"\bfrom\b", lower[start:])
    end = start + from_match.start() if from_match else len(lower)
    return original[start:end].strip() or None


def _clause_after(lower: str, original: str, start_pat: str, stop_words: tuple[str, ...]) -> str | None:
    match = re.search(start_pat, lower)
    if not match:
        return None
    start = match.end()
    stop_positions = []
    for word in stop_words:
        stop = re.search(rf"\b{word}\b", lower[start:])
        if stop:
            stop_positions.append(start + stop.start())
    end = min(stop_positions) if stop_positions else len(lower)
    return original[start:end].strip() or None


def _columns_from_select(select_list: str) -> list[str]:
    parts = _split_top_level(select_list)
    columns: list[str] = []
    for part in parts:
        item = part.strip()
        if not item or item == "*":
            continue
        as_match = re.search(r"\bas\s+([A-Za-z_][\w]*)\s*$", item, flags=re.IGNORECASE)
        if as_match:
            columns.append(as_match.group(1))
            columns.extend(_idents(item[: as_match.start()]))
            continue
        columns.extend(_idents(item))
    return columns


def _split_top_level(text: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    if buf:
        parts.append("".join(buf))
    return parts


def _split_idents(expr: str) -> list[str]:
    return _unique(_idents(expr))


def _idents(expr: str) -> list[str]:
    found: list[str] = []
    for match in re.finditer(r"(?:\"([^\"]+)\"|`([^`]+)`|([A-Za-z_][\w]*))", expr):
        token = match.group(1) or match.group(2) or match.group(3)
        if not token:
            continue
        if token.lower() in _SQL_KEYWORDS:
            continue
        if token.isdigit():
            continue
        found.append(token)
    return found


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out
