# Conversational AI presence (Discord) — design

**Date:** 2026-06-30
**Follow-up to:** the just-chat intent router + private-thread routing. Makes the
bot feel present: it talks back in channels and in the private app thread, refines
the app by chat, and asks what you want when a build request is vague.

## What the user reported

- The private app thread is silent ("are you there?" gets no reply).
- "build me a website" built a generic "Build a website" instead of asking what
  kind.
- In channels the bot only reacts to a build/schedule request and is otherwise
  silent; they want it conversational.

## Decisions

- **Answer general chat in every channel** (user chose). The bot was silent on
  non-request messages; now it answers them.
- **Ask one clarifying question on a vague build** (user chose), then build.

## Design (Discord; Slack DMs already answer generically)

### 1. Channels answer general chat
`commands.py handle_chat_message`: today returns `False` (silent) when `decide` is
`answer`. Change: call `_handle_ask(ctx)` and return True. So any substantive,
non-actionable message gets a real AI reply (the existing `_handle_ask` persona).
Actionable messages still get the confirm card / suggestion. (Cost note: this means
a classify + an answer call per non-actionable message server-wide; acceptable for a
small team, tighten later if noisy.)

### 2. The private app thread is a conversation
Stop skipping the builder thread. `video_intake.extract_chat_message` gains
`channel_name`; `handle_chat` branches:
- thread named `aiui-apps-*` (builder) -> `router.handle_builder_thread_message(ctx,
  text)` with a ctx that posts to the thread AND has `notify_channel` set (so
  build/enhance results deliver there).
- thread named `schedules-*` / `aiui-video-*` -> skip (those flows own them).
- non-thread (channel) -> `handle_chat_message` as in (1).

`handle_builder_thread_message(ctx, text)`:
1. **Pending clarification** (the user was just asked "what kind?"): classify the
   reply — a question -> answer (keep pending); otherwise -> build with the reply,
   clear pending.
2. **Has a current app** (tracked, see below): classify — a question -> answer;
   otherwise -> `run_panel_enhance(ctx, slug, text)` (refine the app by chat).
3. **No app yet** -> answer + a short hint ("tell me what to build").

### 3. Remember "your current app" + ask-what on vague build
- Router holds in-memory `self._user_app_slug: dict[str,str]` (Discord user id ->
  slug), set in `_start_build` once the slug is known and in `run_panel_enhance`. So
  after any build/enhance, the thread knows what to refine. (In-memory: a restart
  forgets it; the next thread message then starts fresh. Persisting is a small
  follow-up.)
- Router holds `self._pending_build_clarify: dict[str,str]` (user id -> the original
  vague detail).
- Pure `is_vague_build(detail)`: True only when the detail has no meaningful words
  beyond generic filler ("a website", "an app"); "a portfolio", "a flower shop site"
  are not vague.
- `run_confirmed_intent` build branch: if `is_vague_build(detail)` -> ask in the
  thread ("What kind of site is it, and what's it for?") and set pending; else build.
  The user's next thread message (step 1 above) completes it.

## Components

| Unit | File | Change |
|------|------|--------|
| `handle_chat_message` answers | `commands.py` | non-actionable -> `_handle_ask`, not silent |
| `_user_app_slug`, `_pending_build_clarify`, `is_vague_build`, `handle_builder_thread_message` | `commands.py` | thread conversation + remember app + vague-build clarify |
| remember slug | `commands.py` `_start_build`, `run_panel_enhance` | set `_user_app_slug[ctx.user_id]` |
| `run_confirmed_intent` build branch | `commands.py` | vague -> ask + pending; else build |
| `extract_chat_message` + `_app_thread_ctx` + `handle_chat` thread branch | `video_intake.py` | carry channel_name; route builder thread; ctx with notify_channel |

Reuses `run_panel_enhance`, `run_panel_build`, `_handle_ask`, `classify`, the
`_watch_build` delivery. No backend changes.

## Tests

- `is_vague_build`: "a website"/"an app" -> True; "a portfolio"/"a flower shop site"
  -> False.
- `handle_chat_message`: non-actionable now calls `_handle_ask` (answers).
- `handle_builder_thread_message`: pending+statement -> build & clears pending;
  pending+question -> answer & keeps pending; has-app+statement -> enhance(slug);
  has-app+question -> answer; no-app -> answer.
- `run_confirmed_intent`: vague build -> asks + sets pending (no build); rich build ->
  builds.
- `_start_build` remembers the slug.
- `extract_chat_message` carries channel_name; `handle_chat` routes `aiui-apps-*`
  thread to `handle_builder_thread_message`, skips `schedules-*`/`aiui-video-*`.

## Deploy

Drift-check + deploy `commands.py`, `video_intake.py`; merge `voice_bot.py` (only if
on_message changed — it does not here) and `discord_commands.py` (unchanged here).
Rebuild; verify in-container (thread answers + enhance; vague build asks).

## Done when

In the app thread "are you there?" gets an answer and "make it a portfolio with a
gallery" refines the app; "build me a website" asks what kind first; channels answer
general chat. Full suite green.
