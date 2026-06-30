# Confirmed chat intents route into the real flows (private thread) — design

**Date:** 2026-06-30
**Follow-up to:** the just-chat intent router. Fixes the confirmed-build bug and
routes confirmed build + schedule from chat into their working private-thread flows.

## Bug (confirmed)

On Discord, the "Yes, do it" button routes via `_handle_panel_route`, which builds a
CommandContext with **no `notify_channel`**. `_start_build` only spawns the result
watcher `if ctx.notify_channel is not None`, so the build starts but the link is
never delivered — the user just sees an ephemeral "Building… I'll post the link
here" that never resolves. (Slack's confirm path already uses `_dm_context`, which
sets the notifiers, so Slack already delivers. Only Discord is broken.)

## Goal

A confirmed chat request runs in a **private space** and actually delivers:
- **Build:** open/reuse the user's private builder thread (the same `aiui-apps-<user>`
  thread the "Build an app" button uses) and run the build there — "still building"
  pings, the ready link, and the Preview/Publish buttons all land in that thread.
- **Schedule (cron from chat):** "summarize my emails every morning at 8am" creates
  the schedule and delivers its runs to the user's private `schedules-<user>` thread.
- Works from any channel (the router already runs everywhere).

## Design

### Build (Discord)
Replace the Discord `aiuiintent:confirm` branch's `_handle_panel_route` call with
`_handle_intent_confirm(payload, token)`:
- peek the parked intent (`router.peek_intent(token)`, no pop).
- `build_app` → `_handle_intent_thread_route(payload, token, kind="builder",
  raw_text="intent build")` — opens/reuses the builder thread via the existing
  `_get_or_make_thread(..., kind="builder")`, posts an ephemeral "Opening your
  private build space → #thread" pointer, builds a ctx whose `respond` posts into
  the thread and whose `notify_channel`/`notify_channel_rich` come from
  `_channel_notifiers(thread)`, then spawns `run_confirmed_intent(ctx, token)`.
  This is the exact pattern `_handle_build_modal_submit` already uses, so the watcher
  spawns and delivers to the thread.
- other intents → `_handle_panel_route` as today (ephemeral reply is fine).

`_handle_intent_thread_route` is generic over `kind`, so schedule reuses it with
`kind="schedules"`.

### Schedule from chat (both platforms)
1. **Classifier extracts slots.** `IntentResult` gains `when: str = ""` and
   `task: str = ""`. For `schedule_task` the model also returns the time phrase
   (`when`, e.g. "every morning at 8am") and the task (`task`, e.g. "summarize my
   emails"). `parse_classification` reads them; other intents leave them empty.
2. **`decide()` makes `schedule_task` a `confirm`** (was `suggest`), so it shows the
   card and can run on confirm.
3. **`park_intent(intent, detail, *, when="", task="")`** stores the slots; the three
   parking sites (`_handle_natural`, `handle_chat_message`, slack `_try_intent`) pass
   `when=result.when, task=result.task`.
4. **`run_confirmed_intent`** gains a `schedule_task` branch →
   `run_scheduled_from_chat(ctx, data)`:
   - `parse_when(data["when"])` → `(cron, human)`; if it fails or `task` is empty,
     reply asking for "what + when" (graceful, no broken state).
   - else `run_schedule_create(ctx, name=f"{human}: {task[:60]}", cron=cron,
     prompt=task, delivery_channel_id=ctx.channel_id, run_once=False)` — which
     creates the schedule and posts its own "Scheduled — …" confirmation; the
     scheduler later delivers runs to the thread.
5. **Discord** routes schedule confirm through `_handle_intent_thread_route(...,
   kind="schedules")` so the ctx targets the `schedules-<user>` thread. **Slack**
   already opens a DM in `_spawn_intent_action` (`_dm_context`), so its ctx is the
   private space — no Slack-side thread work needed.

Connector gating (Gmail/Drive) for chat schedules is skipped for v1 (the run
degrades gracefully, like the daily briefing); the panel flow keeps its gate.

## Components

| Unit | File | Change |
|------|------|--------|
| `IntentResult.when/.task` + prompt + parse | `intent_router.py` | extract schedule slots |
| `decide()` | `intent_router.py` | `schedule_task` -> confirm |
| `park_intent(..., when, task)`, `peek_intent`, `run_scheduled_from_chat`, `run_confirmed_intent` branch | `commands.py` | store slots; schedule run path |
| parking sites pass slots | `commands.py` (`_handle_natural`, `handle_chat_message`), `slack.py` (`_try_intent`) | thread slots through |
| `_handle_intent_confirm`, `_handle_intent_thread_route` | `discord_commands.py` | open private thread (builder/schedules), wire notifiers, run |

Reuses: `_get_or_make_thread`, `_channel_notifiers`, `run_panel_build`,
`run_schedule_create`, `parse_when`, `_pending_intents`. No new infrastructure.

## Tests

- `decide(schedule_task)` -> confirm; `parse_classification` reads when/task.
- `run_scheduled_from_chat`: good when/task -> `run_schedule_create` called with the
  cron + task + delivery channel; missing/garbled -> a help reply, no create.
- `peek_intent` returns the parked dict without popping.
- Discord `_handle_intent_confirm`: build -> thread route (notifiers set, build
  delivers); schedule -> schedules-thread route; briefing -> panel route.
- park_intent stores when/task; parking sites pass them.

## Deploy

Drift-check + deploy `commands.py`, `intent_router.py`, `slack.py`, and merge the
`discord_commands.py` changes onto the server's drifted copy (server is ahead on
video). Rebuild webhook-handler; verify in-container (build confirm opens a thread
and delivers; schedule confirm creates a schedule).

## Done when

"build me a website" -> Yes -> a private thread opens and the build delivers there;
"summarize my emails every morning at 8am" -> Yes -> a schedule is created and runs
deliver to the private thread; full suite green.
