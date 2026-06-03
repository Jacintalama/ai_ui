# App Builder — Two-Button Entry Panel (Slack + Discord)

**Date:** 2026-06-03
**Status:** Design — approved in brainstorming, pending spec review

## Problem

The pinned App Builder panel (both Slack `#app-builder` and Discord) currently shows a
**"Pick a template…" dropdown + a Blank button** directly in the public channel. Now that
builds run in a **private space** with the user (Slack DM / Discord private thread), the
public channel doesn't need the full
template list sitting in it, and there is no clean way for a returning user to reach the apps
they already built without scrolling past the template menu.

## Goal

Replace the in-channel dropdown+Blank with **two intent-based buttons** that move all real
interaction into the user's private space (Slack DM / Discord private thread):

```
🤖 AIUI · App Builder        Build privately in your DM.
   [ 🚀 Build an app ]   [ 📂 My apps ]
```

- **🚀 Build an app** — create something new (template or blank)
- **📂 My apps** — open / manage apps already built

Applies to **both Slack and Discord** (they share the same builder backend).

## Why two buttons (not one, not the old dropdown)

- **New user:** *Build an app* → templates; *My apps* → friendly empty state. No confusion.
- **Returning user:** *My apps* → straight to existing apps, no scrolling past templates.
- A single "Open Workspaces" forces everyone through the template list even when they only
  want to reopen an existing app. Three+ buttons add clutter. Two, named by intent, is the
  sweet spot.

## Platform constraints (decide the flow)

Two platform differences shape the design:

1. **Discord modals support text inputs only** — they cannot contain a select menu. Discord
   puts template selection in a *message* select, then opens a text-only modal for the
   description. Slack matches this shape (select-in-a-message → text modal) for consistency.
   The template picker is posted into the private space as a message, not embedded in a modal.

2. **"Private space" differs per platform — they are NOT both DMs:**
   - **Slack:** a true 1:1 **DM** with the bot (`SlackClient.open_dm`), with the existing
     ephemeral-in-channel fallback when the DM can't be opened.
   - **Discord:** the bot has **no DM primitive**. Its private space is a **private thread**
     created off the channel — exactly the established `_handle_sched_open` pattern
     (`create_private_thread` + `add_thread_member`, reusing the per-user thread via
     `get_user_thread`/`set_user_thread`), falling back to an ephemeral message if the thread
     can't be created.

   Throughout this spec, **"private space"** means *DM on Slack, private thread on Discord*.

## Flows

### 🚀 Build an app (clicked in the public channel)
1. Bot opens the user's **private space** (Slack DM / Discord private thread) and posts the
   **existing** template picker there: `[ Pick a template ▾ ]  [ ⬜ Blank ]`.
2. Channel shows an ephemeral "📩 Check your DM" / "📅 in your thread" note.
3. User picks a template (or Blank) in the private space → the **existing** describe-your-app
   modal opens.
4. Submit → the build runs in the same private space (unchanged downstream path).

### 📂 My apps (clicked in the public channel)
1. Bot resolves the user's email (existing link resolution) and fetches their apps via
   `tasks_client.list_projects(email)` (the same source the existing `aiuibuilder list` uses).
2. Bot opens the **private space** and posts the apps list, using the existing per-platform
   builder:
   - **Discord:** `build_apps_select_components` — a dropdown; picking an app reveals its actions.
   - **Slack:** `build_apps_list_blocks` — one row per app with the actions already on each row.
3. Channel shows an ephemeral "📩 Check your DM" / "📅 in your thread" note.
4. App actions (Open preview / Visual edit / Publish / Enhance) are the existing ones.
5. No apps yet → "No apps yet — hit 🚀 Build an app."

## Components & changes (small — mostly re-wiring)

| Area | Change |
|---|---|
| `webhook-handler/handlers/app_builder_panel.py` (Discord) | Panel builder returns **2 buttons** (`aiuibuild:new`, `aiuibuild:myapps`) instead of dropdown+Blank. |
| `webhook-handler/handlers/slack_app_builder_panel.py` (Slack) | Same — 2 buttons in the panel blocks. |
| `webhook-handler/handlers/discord_commands.py` | Two new click handlers: `new` → post template picker into the user's private **thread** (`create_private_thread`/`get_user_thread` pattern); `myapps` → post `build_apps_select_components` (dropdown) into the thread. |
| `webhook-handler/handlers/slack_interactions.py` | Same two handlers: `new` → `open_dm` + template picker; `myapps` → `open_dm` + `build_apps_list_blocks` (per-app rows). |
| Downstream (template-select → modal → build; app actions) | **Unchanged.** They simply now originate in the private space. Reuse existing builders. |

New custom_ids / action_ids: `aiuibuild:new`, `aiuibuild:myapps`.

## Data flow

- **Build an app:** click → open private space (Slack `open_dm` / Discord `create_private_thread`+`add_thread_member`) → post existing template picker → (existing) select → modal → build → posted in the private space.
- **My apps:** click → resolve user email (existing) → `tasks_client.list_projects(email)` → open private space → post the per-platform apps builder (Discord `build_apps_select_components`, Slack `build_apps_list_blocks`) → (existing) app-action handlers.

## Error handling (reuse existing patterns)

- **Private space can't be opened:**
  - Slack DM fails (missing `im:write`) → existing ephemeral-in-channel fallback + "⚠️ couldn't DM" note.
  - Discord thread can't be created → existing `_handle_sched_open` fallback (post the picker/list as an ephemeral message instead).
  A build/list is never lost on either platform.
- **Account not linked** → existing "link your account first" prompt.
- **No apps** (My apps) → empty-state message.
- **Apps fetch fails** → friendly error, ephemeral.

## Testing (TDD, mirrors existing panel tests)

- Panel builder returns exactly the two buttons with the correct ids — Discord and Slack.
- `new` click → opens the private space (Slack DM / Discord thread) + posts the template picker.
- `myapps` click → opens the private space + posts the apps list (Discord dropdown
  `build_apps_select_components` / Slack `build_apps_list_blocks`); empty list → empty-state text.
- Private-space-open failure → ephemeral fallback (both buttons, both platforms).
- Regression: template-select → modal → build still works from the private space.

## Scope guard (YAGNI)

- No new app-management actions, no new template UI, no new backend endpoints, **no new
  Discord DM client method** — Discord uses the existing private-thread primitive, not DMs.
- Purely: entry-panel rewrite (2 buttons) + two handlers that **reuse** existing builders
  (template picker; Discord `build_apps_select_components` / Slack `build_apps_list_blocks`)
  and the existing private-space routing + fallback (Slack DM, Discord thread).

## Out of scope

- Changing the build pipeline, template catalog, or app-action set.
- The Slack `im:write` scope install (operator action, tracked separately).
