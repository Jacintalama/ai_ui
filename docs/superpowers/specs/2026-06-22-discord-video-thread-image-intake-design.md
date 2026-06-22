# Discord video: drop-to-add screenshot intake

**Date:** 2026-06-22
**Branch:** `fix/video-thread-image-intake` (based on `integrate/video-recruiting`, the deployed lineage)
**Status:** approved design

## Problem

The Discord `#video-generation` feature has no equivalent to the website Video
Studio's drag-and-drop screenshot upload. The only way to supply screenshots is
the `/video add` slash command (12 separate attachment-picker options), which is
non-obvious. A user who does the natural thing — **drops/sends an image into the
thread** — is silently ignored, because the bot reacts only to interactions
(slash commands, buttons, modals), never to posted messages.

Evidence (2026-06-22): `/video add` is registered correctly; the bot logs show
no errors; but **no human has ever created a video draft via Discord**, every
`discord_links.video_thread_id` is NULL, and **zero** screenshots have ever been
ingested through Discord. The intake UX is the blocker.

## Goal

Let users add screenshots by **posting images into their private video thread**,
matching the website's drag-and-drop. `/video add` stays unchanged (additive).

Non-goals (YAGNI): auto-creating a draft from a channel drop; debouncing
multi-message drops; emoji/reaction-based feedback (the project forbids
decorative glyphs — text confirmations only).

## Why this is small

- The bot already runs a Discord **Gateway** client (`webhook-handler/voice_bot.py`)
  in the **same process** as the FastAPI webhook-handler, with
  `intents.message_content = True` (proven live by the `!voice diag` command) and
  an existing `on_message` handler.
- `CommandRouter.run_video_add(ctx, urls)` already performs the entire backend
  job: resolve email → load the current `collecting` draft → POST
  `screenshots-by-url` → reply with the running count + a Generate button, with
  full not-linked / no-draft / size / count / backend error handling.
- The backend `POST /api/video-jobs/{id}/screenshots-by-url` SSRF allow-list
  already accepts `cdn.discordapp.com` / `media.discordapp.net`, which is where
  discord.py serves message attachment URLs.

So the fix mostly **wires existing parts together**; the only genuinely new
logic is "is this image-drop in scope, and which response do I give?"

## Architecture

One new, isolated, discord.py-free unit plus thin wiring.

### New unit: `webhook-handler/handlers/video_intake.py`

`class VideoThreadIntake` — single responsibility: decide what to do with an
image-drop and act. No discord.py imports (so it is unit-testable with plain
data).

Constructor dependencies (passed explicitly):
- `router` — the `CommandRouter` (to call `run_video_add` and build a posting context).
- `discord_client` — the httpx `DiscordClient` (to post replies / the nudge).
- `video_channel_id: str | None` and `video_channel_name: str` — to identify the
  `#video-generation` channel and its threads.

Primary method:

```
async def handle_image_drop(
    self, *, author_id: str, author_name: str, channel_id: str,
    is_thread: bool, parent_channel_id: str | None,
    parent_channel_name: str | None, attachments: list[dict],
) -> None
```

`attachments` items are plain dicts: `{url, content_type, filename}`.

Logic:
1. Filter to image attachments: `content_type` starts with `image/`, or filename
   ends with `.png/.jpg/.jpeg/.webp/.gif` (case-insensitive). No images → return
   (do nothing).
2. Determine scope:
   - **Thread under the video channel** (`is_thread` and the parent matches the
     video channel by id when `video_channel_id` is set, else by name) → build a
     `CommandContext` whose `respond`/`respond_components` post into `channel_id`
     via `discord_client.post_channel_message`, then `await
     self.router.run_video_add(ctx, image_urls)`.
   - **Main video channel** (`not is_thread` and `channel_id`/name matches the
     video channel) → `await self.discord_client.post_channel_message(channel_id,
     <nudge>)`. Nudge text: "To add screenshots, click **New video** to start —
     your screenshots go in your private video thread."
   - Otherwise → return (ignore).

The posting `CommandContext` mirrors the one `DiscordCommandHandler._run_video_set`
builds, but for a Gateway message there is no interaction token, so `respond`
posts a NEW message to the thread (not `edit_original`):

```
ctx = CommandContext(
    user_id=author_id, user_name=author_name, channel_id=channel_id,
    raw_text="video add", subcommand="video", arguments="", platform="discord",
    respond=lambda m: discord_client.post_channel_message(channel_id, m),
    respond_components=lambda m, c, e=None: discord_client.post_channel_message(
        channel_id, m, components=c),
    metadata={}, notify_channel=None, notify_channel_rich=None)
```

