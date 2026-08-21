
# Dimer Build Instructions

You are helping me build **Dimer**, a terminal-native AI agent harness for data workflows.

Dimer is **not** meant to be a generic software engineering coding agent like Claude Code, Codex CLI, Gemini CLI, OpenCode, or Pi. Those tools are useful references for architecture, but Dimer’s main purpose is different.

Dimer should be a **data-native terminal agent** that understands local datasets, notebook state, SQL, charts, assumptions, analysis steps, and reproducibility.

The goal is to build this project incrementally. Do not overbuild the first version. The first milestone should be a useful local data analysis agent that can inspect datasets, run SQL/Python analysis, generate charts/reports, and track what it did.

---

# 1. Product Thesis

Dimer is:

> A terminal-native data agent that understands datasets, notebook state, SQL, outputs, assumptions, and analytical provenance, then helps users move from exploration to reproducible workflows.

This means the agent should not only reason over source code files. It should reason over:

- datasets
- schemas
- columns
- notebook markdown/code/output
- dataframe state
- SQL queries
- charts
- generated files
- filters applied
- assumptions made
- data quality issues
- analysis steps
- reproducibility gaps

A normal coding agent tracks things like:

```txt
files changed
commands run
git diff
tests run
```

Dimer should track things like:

```
datasets inspected
columns selected
filters applied
aggregations run
queries executed
charts created
reports generated
assumptions recorded
quality issues found
analysis state changes
```

---

# 2. Core Project Scope

Build Dimer as a local-first terminal application.

The first version should focus on local files:

- CSV
- Excel
- Parquet
- basic notebooks later
- local SQL over files using DuckDB
- local Python analysis

Do **not** start with:

- full TUI
- cloud warehouses
- dbt/Airflow/Dagster
- full AutoML
- complicated sub-agents
- MCP
- production deployment
- SaaS backend
- multi-user auth

Those can come later.

The first goal is:

```
dimer profile data/sales.csv
dimer ask data/sales.csv "What are the most important trends?"
```

The first impressive demo should be:

```
dimer ask data/sales.csv "Why did revenue drop in March?"
```

Expected behavior:

1. Dimer profiles the dataset.
2. Dimer identifies useful columns.
3. Dimer runs DuckDB SQL and/or Python analysis.
4. Dimer generates a chart.
5. Dimer saves a markdown report.
6. Dimer records assumptions and analysis steps.
7. Dimer ends with findings, artifacts, and caveats.

---

# 3. Development Philosophy

Build the engine before the interface.

The project should eventually have a basic TUI, but do not start there. Start with a simple CLI and interactive command loop. The agent internals should emit structured events so that a future TUI can render them.

Use this progression:

```
Phase 1: CLI commands
Phase 2: interactive CLI
Phase 3: modes and session tracking
Phase 4: notebook awareness
Phase 5: ML mode
Phase 6: pipeline/production mode
Phase 7: basic TUI
```

The architecture should make a future TUI easy by separating:

```
agent logic
tool execution
event emission
rendering
```

Do not put core agent logic directly inside UI code.

---

# 4. Recommended Tech Stack

Use Python for the MVP.

Reason: this is a data-focused agent, and Python has the best ecosystem for local data analysis.
Preferably
Use:

```
Language: Python
Package/project manager: uv if available, otherwise standard venv + pip
CLI: Typer
Console rendering: Rich
Interactive input: prompt_toolkit
Dataframes: pandas first
SQL: DuckDB
Parquet support: pyarrow
Excel support: openpyxl
Charts: matplotlib
Validation/models: Pydantic
Storage: JSON for now in MVP phase, SQLite in the future
Config: TOML
Notebooks later: nbformat
LLM providers: custom provider abstraction
```

Avoid building the first version in Rust or TypeScript unless explicitly asked. Rust/Ratatui or TypeScript/TUI work can come later after the data engine is useful.

---

# 5. High-Level Architecture

Use this project structure:

