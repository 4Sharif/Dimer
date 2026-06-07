"""Notebook context reader (read-only for MVP)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_notebook(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Notebook not found: {p}")
    nb = json.loads(p.read_text(encoding="utf-8"))
    cells = []
    for cell in nb.get("cells", []):
        cell_type = cell.get("cell_type", "")
        source = "".join(cell.get("source", []))
        outputs = []
        for out in cell.get("outputs", []):
            if out.get("output_type") == "stream":
                outputs.append({"type": "stream", "text": "".join(out.get("text", []))})
            elif out.get("output_type") in ("execute_result", "display_data"):
                data = out.get("data", {})
                if "text/plain" in data:
                    outputs.append({"type": "text", "text": "".join(data["text/plain"])})
        cells.append({
            "type": cell_type,
            "source": source[:500],
            "outputs": outputs[:3],
            "execution_count": cell.get("execution_count"),
        })
    return {"path": str(p.resolve()), "cell_count": len(cells), "cells": cells}
