# Dimer Project Status

The active roadmap is [MVP-PROPOSAL.md](../MVP-PROPOSAL.md). [Instructions.md](Instructions.md) is the original design document and [implementations.md](../implementations.md) is the chronological build log; neither expands the current release boundary.

**Last updated:** 2026-08-20

**Current deterministic evidence:** 195 tests pass and 2 opt-in live-provider tests skip in the ARM64 environment. Source compilation, `git diff --check`, both package distributions, archive validation, and independent Standards and Spec reviews pass.

**Remote status:** no changes have been pushed.

## Current milestone

| Milestone | Status |
|---|---|
| Milestone 0 — Repository truth | Complete and preserved in local commits |
| Milestone 1 — Reduce the public product surface | Complete; user accepted |
| Milestone 2 — Harden the safe analytical core | Complete; user accepted |
| Milestone 3 — Make provider support honest and testable | Implementation complete; Tested Ollama and LM Studio configurations recorded; user acceptance pending |
| Later proposal milestones | Not started |

## Current product definition

Dimer is a chat-first terminal agent for evidence-backed analysis of local data. Its main loop is:

1. start `dimer chat`;
2. focus/profile local data;
3. ask a natural-language analytical question;
4. inspect computed evidence, assumptions, caveats, and useful artifacts;
5. resume/replay the saved session or export eligible SQL.

Public secondary commands retain deterministic and automation-friendly paths: `ask`, `profile`, `context`, `sql`, `sessions`, `session`, and `export`. Additional inspection commands include `artifacts`, `assumptions`, `trace`, and `notebook`.

## Milestone 1 implementation

- [x] Removed the public fullscreen UI command and its implementation.
- [x] Removed Textual from runtime dependencies and the lockfile.
- [x] Removed analysis modes from one-shot options, agent context, prompt/tool routing, status, and chat commands.
- [x] Removed baseline model training code, tool registration, aliases, tests, and scikit-learn from runtime dependencies.
- [x] Reduced the primary slash-completion catalog to the currently implemented MVP analysis commands.
- [x] Made `dimer chat` the first workflow in the README.
- [x] Preserved `ask`, `profile`, `sql`, `context`, sessions, and SQL export.
- [x] Stopped deterministic boilerplate report creation.
- [x] Restricted deterministic chart creation to explicit chart/plot/visualization requests.
- [x] Rewrote the README and user manual around the narrowed product.
- [x] Added public-surface contract tests.
- [x] Completed final package build, wheel inspection, and independent standards/spec review.
- [x] User verification and acceptance.

Removed implementation remains recoverable from the pre-MVP local checkpoint `28e6b5e` and subsequent Milestone 0 commits.

## Milestone 2 implementation

- [x] Made automatic approval opt-in for `ask` and the orchestration API; the advanced override is labeled and warned.
- [x] Classified model-visible tools by risk and added approval prompts that show operation, target, reason, and consequence.
- [x] Kept shell execution out of the model-visible registry.
- [x] Moved persistent Python analysis into a per-workspace child process with real timeout termination and recovery.
- [x] Enforced configured Python timeouts over model-supplied arguments and bounded stdout, stderr, and tracebacks.
- [x] Restricted Python file/process/network access to the workspace-oriented execution boundary.
- [x] Applied workspace and `.dimerignore` policy across scanning and model-visible file/data/notebook/report paths.
- [x] Applied best-effort redaction to secret-shaped values in file/Python results and session persistence, with an explicit warning that this is not guaranteed anonymization.
- [x] Added a structured analysis result and omitted empty rendered sections.
- [x] Added regression coverage for approval defaults, denial recovery, timeout, output bounds, ignored paths, and secrets.
- [x] Closed acceptance-review gaps for alternate Python process/filesystem/network operations, direct-CLI ignore enforcement, analytical evidence classification, and best-effort redaction disclosure.
- [x] Passed the full deterministic suite and package build.
- [x] User verification and acceptance.

## Milestone 3 first checkpoint

- [x] Replaced split response content/tool fields with one structured assistant message.
- [x] Preserved native tool-call IDs through assistant/tool-result round trips.
- [x] Normalized and persisted available finish reasons, token usage, and provider request IDs.
- [x] Made raw response diagnostics opt-in and persisted them through the redacting session writer.
- [x] Moved JSON-in-text fallback parsing out of provider transports and kept it in agent policy.
- [x] Removed the unused fake streaming interface.
- [x] Added mocked OpenAI-compatible and Ollama native tool-round-trip transport tests.
- [x] Fixed Ollama and LM Studio provider-level model selection and reset stale chat model overrides on provider switch.
- [x] Stopped routing Anthropic through OpenAI Chat Completions and report it as unsupported.
- [x] Completed checkpoint verification: 146 tests, source compilation, diff check, wheel, and source distribution.
- [x] Completed final standards/spec review with no remaining checkpoint blocker.