```
dimer/
  pyproject.toml
  README.md
  .gitignore
  implementations.md

  dimer/
    __init__.py
    cli.py
    config.py

    agent/
      __init__.py
      loop.py
      events.py
      prompts.py
      tool_router.py
      compaction.py
      session.py

    providers/
      __init__.py
      base.py
      ollama.py
      lmstudio.py
      openai_compatible.py
      openai.py
      anthropic.py
      gemini.py

    tools/
      __init__.py
      files.py
      shell.py
      python_exec.py
      duckdb_exec.py
      dataset_profile.py
      notebook_reader.py
      chart.py
      report.py

    data_context/
      __init__.py
      workspace_scanner.py
      dataset_registry.py
      schema_profile.py
      notebook_context.py
      analysis_state.py
      assumption_log.py
      artifact_registry.py

    safety/
      __init__.py
      permissions.py
      privacy.py
      pii.py
      process_limits.py

    storage/
      __init__.py
      sqlite.py
      sessions.py
      artifacts.py

    ui/
      __init__.py
      console.py
      interactive.py
      approvals.py

  examples/
    sales/
      sales.csv

  tests/
    test_dataset_profile.py
    test_duckdb_exec.py
    test_assumption_log.py
    test_artifact_registry.py
```

Key directories:

```
agent/          generic agent loop
providers/      model/provider connections
tools/          actions the model can request
data_context/   Dimer’s unique data-native layer
safety/         permissions, privacy, process limits
storage/        sessions, logs, artifacts
ui/             CLI now, TUI later
```

The most important differentiator is:

```
data_context/
```

This is where Dimer becomes different from a normal coding agent.

The `implementations.md` file is meant for you. Whenever you're done with whatever you're implementing, write your results in there in a structured format under what's already mentioned. It's useful as a reference so you know what's been done.  Ex:

```
## Implemented Features
- [Date] Feature Name: Brief architectural summary of how it was coded.
```

Also, just to better reflect the context of this project, duplicate this instructions file, and use the duplicate to adjust the current phases, changes, future of the project. Decide whether its necessary to do that after each implementation.

---

# 6. Agent Loop

Implement a basic Thought-Action-Observation style loop.

Conceptually:

```
1. User asks a question.
2. Dimer builds data-aware context.
3. Dimer sends messages + tool schemas to the model.
4. Model either responds directly or requests a tool call.
5. Dimer validates the tool call.
6. Dimer asks user approval if the action is risky.
7. Dimer executes the tool.
8. Dimer stores the tool result in the session.
9. Dimer compacts/summarizes large outputs.
10. Dimer continues until final response.
```

The agent loop must not be hardcoded to one provider. It should call a provider interface.

Rough shape:

```
class AgentLoop:
    def __init__(self, provider, tool_router, session_store, event_sink):
        ...

    def run(self, user_message: str, context: AgentContext) -> AgentResult:
        ...
```

The loop should support tool calls, but if structured tool calling is not available for a local model, support a fallback JSON tool-call format.

---

# 7. Event System

Use structured events from the beginning.

This is important because the first interface can be simple console output, but a future TUI can subscribe to the same events.

Create event types like:

```
agent_started
agent_message_delta
agent_finished

tool_call_requested
tool_call_started
tool_call_finished
tool_call_failed

approval_requested
approval_accepted
approval_denied

dataset_profile_started
dataset_profile_finished

sql_query_started
sql_query_finished

python_exec_started
python_exec_finished

chart_created
report_saved
assumption_recorded
artifact_created
quality_issue_found
```

Events should be plain Pydantic models or dataclasses.

Example:

```
class DimerEvent(BaseModel):
    type: str
    message: str | None = None
    payload: dict = {}
    timestamp: datetime
```

The CLI renderer should consume events and display them with Rich.

Do not print directly from tools unless absolutely necessary. Tools should return structured results, and the renderer should display them.

---

# 8. Provider System

Implement a provider abstraction.

