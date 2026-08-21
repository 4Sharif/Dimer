# Dimer Implementation Log

Entries are chronological history, not a cumulative release promise. The current product boundary is defined by `MVP-PROPOSAL.md` and `project-context/Instructions-status.md`.

## Implemented Features

- [2026-06-06] Project Scaffold: Python package with Typer CLI, Rich console, TOML config loader (`~/.config/dimer/config.toml`), and `.dimer/` workspace initialization via `dimer init`.
- [2026-06-06] Dataset Profiler: `dimer profile` with Pydantic `DatasetProfile` models in `data_context/schema_profile.py`. Supports CSV, Parquet, Excel. Saves JSON to `.dimer/profiles/` and renders Rich tables.
- [2026-06-06] Workspace Context: `workspace_scanner.py` finds datasets, notebooks, SQL, Python, markdown, and artifacts. Exposed via `dimer context`.
- [2026-06-06] DuckDB Executor: `tools/duckdb_exec.py` registers CSV/Parquet as views and returns structured query results. CLI: `dimer sql`.
- [2026-06-06] Artifact & Assumption Tracking: `ArtifactRegistry` and `AssumptionLog` with JSON/JSONL persistence. CLI: `dimer artifacts`, `dimer assumptions`.
- [2026-06-06] Provider Abstraction: `ModelProvider` protocol with Ollama, LM Studio, and OpenAI-compatible implementations. JSON tool-call fallback parser in `providers/base.py`.
- [2026-06-06] Tool Router: Registers inspect/profile/duckdb/python/report/assumption/file tools with risk levels. Executes tools and returns structured results.
- [2026-06-06] Agent Loop: Thought-Action-Observation loop in `agent/loop.py` with structured events, context building from dataset profiles, and session persistence (max 12 iterations).
- [2026-06-06] Interactive CLI: `dimer chat` with `/mode`, `/context`, `/profile`, `/artifacts`, `/assumptions`, `/exit` slash commands via prompt_toolkit.
- [2026-06-06] Persistent Python Session: `tools/python_exec.py` maintains namespace across `run_python` invocations with pandas/matplotlib injected.
- [2026-06-06] Safety: PII redaction, workspace path permissions, process output truncation in `safety/`.
- [2026-06-07] LLM Fixes: Compact agent context via `compact_workspace_summary()` (~1.5KB vs ~54KB before). Ollama: `num_predict`/`num_ctx`, JSON tool fallback by default (`use_native_tools=false`), tool message round-trip. Progress events for model/tool calls. LM Studio auto-appends `/v1`. `dimer sql` saves queries as artifacts.
- [2026-06-07] `.dimerignore`: User-configurable workspace exclusions in `data_context/dimerignore.py`. Gitignore-style patterns, optional negation with `!`. Created by `dimer init`. Built-in ignores only: `.git`, `__pycache__`, `.dimer` (`.dimer/artifacts/` exempt). No hardcoded project-specific path rules. **Verified working** — toggling `agents/` in `.dimerignore` correctly includes/excludes paths in `dimer context` and agent context.
- [2026-06-07] Tests: 18 unit tests (`uv run pytest -q`). Covers profiling, DuckDB, assumptions, artifacts, privacy, permissions, workspace scanner, dimerignore, Ollama message serialization, mocked agent loop.
- [2026-06-13] MVP Agent Bridge: Added forgiving tool-call normalization for aliases and argument aliases, primary dataset injection, DuckDB error surfacing, repeated failure stopping, exact prompt tool schemas, agent-created SQL artifacts, deterministic report saving, basic monthly chart generation, semantic profile hints, and mocked integration tests for the agent contract.
- [2026-06-13] MVP Demo Validation: Manually validated with LM Studio (`qwopus3.5-9b-coder`). The region revenue question recovered from one failed SQL call and answered with computed totals. The March revenue-drop question ran five DuckDB queries, saved query artifacts, saved a markdown report, generated `monthly_metric_trend.png`, and correctly identified that total March revenue increased while average revenue per transaction dropped.
- [2026-06-15] Phase A Trust/UX Pass: Agent final answers now use a deterministic section contract (`Findings`, `Evidence`, `Generated Artifacts`, `Assumptions`, `Data Quality Notes`, `Suggested Next Steps`), final-answer artifacts/assumptions are scoped to the current session, basic deterministic assumptions/data-quality notes are derived from dataset profile hints, `dimer ask` supports `--model` and `--auto-approve/--no-auto-approve`, chat supports `/provider`, `/model`, `/status`, and compact `/context`, and approval-required tools are blocked when auto-approval is disabled.
- [2026-06-15] Phase B/D Foundation: Added deterministic analysis plans, broader quality notes for missing values/duplicates/small samples/row-grain caveats, smarter basic chart selection (monthly line charts and categorical metric breakdown bars), richer query/chart/report lineage metadata in `analysis_state.jsonl`, `dimer trace <target>` plus chat `/trace <target>`, improved DuckDB repair hints with available table/column context, directory focus for workspace-level `ask`, and cloud-provider privacy notices.
- [2026-06-16] Provider Config Cleanup: Direct `api_key` values in config now take precedence over env vars, cloud-provider API-key validation remains in place, and the temporary Google AI Studio aliases/display-name normalization were removed pending a dedicated provider update.
- [2026-07-11] Adaptive Planning Pass: Deterministic plans for drop/why questions now require totals verification, average/per-transaction checks, and segment breakdowns. Successful identical tool calls are blocked and return a reuse hint. After each tool round the agent receives an adaptive checklist update, and plan revisions are recorded in `analysis_state.jsonl`.
- [2026-07-11] JSON Tool-Call Recovery: `parse_json_tool_response` now extracts multiple `tool_call` objects from prose-mixed model content (instead of treating the dump as a final answer). The agent loop also re-parses content when native tool_calls are empty.
- [2026-07-11] Local-Model Stability: Cap to one tool call per turn, raise OpenAI-compatible HTTP timeout to 300s, shorten adaptive checklist nudges, and fall back to tool evidence when the model times out or returns empty content.
- [2026-07-11] March Demo Re-validation: LM Studio run correctly verified March totals rose while avg revenue/txn fell, with sequential SQL + chart + report.
- [2026-07-11] Artifact Browsing: Artifacts are tagged with `session_id`; `dimer artifacts` defaults to recent (supports `--session`, `--type`, `--all`); chat supports `/artifacts`, `/artifacts session`, `/artifacts all`.
- [2026-07-11] Phase 2 Complete: Interactive approvals for risky tools, session list/replay CLI+chat commands, and clearer `/mode` UX. Phase 2 marked complete in status.
- [2026-07-11] Phase 3 Start: Read-only notebook summarization with dataset/variable detection, execution-order warnings, direction-change hints, `dimer notebook`, `/notebook`, and `summarize_notebook`/`read_notebook` tools.
- [2026-07-11] Phase 3 Complete: Notable notebook outputs (dataframe/html/image/error), compact notebook context in agent asks, `ask`/chat notebook focus, and notebook-aware analysis plans.
- [2026-07-12] Phase 4 Start: Analysis events now store `parent_ids`, `columns`, and `transforms`. SQL queries get heuristic lineage (source/filter/group_by/join/order/aggregate). Charts and reports link to parent query events via `source_artifacts`. `dimer trace` / `/trace` expands along parent and child edges instead of only substring-matching JSONL.
- [2026-07-12] Phase 4 Chain UX: SQL events parent-link to dataset inspect/profile events; inspect/profile record dataset paths + columns; `format_trace` prints a readable `dataset → sql → chart/report` Lineage summary above the event list.
- [2026-07-12] Phase 4 Complete: Column-centric `dimer trace <column>` / `/trace` prefers exact column matches, prints usage roles (schema/filter/aggregate/plotted), and keeps parent-linked chains. Phase 4 marked complete; Python variable graphs deferred.
- [2026-07-12] Session-scoped trace: `dimer trace` defaults to the latest session (`--session`, `--all`); chat supports `/trace`, `/trace all`, `/trace session <id>`; chart/report parent linking prefers same-session artifacts so reused filenames do not pull old history.
- [2026-07-12] Data-quality start: Added `data_context/data_quality.py` for grain, metric missingness, negatives/zeros/outliers, and cardinality checks. Profiles and agent Data Quality Notes now use these findings. Tightened repo `.dimerignore` so `dimer context` hides package/tests/docs noise.
- [2026-07-12] Data-quality complete (v1): Schema drift vs last saved profile, multi-dataset schema overlap/type checks, and question-aware aggregate caveats (totals/averages/trends). Ready for Phase 5 ML mode.
- [2026-07-12] Phase 5 Start: Added `train_baseline_model` (sklearn Pipeline: impute/scale/one-hot + LogisticRegression/Ridge), train/test split, metrics, feature importance, leakage warnings, and model artifacts under `.dimer/artifacts/models/`. Wired `ml` mode (`/mode ml`, `ask --mode ml`), ML analysis plan, tool aliases, and approval-required execution.
- [2026-07-12] Phase 5 Complete: Live LM Studio validation passed (revenue regression + region classification). Chat slash commands strip leading whitespace. After successful train+report, adaptive checklist forces a final answer instead of re-profiling. Phase 5 marked complete.
- [2026-07-12] Hard testbeds: Added `examples/retail_ops/` and `examples/saas_churn/` (+ `examples/_generate_testbeds.py`). Manual LM Studio runs showed: workspace `ask .` DuckDB table registration fails; ML mode leaks via `days_to_observed_churn` / `churn_reason_code`; join-heavy analysis can work; notebook summarize works. **Pre-Phase-6 reliability pass required before Phase 6** — details in `project-context/Instructions-status.md`.
- [2026-07-13] Pre-Phase-6 reliability (partial): Workspace DuckDB auto-registers all CSV/Parquet when `data_paths` omitted; ML auto-excludes post-outcome leak columns (`churn_reason_*`, `days_to_*churn`); reject/nudge invalid tool-call JSON finals; empty session `trace` hints `--all`. ML joined-feature assembly still deferred.
- [2026-07-13] Pre-Phase-6 closed: A live re-check confirmed DuckDB workspace queries + honest ~60% churn ML. Tightened malformed tool-call final fallback (missing `tool_name`). Gate opened for Phase 6; ML feature-join remains optional known gap.
- [2026-07-13] Phase 6 held: Pipeline/export deferred in favor of Phase 7 basic TUI. First-slice export design saved at `project-context/phase-6-pipeline-future.md`.
- [2026-07-13] Phase 7 start: Basic TUI on existing chat — status strip, structured user/assistant/tool transcript rows, prompt_toolkit in-pane approvals, `dimer tui` alias. Plan: `project-context/phase-7-tui-plan.md`.
- [2026-07-13] Phase 7 v1: Fullscreen Textual TUI (`dimer/ui/tui_app.py`) with chat/tools panels, status header, worker-thread agent runs, y/n approval gate. Shared `SessionController`. `dimer tui` launches Textual; `dimer chat` remains scrollback REPL. 82 tests.
- [2026-07-15] v0.1 Chat Polish: `dimer chat` now uses prompt_toolkit slash completion with command descriptions and contextual options for modes, artifact scopes, model reset, and trace scope. `/help` uses the same concise command catalog.
- [2026-07-15] v0.1 SQL Session Export: Added `dimer export [session_id]` and chat `/export`. Successful, non-duplicate DuckDB calls are exported from saved session JSON into a standalone replay script plus schema manifest, verified against current source files, and registered as a session-scoped script artifact.
- [2026-07-15] v0.1 Deterministic Validation: `uv run pytest -q` passes with 89 tests; `git diff --check`, CLI initialization/profile/context/SQL, and the new command help surfaces pass. Ollama and LM Studio were unavailable locally, so fresh live-model acceptance remains pending.
- [2026-08-15] Pre-MVP Preservation Checkpoint: Preserved the complete Phase 3–7 worktree—including TUI, ML baseline, reliability fixes, chat polish, and SQL export—in local commit `28e6b5e` before beginning scope reduction. No remote changes were made.
- [2026-08-15] MVP Milestone 0 Complete: Made the active proposal, project context, implementation log, lockfile, example evaluation fixtures, and repository ignore configuration trackable; removed exact duplicate documents and summarized raw run captures; recorded the classification in `project-context/milestone-0-repository-audit.md`; recreated a clean ARM64 CPython 3.13 environment from `uv.lock`; passed 89 tests; and built `dist/dimer-0.1.0-py3-none-any.whl`.
- [2026-08-15] MVP Milestone 1 Surface Reduction: Removed the fullscreen UI command/implementation and Textual runtime dependency; removed analysis modes, baseline-model training, and scikit-learn; narrowed chat completion; made chat the README's primary workflow; stopped automatic boilerplate reports and implicit deterministic charts; retained evidence, sessions, direct/agent SQL, and verified SQL export. The narrowed suite passes 77 tests; the wheel is clean; independent standards/spec findings were resolved; user acceptance is the remaining gate.
- [2026-08-15] MVP Milestone 2 Safe Analytical Core: Made unsafe approval opt-in; added precise tool-risk prompts; moved persistent Python into a per-workspace child process with configured timeout termination, bounded output, recovery, and audit-based workspace/process/network restrictions; enforced `.dimerignore` across model-visible tools; restricted pre-approved DuckDB to bounded read-only workspace-table queries; redacted secret-shaped values before provider round trips and durable persistence; required approval for reports and charts; and introduced structured findings/evidence/caveats/assumptions/artifacts with empty-section omission. The suite passes 117 tests and the wheel builds successfully; user acceptance is the remaining gate.
- [2026-08-15] MVP Milestone 2 Acceptance Hardening: Closed final review gaps by rejecting additional Python process, network-socket, directory-discovery, native-library, hard-link, FIFO/device-node, and filesystem-mutation operations; preserving lexical `.dimerignore` checks across direct profile/SQL/notebook commands and symlink resolution; requiring relevant computation over the requested metric with the requested aggregation/ranking/trend operation for analytical claims; and documenting redaction as best effort rather than guaranteed anonymization. The ARM64 suite passes 139 tests, source compilation succeeds, and both wheel and source distribution build successfully; user acceptance remains the gate before Milestone 3.
- [2026-08-15] MVP Milestone 3 Provider Contract Checkpoint: Replaced split provider responses with structured assistant messages; preserved native tool-call IDs plus finish, normalized usage, request, and opt-in raw diagnostics through session persistence; separated provider-native parsing from agent-owned JSON fallback; removed fake streaming; fixed provider-level local model selection and chat provider-switch resets; stopped treating Anthropic as OpenAI-compatible; and added mocked native plus JSON-fallback round-trip tests. No live provider status was promoted. The ARM64 suite passes 146 tests, source compilation and diff checks pass, and both wheel and source distribution build successfully; user acceptance gates the next Milestone 3 slice.
- [2026-08-15] Local-First MVP Decision: Made Ollama and LM Studio the required MVP provider paths and removed credentialed hosted-provider validation from the release gate. The provider contract and experimental OpenAI-compatible adapters remain in place so cloud support can be promoted later after concrete demand and recorded conformance evidence. This changes roadmap, onboarding, and acceptance criteria without requiring a provider-layer rewrite.
- [2026-08-15] MVP Milestone 3 Capability Policy: Replaced the provider-wide native-tools flag with explicit provider/model tool-protocol capabilities, defaulted unrecorded models to JSON fallback, and made Ollama serialize whichever tool policy the agent selects. Generated configuration now contains only Ollama and LM Studio, remote inference requires an enforced privacy opt-in and pre-analysis disclosure, custom loopback endpoints are recognized as local, and unused OpenAI/Gemini wrapper modules were removed without removing the shared OpenAI-compatible extension adapter. No live provider status was promoted. The ARM64 suite passes 155 tests; source compilation, diff checks, and both package distributions pass. User acceptance gates the next Milestone 3 slice.
- [2026-08-15] MVP Milestone 3 Actionable Provider Errors: Added one shared HTTP transport boundary that turns unreachable endpoints, timeouts, protocol failures, rejected requests, invalid envelopes, and malformed native tool arguments into provider/model/endpoint-specific remedies. Complete error messages are best-effort redacted so credential-bearing endpoints, provider details, and request IDs remain safe through agent evidence recovery and CLI output; console messages preserve literal TOML section names. Mocked error conformance covers Ollama, LM Studio, the OpenAI-compatible extension seam, agent recovery, and CLI rendering. No live provider status was promoted. The ARM64 suite passes 172 tests and focused provider/surface verification passes 57 tests; source compilation, diff checks, wheel, and source distribution pass.
- [2026-08-20] MVP Milestone 3 First Doctor Slice: Added `dimer doctor` through a shared application diagnostic service. It loads and constructs the selected provider, reports provider/model/endpoint/locality, runs one no-tools basic completion through the existing transport, preserves actionable provider failures with a non-zero exit, and explicitly leaves tool-call/tool-result conformance unchecked. No live provider was contacted and no provider status was promoted. The ARM64 suite passes 176 tests and focused provider/surface verification passes 61 tests; source compilation, diff checks, wheel, and source distribution pass.
- [2026-08-20] MVP Milestone 3 Doctor Tool Round Trip: Extended `dimer doctor` with separate tool-call and tool-result stages through the shared provider/application/CLI seams. The diagnostic follows the selected model's native or JSON fallback protocol, validates one deterministic echo call, returns an initially undisclosed result through the same message builder as the agent loop, and requires an exact final summary without another tool call. Stage failures remain actionable and exit non-zero; later stages stay `not checked` after a prerequisite failure. No live provider was contacted and no provider status was promoted. The ARM64 suite passes 179 tests and 64 focused provider/surface tests; source compilation, diff checks, wheel, source distribution, and archive validation pass. Independent Standards and Spec reviews pass with zero findings.
- [2026-08-20] MVP Milestone 3 Opt-In Live Tests: Added environment-gated Ollama and LM Studio conformance tests that run the shared doctor completion and tool-result round trip against an explicitly selected local model/protocol. Normal runs skip before provider construction, configurations contain no real credentials, non-loopback overrides fail before provider construction, and the guide lists the runtime/model/protocol/context/hardware fields operators must record alongside an eventual result. Automatic evidence recording remains outstanding, no provider status was promoted, and no live provider was contacted. The ARM64 suite passes 179 tests with 2 expected live skips; source compilation, diff checks, wheel, source distribution, archive validation, and independent Standards and Spec reviews pass with zero remaining findings.
- [2026-08-20] MVP Milestone 3 Automatic Capability Evidence: Added versioned, redacted JSONL evidence for completely passing doctor conformance runs. Opt-in live checks now require nonblank runtime version, context settings, and hardware before provider construction, then automatically append the exact provider/model/protocol/locality and four stage statuses only after a full pass. Failed, partial, and skipped runs write nothing; provider promotion remains manual. No live provider was contacted and no status was promoted. The ARM64 suite passes 185 tests with 2 expected live skips; 60 focused provider/evidence tests pass with 2 expected live skips.
- [2026-08-20] MVP Milestone 3 Mocked Transport Closure: Audited the proposal's conformance matrix, preserved OpenAI-compatible response-body IDs separately from request-ID headers through session diagnostics, and added explicit mocked checks for LM Studio endpoint/authentication and unknown-model behavior, shared server failures, and Ollama model overrides. No live provider was contacted and no status was promoted. The ARM64 suite passes 190 tests with 2 expected live skips; source compilation, diff checks, both package distributions, and archive validation pass.
- [2026-08-20] MVP Milestone 3 Ollama Live-Safety Hardening: Made the isolated live Ollama configuration apply `num_ctx=4096` and `num_predict=512`, added read-only refusal checks for loaded LM Studio models and unrelated resident Ollama models before doctor generation, and narrowed the operator command to the Granite native check. The preflight does not mutate runtime state, no live generation or evidence recording occurred, and provider status remains unchanged. The ARM64 suite passes 195 tests with 2 expected live skips; source compilation, diff checks, both package distributions, and archive validation pass. Independent Standards and Spec reviews pass with no remaining findings.
- [2026-08-20] MVP Milestone 3 Live Local-Provider Acceptance: Recorded complete four-stage native doctor passes for LM Studio 0.4.21+2 with `qwen/qwen3.5-9b` (Q4_K_M, loaded context 12032) and Ollama 0.32.15 with `granite4.1:8b` (`num_ctx=4096`, `num_predict=512`) on an Apple M5 with 10 cores and 16 GB. Promoted only those evidence-backed configurations to Tested, retained model-specific fallback behavior and hosted-adapter labels, and marked Milestone 3 implementation complete pending user acceptance. No credentials were used and nothing was pushed.

