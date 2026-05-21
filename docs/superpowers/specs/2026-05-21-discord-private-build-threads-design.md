# Discord App Builder — Private Per-App Threads + Fresh Welcome (Feature A) — Design

**Date:** 2026-05-21
**Status:** Approved (pending spec review)
**Topic:** Make each user's app-building a private conversation. The
`#app-builder` channel becomes a permanent welcome page with the template
picker; clicking a template opens a **private thread** for just that user where
their build → enhance → publish → unpublish all happen, hidden from others. Plus
a one-time channel reset to a fresh welcome.

This is **Feature A** of a two-part effort. Feature B (a "My Apps" list to
select/delete existing apps) follows separately.

## Problem

Today `#app-builder` is a single shared channel: everyone sees everyone's
builds, previews, and buttons (see the current cluttered state). The user wants
each person to have a **private** app-builder conversation, the channel to start
**fresh** as a clean welcome page, and the picker/clutter to "hide" into each
user's own space after they pick — mirroring how Open WebUI gives each project
its own focused workspace.

## Goal

- `#app-builder` = permanent **welcome page** (intro + template picker), shared
  and always clean.
- Click a template → bot opens a **private thread** (only that user + bot),
  replies to the user **ephemerally** with a pointer, and runs the whole build
  conversation (Building… → preview → Publish/Enhance buttons) **inside the
  thread**.
- Publish / Enhance / Unpublish keep working unchanged (their buttons live on
  thread messages, so clicks stay in the thread).
- A **reset** that wipes the channel and posts a fresh welcome panel.
- **webhook-handler only** — no tasks-service change (threads are purely a
  Discord-posting concern; the build/publish/enhance/unpublish endpoints don't
  care which channel/thread the bot posts to).

## Non-goals (this feature)

- "My Apps" list / select / delete — that's **Feature B**.
- Changing the slash command `/aiui aiuibuilder build` (stays channel-based, a
  power-user fallback; the *panel* button flow is the private experience).
- Per-user single thread (we chose **one thread per app** — stateless, named
  after the app).
