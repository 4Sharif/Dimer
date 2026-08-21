# Phase 7: Basic TUI

**Status:** v1 fullscreen Textual TUI retained, but further TUI work is deferred beyond v0.1. The scrollback `dimer chat` interface is the release priority. The narrow Phase 6 SQL export is complete — see [`phase-6-pipeline-future.md`](phase-6-pipeline-future.md).

## Goal

A clean, friendly, functional terminal UX for analysis — closer to Codex/Claude Code layout than a plain chat REPL. Agent logic stays outside the UI.

## Stack decision

| Surface | Stack |
|---|---|
| `dimer tui` | **Textual** alternate-screen app (primary TUI) |
| `dimer chat` | Rich + prompt_toolkit scrollback REPL (kept) |

Shared: `SessionController` + `EventSink` → panels. No agent logic in UI modules.

Inspiration from `agents/` (patterns only):

| Product | Steal |
|---|---|
| Codex | Bottom pane swaps composer ↔ approvals; UI listens to events |
| Gemini CLI | Simple transcript + composer |
| Pi | Map session events to render units; runtime outside TUI |
| OpenCode | Context strip / side tools panel (minimized) |

## Layout (v1 Textual)

```
┌─ status: mode | provider | model | dataset | session ─────────────┐
├──────────────────────────────┬────────────────────────────────────┤
│ chat (RichLog)               │ tools (RichLog)                    │
│  you / dimer / final answer  │  started / ok / fail rows          │
├──────────────────────────────┴────────────────────────────────────┤
│ composer Input  —or—  approval bar (y/n)                          │
└───────────────────────────────────────────────────────────────────┘
```

## Architecture rule

```
AgentLoop / ToolRouter  →  EventSink  →  TUI widgets (call_from_thread)
```

Agent runs in a Textual worker thread. Approvals block the worker on a `threading.Event` until the UI resolves y/n.

## Implementation status

### v0 (scrollback chat) — done

1. Structured transcript rows — done
2. Status strip — done
3. prompt_toolkit in-pane approvals — done
4. Shared helpers in `dimer/ui/status.py` / console

### v1 (fullscreen Textual) — done 2026-07-13

1. `dimer/ui/session_controller.py` — shared state + slash commands
2. `dimer/ui/tui_app.py` — `DimerTuiApp` panels, worker, approval gate
3. `dimer tui` launches Textual; `dimer chat` remains REPL
4. Tests in `tests/test_tui_app.py`

### Post-v0.1 follow-ups

- Tool argument previews on tool start (query/code snippets)
- Artifact browser panel
- Schema / dataset browser
- Chart path callouts / preview
- Richer slash UX inside TUI

## Out of scope for now

- Porting OpenCode/Codex UI code
- Embedded chart image viewers
- Pipeline export UI (Phase 6)
- Killing the REPL (`dimer chat`)
