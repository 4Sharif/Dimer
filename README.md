# Dimer

Dimer is an experimental, local-first terminal agent for evidence-backed analysis of datasets, notebooks, and project files. Built as a portfolio project and technical prototype, it combines conversational analysis with deterministic tools and preserved evidence; the safe core and tested local-provider paths are complete through Milestone 3, while broader evaluation, chat polish, and release packaging remain future work.

## Features

- **Chat-First Analysis**: Investigate local data conversationally through `dimer chat`, with concise progress updates and discoverable slash commands.
- **Deterministic Data Tools**: Profile CSV, Parquet, and Excel files; query CSV and Parquet data through DuckDB; and inspect notebooks without executing them.
- **Evidence-Backed Answers**: Tie analytical claims to recorded queries, tool results, caveats, assumptions, and basic provenance.
- **Local Model Support**: Use tested Ollama and LM Studio configurations without sending analysis context to a hosted provider.
- **Safe Execution Boundary**: Require approval for Python, reports, charts, and workspace writes; enforce Python timeouts, output limits, and workspace restrictions.
- **Persistent Analysis State**: Save and replay sessions, inspect artifacts and traces, and export eligible SQL as a verified replay script.
- **Provider Diagnostics**: Validate configuration, completion, tool calling, and tool-result handling with `dimer doctor`.

## Tech Stack

- **Language and CLI**: Python 3.11+, Typer, Rich, prompt-toolkit
- **Data Processing**: DuckDB, pandas, PyArrow, openpyxl
- **Visualization**: Matplotlib
- **Model Providers**: Ollama and LM Studio, with an experimental OpenAI-compatible extension seam
- **Validation and Transport**: Pydantic, HTTPX
- **Testing and Packaging**: pytest, uv, Hatchling

## Getting Started

### Prerequisites

- Python 3.11 or newer
- [uv](https://docs.astral.sh/uv/)
- Ollama or LM Studio with a compatible local model

On memory-constrained systems, keep only one local model runtime loaded at a time.

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

## Usage

Start the primary interactive workflow:

```bash
uv run dimer chat
```

Inside chat, profile a dataset and ask a question:

```text
/profile examples/sales/sales.csv
Which region contributed most revenue?
/artifacts session
/trace revenue
/export
```

One-shot analysis is available for repeatable tasks:

```bash
uv run dimer ask examples/sales/sales.csv \
  "Why did revenue change in March?"
```

Deterministic commands do not require a model provider:

```bash
uv run dimer profile examples/sales/sales.csv
uv run dimer context examples/sales
uv run dimer sql examples/sales/sales.csv \
  "SELECT region, SUM(revenue) AS total FROM sales GROUP BY region"
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

## Architecture & System Design

Dimer keeps provider transport, agent policy, tool execution, and durable evidence behind separate boundaries:

```text
CLI / interactive chat
        │
        ▼
Agent orchestration and policy
        ├── Provider adapters ── Ollama / LM Studio / OpenAI-compatible
        ├── Tool router ──────── profile / DuckDB / Python / files / reports
        └── Analytical context ─ evidence / assumptions / provenance
                                   │
                                   ▼
                           .dimer/ workspace state
```

### Engineering Highlights

- **Lossless Provider Turns**: Structured assistant messages retain native tool-call identifiers, finish reasons, usage, and available request metadata through multi-turn execution.
- **Model-Specific Tool Policy**: Native tools are enabled only for recorded provider/model pairs; unknown models fall back to Dimer's JSON protocol.
- **Bounded Python Worker**: Python runs in a persistent child process with timeout termination, bounded output, recovery, and workspace-oriented audit restrictions.
- **Evidence Contract**: Analytical conclusions are classified against recorded computation so unsupported numeric claims are not presented as verified findings.
- **Replayable SQL**: Successful DuckDB work can be exported with a source manifest, schema fingerprints, and replay-time drift warnings.
- **Ignored-Path Enforcement**: `.dimerignore` applies across scanning and model-visible file, dataset, notebook, and query operations.

## Tested Provider Configurations

Provider behavior depends on the exact runtime, model, protocol, and context settings. The following configurations passed Dimer's four-stage live doctor check on an Apple M5 with 10 cores and 16 GB of memory:

| Provider | Tested Configuration |
|---|---|
| Ollama | Ollama 0.32.15, `granite4.1:8b`, native tools, `num_ctx=4096`, `num_predict=512` |
| LM Studio | LM Studio 0.4.21+2, `qwen/qwen3.5-9b`, native tools, Q4_K_M, loaded context 12032 |

The machine-readable records are stored in [`project-context/provider-capability-evidence.jsonl`](project-context/provider-capability-evidence.jsonl). Other models do not inherit Tested status automatically.

OpenAI and custom OpenAI-compatible endpoints remain experimental and non-gating. Gemini's OpenAI-compatible path is configured but has not completed Dimer's live matrix. Anthropic is unsupported because Dimer does not implement its native Messages API.

## Safety & Privacy

- Python, chart/report creation, and workspace writes require approval by default.
- `--auto-approve` is an explicit advanced override for one-shot analysis.
- Python execution is timeout-bounded and cannot intentionally access paths outside the selected workspace through supported operations.
- SQL and Python execute locally; a local model provider can also keep prompt context local.
- Remote providers require an explicit privacy opt-in and may receive schemas, samples, query results, notebook content, or errors.
- Redaction is best effort rather than guaranteed anonymization; sensitive data should still be reviewed before provider use.
- Raw provider responses are not persisted unless `include_raw_diagnostics = true` is explicitly enabled.

## Workspace State

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

## Development

Run the deterministic test suite:

```bash
uv run pytest -q
```

Build the wheel and source distribution:

```bash
uv build
```

On Apple Silicon, use `arch -arm64` when the shell is running under Rosetta but the environment contains ARM64 packages.

The active scope and roadmap are defined in [`MVP-PROPOSAL.md`](MVP-PROPOSAL.md). Detailed verification history is recorded in [`project-context/Instructions-status.md`](project-context/Instructions-status.md), and the guided manual workflow is in [`project-context/using-dimer.md`](project-context/using-dimer.md).