## Milestone 3 capability-policy slice

- [x] Made native-tool versus JSON-fallback selection explicit per provider/model pair; unrecorded model overrides use JSON fallback.
- [x] Made generated configuration local-only, enforced the cloud privacy opt-in, and recognized custom loopback endpoints as local.
- [x] Removed unused OpenAI and Gemini wrapper modules while preserving the shared OpenAI-compatible extension adapter.
- [x] Verified 155 ARM64 tests, source compilation, `git diff --check`, and both package distributions before final review.

## Milestone 3 actionable-error slice

- [x] Normalized unreachable endpoints, timeouts, protocol failures, non-success HTTP responses, invalid response envelopes, and malformed native tool arguments into actionable provider errors.
- [x] Included provider, model, configured endpoint, redacted provider detail, and request ID when available; added targeted remedies for local-server startup, unknown Ollama models, authentication, rate limits, server failures, and JSON fallback.
- [x] Preserved actionable failures through agent recovery and saved-session caveats when tool evidence already exists.
- [x] Rendered console messages as literal text so TOML section names such as `[providers.lmstudio]` remain visible rather than being consumed as Rich markup.
- [x] Added mocked error conformance coverage through provider, agent, and one-shot CLI seams for both required local transport paths and the hosted-compatible extension seam.
- [x] Verified 172 ARM64 tests and 57 focused provider/surface tests; source compilation, `git diff --check`, wheel, and source distribution pass.

## Milestone 3 first doctor slice

- [x] Added a shared application diagnostic service used by `dimer doctor`.
- [x] Reported the selected provider, model, endpoint, and local-versus-cloud context handling.
- [x] Verified provider construction and one no-tools basic completion through the normal provider transport seam.
- [x] Returned a failing process status with the existing actionable provider remedy when configuration or completion fails.
- [x] Kept tool-call and tool-result conformance visibly `not checked`; no live provider was contacted and no provider status was promoted.
- [x] Verified 176 ARM64 tests and 61 focused provider/surface tests; source compilation, `git diff --check`, wheel, and source distribution pass.

## Milestone 3 doctor tool-round-trip slice

- [x] Added separate tool-call and tool-result diagnostic stages after the existing basic completion check.
- [x] Exercised the selected model's configured native or JSON fallback protocol without executing a workspace tool.
- [x] Preserved the assistant tool-call turn, returned an initially undisclosed deterministic result through the same protocol-specific message builder as the agent loop, and required a final response that summarizes that exact result without another tool call.
- [x] Added mocked LM Studio/OpenAI-compatible transport coverage for native and JSON diagnostic round trips plus stage-specific failures and CLI rendering.
- [x] Kept downstream stages visibly `not checked` after prerequisite failures; no live provider was contacted and no provider status was promoted.
- [x] Verified 179 ARM64 tests and 64 focused provider/surface tests; source compilation, `git diff --check`, wheel, source distribution, and archive validation pass.
- [x] Completed independent Standards and Spec review re-checks with zero findings.

## Milestone 3 opt-in live-test slice

- [x] Added explicitly gated live conformance tests for Ollama and LM Studio through the shared `dimer doctor` application seam.
- [x] Required an opt-in environment flag and provider-specific model before any live transport is constructed; normal deterministic runs skip both checks.
- [x] Kept live configurations isolated, local-only, model/protocol-specific, and free of real credentials.
- [x] Documented exact commands and the evidence fields required when a live run is eventually authorized.
- [x] Verified 179 ARM64 tests with 2 expected live skips, source compilation, `git diff --check`, both package distributions, archive validation, and independent Standards and Spec reviews; no live provider was contacted and no provider status was promoted.

## Milestone 3 automatic capability-evidence slice

- [x] Added a durable, versioned JSONL record for a completely passing doctor report with provider, exact model, endpoint locality, tool protocol, timestamp, runtime version, context settings, hardware, and stage statuses.
- [x] Required live operator metadata before provider construction and recorded evidence automatically only after all four conformance stages pass.
- [x] Kept evidence content best-effort redacted; failed, partially checked, and skipped runs write nothing.
- [x] Kept provider promotion manual and evidence-driven; no live provider was contacted and no adapter status changed.
- [x] Verified 185 ARM64 tests with 2 expected live skips and 60 focused provider/evidence tests with 2 expected live skips.

## Milestone 3 mocked transport-conformance closure

- [x] Audited the proposal's mocked conformance matrix across the Ollama, LM Studio, and shared OpenAI-compatible transport seams.
- [x] Preserved OpenAI-compatible response-body IDs separately from request-ID headers through provider responses and session diagnostics.
- [x] Added explicit mocked coverage for LM Studio authentication/endpoint construction and unknown-model remedies, shared server-failure guidance, and Ollama per-request model overrides.
- [x] Verified 190 ARM64 tests with 2 expected live skips, source compilation, `git diff --check`, both package distributions, and archive contents; no provider was contacted and no adapter status changed.

