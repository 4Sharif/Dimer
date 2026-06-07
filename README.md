# Dimer

Terminal-native AI agent for data workflows.

Dimer understands datasets, SQL, charts, assumptions, and analytical provenance — helping you move from exploration to reproducible workflows.

## Quick start

```bash
uv sync --extra dev
uv run dimer init
uv run dimer profile examples/sales/sales.csv
uv run dimer context .
uv run dimer ask examples/sales/sales.csv "What are the main trends?"
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
