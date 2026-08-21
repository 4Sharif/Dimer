# Dimer

Dimer is a CLI agent for evidence-backed analysis of datasets, notebooks, and project files. It combines conversational analysis with deterministic tools and preserved evidence, ensuring that all data stays on user's machine.

## Features

- **Chat-First Analysis**: Investigate local data conversationally through an interactive chat interface, with concise progress updates and discoverable slash commands.
- **Deterministic Data Tools**: Profile CSV, Parquet, and Excel files; query CSV and Parquet data through DuckDB; and inspect notebooks without executing them.
- **Evidence-Backed Answers**: Tie analytical claims to recorded queries, tool results, caveats, assumptions, and basic provenance.
- **Local Model Support**: Use tested Ollama and LM Studio configurations without sending analysis context to a hosted provider.
- **Safe Execution Boundary**: Require approval for Python, reports, charts, and workspace writes; enforce Python timeouts, output limits, and workspace restrictions.
- **Persistent Analysis State**: Save and replay sessions, inspect artifacts and traces, and export eligible SQL as a verified replay script.

## Tech Stack

- **Language and CLI**: Python 3.11+, Typer, Rich, prompt-toolkit
- **Data Processing**: DuckDB, pandas, PyArrow, openpyxl
- **Visualization**: Matplotlib
- **Model Providers**: Ollama and LM Studio
- **Validation and Transport**: Pydantic, HTTPX
- **Testing and Packaging**: pytest, uv, Hatchling

## Usage

Start the primary interactive workflow:

```bash
uv run dimer chat
```

Inside chat, you can profile a dataset and ask a question:

```text
/profile examples/sales/sales.csv
Which region contributed most revenue?
/artifacts session
/trace revenue
/export
```

One-shot analysis is available for repeatable tasks:

```bash
uv run dimer ask examples/sales/sales.csv "Why did revenue change in March?"
```

Deterministic commands do not require a model provider:

```bash
uv run dimer profile examples/sales/sales.csv
uv run dimer context examples/sales
uv run dimer sql examples/sales/sales.csv "SELECT region, SUM(revenue) AS total FROM sales GROUP BY region"
```

## Commands

| Command | Purpose |
|---|---|
| `dimer chat` | Start an interactive analysis session |
| `dimer doctor` | Check provider configuration and tool round trips |
| `dimer ask` | Run a one-shot model-assisted analysis |
| `dimer profile` | Inspect a dataset's schema and quality warnings |
| `dimer context` | Summarize datasets, notebooks, and files in a workspace |
| `dimer sql` | Execute a deterministic DuckDB query |
| `dimer sessions` / `session` | List or inspect saved sessions |
| `dimer artifacts` / `trace` | Inspect outputs and basic provenance |
| `dimer export` | Export eligible session SQL as a replay script |

## Architecture

Dimer keeps provider transport, agent policy, tool execution, and durable evidence behind separate boundaries:

```text
CLI / interactive chat
        │
        ▼
Agent orchestration and policy
        ├── Provider adapters ── Ollama / LM Studio
        ├── Tool router ──────── profile / DuckDB / Python / files / reports
        └── Analytical context ─ evidence / assumptions / provenance
                                   │
                                   ▼
                           .dimer/ workspace state
```

### Workspace State

`dimer init` creates:

```text
.dimer/
├── sessions/
├── profiles/
├── artifacts/
│   ├── queries/
│   ├── reports/
│   ├── charts/
│   └── scripts/
├── assumptions.md
└── analysis_state.jsonl
```

Use `.dimerignore` at the workspace root to exclude paths from scanning and model-visible tools.

## Limitations

- Local-model quality varies, particularly during longer multi-step investigations.
- Tested status applies only to the exact provider/model configurations listed above.
- Python restrictions are process- and audit-based rather than an operating-system container.
- Notebook support is read-only and does not reproduce kernel state.
- Provenance is heuristic SQL/artifact lineage rather than a complete execution graph.
- Export currently replays successful SQL only.
- Chart generation is intentionally limited to basic line and categorical bar charts.

## Getting Started

### Prerequisites

- Python 3.11 or newer
- [uv](https://docs.astral.sh/uv/)
- Ollama or LM Studio with a compatible local model running in the background.

### Installation

```bash
git clone https://github.com/4Sharif/Dimer.git
cd Dimer
uv sync --extra dev --locked
```

Initialize Dimer's workspace state and user configuration:

```bash
uv run dimer init
```

## Configuration

Dimer reads provider settings from `~/.config/dimer/config.toml`. A tested Ollama configuration looks like:

```toml
default_provider = "ollama"
default_model = "granite4.1:8b"

[providers.ollama]
base_url = "http://localhost:11434"
model = "granite4.1:8b"
num_ctx = 4096
num_predict = 512

[providers.ollama.models."granite4.1:8b"]
tool_protocol = "native"

[privacy]
allow_cloud_llm = false
```

Confirm the selected provider before starting an analysis:

```bash
uv run dimer doctor
```

## Development

Run the deterministic test suite:

```bash
uv run pytest -q
```

Build the wheel and source distribution:

```bash
uv build
```