---

## Historical Pre-MVP State (superseded by Milestone 1)

This section records what the checkpoint at commit `28e6b5e` contained. References to removed modes, baseline training, or a fullscreen interface below are historical evidence only and do not describe the current MVP.

### What works

| Component | Status |
|---|---|
| `dimer init`, `profile`, `context`, `sql` | Working |
| `dimer artifacts` (from manual `dimer sql`) | Working |
| `dimer assumptions` | Working (empty until agent calls `record_assumption`) |
| `pytest` | Passing (89 tests) |
| Artifact browsing | Recent-by-default; `--session` / `/artifacts session` when tagged |
| Session replay | `dimer sessions` / `dimer session <id>` / `/sessions` / `/replay` |
| Approvals | Interactive prompts in chat and `ask --no-auto-approve` |
| `.dimerignore` | Working — user verified hide/unhide of `agents/` |
| LLM simple Q&A (`dimer ask` / `chat`) | Working when answer is in dataset profile context |
| LM Studio + `qwopus3.5-9b-coder` | Working in manual MVP validation (re-validated 2026-07-11) |
| Agent SQL execution | Working with tool/argument normalization and primary dataset injection |
| Agent-created artifacts | Working for SQL queries, deterministic reports, and basic monthly trend charts |
| Agent final-answer contract | Working with deterministic sections and current-session artifact/assumption scope |
| Primary chat UX | Scrollback REPL: described slash completion, status strip, structured transcript, and in-pane approvals |
| Fullscreen TUI | Textual `dimer tui`: chat + tools panels, status, approval gate |
| SQL session export | `dimer export [session_id]` / `/export`: standalone DuckDB script + schema manifest + replay verification |
| Provider/model runtime controls | `--model` for `ask`; `/provider` and `/model` in chat |
| Analysis planning and trace | Phase 4 complete + session-scoped default: parent-linked lineage, SQL transforms, column usage, `dimer trace` / `/trace` default to latest session (`--all` for history) |
| Duplicate successful queries | Blocked; agent is nudged toward remaining checklist items |
| Chart selection | Basic monthly trend line charts and categorical breakdown bar charts |
| Provider configuration | Direct config-file API keys and env-var API keys are supported |
| Notebook awareness | Read-only summarize/read, notable outputs, ask/chat notebook focus |
| ML baseline tool + `ml` mode | Complete for single-file demos; hard `saas_churn` run showed leakage blind spot |
| Multi-table workspace asks | Partial — context/profile OK; DuckDB registration for `ask .` broken (retail_ops) |

