# Decision Engine: Loop Mode + Preview Page Design

**Date:** 2026-04-16
**Source:** April 15 + April 16 standups (Lukas, Jacint, Ralph)
**Status:** Approved

## Overview

Three-phase roadmap for the decision engine's build capabilities:

| Phase | Name | Status |
|-------|------|--------|
| A | One-shot build | **DONE** (commit `3d03dcd`) |
| B | Ralph's Loop (multi-step builds) | Design approved, pending implementation |
| C | Preview Page (Codex-style) | Design approved, pending implementation |

## Phase A — One-shot Build (DONE)

Simple transcripts produce a single Claude Code execution that builds an app in one pass.
Validated with a Todoist app (201 lines HTML/CSS/JS, no over-engineering).
Executor prompt hardened with SCOPE RULES to prevent over-building.

---

## Phase B — Ralph's Loop (Multi-step Builds)

### Problem

Tasks too complex to one-shot fail and go back to pending. Admin must manually re-execute. No plan step, no tests, no accumulated context between attempts.

### Schema Changes

New columns on `tasks.items`:

| Column | Type | Default | Purpose |
|--------|------|---------|---------|
| `max_attempts` | INT | 1 | Max auto-retries for loop mode (1 = one-shot) |
| `attempt_count` | INT | 0 | Current attempt number |
| `conversation_history` | JSONB | `'[]'` | Accumulated Q&A pairs for multi-turn NEEDS_INPUT |
| `plan` | TEXT | NULL | Claude-generated plan |
| `plan_status` | TEXT | NULL | `pending_review` / `approved` / `rejected` |
| `built_app_slug` | TEXT | NULL | Directory name under `apps/` for preview |

New status value: `planning` (generating plan), `awaiting_plan_review` (admin reviews plan).

### Execution Pipeline — Superpowers-style (4 phases)

```
CLARIFY → PLAN → ADMIN REVIEW → TDD EXECUTE → VERIFY → retry if fail
(brainstorm)  (write-plans)  (pause)    (red-green-refactor)  (check app)
```

**Phase 1: CLARIFY** (mirrors `superpowers:brainstorming`): Claude asks structured questions one at a time (multiple choice preferred). Each NEEDS_INPUT pauses for admin. CLARIFY_DONE auto-triggers PLAN phase.

**Phase 2: PLAN** (mirrors `superpowers:writing-plans`): Claude generates detailed plan with 4 sections: Business Requirements, Technical Breakdown, Test Specifications, Implementation Steps. PLAN: sentinel parsed and stored. Admin reviews.

**Phase 3: TDD EXECUTE** (mirrors `superpowers:test-driven-development`): Claude follows Red-Green-Refactor for each feature. Write failing test → implement minimal code → verify passes → commit per cycle. COMPLETED/NEEDS_INPUT/FAILED sentinels.

**Phase 4: VERIFY**: Separate Claude subprocess checks the built app end-to-end. TESTS_PASSED / TESTS_FAILED sentinels.

### Retry Logic

On FAILED or TESTS_FAILED with `attempt_count < max_attempts`:
- Increment `attempt_count`
- Re-run TDD EXECUTE with full context (plan + conversation + error)
- Auto-retry (stay in `running`, no manual intervention)

On exhausting attempts: task status → `failed`.

### Multi-turn Conversation History

Every Q&A pair from CLARIFY and NEEDS_INPUT rounds appends to `conversation_history` JSONB:
```json
[
  {"role": "ai", "content": "Which platform? (a) Web (b) Mobile (c) Both", "attempt": 0},
  {"role": "admin", "content": "Web only, vanilla JS"},
  {"role": "ai", "content": "What features? (a) Basic CRUD (b) With categories (c) With due dates", "attempt": 0},
  {"role": "admin", "content": "All three — CRUD, categories, and due dates"}
]
```

Full history included in all subsequent prompts. Supports unlimited back-and-forth across CLARIFY and EXECUTE phases.

### One-shot vs Loop Mode

| | One-shot (default) | Loop |
|--|---|---|
| `max_attempts` | 1 | 3-5 |
| CLARIFY phase | Skipped | Available |
| PLAN phase | Skipped | Required |
| TDD enforcement | No | Yes (red-green-refactor) |
| VERIFY phase | Skipped | Required |
| Auto-retry | No | Yes |

