# Using and Verifying Dimer

This guide covers the narrowed Dimer MVP: interactive analysis, evidence, saved sessions, and SQL export. Commands assume the repository root.

## 1. Install and inspect the CLI

```bash
uv sync --extra dev --locked
uv run dimer --help
uv run dimer ask --help
```

The root help should present `chat` as the interactive interface and retain the secondary commands `ask`, `profile`, `context`, `sql`, `sessions`, `session`, and `export`. The one-shot help should offer provider, model, and approval controls.

If an Apple Silicon shell reports `x86_64` under Rosetta while the environment is ARM64, use:

```bash
arch -arm64 uv sync --extra dev --locked
arch -arm64 uv run dimer --help
```

## 2. Configure a model provider

Dimer reads `~/.config/dimer/config.toml`. A local Ollama configuration looks like:

```toml
default_provider = "ollama"
default_model = "qwen2.5-coder:7b"

[providers.ollama]
base_url = "http://localhost:11434"
include_raw_diagnostics = false
num_predict = 2048
num_ctx = 8192

[providers.ollama.models."qwen2.5-coder:7b"]
tool_protocol = "json"

[providers.lmstudio]
base_url = "http://127.0.0.1:1234/v1"
api_key = "lm-studio"
model = "local-model"

[privacy]
allow_cloud_llm = false
```

Check the selected provider without starting an analysis session:

```bash
uv run dimer doctor
```

The doctor path verifies configuration/provider construction, one basic completion, one deterministic tool call through the selected model's configured native or JSON protocol, and a follow-up summary of the returned tool result. It reports the provider, model, endpoint, local-versus-cloud data handling, and each diagnostic stage separately. A failure exits non-zero with an actionable stage-specific remedy; later stages remain `not checked` when an earlier prerequisite fails.

A passing result is capability evidence for the exact configuration under test, not for every model a runtime can load. Provider-status promotion remains a separate, evidence-backed documentation decision.

Ollama and LM Studio are the Tested local-first MVP release paths for their recorded configurations: Ollama 0.32.15 with `granite4.1:8b` using native tools, `num_ctx=4096`, and `num_predict=512`; and LM Studio 0.4.21+2 with `qwen/qwen3.5-9b` using native tools, Q4_K_M, and loaded context 12032. Both passed configuration, basic completion, tool call, and tool-result summary on an Apple M5 with 10 cores and 16 GB. This does not imply that every model available through either runtime is Tested. OpenAI and custom OpenAI-compatible adapters remain experimental, optional extensions; Gemini's OpenAI-compatible path is **compatible** but unverified by Dimer's live matrix. Cloud live validation is deferred and does not gate the MVP. Anthropic is unsupported until Dimer has a native Messages API adapter. Confirm the chosen local server is running and the configured model name exists, and record the adapter/model with every live result.

Tool protocol selection is model-specific. Unrecorded models use Dimer's JSON fallback; after a provider/model pair passes the native tool-call conformance check, record `tool_protocol = "native"` beneath that model's provider configuration. Remote endpoints—including Ollama or LM Studio configured on another host—require the explicit `[privacy] allow_cloud_llm = true` opt-in. Custom loopback endpoints are recognized as local, and custom endpoints may declare `data_locality = "local"` or `"cloud"` explicitly.

If a provider call fails, Dimer reports the selected provider, model, configured endpoint, and a targeted remedy. For a local connection failure, start the server and verify `base_url`; for an unknown Ollama model, compare the configured name with `ollama list` and pull it if needed; for malformed native tool arguments, use `tool_protocol = "json"` for that provider/model pair until native conformance is recorded. HTTP provider details and request IDs are shown when useful, with best-effort credential redaction.

Provider responses preserve structured tool turns and available finish, usage, and request metadata. Set `include_raw_diagnostics = true` only while troubleshooting: raw responses are saved with session diagnostics and may contain sensitive context.

Dimer applies best-effort redaction for common PII and credential patterns. This is not guaranteed anonymization, so review sensitive context before using a cloud provider.

## 3. Use the primary chat workflow

```bash
uv run dimer chat
```

Then enter:

```text
/profile examples/sales/sales.csv
/context
Which region contributed most revenue?
/artifacts session
/status
/export
/exit
```

A healthy session should:

1. Save the profile and set the dataset focus.
2. Show short model/tool progress messages rather than raw internal JSON.
3. Ground the answer in computed evidence.
4. Save a session id and any successful SQL query artifact.
5. Avoid creating a chart or markdown report for this ordinary question unless the model has a specific analytical reason to do so.
6. Export the successful SQL calls when the session contains eligible SQL.