### Wiring: `webhook-handler/voice_bot.py`

- `ConversationalVoiceBot.__init__` gains an optional `video_intake=None`, stored
  as `self._video_intake`.
- `on_message` keeps the existing `!voice diag` block, then adds: if
  `self._video_intake` is set and the message has attachments, extract primitives
  from the `discord.Message`/channel (author id/name, channel id, whether the
  channel is a `discord.Thread`, the parent channel id+name, and the attachment
  list) and `await self._video_intake.handle_image_drop(...)`. Bot-authored
  messages are already skipped at the top of `on_message`.
- `start_voice_bot(...)` gains an optional `video_intake=None` and passes it into
  the bot constructor.

`on_message` stays thin: it only translates discord.py objects into primitives
and delegates. All policy lives in the testable intake unit.

### Wiring: `webhook-handler/main.py`

In `lifespan`, after the `CommandRouter` and `DiscordClient` are built, construct
`VideoThreadIntake(router, discord_client, video_channel_id, video_channel_name)`
and pass it to `start_voice_bot(..., video_intake=intake)`. Channel id/name come
from `VIDEO_CHANNEL_ID` / `VIDEO_CHANNEL_NAME` env (default name
`video-generation`); both optional — if neither resolves, the intake simply never
matches and silently no-ops (safe).

### Copy updates (discoverability)

- `handlers/video_panel.py` `build_video_embed`: "> add 1-12 screenshots with
  `/video add`" → "> drop your screenshots in the thread (or `/video add`)".
- `handlers/discord_commands.py` studio message: "Pick a style + voice, add 1-12
  screenshots with `/video add`, then hit **Generate video**." → "Pick a style +
  voice, then **drop your screenshots here** (or use `/video add`), then hit
  **Generate video**."

## Data flow

image dropped in thread → Gateway `MESSAGE_CREATE` → `on_message` → primitives →
`VideoThreadIntake.handle_image_drop` → `run_video_add(ctx, urls)` → backend
`screenshots-by-url` → thread reply "Added screenshots — N/12 so far. Click
**Generate video** when ready." + Generate button.

## Error handling

All reused from `run_video_add` / the backend:
- not linked → existing not-linked link card.
- no active `collecting` draft → "No video in progress — click **New video**
  first."
- > 12 screenshots / oversized / fetch failure → existing clear messages.
- backend `validate_screenshot` rejects a non-image that slips the filter
  (defense-in-depth).

A failure inside `handle_image_drop` must never crash the Gateway loop: wrap the
call site in `on_message` so an exception is logged, not propagated.

## Testing (TDD)

Unit tests on `VideoThreadIntake` (no discord.py needed — pass primitives), with
a fake router (records `run_video_add` calls) and a fake discord client (records
posts):
1. image attachment in a video thread → `run_video_add` called once with exactly
   the image URLs.
2. multiple image attachments → all URLs forwarded, in order.
3. non-image attachment (e.g. `application/pdf`) in a thread → `run_video_add`
   NOT called, no post.
4. image in the main video channel (not a thread) → nudge posted, `run_video_add`
   NOT called.
5. image in an unrelated thread / channel → ignored (no calls).
6. mix of image + non-image → only image URLs forwarded.

`on_message` itself stays thin enough that the intake tests cover the logic;
discord.py message mocking is avoided.

## Scope / deploy

webhook-handler only:
- NEW `webhook-handler/handlers/video_intake.py`
- NEW `webhook-handler/tests/test_video_intake.py`
- EDIT `webhook-handler/voice_bot.py`, `webhook-handler/main.py`
- EDIT copy in `webhook-handler/handlers/video_panel.py`,
  `webhook-handler/handlers/discord_commands.py`

**No backend changes, no migrations.** Deploy = per-file `scp` of the changed
files + `docker compose ... up -d --build webhook-handler` (the orchestrator does
not cover webhook-handler). Requires the Gateway bot running (`ELEVENLABS_API_KEY`
set — it is in prod) and the MESSAGE_CONTENT privileged intent (already enabled,
proven by `!voice diag`).

## Risks

- **Gateway coupling:** image intake works only while the voice/Gateway bot is
  connected. Accepted (it is up in prod; `/video add` remains as a fallback).
- **Per-message backend lookup:** gated cheaply (only fires for messages that
  have image attachments and are in a video-channel thread), so cost is bounded.
- **Multi-message drops:** each message with images posts its own confirmation
  (minor noise). A single Discord message can carry up to 10 attachments, so the
  common case is one drop = one confirmation. Not debounced (YAGNI).