## Milestone 3 Ollama live-safety hardening

- [x] Made the isolated Ollama live harness apply `num_ctx=4096` and `num_predict=512` to the provider used by the doctor run rather than recording those values only as operator metadata.
- [x] Added a read-only preflight that refuses Ollama generation while LM Studio has any loaded model or Ollama has a different resident model.
- [x] Kept the preflight non-mutating: it never loads or unloads a model, allows the selected Ollama model to remain resident, treats a stopped LM Studio server as unloaded, and fails closed on ambiguous running-server state.
- [x] Narrowed the documented live command to the Granite native Ollama check and recorded the actual low-memory settings.
- [x] Verified 195 ARM64 tests with 2 expected live skips, source compilation, `git diff --check`, both package distributions, and archive contents. No live generation ran, no evidence was appended, and no provider status changed.
- [x] Resolved the independent Standards review's test-organization findings; the final Standards and Spec re-checks have no remaining findings.

## Milestone 3 recorded local-provider conformance

- [x] Recorded LM Studio 0.4.21+2 with `qwen/qwen3.5-9b`, native tools, Q4_K_M, loaded context 12032, and Apple M5/10-core/16-GB hardware after all four doctor stages passed.
- [x] Recorded Ollama 0.32.15 with `granite4.1:8b`, native tools, `num_ctx=4096`, `num_predict=512`, and the same hardware after all four doctor stages passed.
- [x] Promoted only those evidence-backed local configurations to Tested; no claim is made for every model either runtime can load.
- [x] Kept hosted adapters experimental or compatible, non-gating extension paths.

Milestone 3 implementation is complete and stops here for user acceptance. Milestones 4–6 have not started.

## Verified core capabilities

- Dataset profiling for CSV, Parquet, and Excel, including semantic hints and quality warnings.
- Direct and agent-driven DuckDB analysis over local CSV/Parquet files.
- Workspace-level multi-file table auto-registration.
- Provider abstraction for Ollama, LM Studio, and OpenAI-compatible endpoints.
- JSON tool-call fallback and normalization for common model mistakes.
- Chat and one-shot analysis with provider/model overrides.
- Current-session evidence, artifact, assumption, and quality-note scoping.
- Saved session list/replay.
- Read-only notebook summary and notebook-aware analysis context.
- JSONL analysis lineage with session/column/artifact tracing.
- Verified SQL session export with replay script and source manifest.

## Current agent tools

| Tool | Purpose |
|---|---|
| `inspect_dataset`, `profile_dataset` | Inspect schema and data quality |
| `run_duckdb_query` | Query local CSV/Parquet data and save SQL evidence |
| `run_python` | Perform analysis in a bounded child process; approval-required |
| `summarize_notebook`, `read_notebook` | Read notebook structure, cells, and outputs |
| `save_report` | Save a report when intentionally requested/useful; approval-required |
| `record_assumption` | Preserve an analytical assumption |
| `list_files`, `read_file`, `write_file` | Workspace file operations; writes require approval |

## Known gaps inside the retained scope

- Live conformance is model- and configuration-specific; unrecorded models still default to JSON fallback rather than inheriting Tested status.
- Automatic protocol discovery is not implemented; native-tool capability remains explicit per provider/model pair.
- Local models can stop before completing every planned analytical branch.
- Python isolation is process- and audit-based rather than an operating-system container.
- Notebook support is read-only.
- Deterministic charts are basic line and categorical bar charts.
- Lineage is heuristic SQL/artifact JSONL, not a full execution graph.
- Export replays successful SQL only.
- The planned `/focus`, `/new`, `/resume`, and `/evidence` session-service UX belongs to Milestone 5; Milestone 1 does not pretend those commands already work.

## Historical prototype record

Before the MVP reset, phases 1–7 explored notebooks, lineage, data-quality checks, baseline modeling, SQL export, and a fullscreen interface. Hard testbeds exposed a valuable multi-file SQL path as well as weak modeling/leakage and duplicated-interface directions. The August proposal retained the evidence/session/export core and retired the distracting release branches.

The detailed chronological record remains in [implementations.md](../implementations.md), the original phase design in [Instructions.md](Instructions.md), and the pre-reduction repository classification in [milestone-0-repository-audit.md](milestone-0-repository-audit.md). Git commit `28e6b5e` is the recoverable source checkpoint for removed experiments.

## Milestone 3 checkpoint acceptance

At minimum:

```bash
uv run pytest -q
uv build
uv run pytest -q tests/test_provider_contract.py tests/test_provider_config.py \
  tests/test_json_tool_parser.py tests/test_interactive.py
```

Live tests remain opt-in. Accepted local-provider records are stored in `provider-capability-evidence.jsonl`; reruns require fresh explicit authorization and exact runtime/model/context/hardware metadata.
