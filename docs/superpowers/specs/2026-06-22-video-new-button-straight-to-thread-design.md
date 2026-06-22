# Discord video: "New video" button → straight into the upload thread

**Date:** 2026-06-22
**Branch:** `fix/video-thread-image-intake` (continues the deployed lineage)
**Status:** approved design

## Problem

Clicking **New video** opens a Discord modal (Title + Description) with no way to
upload screenshots — Discord forbids file inputs in modals — so users hit what
looks like a dead-end form and don't discover that screenshots go in the thread.
The earlier `/video new` slash command works but is not discoverable ("no user
can understand /video new"). The user wants the **click flow** to be the
understandable path: click New video → land in the thread → drag screenshots →
add a description → Generate. No slash commands shown.

## Goal

Make **New video** drop the user directly into their private thread, where they:
drag screenshots in, click **Add title & description** (a small popup), pick
style/voice, and **Generate**. Everything in the thread; no slash command in the
UI. `/video new` and `/video add` stay registered as hidden power paths but are
removed from the panel copy.

Non-goals (YAGNI): removing `/video new`/`/video add` registration; style/voice
in a popup (kept as in-thread selects); multi-step wizards beyond the above.

## Flow

1. Click **New video** → bot ACKs (ephemeral, deferred), resolves the account
   (not-linked → link card), creates an **empty draft** (title "Untitled video",
   empty description), opens/reuses the private video thread, and points the ACK
   at it.
2. The thread shows: **"Drag your screenshots into this thread (up to 12). Then
   click Add title & description, pick a style + voice, and hit Generate video."**
   plus controls: **[Add title & description]** button, style select, voice
   select, **[Generate video]** button (and the voice-sample MP3s, as today).
3. Drag screenshots in → ingested via the existing drop handler → running-count
   reply (N/12).
4. Click **[Add title & description]** → popup (Title optional, Description
   required) → on submit, the draft's title/description are saved → confirmation.
5. Pick style/voice → **Generate**. Backend refuses with a clear message if the
   description is still empty ("Add a description first") or there are no
   screenshots ("Add at least one screenshot first"); otherwise it queues and
   renders as today.

## Backend changes (`mcp-servers/tasks/routes_video.py`) — no migration

`video_jobs.title`/`.prompt` columns already exist; these are request-model +
endpoint changes only.

1. **`DraftRequest`** — make title/prompt optional so a bare draft can be created:
   `title: str = Field("Untitled video", max_length=200)`,
   `prompt: str = Field("", max_length=2000)`. Existing callers that pass real
   values (the `/video new` command) are unchanged.
2. **`DraftPatch`** — add `title: str | None = Field(None, max_length=200)` and
   `prompt: str | None = Field(None, max_length=2000)`.
3. **`update_draft`** (`/draft-set`) — when `body.title`/`body.prompt` are not
   None, set them on the collecting draft (alongside the existing style/voice).
4. **`queue_job`** — in addition to the existing ">=1 screenshot" check, refuse to
   queue when the description is blank: `if not (job.prompt or "").strip(): raise
   HTTPException(400, "Add a description first")`.

Only the Discord draft path (`/draft`, `/draft-set`, `/queue`) is touched; the
website's `/upload` flow is untouched.

## Bot changes

### `webhook-handler/clients/tasks.py`
`set_video_draft_fields(user_email, job_id, *, style=None, voice=None, title=None,
prompt=None)` — include `title`/`prompt` in the POST body when provided.

### `webhook-handler/handlers/video_panel.py`
- New custom_id prefixes: `DETAILS_PREFIX = "aiuivid:details:"`,
  `DETAILS_MODAL_PREFIX = "aiuivid:detailsmodal:"` (disjoint from each other and
  from existing prefixes — verified: `details:` is not a prefix of
  `detailsmodal:`).
- `build_details_modal(job_id)` — a modal (custom_id `DETAILS_MODAL_PREFIX+job_id`)
  with Title (optional, reuse `TITLE_INPUT`, max 200) + Description (required,
  reuse `PROMPT_INPUT`, max 2000).
- `build_studio_components(job_id, voices)` — prepend an **[Add title &
  description]** button row (`DETAILS_PREFIX+job_id`); then style select, voice
  select, **[Generate video]** (4 action rows ≤ 5).
- Predicates/extractors: `is_vid_details`, `is_vid_details_modal`,
  `job_from_details`, `job_from_details_modal`.
- `build_video_embed` — pure click-flow copy, no slash commands:
  ```
  > turn screenshots into a narrated walkthrough
  > 1. click New video below
  > 2. drag-and-drop your screenshots into the thread that opens
  > 3. add a description, pick style + voice, hit Generate
  ```
  (keeps the word "drop" via "drag-and-drop" so the existing copy test holds).
- Remove the now-unused `build_video_modal` + `NEW_MODAL_ID` + `is_vid_new_modal`
  (the New-video button no longer opens a create-modal).

### `webhook-handler/handlers/discord_commands.py`
- **`is_vid_new` handler** — stop returning a modal. ACK ephemeral-deferred and
  `self._spawn(self._open_video_studio(..., title="Untitled video", prompt="",
  screenshot_urls=None))` (reuses the shared helper; builds token/user/channel
  from the component payload).
- **`is_vid_details` handler** — `return {"type": MODAL, "data":
  vid.build_details_modal(job_id)}`.
- **Details-modal submit** — route `is_vid_details_modal` to a new
  `_handle_video_details_modal(payload)`: extract title/description, call
  `self.router.set_video_draft_fields(email, job_id, title=..., prompt=...)` (via a
  thin runner that resolves email + posts a confirmation/edit), confirm "Saved —
  you can Generate when ready." Remove the old `is_vid_new_modal` →
  `_handle_video_new_modal` route and the `_handle_video_new_modal` method.
- **`_open_video_studio`** — the no-screenshots studio message becomes the
  drag+details copy: "Drag your screenshots into this thread (up to 12). Then
  click **Add title & description**, pick a style + voice, and hit **Generate
  video**." (The with-screenshots "Created … added N" message stays for
  `/video new`.) Components now include the Add-details button via
  `build_studio_components`.