- Renaming threads to the final slug (provisional name is fine; the slug shows
  in the thread's build messages).

## Key facts (verified)

- A Discord **thread is a channel with its own id**. `post_channel_message` and
  the build watcher's notifiers already take a channel id, so pointing them at a
  thread id "just works" — no watcher change.
- The picker → modal → **build modal submit** happens in the MAIN channel
  (`payload.channel_id` = main channel). This is the ONE place that creates the
  thread.
- **Enhance/Publish/Unpublish** buttons are posted by the watcher *into the
  thread*; when clicked, their interaction `channel_id` IS the thread id, so the
  existing handlers post results back to the thread automatically — **no change
  needed** to them or to the tasks endpoints.
- Discord requires the initial interaction response within ~3s. Thread creation
  is one REST call but we do it in the background and return an **ephemeral
  deferred** response immediately (mirrors the existing fire-and-forget pattern).
- Private threads (type 12) are available to all guilds (no boost requirement).
  The bot needs **Create Private Threads** + **Send Messages in Threads**
  permissions (a one-toggle grant, like Manage Channels earlier).

## Components

### 1. `webhook-handler/clients/discord.py` — thread helpers

```python
async def create_private_thread(self, parent_channel_id, name) -> str | None
```
`POST /channels/{parent}/threads` with `{"name": name[:100], "type": 12,
"invitable": false, "auto_archive_duration": 1440}` (bot token). Returns the new
thread id, or `None` on failure (never raises) so the caller can fall back.

```python
async def add_thread_member(self, thread_id, user_id) -> bool
```
`PUT /channels/{thread_id}/thread-members/{user_id}` (bot token). Returns success;
never raises.

### 2. `webhook-handler/handlers/discord_commands.py` — thread the build flow

Extract the build branch of `_handle_modal_submit` (currently the inline tail,
lines ~293-338) into `_handle_build_modal_submit(payload, custom_id)`, then make
it thread-aware:

- Parse `template_key`, `description`, user, `channel_id`, `interaction_token`.
- **Return immediately** `{"type": DEFERRED_CHANNEL_MESSAGE, "data": {"flags": 64}}`
  (ephemeral deferred) and do the rest in a background `asyncio.create_task`:
  - `thread_id = await discord.create_private_thread(channel_id, f"{template_key or 'app'}-{user_name}")`
  - If `thread_id`:
    - `await discord.add_thread_member(thread_id, user_id)`
    - `await discord.edit_original(token, "✅ Opening your private build space → <#{thread_id}>")` (the ephemeral pointer)
    - build ctx with `respond` = post to the **thread**, notifiers = the **thread**.
  - Else (thread creation failed): fall back — `respond` = `edit_original`
    (ephemeral), notifiers = the **main channel** (current behavior). The build
    still completes and posts to the channel.
  - `await self.router.run_panel_build(ctx, template_key, description)`.

`_handle_modal_submit` keeps dispatching: enhance-modal branch unchanged;
panel/build modal → `_handle_build_modal_submit`.

The ctx `respond` for the thread path is a closure calling
`discord.post_channel_message(thread_id, msg)` — so run_panel_build's
"Building `slug`…" ack and any error land in the thread (private). The watcher's
`notify_channel_rich` posts the "ready" + Publish/Enhance buttons into the
thread. (run_panel_build itself is unchanged.)

### 3. `webhook-handler/handlers/app_builder_panel.py` — welcome copy

Update `PANEL_CONTENT` to read as a welcome page and explain the private flow,
e.g.: "🚀 **AIUI App Builder** — pick a template and I'll open a **private
space** just for you to build, preview, and publish your app. Or hit **Blank**
to start from scratch." (No structural change to the buttons.)

### 4. `webhook-handler/scripts/setup_app_builder_channel.py` — reset

Add `_delete_channel(channel_id, headers)` (`DELETE /channels/{id}`). In `main()`,
read a reset flag (`APP_BUILDER_RESET` env == "1", or `--reset` argv). When reset
AND the channel exists: delete it, then fall through to the existing
create-channel + post-panel + pin path → guaranteed fresh channel with one clean
welcome panel. Without the flag, behavior is unchanged (reuse-or-create). Delete
+ recreate also clears any old private threads (intended for a full reset).

## Data flow

```
#app-builder (welcome, shared): [Portfolio][Dashboard]...[Blank]
 user clicks Portfolio → modal "Describe your app" → submit
 → _handle_build_modal_submit:
     return ephemeral deferred (flags 64)   [within 3s]
     bg task:
       create_private_thread(main_channel, "portfolio-ralph") → thread_id
       add_thread_member(thread_id, ralph)
       edit_original(ephemeral) "✅ Opening your private build space → #thread"
       ctx.respond = post to thread; notifiers = thread
       run_panel_build → start_build → "Building `slug`…" (in thread)
       _watch_build → "ready (preview): …" + [Publish][Enhance] (in thread)
 ralph clicks Publish (in thread) → interaction channel_id = thread
   → publishes → on_published edits the thread message → [Enhance][Unpublish]
 (Lukas's build runs in HIS own private thread — no overlap)
```

## Error handling

- Thread creation/add failure → fall back to the main-channel flow (feature
  still works, just not private that one time). Never 500.
- Unlinked user → run_panel_build posts the "isn't linked" message (private to
  the user, in the thread or ephemerally). Rare; acceptable that a thread may be
  created first.
- Ephemeral defer guarantees the 3s ACK even if thread creation is slow.

## Testing

**webhook-handler (local, TDD):**
- `create_private_thread` (respx: POST threads → 201 `{id}`, returns id; non-2xx
  → None) and `add_thread_member` (PUT → 204 → True), both bot-token, never raise.
- `_handle_build_modal_submit`:
  - thread success → returns `{"type":5,"data":{"flags":64}}`; after draining the
    bg task, `create_private_thread` called with the parent channel + a name,
    `add_thread_member` called, and `run_panel_build` called with a ctx whose
    `notify_channel`/`respond` post to the thread id (assert by invoking the
    captured ctx's notifier and checking `post_channel_message(thread_id, …)`).
  - thread failure (create returns None) → falls back: `run_panel_build` ctx
    targets the main channel.
- Reset script: monkeypatch the HTTP helpers; with reset flag + existing channel
  → `_delete_channel` called, then create+post+pin; without flag → no delete.
- Regression: existing enhance-modal / publish / template-button tests stay green.

**Live (post-deploy):** click a template → confirm a private thread opens with
the build, and Publish/Enhance happen in it.

## Deployment (webhook-handler only)
- `scp` changed files (`clients/discord.py`, `handlers/discord_commands.py`,
  `handlers/app_builder_panel.py`, `scripts/setup_app_builder_channel.py`) →
  `docker compose ... up -d --build webhook-handler`.
- Grant the bot **Create Private Threads** + **Send Messages in Threads** in the
  server role (one-time toggle).
- Run the setup script with reset to wipe + fresh-welcome:
  `docker compose ... exec -e DISCORD_GUILD_ID=… -e APP_BUILDER_RESET=1
  webhook-handler python /app/scripts/setup_app_builder_channel.py`.
- Verify bot `Up`; click a template → private thread opens end to end.