The agent should not care whether the model is Ollama, LM Studio, OpenAI, Anthropic, Gemini, or another provider.

Create:

```
providers/base.py
```

With something like:

```
class ModelProvider(Protocol):
    name: str

    def generate(
        self,
        messages: list[ModelMessage],
        tools: list[ToolSchema] | None = None,
        model: str | None = None,
        temperature: float = 0.2,
    ) -> ModelResponse:
        ...

    def stream(
        self,
        messages: list[ModelMessage],
        tools: list[ToolSchema] | None = None,
        model: str | None = None,
        temperature: float = 0.2,
    ) -> Iterator[ModelStreamEvent]:
        ...
```

Normalize all provider responses into internal types:

```
ModelMessage
ModelResponse
ModelToolCall
ModelStreamEvent
ToolSchema
```

Start with local/free testing providers:

```
1. Ollama
2. LM Studio or any OpenAI-compatible local server
```

Then add cloud providers later:

```
3. OpenAI
4. Anthropic
5. Gemini
```

Provider config should live in a local config file, not source code.

Example:

```
# ~/.config/dimer/config.toml

default_provider = "ollama"
default_model = "qwen2.5-coder:7b"

[providers.ollama]
base_url = "http://localhost:11434"

[providers.lmstudio]
base_url = "http://localhost:1234/v1"
api_key = "lm-studio"

[providers.openai]
api_key_env = "OPENAI_API_KEY"
model = "gpt-5.2"

[providers.anthropic]
api_key_env = "ANTHROPIC_API_KEY"
model = "claude-sonnet-4.5"

[providers.gemini]
api_key_env = "GEMINI_API_KEY"
model = "gemini-pro"
```

Do not store real API keys in project files.

Prefer:

```
environment variables first
OS keychain later
```

For local OpenAI-compatible providers, implement one reusable provider:

```
openai_compatible.py
```

It should support LM Studio, vLLM, LiteLLM, and other compatible endpoints.

---

# 9. Tool System

Implement tools as structured callable units.

Each tool should have:

```
name
description
input schema
risk level
execute function
structured output
```

Example:

```
class ToolDefinition(BaseModel):
    name: str
    description: str
    input_schema: dict
    risk_level: Literal["safe", "approval_required", "dangerous"]
```

Start with these tools:

## File tools

```
list_files(path)
read_file(path)
write_file(path, content)
```

Restrictions:

- Do not allow reading outside the workspace by default.
- Do not allow writing outside the workspace.
- Do not read `.env`, SSH keys, or credential files without approval.

## Dataset tools

```
inspect_dataset(path)
profile_dataset(path)
```

These are core tools.

They should support:

```
CSV
Excel
Parquet
```

`inspect_dataset` should be quick and lightweight.

`profile_dataset` can compute more details.

Dataset profile should include:

```
path
file type
file size
row count
column count
column names
dtypes
missing values
numeric summaries
categorical top values
date ranges
duplicate count if feasible
potential ID columns
possible target columns
quality warnings
small redacted sample if allowed
```

Do not send entire datasets to the model.

## SQL tools

Use DuckDB.

Implement:

```
run_duckdb_query(query, data_paths, max_rows=50)
```

The result should include:

```
query
row count
column names
preview rows
truncation flag
execution time
error if failed
```

The model should be encouraged to use DuckDB for local analytics over CSV/Parquet.

## Python tool

Implement a controlled Python execution tool.

```
run_python(code, timeout_seconds=30)
```

Restrictions:

- Run in the project workspace.
- Capture stdout/stderr.
- Enforce timeout.
- Truncate output.
- Avoid unrestricted long-running jobs.
- Ask approval for file writes, network calls, or shell calls inside Python if detectable.
- Later, consider subprocess isolation.

The result should include:

```
stdout
stderr
return value summary if possible
created files
execution time
error/traceback
```

## Chart tool

The first implementation can let Python generate charts using matplotlib.