### `set_video_draft_fields` runner
Add `CommandRouter.run_video_set_details(ctx, job_id, *, title, prompt)` (or reuse
`run_video_set_field`) that resolves email, calls `set_video_draft_fields(...,
title=title, prompt=prompt)`, and responds "Saved." with error handling matching
the other `run_video_*` runners.

## Error handling

- `run_video_generate` already surfaces queue 4xx verbatim
  ("Couldn't start the render: Add a description first" /
  "… Add at least one screenshot first") — no extra bot work.
- Details-modal submit / studio-open failures use the existing not-linked card and
  the "Couldn't open the video studio" / "Couldn't save" ACK edits.
- All async work is `_spawn`-ed under try/except (no unhandled task exceptions).

## Testing (TDD)

**Backend** (`mcp-servers/tasks/tests` — match existing video route tests):
1. `POST /draft` with empty body → 201, draft with title "Untitled video", prompt "".
2. `POST /draft-set` with `{title, prompt}` → updates the draft; GET reflects them.
3. `POST /queue` on a draft with screenshots but blank prompt → 400 "Add a
   description first"; with prompt set + screenshot → 200 queued.

**Bot:**
4. `build_studio_components` includes an Add-title-&-description button whose
   custom_id starts with `DETAILS_PREFIX`.
5. `build_details_modal(job_id)` custom_id == `DETAILS_MODAL_PREFIX+job_id`, has
   Title + Description inputs.
6. Prefix predicates: `is_vid_details`/`is_vid_details_modal` match their own ids
   and not each other; `job_from_*` round-trip.
7. `set_video_draft_fields(..., title=t, prompt=p)` puts title/prompt in the body.
8. `build_video_embed` copy contains no "/video" and still contains "drop".

## Scope / deploy

- **Backend:** `mcp-servers/tasks/routes_video.py` → scp + rebuild `tasks` (no
  migration). Smoke `/tasks/healthz` + a `POST /draft` empty-body check.
- **Bot:** `clients/tasks.py`, `handlers/video_panel.py`,
  `handlers/discord_commands.py` → per-file scp + rebuild `webhook-handler`.
- **Panel:** re-post / refresh the channel card so it shows the new click-flow
  copy (no slash commands).
- No command re-registration needed (commands unchanged; `/video new` stays a
  hidden power path).
- Live e2e: New video → bare draft + thread; drop a screenshot (count); set
  title/description via draft-set; blank-description Generate → "Add a description
  first"; with description → queued.

## Risks

- `DraftRequest` defaults change the contract: a bare `/draft` now succeeds. Only
  the Discord flow calls it; verified the web uses `/upload`. Tests pin both the
  bare and the with-values create.
- Removing `build_video_modal`/`_handle_video_new_modal` is safe only if nothing
  else references them — the plan greps first and updates/removes dependent tests.
