# App Builder — Two-Button Entry Panel (Slack + Discord)

**Date:** 2026-06-03
**Status:** Design — approved in brainstorming, pending spec review

## Problem

The pinned App Builder panel (both Slack `#app-builder` and Discord) currently shows a
**"Pick a template…" dropdown + a Blank button** directly in the public channel. Now that
builds run in a **private DM** with the user, the public channel doesn't need the full
template list sitting in it, and there is no clean way for a returning user to reach the apps
they already built without scrolling past the template menu.

## Goal

Replace the in-channel dropdown+Blank with **two intent-based buttons** that move all real
interaction into the user's private DM:

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

## Platform constraint (decides the flow)

**Discord modals support text inputs only** — they cannot contain a select menu. Discord
therefore puts template selection in a *message* select, then opens a text-only modal for the
description. To keep Slack and Discord consistent, both use the same shape:
**select-in-a-message → text modal.** The template picker is posted into the DM (a message),
not embedded in a modal.

## Flows

### 🚀 Build an app (clicked in the public channel)
1. Bot opens the user's DM and posts the **existing** template picker there:
   `[ Pick a template ▾ ]  [ ⬜ Blank ]`.
2. Channel shows an ephemeral "📩 Check your DM" note (only the clicker sees it).
3. User picks a template (or Blank) in the DM → the **existing** describe-your-app modal opens.
4. Submit → the build runs in the same DM (unchanged downstream path).

### 📂 My apps (clicked in the public channel)
1. Bot fetches the user's apps (reuse the existing `aiuibuilder list` path / `tasks_client`).
2. Bot opens the DM and posts the apps as a dropdown (reuse `build_apps_select_components`).
3. Channel shows an ephemeral "📩 Check your DM" note.
4. User picks an app → its existing actions (Open preview / Visual edit / Publish / Enhance).
5. No apps yet → "No apps yet — hit 🚀 Build an app."

## Components & changes (small — mostly re-wiring)

| Area | Change |
|---|---|
| `webhook-handler/handlers/app_builder_panel.py` (Discord) | Panel builder returns **2 buttons** (`aiuibuild:new`, `aiuibuild:myapps`) instead of dropdown+Blank. |
| `webhook-handler/handlers/slack_app_builder_panel.py` (Slack) | Same — 2 buttons in the panel blocks. |
| `webhook-handler/handlers/discord_commands.py` | Two new click handlers: `new` → DM the template picker; `myapps` → DM the apps dropdown. |
| `webhook-handler/handlers/slack_interactions.py` | Same two handlers, Slack-flavored. |
| Downstream (template-select → modal → build; app actions) | **Unchanged.** They simply now originate in the DM. Reuse existing builders. |

New custom_ids / action_ids: `aiuibuild:new`, `aiuibuild:myapps`.

## Data flow

- **Build an app:** click → `open_dm`/create-private-DM → post existing template picker → (existing) select → modal → build → DM.
- **My apps:** click → resolve user email (existing link resolution) → `tasks_client` apps list → `open_dm` → post `build_apps_select_components` → (existing) app-action handlers.

## Error handling (reuse existing patterns)

- **DM can't be opened** (Slack missing `im:write`, Discord DMs blocked) → fall back to posting
  the picker/list **ephemerally in the channel**, plus the existing "⚠️ couldn't DM" note.
  A build/list is never lost.
- **Account not linked** → existing "link your account first" prompt.
- **No apps** (My apps) → empty-state message.
- **Apps fetch fails** → friendly error, ephemeral.

## Testing (TDD, mirrors existing panel tests)

- Panel builder returns exactly the two buttons with the correct ids — Discord and Slack.
- `new` click → opens DM + posts the template picker.
- `myapps` click → opens DM + posts the apps dropdown; empty list → empty-state text.
- DM-open failure → ephemeral fallback (both buttons).
- Regression: template-select → modal → build still works from the DM.

## Scope guard (YAGNI)

- No new app-management actions, no new template UI, no new backend endpoints.
- Purely: entry-panel rewrite (2 buttons) + two handlers that **reuse** existing builders
  (template picker, apps select) and the existing DM-routing + fallback.

## Out of scope

- Changing the build pipeline, template catalog, or app-action set.
- The Slack `im:write` scope install (operator action, tracked separately).
