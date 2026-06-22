# Discord video: `/video new` one-shot create-with-screenshots

**Date:** 2026-06-22
**Branch:** `fix/video-thread-image-intake` (continues on the deployed lineage; same branch as the drop-to-add fix)
**Status:** approved design

## Problem

After clicking **New video**, the user gets a Discord modal with only Title +
Description — there is no obvious single place to *send screenshots*, which is
confusing. Discord modals **cannot** contain a file-upload field (platform
limitation: modals allow only text inputs and select menus), so screenshots can
never live in that form. Today screenshots arrive via `/video add` or by dropping
images in the thread (shipped earlier). The user wants **one simple command** that
takes the description and the screenshots together.

## Goal

Add `/video new` — a single slash command that creates a video draft from a
description plus attached screenshots, then opens the user's private thread with
the style/voice + Generate controls. Keep the **New video** button as a guided
alternative. Lead the channel panel with `/video new`.

Non-goals (YAGNI): style/voice as command options (defaulted, picked in-thread);
enforcing ≥1 screenshot at the command layer (the thread/Generate step guides
that); any backend change.

## The command

`/video new`:
- `description` (STRING, **required**) — the narration prompt (backend `prompt`).
- `title` (STRING, optional) — defaults to the first 60 chars of the description,
  or `"Untitled video"` if empty.
- `shot1` … `shot12` (ATTACHMENT, optional) — the screenshots.

Order satisfies Discord's "required options before optional" rule (description is
required and first; title + shots optional). Style/voice are not options — they
default to `clean_product_demo` / `amy` and are chosen in the thread.

## Architecture

### DRY refactor: one shared "open studio" path

`DiscordCommandHandler._handle_video_new_modal` (the button/modal submit) and the
new `/video new` handler share almost all behavior. Extract the modal's inner
`_open_studio` closure into a reusable method:

```
async def _open_video_studio(self, *, interaction_token, user_id, user_name,
                             channel_id, title, prompt, screenshot_urls=None) -> None
```

It performs, with the existing try/except (logs + edits the ACK to an error on
failure):
1. resolve email via `self.router._resolve_email(user_id)`; `None` → post the
   not-linked card to the ephemeral ACK and return.
2. `create_video_draft(email, title, prompt, "clean_product_demo", "amy")`.
3. open/reuse the private video thread (`_get_or_make_thread(kind="video")`);
   edit the ephemeral ACK to point at it.
4. post the voice-sample MP3s (best-effort; failure never blocks).
5. **(new)** if `screenshot_urls`, call
   `self.router._tasks_client.add_video_screenshots_urls(email, job_id, urls)`
   and capture the count (best-effort; a failure logs and continues so the studio
   still opens).
6. post the studio message + `build_studio_components(job_id, voices)`. The
   message mentions the screenshot count when any were added, e.g. *"Created
   '<title>'. Added N screenshots — pick a style + voice, drop more here (or
   `/video add`), then hit **Generate video**."*; otherwise the existing
   "drop your screenshots here" copy.

`_handle_video_new_modal` becomes a thin caller: extract title/prompt from the
modal, then `self._spawn(self._open_video_studio(..., screenshot_urls=None))`.

### `/video new` handler

In `_handle_video_command` (which already routes `/video add` and `/video list`):
add a `sub == "new"` branch handled BEFORE building the add/list `CommandContext`
(the studio path posts directly via `self.discord`, so it needs no ctx):
- parse fields with a pure, testable static helper
  `_parse_video_new(data) -> (title, prompt, urls)`:
  - read the `new` subcommand's nested STRING options by name (`description`,
    `title`);
  - `title = given_title.strip() or description[:60].strip() or "Untitled video"`;
  - `urls = [a["url"] for a in _all_attachments(data) if a.get("url")]` (all
    attached shots; the backend validates each is an image, matching `/video add`).
- `self._spawn(self._open_video_studio(interaction_token=token, user_id=...,
  user_name=..., channel_id=..., title=title, prompt=description,
  screenshot_urls=urls))`.
- return `{"type": DEFERRED_CHANNEL_MESSAGE, "data": {"flags": 64}}` (ephemeral
  deferred), as the modal handler does.

Zero-screenshot case: draft + thread open normally; the studio message uses the
no-count copy and the user drops screenshots in the thread.

### Registration

Add a `new` subcommand to `build_video_command_payload` in
`scripts/register_discord_commands.py`: options = `description` (required) +
`title` (optional) + the same `shot1..shot12` ATTACHMENT list `add` uses. The
script PUTs `[/aiui, /video]` together (PUT replaces all), so re-running it
registers `/video new` instantly (guild-scoped).

### Panel copy

`build_video_embed` leads with `/video new` and keeps the button + drop:

```
> turn screenshots into a narrated walkthrough
> fastest: /video new  — attach screenshots + describe it
> or New video -> drop screenshots in your thread
> Generate -> we render it in your private thread
```

(Still contains "drop", so the existing copy test stays green.)

## Data flow

`/video new description:… shot1:…` → ephemeral-deferred ACK → `_parse_video_new`
→ `_open_video_studio` → create draft → open thread → (add screenshots via
`screenshots-by-url`) → post style/voice + Generate into the thread → ephemeral
reply points to the thread.

## Error handling

Reused from the shared helper / backend: not-linked → link card; draft-create or
studio failure → the existing "Couldn't open the video studio — please try again"
ACK edit; screenshot-add failure → logged, studio still opens (user can retry via
drop / `/video add`); backend rejects non-image / oversize / >12 with its existing
messages. `_open_video_studio` is `_spawn`-ed; its outer try/except prevents an
unhandled task exception.

## Testing (TDD)

1. **Register payload:** `build_video_command_payload()` includes a `new`
   subcommand with `description` (required), `title` (optional), and 12 `shotN`
   ATTACHMENT options.
2. **Field parser (pure):** `_parse_video_new` extracts description, returns the
   given title when present, derives the 60-char default when blank, falls back to
   "Untitled video" for an empty description, and returns the attachment URLs.
3. **Panel copy:** `build_video_embed` description contains `/video new`.
4. **`_open_video_studio`:** with mocked `router` (`_resolve_email`,
   `_tasks_client.create_video_draft`, `get_video_voices`,
   `add_video_screenshots_urls`) and mocked `discord` client, verify: with
   `screenshot_urls` it creates the draft, adds those URLs, and posts the studio
   components; with `screenshot_urls=None` it creates the draft and posts the
   components without calling `add_video_screenshots_urls`; not-linked email posts
   the link card and creates no draft.

## Scope / deploy

Bot only:
- EDIT `webhook-handler/handlers/discord_commands.py` (`_open_video_studio`
  refactor; `_handle_video_new_modal` thin caller; `/video new` branch +
  `_parse_video_new`).
- EDIT `webhook-handler/handlers/video_panel.py` (embed copy).
- EDIT `scripts/register_discord_commands.py` (`new` subcommand).
- Tests: `webhook-handler/tests/` (+ a register-payload test).

**No backend changes, no migrations.** Deploy = per-file scp + rebuild
webhook-handler, then **re-run the register script** so `/video new` appears.
Optional: re-post the channel panel so its card shows the new copy.

## Risks

- Re-running the register script re-PUTs all commands — confirmed it includes both
  `/aiui` and `/video`, so nothing is dropped.
- A user may attach a non-image as a `shotN`; the backend `validate_screenshot`
  rejects it (same as `/video add`), surfaced as a clear error — no new risk.