### Prompt Templates (Superpowers-style)

**CLARIFY prompt** (mirrors brainstorming — ask structured questions):
```
Ask ONE clarifying question at a time.
Prefer MULTIPLE CHOICE: "Which platform? (a) Web (b) Mobile (c) Both"
Minimum 2 questions before proceeding.
NEEDS_INPUT: <question>  or  CLARIFY_DONE: <requirements summary>
```

**PLAN prompt** (mirrors writing-plans — detailed 4-section plan):
```
## 1. BUSINESS REQUIREMENTS — what + why + success criteria
## 2. TECHNICAL BREAKDOWN — file paths, components, data flow
## 3. TEST SPECIFICATIONS — tests to write BEFORE code, edge cases
## 4. IMPLEMENTATION STEPS — bite-sized, tests first per feature
PLAN: <complete plan>
```

**TDD EXECUTE prompt** (mirrors test-driven-development — red-green-refactor):
```
For EACH feature: RED (write failing test) → GREEN (minimal code) → REFACTOR
Commit after each cycle. Include approved plan + conversation history.
COMPLETED: <summary>  or  NEEDS_INPUT: <question>  or  FAILED: <error>
```

**VERIFY prompt** (final check):
```
Check files exist, HTML valid, JS no syntax errors, tests pass, app works.
If it works: TESTS_PASSED: <summary>
If broken: TESTS_FAILED: <what's wrong>
```

---

## Phase C — Preview Page (Codex-style)

### Problem

Built apps exist as files in `apps/<slug>/` but users can't see or interact with them. Ralph and Lukas agreed a separate page (not inline in the chat) is needed — like Codex is to ChatGPT.

### New API Endpoints (`routes_preview.py`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/tasks/{id}/files` | List file tree under `apps/{slug}/` |
| GET | `/api/tasks/{id}/files/{path}` | Read file content |
| POST | `/api/tasks/{id}/preview/start` | Start app subprocess |
| POST | `/api/tasks/{id}/preview/stop` | Kill preview process |
| GET | `/api/tasks/{id}/preview/status` | Running? Port? |

### App Runner (`app_runner.py`)

Manages preview subprocesses inside the tasks container:
- One preview at a time (3.8GB RAM constraint)
- Port range: 9100-9110
- Auto-kill after 30 minutes idle
- Detection: `package.json` with `dev` → npm, else `npx serve`

### Preview Page Layout (`static/preview.html`)

```
┌──────────────────────────────────────────────────────────┐
│  ← Back to Tasks    Task: "Build a Todoist app"    ⚡ Run │
├──────────────┬───────────────────────────────────────────┤
│ FILE TREE    │  [Code]  [Preview]  [Tests]  [Logs]      │
│              │                                           │
│ 📁 apps/    │  (selected tab content)                   │
│  └─todo/    │                                           │
│    index.html│                                           │
│    style.css │                                           │
│    app.js    │                                           │
├──────────────┴───────────────────────────────────────────┤
│  Status: ● Running on port 9100  │  Attempt 2/3         │
└──────────────────────────────────────────────────────────┘
```

Four tabs: Code (syntax highlighted), Preview (iframe), Tests (output), Logs (execution history).

### Caddy Routing

```caddyfile
handle /tasks/preview-app/* {
    uri strip_prefix /tasks/preview-app
    reverse_proxy tasks:9100
}
```

### Task Panel Integration

Completed BUILD tasks with `built_app_slug` get a "Preview App" button that opens the preview page in a new tab.

---

## Implementation Order

1. Migration `002_loop_and_preview.sql` (schema changes)
2. Phase B backend: plan/test sentinels, retry loop, conversation history
3. Phase B frontend: plan review modal, attempt badges, loop toggle
4. Phase C backend: file tree API, app runner, preview endpoints
5. Phase C frontend: preview.html page
6. Phase C routing: Caddy preview-app proxy
7. Integration test: fake transcript → plan → build → test → preview

## Constraints

- 3.8GB server RAM — one preview at a time, kill idle processes
- No git on VPS — deploy via SCP
- Tasks container already runs Claude CLI — preview subprocess shares the container
- Preview is experimental — Lukas flagged Phase C as "pretty big task, very tough"
