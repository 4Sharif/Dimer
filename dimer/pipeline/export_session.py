"""Export successful session SQL as a replayable DuckDB script."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from pprint import pformat
from typing import Any

import duckdb

from dimer.data_context.artifact_registry import ArtifactRegistry
from dimer.storage.artifacts import ensure_workspace_dirs, get_dimer_dir
from dimer.storage.sessions import list_sessions, load_session
from dimer.tools.duckdb_exec import _table_name


@dataclass
class ExportResult:
    session_id: str
    script_path: Path
    manifest_path: Path
    query_count: int
    verified: bool
    warnings: list[str] = field(default_factory=list)


def export_session(
    session_id: str | None = None,
    workspace: Path | None = None,
) -> ExportResult:
    ws = (workspace or Path.cwd()).resolve()
    ensure_workspace_dirs(ws)
    selected_session = session_id or _latest_session_id(ws)
    session = load_session(selected_session, ws)
    queries = _eligible_queries(session)
    if not queries:
        raise ValueError(
            f"Session {selected_session} has no successful DuckDB queries to export. "
            "Run a tool-backed SQL analysis, then export that session."
        )

    exported_at = datetime.now(timezone.utc).isoformat()
    sources, source_warnings = _build_sources(queries, ws)
    verification_warnings = _verify_queries(queries, sources)
    warnings = [*source_warnings, *verification_warnings]
    verified = not warnings

    scripts_dir = get_dimer_dir(ws) / "artifacts" / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    base_name = f"export-{selected_session.removeprefix('session-')}"
    script_path = scripts_dir / f"{base_name}.py"
    manifest_path = scripts_dir / f"{base_name}.manifest.json"

    manifest = {
        "session_id": selected_session,
        "question": session.get("question"),
        "exported_at": exported_at,
        "verified": verified,
        "warnings": warnings,
        "sources": sources,
        "queries": queries,
    }
    script_text = _render_script(session, manifest)
    compile(script_text, str(script_path), "exec")
    script_path.write_text(script_text, encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    ArtifactRegistry(ws).register(
        script_path,
        "script",
        description=f"Replayable SQL export for {selected_session}",
        metadata={
            "session_id": selected_session,
            "manifest_path": str(manifest_path),
            "verified": verified,
            "query_count": len(queries),
        },
    )
    return ExportResult(
        session_id=selected_session,
        script_path=script_path,
        manifest_path=manifest_path,
        query_count=len(queries),
        verified=verified,
        warnings=warnings,
    )


def _latest_session_id(workspace: Path) -> str:
    sessions = list_sessions(workspace, limit=1)
    if not sessions:
        raise FileNotFoundError("No saved sessions found. Run an analysis before exporting.")
    return str(sessions[0]["session_id"])


def _eligible_queries(session: dict[str, Any]) -> list[dict[str, Any]]:
    queries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for observation in session.get("tool_results") or []:
        if (
            observation.get("tool_name") != "run_duckdb_query"
            or observation.get("success") is not True
            or observation.get("duplicate")
        ):
            continue
        arguments = observation.get("arguments")
        if not isinstance(arguments, dict):
            continue
        query = arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            continue
        raw_paths = arguments.get("data_paths") or []
        if isinstance(raw_paths, str):
            raw_paths = [raw_paths]
        if not isinstance(raw_paths, list) or not all(isinstance(path, str) for path in raw_paths):
            continue
        item = {"query": query, "data_paths": raw_paths}
        signature = json.dumps(item, sort_keys=True)
        if signature in seen:
            continue
        seen.add(signature)
        queries.append(item)
    return queries


def _build_sources(
    queries: list[dict[str, Any]],
    workspace: Path,
) -> tuple[list[dict[str, Any]], list[str]]:
    sources: list[dict[str, Any]] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for query in queries:
        for raw_path in query["data_paths"]:
            path = Path(raw_path)
            if not path.is_absolute():
                path = workspace / path
            path = path.resolve()
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            source: dict[str, Any] = {
                "path": key,
                "table_name": _table_name(path),
                "exists": path.exists(),
                "schema": [],
                "schema_fingerprint": None,
            }
            if not path.exists():
                warnings.append(f"Source file is missing: {path}")
            elif path.suffix.lower() not in {".csv", ".parquet"}:
                warnings.append(f"Unsupported DuckDB source type: {path}")
            else:
                try:
                    schema = _read_schema(path)
                    source["schema"] = schema
                    source["schema_fingerprint"] = _schema_fingerprint(schema)
                except Exception as exc:
                    warnings.append(f"Could not inspect schema for {path}: {exc}")
            sources.append(source)
    return sources, warnings


def _read_schema(path: Path) -> list[dict[str, str]]:
    con = duckdb.connect()
    try:
        _register_source(con, path, _table_name(path))
        rows = con.execute(f"DESCRIBE {_quote_identifier(_table_name(path))}").fetchall()
        return [{"name": str(row[0]), "type": str(row[1])} for row in rows]
    finally:
        con.close()


def _schema_fingerprint(schema: list[dict[str, str]]) -> str:
    payload = json.dumps(schema, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _verify_queries(
    queries: list[dict[str, Any]],
    sources: list[dict[str, Any]],
) -> list[str]:
    warnings: list[str] = []
    con = duckdb.connect()
    try:
        for source in sources:
            path = Path(source["path"])
            if not path.exists() or path.suffix.lower() not in {".csv", ".parquet"}:
                continue
            try:
                _register_source(con, path, source["table_name"])
            except Exception as exc:
                warnings.append(f"Could not register {path}: {exc}")
        for index, query in enumerate(queries, start=1):
            try:
                con.execute(query["query"]).fetchmany(51)
            except Exception as exc:
                warnings.append(f"Query {index} failed verification: {exc}")
    finally:
        con.close()
    return warnings


def _register_source(con: duckdb.DuckDBPyConnection, path: Path, table_name: str) -> None:
    path_literal = str(path).replace("'", "''")
    table = _quote_identifier(table_name)
    if path.suffix.lower() == ".csv":
        reader = f"read_csv_auto('{path_literal}')"
    elif path.suffix.lower() == ".parquet":
        reader = f"read_parquet('{path_literal}')"
    else:
        raise ValueError(f"Unsupported data file for DuckDB: {path.suffix.lower()}")
    con.execute(f"CREATE OR REPLACE VIEW {table} AS SELECT * FROM {reader}")


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _render_script(session: dict[str, Any], manifest: dict[str, Any]) -> str:
    header = [
        "# Dimer SQL session export",
        f"# Session: {manifest['session_id']}",
        f"# Question: {_single_line(session.get('question') or '(not recorded)')}",
        f"# Exported: {manifest['exported_at']}",
        "# Assumptions:",
    ]
    assumptions = session.get("assumptions") or []
    header.extend(
        f"# - {_single_line(assumption)}" for assumption in assumptions
    )
    if not assumptions:
        header.append("# - None recorded")

    sources_literal = pformat(manifest["sources"], sort_dicts=False, width=100)
    queries_literal = pformat(manifest["queries"], sort_dicts=False, width=100)
    body = f'''
from __future__ import annotations

from pathlib import Path

import duckdb


SOURCES = {sources_literal}
QUERIES = {queries_literal}
MAX_ROWS = 50


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _register_source(con, source: dict) -> bool:
    path = Path(source["path"])
    if not path.exists():
        print(f"WARNING: source file is missing: {{path}}")
        return False
    path_literal = str(path).replace("'", "''")
    table = _quote_identifier(source["table_name"])
    if path.suffix.lower() == ".csv":
        reader = f"read_csv_auto('{{path_literal}}')"
    elif path.suffix.lower() == ".parquet":
        reader = f"read_parquet('{{path_literal}}')"
    else:
        print(f"WARNING: unsupported DuckDB source type: {{path}}")
        return False
    con.execute(f"CREATE OR REPLACE VIEW {{table}} AS SELECT * FROM {{reader}}")
    current_schema = [
        {{"name": str(row[0]), "type": str(row[1])}}
        for row in con.execute(f"DESCRIBE {{table}}").fetchall()
    ]
    expected_schema = source.get("schema") or []
    if expected_schema and current_schema != expected_schema:
        print(f"WARNING: schema drift detected for {{path}}")
    return True


def main() -> None:
    failed = False
    con = duckdb.connect()
    try:
        for source in SOURCES:
            try:
                if not _register_source(con, source):
                    failed = True
            except Exception as exc:
                failed = True
                print(f"WARNING: could not register {{source['path']}}: {{exc}}")

        for index, item in enumerate(QUERIES, start=1):
            print(f"\\nQuery {{index}}:")
            print(item["query"])
            try:
                result = con.execute(item["query"])
                columns = [description[0] for description in result.description or []]
                rows = result.fetchmany(MAX_ROWS + 1)
                truncated = len(rows) > MAX_ROWS
                for row in rows[:MAX_ROWS]:
                    print(dict(zip(columns, row)))
                if truncated:
                    print(f"... preview truncated at {{MAX_ROWS}} rows")
            except Exception as exc:
                failed = True
                print(f"ERROR: query {{index}} failed: {{exc}}")
    finally:
        con.close()
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
'''
    return "\n".join(header) + "\n" + body.lstrip()


def _single_line(value: Any) -> str:
    return " ".join(str(value).splitlines()).strip()
