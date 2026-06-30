# Discord Plain-Text Intent (no slash) — design

**Date:** 2026-06-30
**Follow-up to:** the just-chat intent router (sub-project 1). Makes it reachable on
Discord by **plain typing in any channel**, because users don't know slash commands.

## Why

On Discord, slash commands force a fixed menu choice — a user can't type a free
sentence. The point of "just chat" is no commands at all. So Discord needs the bot
to read ordinary messages and act on real requests.

## Feasibility (from exploration)

The webhook-handler already runs a persistent Discord gateway (the voice bot,
`voice_bot.py`), `message_content` intent is already enabled, and `on_message`
already fires for every message and reads `message.content`. It also already holds
the shared `CommandRouter` (via `VideoThreadIntake._router`) and can post messages
with buttons (`post_channel_message(..., components=...)`). Button clicks already
route back to `_handle_message_component` -> `run_confirmed_intent`. So the only
missing link is one `on_message` branch that hands plain text to the router.

## Scope (user chose: every channel)

Plain typing is understood in **every channel and DMs**. To avoid the bot butting
into normal conversation, guards keep it quiet:
- It **stays silent** unless the classifier detects a real request (confirm or
  suggest). Questions / chatter -> no response.
- Skips bots, itself, blanks, commands (`!`/`/`), bare URLs (handled elsewhere),
  attachment messages, and **very short messages** (< 3 words or < 12 chars).
- Skips messages **inside threads** (build/video/schedule flows own threads).
- Uses a **higher confidence bar (0.75)** in channels than the Slack/slash default
  (0.6), so a vaguely request-like sentence won't misfire.
- Flag-gated by the existing `INTENT_ROUTER` (already on in prod).

Trade-off (accepted): one cheap classify call per substantive message server-wide.
Fine for a small team; tighten the bar or narrow scope if it gets noisy/heavy.

## Components

| Unit | File | Responsibility |
|------|------|----------------|
| `looks_like_chat_request(text)` | `video_intake.py` (pure) | True only for substantive plain text (not command/url/short/diag) |
| `extract_chat_message(message)` | `video_intake.py` (pure-ish) | discord message -> {author_id, author_name, channel_id, is_thread, text} or None |
| `VideoThreadIntake.handle_chat(...)` | `video_intake.py` | skip threads; build a gateway ctx (reuse `_thread_ctx`); call `router.handle_chat_message` |
| `CommandRouter.handle_chat_message(ctx)` | `commands.py` | classify+decide@0.75; confirm -> park + post card; suggest -> post; answer -> silent (return False) |
| `on_message` branch | `voice_bot.py` | after the diag/image/url branches, call `extract_chat_message` + `handle_chat` (best-effort, never crash the gateway) |

Reuses the existing brain (`classify`/`decide`), cards (`confirm_components_discord`),
and `_pending_intents` (shared, so the button click round-trip already works).

## Testing

- `looks_like_chat_request`: true for "build me a feedback form"; false for "ok",
  "!voice diag", a bare URL, "lol thanks".
- `extract_chat_message`: dict for plain text; None for attachment / url / short.
- `handle_chat`: thread -> no router call; non-thread substantive -> router called.
- `handle_chat_message`: flag off -> False; build_app@high -> posts card + parks;
  question -> False (silent); make_video -> posts suggestion.

## Deploy

`voice_bot.py` has server drift (server is ahead), so merge the one `on_message`
branch onto the **server's** copy (like `discord_commands.py`), and scp the new
`commands.py` + `video_intake.py` (drift-checked), then rebuild. Verify in-container.

## Done when

Typing "build me a feedback form" in a Discord channel (no slash) pops the confirm
card; ordinary chatter gets no response; full suite green.