Type `/` before pressing Enter to inspect completion. The primary menu is intentionally small:

| Command | Purpose |
|---|---|
| `/help` | Show the same concise catalog |
| `/profile <path>` | Profile and select a dataset |
| `/context` | Summarize workspace context |
| `/provider [name]` | Show or switch provider |
| `/model [name]` | Show or switch model |
| `/status` | Show focus, provider, model, approvals, and session |
| `/artifacts [session\|all]` | Inspect generated evidence and outputs |
| `/trace <target>` | Inspect basic provenance |
| `/export [session-id]` | Export eligible SQL |
| `/exit` | Leave chat |

The contextual aliases `/assumptions`, `/notebook <path>`, `/sessions`, `/replay <session-id>`, and `/quit` remain accepted but are not promoted in the first menu.

## 4. Run deterministic commands

These commands do not need a model provider:

```bash
uv run dimer init
uv run dimer profile examples/sales/sales.csv
uv run dimer context examples/sales
uv run dimer sql examples/sales/sales.csv \
  "SELECT region, SUM(revenue) AS total FROM sales GROUP BY region ORDER BY total DESC"
uv run dimer artifacts
```

Expected direct-SQL behavior:

- the result contains grouped revenue rows;
- the query is saved beneath `.dimer/artifacts/queries/`;
- `dimer artifacts` lists the query.

## 5. Run one-shot analysis

```bash
uv run dimer ask examples/sales/sales.csv \
  "Which region contributed most revenue?" \
  --provider <configured-provider>
```

Use `--model <model-id>` when the provider default is not suitable. One-shot analysis asks before approval-required tools by default. `--auto-approve` is an explicit advanced override that allows unsafe operations without prompting and prints a warning.

The answer renders a structured result containing findings plus any available evidence, artifacts, assumptions, caveats, and suggested next steps. Empty sections are omitted. The exact prose may vary by provider, but numeric claims must come from tool results.

## 6. Request an intentional chart or report

Charts are no longer a side effect of words such as “trend” or “contributed.” Ask explicitly:

```text
Create a chart showing which region contributed most revenue.
```

That request should ask for approval before creating a chart artifact when the focused dataset contains a usable metric and category. For a report, explicitly ask Dimer to save a markdown report; the model may call the approval-required report tool. An ordinary analytical question should not receive a boilerplate report.

## 7. Inspect sessions and replay evidence

```bash
uv run dimer sessions
uv run dimer session <session-id>
uv run dimer artifacts --session <session-id>
uv run dimer trace revenue --session <session-id>
```

Session listing should show the question, tool count, and artifact count. Replay should show the tool log, artifacts, assumptions, and final answer. Trace is heuristic SQL/artifact lineage rather than a full execution graph.

## 8. Verify SQL export

Choose a saved session containing at least one successful SQL tool call:

```bash
uv run dimer export <session-id>
```

Expected output:

- a Python replay script under `.dimer/artifacts/scripts/`;
- a source schema/fingerprint manifest beside it;
- export-time DuckDB replay verification;
- warnings when a source is missing or its schema has drifted.

Export intentionally covers successful SQL calls only. Failed calls, blocked duplicates, and unsupported non-SQL execution are excluded.

## 9. Read notebooks

```bash
uv run dimer notebook examples/retail_ops/march_revenue_exploration.ipynb
uv run dimer ask examples/retail_ops/march_revenue_exploration.ipynb \
  "Explain the analysis and any execution-order problems"
```

Notebook support is read-only. Dimer summarizes cells, detected datasets, notable outputs, execution-order problems, and direction changes; it does not execute a kernel.

## 10. Milestone 1 acceptance check

Run the deterministic gate:

```bash
uv run pytest -q
uv build
```

The current deterministic result is recorded in
[Instructions-status.md](Instructions-status.md). Live-provider checks skip
unless their explicit environment opt-in is present.

Then inspect the reduced surface:

```bash
uv run dimer --help
uv run dimer ask --help
uv tree
```

Verify all of the following:

- `chat` is the documented first workflow.
- No fullscreen UI command appears in CLI help.
- No analysis-mode option appears in `ask --help` (the valid `--model` option remains).
- Slash completion does not advertise `/mode`.
- The runtime dependency tree contains neither Textual nor scikit-learn.
- A normal agent question saves session/query evidence without an automatic chart or report.
- An explicit chart question can still create a chart.
- Chat, one-shot analysis, direct SQL, session listing/replay, and SQL export continue to work.

