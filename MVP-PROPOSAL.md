# Dimer MVP Proposal

**Status:** Proposed
**Date:** 2026-08-14
**Purpose:** Define the smallest coherent version of Dimer that is useful, trustworthy, and ready for public iteration.

This proposal supersedes the product direction in `project-context/v0.1-finalization-plan.md`. That document remains a useful record of how the current implementation was completed, but it treats the existing feature set as the release boundary. This proposal instead treats the current implementation as raw material and narrows Dimer around its strongest product idea.

---

## 1. Executive Decision

Dimer should become a **chat-first, local-friendly analytical agent for the terminal**.

Its main interface should be:

```bash
dimer chat
```

Inside chat, users should describe what they want in ordinary language and use discoverable slash commands when they need explicit control. One-shot commands such as `dimer ask` should remain available for repeatable or scripted use, but they are the secondary interaction model.

The MVP should not attempt to be:

- a fullscreen terminal application
- a general coding agent
- a notebook replacement
- an AutoML product
- a pipeline orchestrator
- a business-intelligence dashboard
- a universal abstraction over every AI provider

The MVP is successful when a technical data user can enter a project, connect a tested model, investigate local data conversationally, verify the evidence behind the answer, and preserve or export the useful parts of the analysis.

---

## 2. Product Definition

### Positioning

> Dimer is a terminal-native analytical agent that understands datasets, notebooks, queries, outputs, and assumptions, then turns an exploratory conversation into evidence-backed, reproducible work.

This is more specific than “chat with your data.” Natural-language dataframe and SQL tools are already common. Dimer's distinguishing responsibility is to maintain **analytical context and provenance** while remaining lightweight and comfortable for terminal users.

### Target user

The initial user is a data analyst, analytics engineer, data scientist, or technically comfortable researcher who:

- already works with files, SQL, Python, notebooks, and terminals
- wants to investigate a local data project without setting up a web platform
- wants AI assistance but does not want unsupported conclusions hidden behind fluent prose
- values local model options and clear disclosure when data is sent to a cloud model
- wants useful analysis state to survive beyond one chat response

The MVP does not need to serve non-technical business users.

### Core job to be done

> Help me understand what is happening in this data, show me the computation supporting the answer, remember the path we took, and let me reproduce the useful result.

### Product principles

1. **Evidence before explanation.** Dimer computes before it concludes.
2. **Conversation first, commands when useful.** Slash commands provide control without making users memorize a large CLI.
3. **Progressive disclosure.** Default output is concise; evidence, trace, and artifacts are available when requested.
4. **Safe by default.** Reading and bounded queries can be easy; code execution and writes require meaningful controls.
5. **Local-first, not local-only.** Ollama and LM Studio are the MVP release paths. Preserve the provider seam for hosted providers later, but do not require cloud access or credentials to ship the MVP.
6. **Reproducibility over feature count.** A smaller analysis that can be inspected and replayed is more valuable than a broad demo that cannot be trusted.

---

## 3. The MVP Experience

The primary workflow should feel like this:

```text
install Dimer
    -> open a data project
    -> run `dimer chat`
    -> select or verify a model
    -> ask a question
    -> Dimer inspects and computes
    -> receive a concise answer with evidence
    -> inspect trace or assumptions when needed
    -> resume the session or export the useful analysis
```

### Primary interface: interactive chat

`dimer chat` should:

- start successfully in an initialized or uninitialized project
- explain the minimum next action when configuration is incomplete
- accept a dataset, notebook, directory, or question naturally
- show short tool-progress messages without dumping internal JSON
- ask for approval at the point an unsafe operation is requested
- display a concise final answer, supporting evidence, caveats, and created artifacts
- preserve the session automatically
- provide a described slash-command menu when the user types `/`

The MVP slash-command surface should be small:

| Command | Purpose |
|---|---|
| `/help` | Show the concise command catalog |
| `/focus <path>` | Set or change the current dataset, notebook, or project |
| `/context` | Summarize what Dimer knows about the current focus |
| `/profile [path]` | Inspect schema and important quality warnings |
| `/provider [name]` | Show or change the provider |
| `/model [name]` | Show or change the model |
| `/status` | Show focus, provider, model, and session |
| `/evidence` | Show the computations supporting the latest answer |
| `/trace [target]` | Inspect provenance for the session, column, or artifact |
| `/artifacts` | List useful outputs from the current session |
| `/export` | Export eligible analysis from the current session |
| `/new` | Start a clean session without leaving chat |
| `/resume [session]` | Continue a prior session |
| `/exit` | Leave chat |

`/assumptions` and `/notebook` may remain aliases or contextual commands, but they do not need equal prominence in the first menu. `/mode` should leave the primary interface: the user should ask for SQL, Python, or an explanation naturally, while Dimer chooses the appropriate analytical tool.

### Secondary interface: one-shot commands

Keep these public entry points:

```bash
dimer ask <path> "<question>"
dimer profile <path>
dimer sql <path> "<query>"
dimer context [path]
dimer export [session-id]
dimer doctor
```

One-shot and chat interactions must use the same application services, permissions, provider behavior, session format, and answer contract. The CLI should not contain a second implementation of the agent workflow.

---

## 4. Scope Decisions

### Keep as core

| Capability | MVP decision |
|---|---|
| CSV and Parquet inspection | Keep and harden |
| Excel inspection | Keep if it remains inexpensive, but do not make it release-critical |
| DuckDB queries | Keep; this is the preferred deterministic analysis path |
| Persistent Python analysis | Keep only after execution safety is fixed |
| Workspace context | Keep, with concise summaries and predictable ignore behavior |
| `dimer chat` | Make the primary product |
| `dimer ask` | Keep as the automation-friendly equivalent of chat |
| Sessions | Keep, but simplify how users resume and inspect them |
| Evidence and provenance | Keep; make them central to the answer contract |
| Assumption capture | Keep when assumptions affect an answer; avoid logging trivial noise |
| Read-only notebook awareness | Keep as a meaningful differentiator |
| SQL session export | Keep as the first reproducibility bridge |

### Improve before release

| Area | Required change |
|---|---|
| Provider integration | Replace claimed compatibility with tested compatibility levels |
| Agent loop | Separate provider transport, tool protocol, policy, and answer assembly |
| Approval behavior | Disable automatic approval by default and make consequences clear |
| Python execution | Enforce a real timeout and isolate execution from the Dimer process |
| Answer output | Lead with findings and evidence; avoid mandatory empty sections |
| Artifact creation | Create artifacts intentionally, not automatically after every answer |
| Chat discoverability | Use a small described slash menu and actionable setup errors |
| Installation | Provide a global tool installation path; keep `uv run` for contributors |
| Testing | Add provider conformance tests and fixed analytical evaluations |
| Documentation | Describe verified behavior only and separate user and contributor setup |

### Remove from the MVP product

- The Textual fullscreen TUI and the public `dimer tui` command
- Textual as a runtime dependency
- ML mode, `/mode ml`, and baseline-model training from the primary interface
- General pipeline-production language beyond the existing SQL export
- Multiple interaction modes that ask users to understand Dimer's internal routing
- Automatic report or chart creation when it does not help answer the question
- Provider claims that have not passed a real tool-call round trip

Existing ML code may be retained temporarily in an internal or experimental location while the scope is reduced, but it should not appear in the MVP README, command discovery, acceptance criteria, or product promise. If keeping it makes the architecture or dependencies harder to simplify, remove it and recover it later from Git.

### Explicitly defer

- AutoML and joined-feature modeling
- Notebook execution or kernel-state replay
- Python/dataframe variable-level lineage
- Python, chart, ML, and notebook replay export
- Scheduling, deployment, DAGs, dbt, and Airflow integration
- Fullscreen artifact, schema, or chart browsers
- Advanced visualization systems
- Multi-user collaboration and hosted storage
- A semantic metrics layer

---

## 5. Competitive Context

Current products validate the need but also make generic positioning dangerous:

