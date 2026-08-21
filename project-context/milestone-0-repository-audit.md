# Milestone 0 Repository Audit

**Date:** 2026-08-15
**Starting commit:** `fa99b74`
**Preservation checkpoint:** `28e6b5e` (`checkpoint: preserve pre-MVP implementation`)
**Remote changes:** None. The checkpoint is local only.

This audit classifies the repository state that existed before the MVP scope reduction. It exists so later milestones can remove public features without losing the implementation that preceded the new roadmap. The Git-visible starting inventory came from `git status --short`; every modified and untracked entry from that inventory is named in the preserved, authored, or disposable sections below. Pre-existing ignored local directories are classified separately because they were not candidates for the checkpoint commit.

## Preserved pre-MVP implementation

The following modified and untracked implementation files were verified together with the 89-test deterministic suite, then preserved in checkpoint commit `28e6b5e`:

- `README.md`
- `pyproject.toml`
- `dimer/agent/loop.py`
- `dimer/agent/prompts.py`
- `dimer/agent/tool_router.py`
- `dimer/cli.py`
- `dimer/data_context/analysis_state.py`
- `dimer/data_context/workspace_scanner.py`
- `dimer/pipeline/__init__.py`
- `dimer/pipeline/export_session.py`
- `dimer/storage/artifacts.py`
- `dimer/tools/ml_baseline.py`
- `dimer/ui/approvals.py`
- `dimer/ui/console.py`
- `dimer/ui/interactive.py`
- `dimer/ui/session_controller.py`
- `dimer/ui/status.py`
- `dimer/ui/tui_app.py`
- `tests/test_agent_loop.py`
- `tests/test_interactive.py`
- `tests/test_ml_baseline.py`
- `tests/test_pipeline_export.py`
- `tests/test_reliability_pass.py`
- `tests/test_tui_app.py`

This checkpoint intentionally preserves the TUI, ML baseline, reliability pass, chat polish, and SQL export before Milestone 1 changes the public product surface.

## Authored project material retained for version control

The original `.gitignore` hid several files that the project treats as source material. Milestone 0 makes the following categories trackable:

- Repository configuration: `.gitignore`, `.dimerignore`, `uv.lock`
- Active roadmap and history: `MVP-PROPOSAL.md`, `implementations.md`
- Project context: `project-context/Instructions.md`, `project-context/Instructions-status.md`, `project-context/using-dimer.md`, `project-context/v0.1-finalization-plan.md`, `project-context/phase-6-pipeline-future.md`, and `project-context/phase-7-tui-plan.md`
- Evaluation fixtures: `examples/_generate_testbeds.py`, the `examples/sales/`, `examples/retail_ops/`, and `examples/saas_churn/` source fixtures, plus `tests/fixtures/sales_exploration.ipynb`

The example datasets are small, deterministic repository fixtures used by the documented evaluation plan. They are not user data.

## Disposable files removed

- `README copy.md` was byte-for-byte identical to `README.md`.
- `implementations copy.md` was byte-for-byte identical to `implementations.md`.
- `output1.txt`, `output2.txt`, and `output3.txt` were raw terminal captures produced with LM Studio and `qwopus3.5-9b-coder`. Their unique conclusions, provider/model identity, failures, and follow-up validation were already summarized in `project-context/Instructions-status.md` under the hard-testbed and reliability sections.
- `examples/saas_churn/churn_baseline_report.md` was a generated model-run artifact whose relevant leakage findings and corrected result were already recorded in the status document.

Root `output*.txt`, root `* copy.md`, and the known generated churn report are now ignored so the same repository noise is not accidentally staged again.

## Local-only material retained

The following material remains on disk and ignored; Milestone 0 did not delete it:

- `agents/`: copied reference agent repositories, including nested Git histories
- `notes/Why AI Agents Struggle More With Data Science Code Than Software Engineering Code _ DataCamp.pdf`: the project-inspiration article
- `notes/session-20260607-194309.json`, `notes/session-20260607-195004.json`, and `notes/session-20260607-195108.json`: early generated session captures
- `notes/test.md`: an early exploratory run capture
- `notes/charts.png`: an exploratory generated chart
- `.dimer/`: local Dimer sessions, profiles, and generated artifacts
- `.venv/`, `.pytest_cache/`, `__pycache__/`, `.DS_Store`: local environment and cache data
- `ss.png`: a local screenshot ignored by the existing image rule

## Environment evidence

The inherited environment mixed an x86_64 process with ARM64 compiled dependencies. The initial test run failed during collection with incompatible-architecture imports from NumPy and `pydantic-core`.

The old environment was moved, without deletion, to:

```text
/private/tmp/dimer-venv-x86-backup-20260815
```

A fresh ARM64 environment was created from the checked `uv.lock` with CPython 3.13.0. The deterministic suite then completed successfully:

```text
89 passed in 5.35s
```

The first cold-environment run also passed in 48.90 seconds; the value above is the final Milestone 0 rerun.

Because the Codex host shell itself runs under Rosetta, the successful commands explicitly selected the environment's native ARM64 architecture:

```bash
arch -arm64 uv sync --extra dev --locked
arch -arm64 uv run pytest -q
```

The package wheel also built successfully:

```text
dist/dimer-0.1.0-py3-none-any.whl
```

No live provider acceptance was performed in Milestone 0; that remains a later roadmap milestone.