Track generated charts as artifacts.

```
create_chart(...)
```

or let `run_python` generate charts and detect/save artifact paths.

For MVP, it is okay to generate charts through Python code and register any created image files.

## Report tool

Implement:

```
save_report(path, markdown_content)
```

Reports should usually go under:

```
.dimer/artifacts/reports/
```

or a user-specified output path.

## Assumption tool

Implement:

```
record_assumption(text, source=None, confidence=None)
```

Save assumptions in session storage and optionally in:

```
.dimer/assumptions.md
```

## Artifact tool

Implement an artifact registry that tracks:

```
charts
reports
scripts
queries
notebooks
models later
logs
```

---

# 10. Data Context Layer

This is the most important part of Dimer.

Implement a data context system that builds a compact summary of the workspace and session.

It should include:

```
datasets discovered
dataset profiles
known schemas
notebooks discovered
recent queries
charts generated
reports generated
assumptions
quality warnings
analysis steps
artifacts
```

Create these modules:

## workspace_scanner.py

Find relevant files:

```
.csv
.xlsx
.xls
.parquet
.ipynb
.sql
.py
.md
```

Ignore:

```
.git
.venv
venv
node_modules
__pycache__
.dimer/cache
large binary files
```

## dataset_registry.py

Keeps track of known datasets and their profiles.

## schema_profile.py

Contains profile data models and profiling logic.

## notebook_context.py

Initially read notebooks only. Do not execute notebooks in MVP.

For `.ipynb`, extract:

```
markdown cells
code cells
text outputs
dataframe-like outputs when available
image output metadata if available
execution counts
possible out-of-order execution warnings
datasets loaded
major variables if easily detectable
```

## analysis_state.py

Tracks analytical events:

```
dataset_inspected
dataset_profiled
filter_applied
aggregation_run
sql_query_run
python_code_run
chart_created
report_created
assumption_added
quality_issue_found
```

Each event should have:

```
event id
timestamp
event type
inputs
outputs
reason if available
tool source
artifact paths
```

## assumption_log.py

Stores assumptions and decisions.

Examples:

```
- Revenue includes refunds as negative values.
- March drop is compared against February, not same month last year.
- Rows with missing product_category were kept.
- Outliers above 99th percentile were removed only for visualization.
```

## artifact_registry.py

Tracks generated artifacts.

Examples:

```
- charts/monthly_revenue.png
- reports/march_revenue_drop.md
- queries/march_breakdown.sql
- scripts/march_analysis.py
```

---

# 11. Privacy and Safety

Because Dimer works with data, privacy matters more than in a normal coding agent.

Default rules:

```
- Never send full datasets to the model.
- Send profiles and summaries instead.
- Do not include sample rows by default unless the config allows it.
- If sample rows are included, limit them.
- Redact obvious PII.
- Ask before reading credential files.
- Ask before sending raw rows to cloud providers.
- Ask before writing/deleting files.
- Ask before running network commands.
- Ask before long-running Python/shell commands.
```

Config example:

```
[privacy]
send_sample_rows = false
max_sample_rows = 5
redact_pii = true
allow_cloud_llm = true
```

Implement basic PII detection:

```
email addresses
phone numbers
SSN-like patterns
credit-card-like patterns
```

Do not try to make this perfect in MVP. Make it clear and conservative.

---

# 12. Permission System

Tools should have risk levels.

Suggested risk levels:

```
safeapproval_required
dangerous
```

Safe examples:

```
list files in workspace
read normal project files
profile dataset without sending raw rows
run read-only DuckDB query
save report to .dimer/artifacts
```

Approval required:

```
delete files
access home directory secrets
network exfiltration
git reset --hard
git push
sudo commands
curl | bash
```

Dangerous:

```
timeout_seconds = 30
max_output_chars = 20000
max_preview_rows = 50
```

MVP can block dangerous actions entirely.

---

# 13. Process Management

For Python and shell execution:

- enforce timeouts
- capture stdout/stderr
- truncate output
- return structured errors
- avoid zombie child processes
- allow cancellation later

Recommended default limits:

```
timeout_seconds = 30max_output_chars = 20000max_preview_rows = 50
```

Long-running ML jobs should not be part of MVP.

---

# 14. CLI Commands

Implement these first:

```
dimer profile PATH
```

Profiles a dataset.

```
dimer context [PATH]
```

Scans the workspace and summarizes datasets/notebooks/artifacts.

```
dimer ask PATH "QUESTION"
```

Runs a one-shot data agent query against a file or workspace.

```
dimer chat
```

Starts an interactive CLI session.

Inside interactive mode, support slash commands:

```
/mode analysis
/mode sql
/context
/profile path
/assumptions
/artifacts
/help
/exit
```

Do not implement every future mode yet. For now:

```
analysis mode
sql mode
```

Stub the rest:

```
ml mode: planned
scientist mode: planned
pipeline mode: planned
```

---

# 15. Modes

A mode is:

```
system prompt + tool preferences + output style
```

Implement mode as config, not as separate code paths.

## Analysis Mode

Default.

Behavior:

```
- inspect data before answering
- prefer dataset profile first
- use SQL/Python for real computations
- generate charts when useful
- produce findings and caveats
- record assumptions
```

Final answer format:

```
Findings
Evidence
Generated artifacts
Assumptions
Data quality notes
Suggested next steps
```

## SQL Mode

Behavior:

```
- prefer DuckDB queries
- explain queries
- validate results
- save important SQL
- avoid unnecessary pandas
```

## Future ML Mode

Do not fully implement yet.

Planned behavior:

```
- baseline model training
- train/test split
- metrics
- feature importance
- leakage warnings
- model artifact saving
```

## Future Pipeline Mode

Do not fully implement yet.

Planned behavior:

```
- convert exploration to scripts
- add data validation checks
- create reproducible workflow
- eventually support dbt/Airflow/Dagster-style projects
```

---

# 16. System Prompt for the Agent

Use a system prompt like this for Analysis Mode:

```
You are Dimer, a terminal-native AI agent for data analysis, data science, SQL, notebooks, and reproducible analytical workflows.

Your job is not just to write code. Your job is to understand the analytical context of the workspace.

Default behavior:
- Inspect dataset schemas before making claims.
- Use tools to compute results instead of guessing.
- Prefer DuckDB SQL or Python for analysis.
- Do not request or expose full raw datasets unless explicitly allowed.
- Treat dataset profiles, notebook outputs, assumptions, and artifacts as first-class context.
- Record important assumptions and decisions.
- Mention data quality issues that affect conclusions.
- Preserve exploratory flexibility; do not over-refactor early.
- When useful, create charts and markdown reports.
- End with findings, evidence, generated artifacts, assumptions, and caveats.

Privacy:
- Never send full datasets to the model by default.
- Prefer aggregate summaries, schema information, and redacted samples.
- Ask for approval before exposing raw rows to a cloud model.

When using tools:
- Use inspect_dataset/profile_dataset before analyzing unknown data.
- Use DuckDB for SQL-friendly analysis over CSV/Parquet files.
- Use Python for more complex analysis or charts.
- Save generated outputs as artifacts.
- Keep results reproducible by saving important queries/code where possible.
```

SQL Mode prompt should add:

```
You are in SQL mode. Prefer DuckDB SQL for analysis. Explain and validate SQL queries. Use Python only when SQL is insufficient.
```

---

# 17. Compaction

Do not send massive outputs back into the model.

Implement simple compaction early:

```
- truncate stdout/stderr over max length
- show dataframe previews only
- summarize dataset profiles compactly
- store full outputs locally if needed
- include file paths to full logs/artifacts
```

For dataset profile context, include:

```
row count
column count
columns/dtypes
missing value summary
numeric summary
categorical top values
date ranges
quality warnings
```

Do not include thousands of rows.