- [Hex](https://learn.hex.tech/docs/explore-data/notebook-view/notebook-agent), [Deepnote](https://deepnote.com/docs/deepnote-agent), [Zerve](https://www.zerve.ai/notebooks), and [DataLab](https://www.datacamp.com/datalab/home) provide mature browser-based notebook agents.
- [Lumen](https://github.com/holoviz/lumen) and [PandasAI](https://docs.pandas-ai.com/v3/introduction) offer open-source natural-language data analysis capabilities.
- [Vanna](https://vanna.ai/docs) and [Wren AI](https://docs.getwren.ai/) focus heavily on text-to-SQL, databases, and governed semantics.
- [marimo](https://docs.marimo.io/) and [Jupyter AI](https://jupyter-ai.readthedocs.io/en/v3.0/getting-started.html) bring AI into local or notebook-oriented workflows.
- [Open Interpreter](https://github.com/openinterpreter/open-interpreter) and general coding agents already perform ad hoc terminal-based data analysis.

Dimer should therefore avoid competing on “AI can write pandas or SQL.” Its wedge is:

1. terminal conversation as the primary environment
2. explicit analytical evidence, assumptions, and provenance
3. awareness of files, notebooks, queries, and prior outputs as one analytical context
4. first-class local provider support with a clean extension path for hosted providers
5. a direct path from exploration to a reproducible artifact

This positioning should be tested with real users during and after the MVP; it is a hypothesis, not proof of product-market fit.

---

## 6. AI Provider Strategy

The current provider interface is a useful prototype, but the MVP must advertise only behavior that has been verified.

### Supported connection classes

| Provider | MVP status target | Reason |
|---|---|---|
| LM Studio | Tested, first-class | Primary local development path and existing manual evidence |
| Ollama | Tested, first-class | Popular local runtime with a documented native tool protocol |
| OpenAI | Experimental, deferred | Preserve the hosted extension path without making credentials or a live cloud test an MVP gate |
| Custom OpenAI-compatible endpoint | Experimental | Compatibility varies by server and model |
| Gemini OpenAI compatibility | Compatible, deferred | Official compatibility exists, but Dimer still needs conformance evidence before promotion |
| Anthropic | Unsupported until a native adapter exists | The current OpenAI-compatible routing does not implement Anthropic's Messages API |

Provider support should be documented with three labels:

- **Tested:** passes automated contract tests and a live tool-call evaluation
- **Compatible:** uses a supported protocol but has not completed the live matrix
- **Experimental:** may work, with no compatibility guarantee

Local-first is a release strategy, not a permanent exclusion of cloud models. Keep the provider contract protocol-neutral and retain experimental hosted adapters, but promote a hosted provider only after a concrete user need and recorded conformance evidence.

### Provider contract changes

The shared provider response needs to preserve:

- the structured assistant message
- zero or more structured tool calls
- tool-call identifiers needed for the next provider turn
- finish reason
- token usage when available
- provider request ID when available
- the raw response for opt-in diagnostics

Provider transport must be separate from the agent's fallback protocol:

- Prefer native tool calling for a tested provider/model pair.
- Use Dimer's JSON-in-text fallback when native tools are unavailable or a model fails the conformance probe.
- Do not force a provider/model pair with verified native capability through the fallback by default.
- Do not call a method `stream` unless it returns incremental provider output.

### `dimer doctor`

Add one user-facing diagnostic command that checks:

1. configuration can be loaded
2. the selected provider is reachable
3. the configured model exists or can respond
4. a basic completion succeeds
5. a single tool call is produced
6. the tool result can be returned and summarized
7. local versus cloud data handling is explained

Failures must provide actionable remedies, such as the exact missing environment variable, an unreachable local URL, or an unknown model name.

### Provider conformance tests

Create mocked contract fixtures for each transport and opt-in live tests for installed/configured providers. Cover:

- authentication and endpoint construction
- ordinary completion
- native tool call parsing
- assistant tool-call and tool-result round trip
- malformed tool arguments
- timeout and unreachable endpoint
- rate-limit and provider error messages
- usage and finish-reason parsing
- model override and provider switching

### Model evaluation matrix

Use a fixed set of repository fixtures and expected facts. For the MVP, run at least:

1. one capable local model through LM Studio
2. one capable local model through Ollama

A hosted model may join the same matrix later, but it is not an MVP release gate.

Evaluate:

- factual correctness
- successful completion of required tool steps
- unsupported claims
- recovery from one tool error
- early stopping before the question is answered
- latency
- token usage or approximate context size

Pin and record exact provider, model identifier, version when available, context settings, and relevant hardware. Do not describe “LM Studio” or “Ollama” as if the runtime guarantees the behavior of every model it can load.

### Privacy behavior

Local execution and local inference are different promises:

- SQL and Python tools execute locally.
- A local provider can keep model traffic local.
- A cloud provider receives prompts and relevant context, which may include schemas, samples, query results, notebook content, or error output.

Dimer must display this distinction during provider setup and before the first cloud-backed analysis. Environment variables should be the documented default for API keys; direct keys in TOML may remain supported with a warning about file permissions.

---

## 7. Safety Requirements

The MVP must not ship with unrestricted code execution hidden behind an automatically approved chat request.

### Approval policy

- `dimer ask` and `dimer chat` default to approval required for unsafe operations.
- Read-only file metadata, bounded dataset inspection, and bounded DuckDB queries may be pre-approved.
- Python execution, shell execution, file writes, model training, and destructive operations require approval.
- `--auto-approve` may exist as an explicit advanced option with a warning; it must not be the default.
- An approval prompt should show the operation, target, and why it is needed.

### Python and shell execution

- Run generated Python outside the main Dimer process.
- Enforce the configured wall-clock timeout instead of merely accepting a timeout argument.
- Bound captured output and terminate the child process on timeout.
- Limit execution to the chosen workspace unless the user explicitly expands access.
- Keep shell execution out of the model-visible default tool set unless an MVP use case proves it is necessary.

### Data handling

- Respect `.dimerignore` consistently across scanning, prompting, and tools.
- Do not include sample rows in model context unless the privacy configuration permits it.
- Label redaction as best effort rather than guaranteed anonymization.
- Avoid storing secrets or complete provider responses in session artifacts.

These are release requirements, not optional hardening after the MVP.

---

## 8. Architecture Direction

The codebase does not need a rewrite. It needs a few clear seams that make continued iteration predictable.

### Desired dependency direction

```text
CLI / interactive chat
        -> application session service
            -> agent orchestration and policy
                -> provider adapters
                -> tool registry and execution boundary
                -> analytical context and evidence
            -> session and artifact storage
```

UI code should render state and collect input. It should not own agent policy, provider-specific behavior, or duplicate command semantics.

### Priority module changes

1. **Split the agent loop by responsibility.** Extract tool-call decoding, execution policy, repetition/repair policy, and final-answer assembly from the central loop. Preserve behavior with characterization tests before moving code.
2. **Make provider messages lossless.** Keep provider-native structured assistant tool calls through the entire round trip.
3. **Create one session application service.** Chat and one-shot commands should call the same methods for focus, provider/model changes, analysis, approvals, persistence, and export.
4. **Make evidence a first-class result.** The final answer should refer to structured evidence records rather than reconstructing provenance from formatted text.
5. **Put execution behind a boundary.** Python and any shell operations should run through an executor that owns timeouts, working directory, output bounds, and cancellation.
6. **Keep storage formats simple.** JSON/JSONL and filesystem artifacts are sufficient for the MVP; do not introduce a database until concrete queries require it.

### Refactoring rule

Do not pause all product work for an architecture rewrite. Each extraction must support an MVP behavior, retain or improve tests, and leave the application runnable. Prefer vertical changes that pass through UI, application service, agent, tool/provider, storage, and tests.

---

## 9. Installation and First-Run Experience

End users should not need to understand a project virtual environment or prefix every command with `uv run`.

### Installation target

Document a tool installation such as:

```bash
uv tool install dimer
dimer doctor
dimer chat
```

`pipx install dimer` may be documented as an alternative once packaging is verified. `uv sync` and `uv run` remain contributor commands because a development checkout needs an isolated, reproducible environment. The virtual environment protects Dimer's compiled and Python dependencies from conflicting with a user's other projects; it is an implementation detail for installed tools, not something the normal user should manage manually.

### First run

On first use, Dimer should:

1. create or explain its user configuration location
2. detect reachable LM Studio and Ollama endpoints
3. offer concise instructions for starting or installing a supported local runtime when none is available
4. explain local versus cloud context sharing
5. run or recommend `dimer doctor`
6. enter chat once a valid provider/model pair is available

Experimental hosted configuration may remain available as an advanced option, but first-run success must not depend on it.

### Packaging requirements

- Track the dependency lockfile used for development and CI.
- Test wheel construction and installation into a clean environment.
- Test on a supported macOS environment and Linux in CI.
- Ensure architecture-specific compiled dependencies are installed fresh rather than copied between ARM64 and x86_64 environments.
- Remove Textual and, if ML is removed from the release, move scikit-learn out of required runtime dependencies.
- Keep the runtime dependency set as small as the core data formats allow.

---

## 10. Implementation Plan

The milestones below are ordered. Each one ends in a runnable, reviewable state.

### Milestone 0 — Establish repository truth

**Goal:** Produce a trustworthy starting point without losing existing work.

Work:

- inventory every modified and untracked file
- distinguish intended implementation from generated outputs, copied documents, and temporary test evidence
- preserve meaningful current work in reviewable commits
- remove or ignore disposable files such as copied READMEs and raw output captures after verifying they contain no unique information
- recreate the development environment for one native architecture
- run the full deterministic test suite and record the actual result
- verify that the package builds
- mark this proposal as the active roadmap in the README and status document

Exit criteria:

- the working tree is understandable and intentionally clean
- tests pass from a freshly created compatible environment
- a wheel can be built
- no user-authored work was silently discarded

### Milestone 1 — Reduce the public product surface

**Goal:** Make the application describe one coherent product.

Work:

- remove `dimer tui` and the Textual runtime dependency
- remove ML mode and ML promises from normal command discovery and documentation
- remove `/mode` from the primary chat experience
- reduce slash commands to the MVP catalog
- make `dimer chat` the first command shown in the README
- preserve `ask`, `profile`, `sql`, `context`, and `export` as secondary commands
- stop generating reports or charts unless requested or clearly useful
- update help text so experimental internals do not look like release commitments

Exit criteria:

- a new user can understand Dimer's purpose and main workflow from the first README screen
- the runtime no longer depends on Textual
- chat, one-shot analysis, direct SQL, sessions, and export still work
- deferred features are absent from the public MVP promise

### Milestone 2 — Harden the safe analytical core

**Goal:** Make the main workflow safe enough to hand to another user.

Work:

- change automatic approval to opt-in
- classify tools by risk and show precise approval prompts
- move Python execution to a bounded child process with a real timeout
- keep shell execution unavailable to the default agent unless explicitly enabled
- normalize workspace boundaries and `.dimerignore` behavior
- create one structured result containing findings, evidence, caveats, assumptions, and artifacts
- simplify final rendering so empty sections are omitted
- add regression tests for denial, timeout, output bounds, ignored paths, and secret handling

Exit criteria:

- an ordinary chat cannot execute Python, write files, or run shell commands without the configured approval
- a timed-out Python task is terminated without corrupting the Dimer process
- every factual analytical answer exposes its supporting query or computed result
- denied operations leave the session usable

### Milestone 3 — Make provider support honest and testable

**Goal:** Establish two reliable local connection paths while preserving an honest extension seam for future hosted providers.

Work:

- revise the provider message and response types to preserve structured tool turns and metadata
- fix provider-level model selection for LM Studio and Ollama
- make native tool calling capability-based rather than globally assumed or disabled
- keep JSON fallback as an explicit model capability path
- replace fake streaming with real streaming or remove streaming from the MVP interface
- implement `dimer doctor`
- implement mocked transport conformance tests
- implement opt-in live tests for LM Studio and Ollama
- retain mocked conformance coverage for experimental OpenAI-compatible transport; hosted live validation is deferred until promotion is justified
- stop routing Anthropic through the OpenAI chat-completions adapter
- label Gemini and custom endpoints according to verified status

Exit criteria:

- LM Studio and Ollama each complete a simple live tool round trip
- provider/model switching does not retain an incompatible model silently
- provider errors give actionable messages
- the README support matrix matches recorded test evidence
- no unsupported Anthropic claim remains

### Milestone 4 — Validate the analytical product loop

**Goal:** Prove that Dimer answers representative questions through evidence rather than demonstrations tailored to one dataset.

Work:

- define versioned evaluation cases for sales, multi-table retail, and notebook analysis
- include a simple fact, aggregation, multi-step driver investigation, tool-error recovery, and notebook-context question
- define expected facts and unacceptable claims for each case
- run the evaluation matrix across selected LM Studio and Ollama models
- keep the matrix reusable by hosted providers without making them part of the MVP gate
- fix agent behavior only when the change improves the shared evaluation rather than one transcript
- verify session resume, evidence inspection, trace, and SQL export for the same workflows
- record model-specific limitations without hiding them behind fallback prose

ML training is excluded from this milestone.

Exit criteria:

- at least one selected local model passes all core cases
- the second local connection path passes the agreed minimum task threshold
- failed or partial analyses are labeled honestly
- multi-step questions do not stop after one insufficient query
- a successful SQL investigation exports to a runnable script with source and drift warnings

### Milestone 5 — Polish chat and first-run UX

**Goal:** Make the verified core pleasant for the target technical user.

Work:

- add `/focus`, `/new`, `/resume`, and `/evidence` around the simplified session service
- ensure slash completion shows short descriptions and useful path/model candidates
- make progress output compact and suppress raw provider/tool protocol data by default
- make `/status` show only focus, provider, model, approval posture, and session
- guide users from missing configuration to a successful `doctor` result
- add cloud-context disclosure at the first relevant moment
- perform manual terminal checks for narrow windows, scrollback, cancellation, approvals, and error recovery

Exit criteria:

- a new technical user can install, configure, focus a dataset, ask a question, inspect evidence, and resume the session without reading the full manual
- chat output remains readable during a multi-tool investigation
- all slash commands have descriptions and consistent semantics
- one-shot and chat answers use the same result structure

### Milestone 6 — Package and release the MVP

**Goal:** Publish a clean, honest project that is ready for incremental improvement.

Work:

- test `uv tool install` from the built package in a clean environment
- add Linux and supported Python-version CI coverage
- write a short quick start centered on chat
- move detailed verification and contributor instructions out of the main README
- include the provider support matrix, privacy explanation, and known limitations
- include one small end-to-end example with expected evidence
- update `implementations.md` and `Instructions-status.md` from verified results
- choose and document the license, contribution expectations, and security-reporting path before broader promotion
- tag the release only after the complete acceptance checklist passes

Exit criteria:

- a clean machine can install and launch `dimer` without cloning the repository
- documentation contains no unverified provider or feature claims
- CI, deterministic tests, provider contract tests, and the agreed live acceptance run pass
- the repository has no generated analysis data, secrets, temporary output, or duplicate documentation accidentally staged for release

---

## 11. MVP Acceptance Checklist

The MVP is complete only when all of the following are true.

### Installation and setup

- [ ] Dimer installs as an isolated global tool from a built package.
- [ ] `dimer doctor` identifies a working provider/model or gives an actionable remedy.
- [ ] End-user documentation does not require `uv run`.
- [ ] Contributor setup creates a fresh, architecture-compatible environment.

### Product workflow

- [ ] `dimer chat` is the documented and polished primary interface.
- [ ] A user can focus a CSV, Parquet file, notebook, or data-project directory.
- [ ] Dimer can profile the focus and surface important data-quality caveats.
- [ ] Dimer can answer a simple question and a multi-step driver question with computed evidence.
- [ ] Dimer can recover from at least one incorrect tool call or query error.
- [ ] The latest evidence, assumptions, artifacts, and trace are inspectable without reading raw session JSON.
- [ ] A prior session can be resumed.
- [ ] Eligible SQL analysis can be exported and replayed.

### Safety and privacy

- [ ] Unsafe tools are not automatically approved by default.
- [ ] Python execution is isolated, timed out, and output-bounded.
- [ ] Workspace ignores apply consistently.
- [ ] Cloud context sharing is disclosed before use.
- [ ] API keys and secrets do not appear in logs or session artifacts.

### AI reliability

- [ ] LM Studio passes the selected live provider and analytical evaluations.
- [ ] Ollama passes the selected live provider and analytical evaluations.
- [ ] Experimental hosted adapters remain optional, accurately labeled, and non-gating.
- [ ] Provider tool-call round trips are represented losslessly.
- [ ] JSON fallback is tested independently from native tools.
- [ ] Unsupported, compatible, experimental, and tested providers are labeled accurately.

### Code and release quality

- [ ] Deterministic tests pass in CI and a fresh local environment.
- [ ] Core modules have clear ownership and no UI-specific duplication of agent behavior.
- [ ] The package builds and installs cleanly.
- [ ] The README matches the released command surface.
- [ ] Known limitations are explicit.
- [ ] The worktree and published history contain no accidental generated files or secrets.

---

## 12. Success Measures

For pre-release testing, track a small number of useful measures rather than vanity metrics:

- **Setup success:** a target user reaches a successful first answer without developer help.
- **Task success:** percentage of fixed evaluation questions answered correctly and completely.
- **Grounding:** percentage of factual claims supported by a recorded computation or source context.
- **Unsafe-action control:** unsafe operations executed without the required approval; target is zero.
- **Local minimum:** at least one documented local model completes the core workflow at acceptable latency.
- **Recovery:** a tool or provider error produces a useful next action instead of ending the session or inventing an answer.
- **Reproducibility:** an eligible successful SQL investigation replays from its exported script.

Do not add product analytics or telemetry to the MVP merely to collect these numbers. They can be captured through the evaluation suite and structured manual testing.

---

## 13. Git and Publication Strategy

Do not erase the repository history as part of MVP work.

The current history is short and documents real development. A new root commit would make the project look artificially clean while removing useful context and increasing the risk of losing uncommitted work. GitHub users generally care more about the current tree, documentation, and release quality than whether early implementation commits were messy.

Use the following sequence instead:

1. Audit and classify the current dirty worktree.
2. Commit preserved existing work in a clearly labeled checkpoint if it cannot be separated safely.
3. Make the scope reduction a dedicated commit.
4. Make safety, provider, UX, and packaging changes in reviewable commits tied to the milestones above.
5. Squash only noisy commits within a not-yet-published feature branch when it improves reviewability.
6. Tag the first public MVP from a clean, passing tree.

If a history rewrite is still desired immediately before first publication, make that a separate, explicit decision after creating a recoverable tag or backup reference. It is not required for product quality.

---

## 14. Post-MVP Decision Gates

Do not restore deferred features simply because their code already exists. Require user evidence.

### ML

Reconsider ML only when users repeatedly ask to move from investigation into modeling. The next version would need joined-feature construction, temporal splits, leakage defenses, and model-evaluation provenance; the current single-table baseline is not enough to define the product.

### Fullscreen TUI

Reconsider a TUI only when chat users demonstrate workflows that cannot be served by scrollback, slash completion, and opening generated artifacts in their existing tools. A preference for visual polish alone is not sufficient justification for maintaining a second interface framework.

### Broader reproducibility

Extend export from SQL into Python or notebook replay only after the SQL path is used and trusted. Preserve the same standard: source identity, ordered operations, environment assumptions, validation, and explicit drift warnings.

### More providers

Add a provider only when there is a concrete user need and it can join the conformance suite. Provider count is not a product metric.

### Hosted or collaborative Dimer

Do not plan a hosted service until local usage shows that shared sessions, managed credentials, or collaboration are important enough to justify a different privacy and infrastructure model.

---

## 15. Immediate Next Action

Begin with **Milestone 0 only**.

Do not start by rewriting the agent loop or deleting the TUI. First establish a native, reproducible development environment; review the modified and untracked implementation; preserve intended work; remove accidental repository noise; run the full test suite; and build the package. Once the starting state is trustworthy, complete the public-surface reduction in Milestone 1 as the first product change.

This proposal should be revised only when implementation evidence or user feedback changes the underlying product decision. Progress checkboxes belong in `Instructions-status.md`; this document should remain the stable statement of the intended MVP.
