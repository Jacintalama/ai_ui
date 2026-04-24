# Harder-Build Test — Shared Meeting Notes Web App

**Date:** 2026-04-17
**Goal:** Stress-test the Ralph Loop pipeline with a multi-step task that can't be one-shotted
**Status:** Task created, awaiting execution

## Background

Yesterday we deployed the decision engine loop (CLARIFY → PLAN → TDD EXECUTE → VERIFY → auto-retry) and the Codex-style preview page on `feat/decision-engine-loop-preview`. We proved the pipeline works end-to-end with a simple habit tracker (~60 seconds, zero retries).

Today Lukas gave new direction in standup:
- Push for longer, more sophisticated apps with plan mode
- Use SQLite for data persistence — "database is part of the code and part of the repo"
- Use Prisma — "AI is really good at writing Prisma"
- Stay on web apps (preview button is a known gap for mobile/desktop)

This document is the test design for that push.

## Goal

Verify the Ralph Loop survives a harder task than the habit tracker. We want to see the full pipeline fire — including at least one auto-retry — on a task that uses SQLite + Prisma + a real backend.

### Success criteria (priority order)

1. Claude uses **Prisma + SQLite** (not Postgres, not raw SQL, not in-memory)
2. The **full pipeline fires**: CLARIFY → PLAN → admin approves → TDD EXECUTE → VERIFY
3. If VERIFY fails once, the **auto-retry** triggers and the loop recovers
4. Final app runs in preview, features work (add meeting, attach note, search, delete)

### Anti-success (still valuable)

If the loop exhausts 3 attempts and fails, we document WHERE and WHY. Failure points become the Monday standup report and the next backlog items.

## The test task

**Task ID:** `16737bca-f408-455e-ba3a-165d44b0a445`
**Mode:** loop (max_attempts=3)
**Assignee:** jacint
**Description:**

> Build a shared meeting notes web app. Use SQLite with Prisma ORM for persistence so all admins see the same notes. Features:
> (1) Add a meeting with title and date.
> (2) Attach one or more notes to a meeting.
> (3) List all meetings chronologically.
> (4) Search notes by keyword.
> (5) Delete a meeting or a single note.
> Single-page web app, vanilla HTML + JS for the frontend, lightweight Node/Express backend with Prisma for the API.

## Architecture (what Claude will build)

```
apps/meeting-notes/
├── package.json          (express, prisma, @prisma/client)
├── prisma/
│   ├── schema.prisma     (Meeting + Note models, 1-to-many)
│   └── migrations/       (auto-generated SQL)
├── dev.db                (SQLite file)
├── server.js             (Express backend, API routes)
├── public/
│   ├── index.html
│   ├── style.css
│   └── app.js            (vanilla JS, fetches /api)
└── tests/
    └── test.js
```

### Prisma schema (the hard part)

```prisma
datasource db {
  provider = "sqlite"
  url      = "file:./dev.db"
}

generator client {
  provider = "prisma-client-js"
}

model Meeting {
  id        Int      @id @default(autoincrement())
  title     String
  date      DateTime
  createdAt DateTime @default(now())
  notes     Note[]
}

model Note {
  id        Int      @id @default(autoincrement())
  body      String
  createdAt DateTime @default(now())
  meetingId Int
  meeting   Meeting  @relation(fields: [meetingId], references: [id], onDelete: Cascade)
}
```

### API routes

| Method | Path | Purpose |
|---|---|---|
| POST | `/meetings` | Create meeting |
| GET | `/meetings` | List meetings (chronological) |
| DELETE | `/meetings/:id` | Delete meeting |
| POST | `/meetings/:id/notes` | Add note to meeting |
| DELETE | `/notes/:id` | Delete note |
| GET | `/notes?q=keyword` | Search notes |

### Runtime flow

```
Browser → /tasks/preview-app/ → Caddy → tasks:9100 → node server.js
                                                       ↓ Prisma Client
                                                      dev.db (SQLite)
```

## Likely failure points (where the loop matters)

| Phase | Likely failure | Loop handles? |
|---|---|---|
| CLARIFY | Too few questions → weak plan | No retry — just bad plan quality |
| PLAN | Missing `npx prisma migrate` step | Admin rejects → re-plan |
| TDD EXECUTE | `prisma migrate` permission / path errors | FAILED → auto-retry with error context |
| VERIFY | Server boots but API returns 500 | TESTS_FAILED → auto-retry |
| PREVIEW | Port 9100 orphan processes | Already fixed (process groups) |

## Measurement plan

### Auto-captured (from DB)
- `tasks.items.attempt_count` — retry count
- `tasks.items.status` — final state
- `tasks.items.built_app_slug` — directory created
- `tasks.executions[].log` — full Claude output per attempt

### Manual (for Monday report)
- Wall-clock time from Clarify → Preview working
- Which phase broke (if any)
- Did Claude actually use Prisma? (grep schema.prisma in built files)
- Is the app usable when opened in preview iframe?
- Qualitative notes on clarify question quality

## What happens after

- **Success (no retries):** Loop is too easy — design a harder task next
- **Success (1-2 retries):** Loop working as designed — PR the branch to main
- **Failure (3 retries exhausted):** Fix the underlying issue, document in backlog, may require prompt tuning in `claude_executor.py`

## References

- Design doc for the loop itself: `docs/plans/2026-04-16-decision-engine-loop-preview-design.md`
- Implementation plan: `docs/plans/2026-04-16-decision-engine-loop-preview-plan.md`
- Standup April 17 (afternoon) — Lukas's SQLite + Prisma direction
