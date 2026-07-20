# Enhance regression guard: revert an edit that breaks what worked

Date: 2026-07-17
Status: Approved direction (Jacint, 2026-07-17: roll back automatically).

Origin: `docs/ai-coding-market-scan-2026-07-15.md` opportunity 3 (client's pick),
sharpened by the 2026-07-17 engineering research pass.

## Why

Cascade regressions are the category's top unsolved failure mode: an edit
quietly breaks something that used to work. Today IO can ship exactly that. The
AutoFix loop (`_run_autofix`) answers *"does the app load now?"* but never
*"does it still do what it did before?"*, so an enhance that trades a working
feature for a broken one passes.

Three findings from the 2026-07-17 research converge on the same rule:

- **Jules mandates a read-only check after every state-mutating action** to
  confirm the action "had the intended effect", not merely that it applied.
  Claude Code explicitly forbids that re-read because its harness proves the
  write landed. Since IO drives the Claude Code CLI as a subprocess, it
  **inherits the weaker guarantee**: tool failure proves the file saved and says
  nothing about whether the app still works. That gap is exactly this failure
  mode.
- **Runtime signals belong in the loop as evidence**, not as a one-shot pass.
  (Lovable exposes console logs and network requests as queryable tools.)
- Nothing published describes how any builder prevents regressions, and no
  vendor publishes a fix-loop budget. There is no prior art to copy here.

This was **not buildable before 2026-07-16**. Auto-rollback needs version
history, and 43 of 47 prod apps had none until the commit sweep shipped
(`2026-07-16-app-history-commit-sweep-design.md`). That fix is the enabling
dependency.

## Correction to a stated premise

The research brief described `app_smoke.py` as a "does the page load" check.
That is **wrong**, verified by reading the file: it already registers
`page.on("pageerror")`, `page.on("console")` filtered to `console.error`, and
`page.on("requestfailed")` before `goto`, plus the main-response status
(`app_smoke.py:45-75`). `_run_autofix` already scopes fix passes to exactly
those errors.

So the gap is **not** "capture errors". The smoke check is good. The gap is that
its output is only ever compared against nothing. This spec adds the comparison.

## Design

New module `app_regression.py`, following the established one-purpose-per-file
convention (`app_smoke.py`, `app_git.py`, `app_docs.py`).

### Data flow

Inside `_run_execution` (both points are in that one function, so the baseline
travels as a local variable, no storage):

1. **Before the agent runs** — if this execution is an enhance with a slug and
   the app has at least one commit, capture a baseline:
   - `was_clean` = `await _smoke_app(slug) is None`
   - `baseline_sha` = current repo `HEAD`
2. Agent runs. AutoFix runs. Docs sweep runs. Commit sweep runs. **All
   unchanged.** The enhance is committed even when broken.
3. **After the commit sweep** — decide with the `smoke_report` already returned
   by `_run_autofix`:
   - `was_clean and smoke_report` → **regression**: roll back to `baseline_sha`
     and replace the user-facing result.
   - anything else → do nothing.

### Why the check runs after the commit sweep

Rolling back *before* the commit would mean discarding uncommitted work with
`git checkout`, which cannot remove newly-added untracked files and leaves the
attempt with no record. Running after means:

- The attempt is a real commit, so "your version history still has it" is
  literally true and someone can go forward and fix it by hand.
- Rollback reuses `rollback_app_core` (`routes_projects.py:648`) exactly as
  designed: it restores the tree at a SHA as a **new** commit, so nothing is
  destroyed and the history reads honestly (`Enhance ...` then `Rollback ...`).
- `git checkout <sha> -- apps/<slug>/` handles files the enhance added, because
  it restores the whole directory as it was.

### Scope guards

Each exists to make the guard incapable of making things worse:

- **Enhances only.** A fresh build has no prior state to regress from.
- **Only clean → broken.** If the app was already failing, never roll back; the
  enhance may well be the fix.
- **No prior commit → skip.** Nothing to restore. (10 prod apps are in this
  state, mostly junk and video-only dirs.)
- **Fails open.** Any exception inside the guard is logged and swallowed, the
  same contract `_run_autofix` and `sweep_app_commit` already use. A build must
  never fail because the guard failed.

### User-facing result

On a regression, the result explains what happened in plain words, names the
errors, and says the attempt is recoverable. Plain text, no emoji or icons, per
project preference. Approximate shape:

```
Reverted: this change broke the app, so I put it back the way it was.

What broke:
- console.error: ...

Your attempt is saved in version history if you want to look at it.
```

## Cost

One extra headless smoke (~5s, `_SETTLE_MS` is 2500ms plus load) at the start of
an enhance that already takes minutes. No new table, no migration, no new route,
no UI change, no new dependency.

## Out of scope

- **Exposing the error buffer as a queryable tool** to the agent (Lovable's
  pull-style `read-console-logs`). Real finding, needs tool plumbing into the
  Claude Code subprocess, its own project.
- **Capturing errors past page load** (interaction-driven failures). The smoke
  listeners stop after one navigation and a settle. Real gap, bigger job.
- **Multi-route checking.** Built apps are effectively single-page today.
- Export, RLS verification, `schema.sql` truthfulness. Separate, still open.

## Testing

Unit (no browser, no git, no LLM), following the `_smoke_app` monkeypatch seam
already used by `test_autofix_loop.py`:

- decision: clean→broken is a regression; broken→broken is not; clean→clean is
  not; broken→clean is not.
- non-enhance builds never capture a baseline and never roll back.
- an app with no prior commit skips the guard.
- rollback is called with the captured baseline SHA and the task's actor.
- fail-open: baseline smoke raising, post smoke raising, and rollback raising
  each leave the build result unchanged.
- the regression message names the errors and does not begin with "Rollback"
  (that prefix is reserved by `list_app_versions_core` for rollback entries;
  note the rollback commit itself is created by `rollback_app_core` and
  correctly keeps that prefix).

End-to-end on the live server, exercising real browser, real git, real
rollback: build a real app, confirm the guard records a clean baseline, then
drive a real regression through the actual functions and confirm the app is
restored on disk and both commits appear in the timeline.

## Deploy

tasks service only. Verify with a real enhance that does not regress (guard runs,
does nothing, app keeps the change) and the driven regression case above.