---

# 18. Storage

Create a local `.dimer/` directory in the workspace.

Suggested structure:

```
.dimer/
  sessions/
    session-YYYYMMDD-HHMMSS.json

  artifacts/
    charts/
    reports/
    queries/
    scripts/
    logs/

  profiles/
    sales.csv.profile.json

  assumptions.md
  analysis_state.jsonl
```

Use SQLite later if helpful. For MVP, JSON/JSONL files are fine. If SQLite is easy, use it, but do not let storage complexity block progress.

Session should store:

```
messages
tool calls
tool results
events
artifacts
assumptions
analysis state
```

---

# 19. Final Response Style

When Dimer finishes an analysis task, it should not respond like a coding agent.

It should respond like this:

```
Findings
1. March revenue dropped 18.4% compared with February.
2. The drop was concentrated in the West region.
3. Subscription products accounted for most of the decline.

Evidence
- Query: .dimer/artifacts/queries/march_revenue_breakdown.sql
- Chart: .dimer/artifacts/charts/monthly_revenue.png
- Report: .dimer/artifacts/reports/march_revenue_drop.md

Assumptions
- Revenue includes refunds as negative values.
- March was compared against February because no prior-year data was available.

Data quality notes
- 4.2% of March rows have missing product_category.
- 17 rows have negative revenue.

Generated artifacts
- .dimer/artifacts/charts/monthly_revenue.png
- .dimer/artifacts/reports/march_revenue_drop.md
```

The agent should be transparent about uncertainty.

---

# 20. MVP Build Order

Build in this exact order unless there is a strong reason not to:

## Step 1: Project scaffold

- Create Python package.
- Add Typer CLI.
- Add Rich console.
- Add config loader.
- Add `.dimer/` workspace initialization.

Commands:

```
dimer --help
dimer init
```

## Step 2: Dataset profiler

Implement:

```
dimer profile data/sales.csv
```

Support CSV first, then Parquet, then Excel.

Output a readable table in terminal and save profile JSON.

## Step 3: Workspace context

Implement:

```
dimer context .
```

Find datasets, notebooks, SQL files, Python files, existing artifacts.

## Step 4: DuckDB executor

Implement a command like:

```
dimer sql data/sales.csv "SELECT * FROM sales LIMIT 5"
```

or internally support DuckDB tool execution.

## Step 5: Artifact and assumption tracking

Implement:

```
dimer artifacts
dimer assumptions
```

And internal registries.

## Step 6: Provider abstraction

Implement:

```
providers/base.py
providers/ollama.py
providers/openai_compatible.py
providers/lmstudio.py
```

Test simple non-agent completions first.

## Step 7: Tool router

Register tools:

```
inspect_dataset
profile_dataset
run_duckdb_query
run_python
save_report
record_assumption
list_files
read_file
```

## Step 8: Agent loop

Implement one-shot:

```
dimer ask data/sales.csv "What are the main trends?"
```

Use the provider, context, and tools.

For local models without native tool calling, use a strict JSON protocol.

## Step 9: Interactive CLI

Implement:

```
dimer chat
```

Support:

```
/mode analysis
/mode sql
/context
/profile
/artifacts
/assumptions
/exit
```

## Step 10: Reports and charts

Have the agent create:

```
.dimer/artifacts/reports/*.md
.dimer/artifacts/charts/*.png
```

## CRITICAL EXECUTION RULE FOR THE SANDBOX:

The `run_python` tool MUST execute code inside a single, persistent background session that maintains variable memory across multiple sequential tool invocations. Do NOT spawn stateless, ephemeral python sub-processes. Use an active `subprocess.Popen` interactive pipeline or a background IPython kernel session so that datasets loaded into memory during Step 2 remain fully accessible during Step 8.

---

# 21. JSON Tool Call Fallback Protocol

For local models that do not support native tool calling, use this format.

The model must respond with either:

```
{
  "type": "final",
  "content": "..."
}
```

or:

```
{
  "type": "tool_call",
  "tool_name": "profile_dataset",
  "arguments": {
    "path": "data/sales.csv"
  }
}
```

The agent should parse, validate, execute, and return the observation.

Tool observation format:

```
{
  "type": "tool_result",
  "tool_name": "profile_dataset",
  "success": true,
  "result": {
    "rows": 1000,
    "columns": ["date", "revenue"]
  }
}
```

If parsing fails, ask the model to retry with valid JSON. Do not execute malformed tool calls.

---

# 22. Testing Expectations

Add tests for core deterministic pieces.

Minimum tests:

```
test_dataset_profile_csv
test_dataset_profile_missing_values
test_dataset_profile_date_detection
test_duckdb_query_preview
test_assumption_log_write_read
test_artifact_registry_register
test_privacy_redacts_email
test_permissions_blocks_path_escape
```

Do not rely on live LLM calls in unit tests.

Mock providers for agent loop tests.

---

# 23. Important Design Rules

Follow these rules:

1. **Do not build the TUI first.**
    Build CLI and event system first.
2. **Do not hardcode one model provider.**
    Use provider abstraction from the beginning.
3. **Do not send raw datasets to the model.**
    Send profiles/summaries by default.
4. **Do not make claims without computation.**
    Use tools for actual analysis.
5. **Do not over-refactor exploratory work.**
    Preserve context during exploration.
6. **Do not hide uncertainty.**
    Show assumptions, caveats, and data quality issues.
7. **Do not make the agent only code-aware.**
    Make it data-state-aware.
8. **Do not create giant outputs in chat.**
    Save artifacts and summarize.
9. **Do not let the LLM run arbitrary commands unchecked.**
    Validate tools and require approval for risky actions.
10. **Keep MVP small but real.**
    The first version should actually analyze data and produce useful artifacts.

---

# 24. What Success Looks Like for Version 0.1

Version 0.1 is successful if this works:

```
dimer profile examples/sales/sales.csv
```

and this works:

```
dimer ask examples/sales/sales.csv "What are the most important trends in this dataset?"
```

The result should include:

```
- dataset profile
- real computed analysis
- at least one generated chart when useful
- a markdown report
- assumptions log
- artifact list
- data quality notes
```

The codebase should have:

```
- clean module boundaries
- provider abstraction
- tool registry
- event system
- data context layer
- privacy defaults
- tests for deterministic pieces
```

---

# 25. Future Roadmap

After MVP:

## Phase 2: Better interactive CLI

- better `/mode`
- better session replay
- better artifact browsing
- better approval prompts

## Phase 3: Notebook awareness

- summarize `.ipynb`
- read markdown/code/output
- detect execution order issues
- explain why analysis changed direction
- produce notebook summaries

## Phase 4: Analysis state graph

- trace variables
- trace charts back to queries/data
- track filters and transformations
- `/trace column_or_artifact`

## Phase 5: ML mode

- baseline model training
- metrics
- train/test split
- leakage warnings
- feature importance
- saved model artifacts

## Phase 6: Pipeline/production mode

- productionize notebook
- generate scripts
- generate validation checks
- generate config
- generate reproducible reports

## Phase 7: Basic TUI

- dataset panel
- chat panel
- tool log panel
- artifact panel
- approval dialogs
- chart preview if terminal supports it

---

# 26. Immediate Task

Start by creating the project scaffold and implementing the deterministic non-LLM pieces first.

First deliverable:

```
A working Python package with:
- Typer CLI
- Rich output
- dimer init
- dimer profile <path>
- .dimer directory creation
- dataset profile saved as JSON
- basic tests
```

Do not start with model calls until dataset profiling and local context tracking work.

Once those work, implement provider abstraction and the first local provider.

Final reminder:

Dimer is not “Claude Code with pandas.”
Dimer is an analysis-native terminal agent.
Its unique value is understanding data context, analytical state, assumptions, and reproducible artifacts.