### What does NOT work yet

| Component | Status |
|---|---|
| Provider/model coverage | LM Studio re-validated; Ollama and cloud providers should still be checked with live models |
| Fully adaptive hypothesis search | Checklist + duplicate blocking landed; deeper statistical driver search still future work |
| Python variable lineage | Deferred past Phase 4; SQL/dataset/artifact lineage is what Phase 4 covers |
| Advanced AutoML | Out of scope; baseline sklearn only |
| `dimer train` CLI | Deferred; use `ask --mode ml` / `/mode ml` |
| Workspace DuckDB multi-file registration | Fixed 2026-07-13 — omit `data_paths` → auto-register workspace CSV/Parquet |
| ML leakage refusal / joined feature train | Leak columns auto-excluded; **joined feature assembly still deferred** |

### Previous root cause: tool name/argument mismatch

The model called tools with wrong names/args. Example from session `195108`:

```json
{"type": "tool_call", "tool_name": "duckdb", "arguments": {"sql": "SELECT ... FROM 'examples/sales/sales.csv'"}}
```

Dimer expects:

```json
{"type": "tool_call", "tool_name": "run_duckdb_query", "arguments": {"query": "SELECT ...", "data_paths": ["examples/sales/sales.csv"]}}
```

Registered tool names in `agent/tool_router.py`: `run_duckdb_query`, `run_python`, `profile_dataset`, `inspect_dataset`, `save_report`, `record_assumption`, `list_files`, `read_file`, `write_file`.

