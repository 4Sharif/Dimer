# Phase 6: Pipeline / Session Script Export

**Status:** v0.1 SQL session-export slice completed on 2026-07-15. Broader pipeline work remains on hold.
**Source:** The first-slice design was completed through `dimer export` and `/export`, with schema manifests and replay verification added by the v0.1 finalization plan.

## Completed v0.1 scope

Deterministic **replayable SQL scripts from a completed session**. No LLM and no new agent mode.

Still deferred: validation-check generation, pipeline config packs, notebook productionize, ML/Python replay, and `/mode pipeline`.

## Approach

```
.dimer/sessions/*.json
        ↓
pipeline/export_session.py
        ↓
.dimer/artifacts/scripts/*.py  +  ArtifactRegistry(type=script)
        ↑
dimer export / /export
```

**Source of truth:** successful `run_duckdb_query` entries in session `tool_results` (ordered), using `arguments.query` + `arguments.data_paths`. Skip failed and duplicate-blocked calls. Prefer session JSON over parsing chat text.

**Output:** one Python script that:

- documents `session_id`, question, mode, and assumptions in a header comment
- registers each unique data path as a DuckDB view (same stem rules as `dimer/tools/duckdb_exec.py` `_table_name`)
- re-runs each successful query and prints a short preview
- is written to `.dimer/artifacts/scripts/`
- is registered via `ArtifactRegistry` with `type="script"` and `session_id` metadata

**CLI:** `dimer export [session_id]` — omit id → latest session. Print the script path.

**Chat:** `/export` and `/export <session_id>`.

## Implemented files

| Action | Path |
|---|---|
| Added | `dimer/pipeline/__init__.py`, `dimer/pipeline/export_session.py` |
| Wired | `dimer/cli.py` — `export` command |
| Wired | `dimer/ui/session_controller.py` — shared `/export` behavior |
| Tested | `tests/test_pipeline_export.py` |
| Documented | `implementations.md`, `Instructions-status.md`, README, usage guide |

Reuse: `load_session` / `list_sessions`, `ArtifactRegistry`, DuckDB registration pattern from `duckdb_exec`.

## Out of scope for that first slice

- Great Expectations / custom validation suites from DQ findings
- Exporting `run_python` / charts / ML train as production code
- dbt/Airflow/Dagster
- LLM rewriting of exploratory SQL into “clean” pipelines