The deterministic suite uses mock model providers and needs no running model server. Live chat and one-shot acceptance do require a valid provider/model pair, so record both when reporting a result.

## 11. Milestone 2 acceptance check

Inspect the safe-by-default surface:

```bash
uv run dimer ask --help
uv run pytest -q tests/test_approvals.py tests/test_python_exec.py \
  tests/test_privacy_permissions.py tests/test_agent_loop.py
```

Verify all of the following:

- `ask` reports `[default: no-auto-approve]` and labels `--auto-approve` as advanced.
- Python, chart/report creation, and workspace file writes require approval by default.
- Denying an operation leaves the agent able to finish and save the session.
- Python runs in a child process rooted at the workspace; a timeout terminates that worker and the next run starts cleanly.
- Captured Python output is bounded, and outside-workspace file/process/network access is rejected.
- `.dimerignore` applies to scanning, file tools, dataset/notebook inspection, DuckDB registration, and report targets.
- Best-effort redaction removes recognized secret-shaped values from file/Python tool output and persisted session JSON; it is not guaranteed anonymization.
- Answers expose structured findings/evidence/caveats/assumptions/artifacts and omit empty sections.

## 12. Run opt-in local provider conformance

Without its explicit environment opt-in, the normal test suite never contacts a
model provider. To exercise the same completion and tool-round-trip checks
against a running local server, opt in to one provider explicitly and pin the
model plus its configured protocol:

```bash
DIMER_RUN_LIVE_PROVIDER_TESTS=1 \
DIMER_LIVE_OLLAMA_MODEL=granite4.1:8b \
DIMER_LIVE_OLLAMA_TOOL_PROTOCOL=native \
DIMER_LIVE_OLLAMA_RUNTIME_VERSION='Ollama <version>' \
DIMER_LIVE_OLLAMA_CONTEXT_SETTINGS='num_ctx=4096, num_predict=512' \
DIMER_LIVE_OLLAMA_HARDWARE='<hardware and memory>' \
arch -arm64 uv run pytest -q -m live_provider -k ollama \
  tests/test_live_provider_conformance.py
```

```bash
DIMER_RUN_LIVE_PROVIDER_TESTS=1 \
DIMER_LIVE_LMSTUDIO_MODEL=<loaded-model-id> \
DIMER_LIVE_LMSTUDIO_TOOL_PROTOCOL=native \
DIMER_LIVE_LMSTUDIO_RUNTIME_VERSION='LM Studio <version>' \
DIMER_LIVE_LMSTUDIO_CONTEXT_SETTINGS='context_length=8192' \
DIMER_LIVE_LMSTUDIO_HARDWARE='<hardware and memory>' \
uv run pytest -q -m live_provider \
  tests/test_live_provider_conformance.py
```

Override `DIMER_LIVE_OLLAMA_BASE_URL` or `DIMER_LIVE_LMSTUDIO_BASE_URL` only
when the local server uses a non-default loopback endpoint. The tests construct
an isolated configuration, generate only through the selected local provider,
and fail unless configuration, basic completion, tool call, and tool-result
summary all pass. Runtime version, context settings, and hardware are required
before the provider is constructed. After all four stages pass, the test
appends a redacted record containing the provider, exact model identifier,
endpoint locality, protocol, operator metadata, timestamp, and stage statuses to
`project-context/provider-capability-evidence.jsonl`. Set
`DIMER_LIVE_EVIDENCE_PATH` to write that JSONL record elsewhere. Failed,
partially checked, and skipped runs record nothing. A passing local run is
evidence for that provider/model configuration; it does not by itself change
the README support label.

The Ollama live harness applies `num_ctx=4096` and `num_predict=512` to the
actual provider requests. Before its first completion, it uses read-only model
state endpoints to refuse the run if LM Studio has any loaded model or if
Ollama has a resident model other than the selected Granite model. A stopped
LM Studio server counts as unloaded; an ambiguous LM Studio response fails
closed. This preflight does not load, unload, or generate with either runtime.

## Current limits

- Provider quality varies; local models can stop before completing every analytical branch.
- Python isolation uses a bounded child process and Python audit restrictions; it is not an operating-system container.
- Notebook support is read-only.
- Deterministic charts are basic line or categorical bar charts.
- Provenance is JSONL with heuristic SQL lineage.
- Export replays SQL only.
