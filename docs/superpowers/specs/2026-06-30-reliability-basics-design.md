# Reliability Basics — design (sub-project 2 of 3)

**Date:** 2026-06-30
**Status:** design + implementation (autonomous build per user "continue everything").

## Problem (from the 2026-06-05 audit + Maria walkthrough)

Once a build starts, the experience is fragile:
- **Silent for minutes** (audit #4 / Maria quit #5): one "usually a few minutes" line then nothing. Users think it crashed.
- **Can leave you hanging** (audit #5): `_watch_build` has no outer try/except and only catches `TasksAPIError`; an unexpected error (or a non-`TasksAPIError` httpx error) kills the watcher with no message, and the spawn's done-callback only discards (no logging).
- **Code-name only** (audit #8): everything shows the slug `landing-3a1f`; users don't recognize their own app. `start_build` accepts a `name` but webhook-handler always sends `None`.

## Scope decision

All three fixes live in `webhook-handler/handlers/commands.py` (+ tests). They are
strict improvements (not misfire-prone like the intent router), so **no feature
flag** — the unpushed branch is the gate. No new Discord/Slack client methods.

**Heartbeat = one reassurance ping, NOT edit-in-place.** A true edit-in-place
rotating status would need: a Discord "edit channel message" method, capturing the
posted message id, a new Slack `chat.update`, and threading a new callback through
8+ `_channel_notifiers` call sites. That cost is not justified now. Instead the
watcher posts ONE "still building..." message after ~36s if still running. That
removes the "is it dead?" panic with zero new plumbing. (Edit-in-place noted as
future polish.)

## The three changes

1. **Friendly names.** Pure `friendly_name(description)` derives a human title
   (first clause, drop a leading article, cap length). `_start_build` passes it to
   `start_build(name=...)` and shows it in the ack and watcher messages as
   `**Name**`, keeping the slug in the ack and the status hint for reference.
2. **Guaranteed delivery.** `_watch_build` body wrapped in an outer try/except that
   always posts a final "I lost track... check status" message on any unexpected
   crash; the poll catches `(TasksAPIError, httpx.HTTPError)`; a new
   `_on_build_watcher_done` done-callback logs a crashed watcher (belt and braces).
3. **Reassurance ping.** After `BUILD_REASSURE_AFTER_POLLS` (3 ≈ 36s) of "running",
   post one "Still building **Name** — writing your pages..." message, once.

## Compatibility

Existing `test_aiuibuilder_build.py` assertions are preserved: the ack still
contains "Building" + the slug; watcher messages keep the substrings the tests
assert ("more detail", "failed", "still building", "Lost track", the preview URL).
`display` defaults to the slug when no `display_name` is passed, so the direct
`_watch_build(...)` tests are unaffected. The one change: `fake_watch` in the happy
-path test gains `**kw` to tolerate the new `display_name=` keyword.

## Tests

- `friendly_name`: basic, article+first-clause strip, empty, long-truncates.
- watcher: one reassurance then completes; guaranteed message on unexpected crash;
  httpx error treated as transient; (existing completed/needs_input/failed/timeout/
  transient/give-up/noop all still green).
- start path: `start_build` receives the friendly `name`; the ack shows it.

## Done when

The build flow shows a human name, never goes silent past ~36s, and always posts a
final message even on an unexpected crash — with the full suite green.