This has been addressed with tool alias normalization, argument normalization, primary dataset injection, and repeated-failure stopping. Mocked integration tests now cover these cases.

`dimer sql` CLI works independently, and the agent-to-tool bridge is now validated for the MVP sales workflow.

---

## Current Architecture Summary

```
CLI (Typer) → Agent Loop → Provider (Ollama/LM Studio/etc.)
                ↓
           Tool Router → tools/ (duckdb, python, profile, ...)
                ↓
           data_context/ (profiles, workspace scan, assumptions, artifacts)
                ↓
           .dimer/ storage (sessions, profiles, artifacts, analysis_state.jsonl)
```

Key files:
- `dimer/cli.py` — all commands
- `dimer/agent/loop.py` — agent orchestration
- `dimer/agent/tool_router.py` — tool registry and execution
- `dimer/agent/prompts.py` — analysis system prompt and tool protocol
- `dimer/providers/ollama.py` — Ollama provider
- `dimer/data_context/analysis_state.py` — analysis events, parent links, graph-aware trace
- `dimer/data_context/sql_lineage.py` — heuristic SQL filter/transform/column extraction
- `dimer/data_context/data_quality.py` — grain/missingness/drift/overlap quality checks
- `dimer/ui/session_controller.py` — scrollback chat state + slash commands
- `~/.config/dimer/config.toml` — provider/model config

---

## Next Priority

1. **Accept Milestone 3** — review the recorded LM Studio and Ollama configurations and provider-status wording
2. **Keep later milestones gated** — do not begin analytical evaluation, session UX, or release work until Milestone 3 is accepted
3. **Preserve evidence discipline** — new provider/model claims require their own recorded conformance; hosted promotion remains optional and evidence-driven

Reference: original spec in `project-context/Instructions.md`, live status in `project-context/Instructions-status.md`, and active scope in `MVP-PROPOSAL.md`.
