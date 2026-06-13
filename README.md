# Dimer

Dimer is a terminal-native AI agent for analytical workflows.

It profiles datasets, runs DuckDB analysis, works with LLM providers, saves queries/reports/charts, and keeps session provenance under `.dimer/`.

## Current Status

Validated locally with:

```bash
uv run pytest -q
uv run dimer ask examples/sales/sales.csv "Which region contributed most revenue?"
uv run dimer ask examples/sales/sales.csv "Why did revenue drop in March?"
```

Current behavior:

- Profiles local CSV, Parquet, and Excel files.
- Runs SQL over local CSV/Parquet files with DuckDB.
- Supports one-shot `ask` and interactive `chat`.
- Uses provider abstraction for Ollama, LM Studio, and OpenAI-compatible endpoints.
- Normalizes common model tool-call mistakes, such as `duckdb` to `run_duckdb_query` and `sql` to `query`.
- Auto-injects the primary dataset path when a SQL tool call omits `data_paths`.
- Saves successful agent SQL queries under `.dimer/artifacts/queries/`.
- Saves deterministic markdown reports under `.dimer/artifacts/reports/`.
- Saves session traces under `.dimer/sessions/`.

Known limitations:

- Chart generation is intentionally basic.
- Assumptions are only recorded when the model calls `record_assumption`; common caveats are not yet deterministic.
- `chat` cannot switch model/provider at runtime.
- There is no `--model` CLI flag yet; change the model in config.
- `/context` in chat prints the full workspace scan.
- Notebooks, ML mode, pipeline mode, and TUI will be future implementations.

## Quick start

```bash
uv sync --extra dev
uv run dimer init
uv run dimer profile sales.csv
uv run dimer context .
uv run dimer ask sales.csv "Which region contributed most revenue?"
uv run dimer ask sales.csv "Why did revenue drop in March?"
```

## Commands

- `dimer init` — initialize `.dimer/` workspace
- `dimer profile <path>` — profile a dataset
- `dimer context [path]` — scan workspace for data assets
- `dimer sql <path> <query>` — run DuckDB query
- `dimer artifacts` — list generated artifacts
- `dimer assumptions` — list recorded assumptions
- `dimer ask <path> "<question>"` — one-shot data analysis
- `dimer chat` — interactive session

## Example Workflow

Profile the sample dataset:

```bash
uv run dimer profile sales.csv
```

Run direct SQL:

```bash
uv run dimer sql sales.csv "SELECT region, SUM(revenue) AS total FROM sales GROUP BY region ORDER BY total DESC"
```

Ask the agent a question:

```bash
uv run dimer ask sales.csv "Why did revenue drop in March?"
```

Inspect generated artifacts:

```bash
uv run dimer artifacts
```

Generated files are stored under:

```text
.dimer/
  sessions/
  profiles/
  artifacts/
    queries/
    reports/
    charts/
  assumptions.md
  analysis_state.jsonl
```

## Config

User config: `~/.config/dimer/config.toml`

```toml
default_provider = "ollama"
default_model = "gemma4:e4b"

[providers.ollama]
base_url = "http://localhost:11434"
use_native_tools = false
num_predict = 2048
num_ctx = 8192
```

Switch provider for one command:

```bash
uv run dimer ask examples/sales/sales.csv "..." --provider lmstudio
```

Change model by editing `default_model` in config (CLI `--model` coming soon).

For local models that do not support native tool calling reliably, keep JSON fallback enabled:

```toml
use_native_tools = false
```

## Workspace ignores

Create `.dimerignore` at the workspace root (created by `dimer init` with defaults).
Uses gitignore-style patterns to exclude paths from `dimer context` and agent context.

```
agents/
node_modules/
.venv/
*.log
/data/raw/
```

Only built-in ignores: `.git`, `__pycache__`, `.dimer` (except `.dimer/artifacts/`).
Everything else is user-controlled via `.dimerignore`.

## Development

Run the test suite:

```bash
uv run pytest -q
```

Current expected result:

```text
N passed
```

The tests cover deterministic profiling, DuckDB execution, artifact/assumption storage, privacy and path safety, workspace scanning, provider serialization, and mocked agent tool-call flows.
