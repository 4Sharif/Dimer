"""Notebook context reader (read-only)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


DATASET_PATTERNS = [
    re.compile(r"""(?:pd|pandas)\.read_(?:csv|parquet|excel|json|feather)\(\s*['"]([^'"]+)['"]"""),
    re.compile(r"""(?:duckdb\.)?read_csv(?:_auto)?\(\s*['"]([^'"]+)['"]"""),
    re.compile(r"""open\(\s*['"]([^'"]+\.(?:csv|parquet|xlsx|xls|json))['"]"""),
    re.compile(r"""['"]([^'"]+\.(?:csv|parquet|xlsx|xls))['"]"""),
]

ASSIGN_PATTERN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=", re.MULTILINE)
DIRECTION_HINTS = re.compile(
    r"\b(instead|pivot(?:ed|ing)?|changed (?:approach|direction|course)|switch(?:ed|ing)? to|now (?:we|let'?s)|revised|alternative)\b",
    re.IGNORECASE,
)


def read_notebook(path: str | Path, *, source_limit: int = 2000, output_limit: int = 5) -> dict[str, Any]:
    """Parse a notebook into structured cells (read-only; never executes)."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Notebook not found: {p}")
    if p.suffix.lower() != ".ipynb":
        raise ValueError(f"Not a notebook file: {p}")

    nb = json.loads(p.read_text(encoding="utf-8"))
    cells: list[dict[str, Any]] = []
    for idx, cell in enumerate(nb.get("cells", [])):
        cell_type = cell.get("cell_type", "")
        source = _join_source(cell.get("source", []))
        outputs = _extract_outputs(cell.get("outputs", []), limit=output_limit)
        cells.append(
            {
                "index": idx,
                "type": cell_type,
                "source": source[:source_limit],
                "source_chars": len(source),
                "outputs": outputs,
                "execution_count": cell.get("execution_count"),
                "has_error": any(o.get("type") == "error" for o in outputs),
            }
        )
    return {
        "path": str(p.resolve()),
        "cell_count": len(cells),
        "nbformat": nb.get("nbformat"),
        "cells": cells,
    }


def summarize_notebook(path: str | Path) -> dict[str, Any]:
    """Build a compact analytical summary of a notebook."""
    raw = read_notebook(path, source_limit=4000, output_limit=8)
    cells = raw["cells"]

    markdown_cells = [c for c in cells if c["type"] == "markdown"]
    code_cells = [c for c in cells if c["type"] == "code"]
    executed = [c for c in code_cells if c.get("execution_count") is not None]
    errored = [c for c in code_cells if c.get("has_error")]

    datasets = _dedupe(_detect_datasets(c["source"] for c in code_cells))
    variables = _dedupe(_detect_variables(c["source"] for c in code_cells))[:30]
    order_issues = detect_execution_order_issues(cells)
    direction_notes = detect_analysis_direction_changes(cells)

    outline: list[dict[str, Any]] = []
    notable_outputs: list[dict[str, Any]] = []
    for cell in cells:
        preview = " ".join(cell["source"].strip().split())
        if len(preview) > 120:
            preview = preview[:117] + "..."
        outline.append(
            {
                "index": cell["index"],
                "type": cell["type"],
                "execution_count": cell.get("execution_count"),
                "preview": preview,
                "output_count": len(cell.get("outputs") or []),
                "has_error": cell.get("has_error", False),
            }
        )
        for output in cell.get("outputs") or []:
            if output.get("type") == "error":
                notable_outputs.append(
                    {
                        "cell_index": cell["index"],
                        "kind": "error",
                        "detail": f"{output.get('ename')}: {output.get('evalue')}",
                    }
                )
            elif output.get("looks_like_dataframe") or output.get("html_kind") == "dataframe":
                text = output.get("text") or "dataframe-like output"
                notable_outputs.append(
                    {
                        "cell_index": cell["index"],
                        "kind": "dataframe",
                        "detail": " ".join(str(text).split())[:160],
                    }
                )
            elif output.get("has_image"):
                notable_outputs.append(
                    {
                        "cell_index": cell["index"],
                        "kind": "image",
                        "detail": ",".join(output.get("image_mimes") or ["image"]),
                    }
                )

    summary_lines = [
        f"Notebook `{Path(raw['path']).name}` has {raw['cell_count']} cells "
        f"({len(code_cells)} code, {len(markdown_cells)} markdown).",
        f"Executed code cells: {len(executed)}; cells with errors: {len(errored)}.",
    ]
    if datasets:
        summary_lines.append("Datasets referenced: " + ", ".join(f"`{d}`" for d in datasets[:12]) + ".")
    if variables:
        summary_lines.append("Likely variables: " + ", ".join(f"`{v}`" for v in variables[:12]) + ".")
    if notable_outputs:
        summary_lines.append(f"Notable outputs: {len(notable_outputs)} (dataframes/images/errors).")
    if order_issues:
        summary_lines.append(f"Execution-order warnings: {len(order_issues)}.")
    if direction_notes:
        summary_lines.append(f"Possible analysis direction shifts: {len(direction_notes)}.")

    return {
        "path": raw["path"],
        "cell_count": raw["cell_count"],
        "code_cells": len(code_cells),
        "markdown_cells": len(markdown_cells),
        "executed_code_cells": len(executed),
        "error_cells": len(errored),
        "datasets_referenced": datasets,
        "variables": variables,
        "notable_outputs": notable_outputs[:20],
        "execution_order_issues": order_issues,
        "direction_changes": direction_notes,
        "outline": outline,
        "summary": " ".join(summary_lines),
    }


def detect_execution_order_issues(cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    last_count: int | None = None
    last_index: int | None = None

    for cell in cells:
        if cell.get("type") != "code":
            continue
        count = cell.get("execution_count")
        outputs = cell.get("outputs") or []
        index = cell.get("index")

        if outputs and count is None:
            issues.append(
                {
                    "type": "output_without_execution_count",
                    "cell_index": index,
                    "message": f"Code cell {index} has outputs but no execution_count (may have been cleared or run oddly).",
                }
            )

        if isinstance(count, int):
            if last_count is not None and count < last_count:
                issues.append(
                    {
                        "type": "out_of_order_execution",
                        "cell_index": index,
                        "message": (
                            f"Code cell {index} executed as [{count}] after cell {last_index} executed as [{last_count}] "
                            "(notebook may have been run out of order)."
                        ),
                        "previous_cell_index": last_index,
                        "previous_execution_count": last_count,
                        "execution_count": count,
                    }
                )
            last_count = count
            last_index = index

    return issues


def detect_analysis_direction_changes(cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    notes: list[dict[str, Any]] = []
    for cell in cells:
        if cell.get("type") != "markdown":
            continue
        source = cell.get("source") or ""
        if not DIRECTION_HINTS.search(source):
            continue
        preview = " ".join(source.strip().split())
        if len(preview) > 160:
            preview = preview[:157] + "..."
        notes.append(
            {
                "cell_index": cell.get("index"),
                "message": f"Markdown cell {cell.get('index')} may mark an analysis direction change.",
                "preview": preview,
            }
        )
    return notes


def format_notebook_summary(summary: dict[str, Any]) -> str:
    lines = [
        f"# Notebook summary: {Path(summary['path']).name}",
        "",
        summary.get("summary", ""),
        "",
        "## Structure",
        f"- Cells: {summary.get('cell_count', 0)}",
        f"- Code: {summary.get('code_cells', 0)}",
        f"- Markdown: {summary.get('markdown_cells', 0)}",
        f"- Executed code cells: {summary.get('executed_code_cells', 0)}",
        f"- Error cells: {summary.get('error_cells', 0)}",
        "",
        "## Datasets referenced",
    ]
    datasets = summary.get("datasets_referenced") or []
    if datasets:
        lines.extend(f"- `{d}`" for d in datasets)
    else:
        lines.append("- None detected")

    lines.extend(["", "## Likely variables"])
    variables = summary.get("variables") or []
    if variables:
        lines.append("- " + ", ".join(f"`{v}`" for v in variables))
    else:
        lines.append("- None detected")

    lines.extend(["", "## Notable outputs"])
    outputs = summary.get("notable_outputs") or []
    if outputs:
        for item in outputs[:12]:
            lines.append(f"- Cell {item.get('cell_index')} ({item.get('kind')}): {item.get('detail')}")
    else:
        lines.append("- None detected")

    lines.extend(["", "## Execution-order issues"])
    issues = summary.get("execution_order_issues") or []
    if issues:
        for issue in issues:
            lines.append(f"- {issue.get('message')}")
    else:
        lines.append("- None detected")

    lines.extend(["", "## Direction-change hints"])
    notes = summary.get("direction_changes") or []
    if notes:
        for note in notes:
            lines.append(f"- Cell {note.get('cell_index')}: {note.get('preview')}")
    else:
        lines.append("- None detected")

    lines.extend(["", "## Cell outline"])
    for item in summary.get("outline") or []:
        exec_bit = f"[{item.get('execution_count')}]" if item.get("execution_count") is not None else "[ ]"
        err = " ERROR" if item.get("has_error") else ""
        lines.append(
            f"- {item.get('index')}. {item.get('type')} {exec_bit}{err}: {item.get('preview') or '(empty)'}"
        )
    return "\n".join(lines)


def _join_source(source: Any) -> str:
    if isinstance(source, list):
        return "".join(source)
    return str(source or "")


def _extract_outputs(outputs: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    parsed: list[dict[str, Any]] = []
    for out in outputs:
        output_type = out.get("output_type")
        if output_type == "stream":
            text = _join_source(out.get("text", []))[:500]
            parsed.append({"type": "stream", "text": text, **_classify_text_output(text)})
        elif output_type in ("execute_result", "display_data"):
            data = out.get("data", {})
            entry: dict[str, Any] = {"type": "display"}
            if "text/plain" in data:
                text = _join_source(data["text/plain"])[:500]
                entry["text"] = text
                entry.update(_classify_text_output(text))
            if "text/html" in data:
                html = _join_source(data["text/html"])
                entry["has_html"] = True
                entry["html_kind"] = _classify_html_output(html)
                if entry["html_kind"] == "dataframe" and "text" not in entry:
                    entry["looks_like_dataframe"] = True
            image_mimes = [k for k in data if k.startswith("image/")]
            if image_mimes:
                entry["image_mimes"] = image_mimes
                entry["has_image"] = True
                # Rough size hint from base64 payload when present.
                for mime in image_mimes:
                    payload = data.get(mime)
                    if isinstance(payload, str):
                        entry["image_chars"] = len(payload)
                        break
                    if isinstance(payload, list):
                        entry["image_chars"] = sum(len(str(part)) for part in payload)
                        break
            parsed.append(entry)
        elif output_type == "error":
            parsed.append(
                {
                    "type": "error",
                    "ename": out.get("ename"),
                    "evalue": out.get("evalue"),
                    "text": "\n".join(out.get("traceback", [])[-5:])[:500],
                }
            )
        if len(parsed) >= limit:
            break
    return parsed


def _classify_text_output(text: str) -> dict[str, Any]:
    flags: dict[str, Any] = {}
    stripped = text.strip()
    if not stripped:
        return flags
    lines = [ln for ln in stripped.splitlines() if ln.strip()]
    if len(lines) >= 2 and ("\t" in stripped or re.search(r"\s{2,}", lines[0])):
        # pandas Series/DataFrame text often has aligned columns / index labels
        if any(tok in stripped for tok in ("dtype:", "Name:", "Index:", "Columns:")) or (
            len(lines) >= 3 and sum(1 for ln in lines if re.search(r"\d", ln)) >= 2
        ):
            flags["looks_like_dataframe"] = True
    if stripped.startswith("{") and stripped.endswith("}"):
        flags["looks_like_mapping"] = True
    return flags


def _classify_html_output(html: str) -> str:
    lower = html.lower()
    if "<table" in lower and ("dataframe" in lower or "<th" in lower):
        return "dataframe"
    if "<table" in lower:
        return "table"
    if "<img" in lower:
        return "image"
    return "html"


def compact_notebook_for_context(path: str | Path, *, max_outline: int = 8) -> dict[str, Any]:
    """Compact notebook summary suitable for LLM context."""
    summary = summarize_notebook(path)
    return {
        "path": summary["path"],
        "summary": summary["summary"],
        "datasets_referenced": summary.get("datasets_referenced", [])[:8],
        "variables": summary.get("variables", [])[:12],
        "execution_order_issues": [
            {"type": i.get("type"), "message": i.get("message")}
            for i in (summary.get("execution_order_issues") or [])[:5]
        ],
        "direction_changes": [
            {"cell_index": n.get("cell_index"), "preview": n.get("preview")}
            for n in (summary.get("direction_changes") or [])[:3]
        ],
        "notable_outputs": (summary.get("notable_outputs") or [])[:5],
        "outline": (summary.get("outline") or [])[:max_outline],
    }


def find_notebooks_for_context(
    workspace: Path,
    *,
    explicit_path: str | None = None,
    question: str | None = None,
    limit: int = 2,
) -> list[Path]:
    """Resolve notebooks to inject into agent context."""
    if explicit_path:
        path = Path(explicit_path)
        if path.exists() and path.suffix.lower() == ".ipynb":
            return [path.resolve()]

    from dimer.data_context.workspace_scanner import scan_workspace

    scan = scan_workspace(workspace)
    notebooks = [workspace / rel for rel in scan.get("notebooks", [])]
    if not notebooks:
        return []

    lower_q = (question or "").lower()
    notebook_question = any(
        term in lower_q
        for term in ("notebook", "ipynb", "cell", "execution order", "out of order", "kernel")
    )
    if not notebook_question and explicit_path is None:
        # Still include a sample when the workspace focus is unclear and notebooks exist?
        # Only auto-include when the question is notebook-related to avoid context bloat.
        return []

    ranked: list[tuple[int, Path]] = []
    for path in notebooks:
        score = 0
        name = path.name.lower()
        if any(tok and tok in name for tok in re.findall(r"[a-z0-9_]+", lower_q)):
            score += 2
        if "sales" in lower_q and "sales" in name:
            score += 3
        ranked.append((score, path))
    ranked.sort(key=lambda item: (-item[0], str(item[1])))
    return [path for _, path in ranked[:limit]]


def _detect_datasets(sources: Any) -> list[str]:
    found: list[str] = []
    for source in sources:
        for pattern in DATASET_PATTERNS:
            for match in pattern.findall(source):
                if match.endswith((".csv", ".parquet", ".xlsx", ".xls", ".json", ".feather")):
                    found.append(match)
    return found


def _detect_variables(sources: Any) -> list[str]:
    found: list[str] = []
    skip = {"df", "pd", "np", "plt", "sns", "True", "False", "None"}
    for source in sources:
        for match in ASSIGN_PATTERN.findall(source):
            if match not in skip and not match.startswith("_"):
                found.append(match)
    return found


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out
