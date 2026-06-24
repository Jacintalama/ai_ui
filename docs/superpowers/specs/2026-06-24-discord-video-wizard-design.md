# Discord Video Studio: Step-by-Step Wizard

Date: 2026-06-24
Status: Approved design (user approved flow + 2 specifics), pending implementation
Branch: feat/video-source-wizard (off origin/main)

## Problem

The #video-generation studio card (`build_studio_components`, video_panel.py:160-170)
shows SIX controls at once: style select, voice select, output-mode select, a
"Paste your site link" button, an "Add description" button, and a "Generate
video" button. New users do not know where to start. (See the user screenshot.)

## Goal

Replace the all-at-once card with a wizard that shows one decision at a time.
The first decision is the source: a website URL (auto-captured) or the user's
own screenshots. Style/voice/output-mode move behind a single optional button
with good defaults. No change to capture or render: this is a UI-layer refactor
that reuses the existing runners and tasks endpoints.

## Non-goals

- No change to the Playwright capture (`/{job_id}/capture-from-url`), the render
  pipeline, or the tasks DB schema.
- No change to the refine / version / apply flow after a video is delivered.
- No new bot-side state. Cards stay stateless; job_id stays embedded in custom_ids.

## Approved decisions

- Style/voice/output-mode: hidden behind ONE optional "Style & voice" button at
  the Generate step (defaults already set).
- Screenshot path: auto-advance when the intake detects dropped images (with a
  fallback "Continue" button in case detection lags).

## The wizard

Step 1 — Source choice (the only thing shown when a thread opens):
- Card text: "How do you want to make this video?"
- Two buttons: `From a website` (SRC_URL) and `From my screenshots` (SRC_SHOTS).

Path A — From a website:
1. Click `From a website` -> open the existing capture modal (paste URL).
2. On modal submit -> run the existing `run_video_capture` (Playwright). After
   capture, post the Describe step card.

Path B — From my screenshots:
1. Click `From my screenshots` -> edit the card in place to the Upload step:
   "Drag your screenshots into this thread (up to 12)." Include a fallback
   `Continue` button (SRC_SHOTS_CONTINUE).
2. The existing intake (`VideoThreadIntake.handle_image_drop` -> `run_video_add`)
   already fires on dropped images. After a successful add, post the Describe
   step card (auto-advance). The Continue button posts the Describe step too.

Step 2 — Describe (both paths):
- Card text: "Add a short description of what the walkthrough should show."
- One button: `Add description` (existing DETAILS button -> details modal).
- On details-modal submit -> post the Generate step card.

Step 3 — Generate (both paths):
- Card text: "Ready. Generate when you are. Style and voice are optional."
- Buttons: `Generate video` (existing GENERATE) and `Style & voice` (OPTIONS).
- `Style & voice` -> edit the card in place to reveal the three existing selects
  (style, voice, mode) plus `Generate video` and a `Back` button. Selecting a
  value uses the existing `run_video_set_field` (persists to DB); the card stays
  on the options view until Generate or Back.

## Card-advance pattern

Verified against the code (see reviewer notes):
- In-place edit IS supported: a component handler returns `{"type":
  UPDATE_MESSAGE, "data": {...}}` and the message is edited in place (already
  used at discord_commands.py:288-289, :332, :1420, :1443). So source-buttons,
  Style & voice, Back, and Continue can edit their own card.
- BUT the `options` handler needs network reads first (get_video for current
  style/voice/mode AND the voices catalog for build_voice_select). Doing 2-3
  awaits inline before returning UPDATE_MESSAGE is borderline against Discord's
  3s window. So the options handler acks `DEFERRED_UPDATE_MESSAGE` and then
  `edit_original`s the component message with the options card (do NOT do the
  reads inline). Same for any handler that must hit the network before editing.
- Modal submits (capture, details) and the on_message intake (dropped images)
  do NOT carry the studio card message, so they POST the next step card as a NEW
  message in the thread. IMPORTANT: today the modal-submit contexts have NO
  new-message poster (see "Handler wiring", below) — that wiring is the
  load-bearing change of this spec.
- When choosing the URL source, the srcurl handler acks MODAL (opens the capture
  modal); it cannot also edit Step 1 in the same response. After the capture
  runner posts the Describe card, the Step 1 card is left behind. To avoid a
  dangling Step 1, the srcurl handler should, before/after opening the modal,
  not be relied on to edit; instead accept that Step 1 remains until capture
  posts Describe. (Acceptable: Step 1's buttons re-open the modal harmlessly.)
  For the screenshots path, the srcshots handler DOES edit Step 1 in place
  (UPDATE_MESSAGE) to the Upload step, so that branch has no dangling Step 1.

## Components / custom_ids (video_panel.py)

New:
- `SRC_URL_PREFIX = "aiuivid:srcurl:"`, `is_vid_src_url`, `job_from_src_url`
- `SRC_SHOTS_PREFIX = "aiuivid:srcshots:"`, `is_vid_src_shots`, `job_from_src_shots`
- `SRC_SHOTS_CONTINUE_PREFIX = "aiuivid:srcshotsgo:"`, predicate + extractor
- `OPTIONS_PREFIX = "aiuivid:options:"`, `is_vid_options`, `job_from_options`
- `OPTIONS_BACK_PREFIX = "aiuivid:optionsback:"`, predicate + extractor

New builders (each returns only the current step's rows):
- `build_source_components(job_id)` -> Step 1 (two buttons).
- `build_source_chosen_text(kind)` -> the "Source: website/screenshots" resolved
  text used when editing Step 1 in place.
- `build_upload_components(job_id)` -> Upload step (Continue button + instruction).
- `build_describe_components(job_id)` -> Describe step (Add description button).
- `build_generate_step_components(job_id)` -> Generate step (Generate + Style & voice).
- `build_options_components(job_id, voices, current_style, current_voice, current_mode)`
  -> the three selects + Generate + Back (reuses build_style_select/voice/mode).

Reused unchanged: `build_capture_modal`, `build_details_modal`,
`build_style_select`, `build_voice_select`, `build_mode_select`,
`build_done_components`, `build_refine_modal`, `build_proposal_components`.

Removed/replaced: `build_studio_components` is replaced by
`build_source_components` at the New-video entry point (discord_commands.py
around the `post_channel_message(... build_studio_components ...)` call). Keep
`build_generate_row` or fold it into `build_generate_step_components`.

## Handlers (discord_commands.py)

- `aiuivid:srcurl:*` -> ack MODAL, open `build_capture_modal(job_id)`. (Before
  opening the modal there is no card edit; after capture the runner posts the
  Describe step. Optionally also edit Step 1 to "Source: website" via a separate
  follow-up edit using the interaction's message.)
- `aiuivid:srcshots:*` -> ack UPDATE_MESSAGE, edit the card to
  `build_upload_components(job_id)`.
- `aiuivid:srcshotsgo:*` (Continue) -> this is a component interaction, so ack
  UPDATE_MESSAGE to resolve the Upload card (strip its Continue button, show
  "Screenshots added"), and spawn a background `post_channel_message` of
  `build_describe_components(job_id)` so Describe appears as the next card. (No
  dangling Continue button left behind.)
- `aiuivid:options:*` -> ack DEFERRED_UPDATE_MESSAGE (not inline UPDATE_MESSAGE:
  it must hit the network first), then read current style/voice/mode via
  `get_video(email, job_id)` AND the voices catalog (the same call
  `_open_video_studio` uses, e.g. get_video_voices), and `edit_original` the
  component message with `build_options_components(job_id, voices, style, voice,
  mode)`. Confirm the exact tasks-client method names against commands.py
  (`get_video` GET /api/video-jobs/{job_id} exists; voices via the same helper
  _open_video_studio already calls).
- `aiuivid:optionsback:*` -> ack UPDATE_MESSAGE, edit back to
  `build_generate_step_components(job_id)`.
- Existing style/voice/mode select handlers: unchanged (still call
  run_video_set_field). They now appear only on the options view.

## Handler wiring for modal submits (BLOCKING fix)

Reality check (verified): `run_video_add` (commands.py:2373-2378) and
`run_video_capture` (commands.py:2411-2415) post a component row ONLY when
`ctx.respond_components is not None`. The modal-submit contexts built by
`_handle_video_capture_modal` (discord_commands.py:1078-1083) and
`_handle_video_details_modal` (:1053-1057) set ONLY `ctx.respond` —
`respond_components`/`notify_channel_msg` are None. The only place a real
new-message poster is wired is `video_intake.py` `_thread_ctx`
(post_channel_message) and `_handle_video_route` (discord_commands.py:851-878).

So before the runner-advance changes can work, wire a new-message poster into
both modal-submit contexts: in `_handle_video_capture_modal` and
`_handle_video_details_modal`, build the CommandContext with
`respond_components` (and/or `notify_channel_msg`) set to a `post_channel_message`
into the thread, exactly as `_handle_video_route` / `video_intake._thread_ctx`
do. Without this, the capture and details steps dead-end. This is the single
most important change in the spec.

## Runner / intake advance (commands.py, video_intake.py)

- `run_video_capture` (commands.py ~2411): today posts `build_generate_row` when
  respond_components is set; change that to post `build_describe_components(job_id)`
  (Describe is the next wizard step). Keep the "Capturing..." progress message.
  Now reachable from the capture modal because of the wiring fix above.
- `run_video_add` (commands.py ~2373): today posts `build_generate_row`; change
  to post `build_describe_components(job_id)`. GUARD against auto-advance
  double-fire: each dropped-image message fires `handle_image_drop` -> run_video_add
  independently, so dropping several screenshots posts several Describe cards.
  Post Describe ONLY on the first add (when the draft had zero screenshots before
  this add; the runner already fetches the draft via get_current_video_draft, so
  compare the prior count). Subsequent adds just update the "N/12" text.
  CAVEAT: run_video_add is shared by `/video add` (ephemeral edit_original) and
  the image-drop intake (post_channel_message); the change affects both surfaces.
- `run_video_set_details` (commands.py ~2428): today only calls `ctx.respond(text)`.
  Change to post `build_generate_step_components(job_id)` via the new poster wired
  into the details-modal context. Keep a short confirmation line.

## Entry point changes (_open_video_studio, discord_commands.py:985-1023)

- Replace the `post_channel_message(... build_studio_components ...)` call with
  `build_source_components(job_id)` (the Step 1 card).
- REMOVE the up-front dump of six voice-preview MP3s (:985-1000). Voices now live
  behind the optional Style & voice button, so previewing all voices at thread
  open reintroduces the exact clutter this redesign removes. (If previews are
  still wanted, surface them only inside the options view later; out of scope
  here, just drop the up-front dump.)
- Rewrite the long `studio_msg` text (:1003-1018) from the old all-at-once
  4-step description to a one-line Source-step prompt that matches the Step 1
  card, e.g. "Let's make a video. How do you want to start?".
- Pre-attached screenshots path (`_open_video_studio` called with
  `screenshot_urls`, :976-983, from `/video new`): this bypasses the source
  choice because screenshots already exist. In that case skip Step 1 and post
  `build_describe_components(job_id)` directly.

## Embed copy (build_video_embed)

Update the how-it-works text to describe the two paths:
"1. Click New video. 2. Choose your source: paste a website link (we screenshot
it) or drag your own images. 3. Add a short description. 4. Generate."

## Testing

- test_video_panel.py:
  - Assert each new builder returns the expected single-step rows and that the
    new predicates/extractors round-trip the job_id.
  - Add a DISJOINTNESS guard test (mirror the existing one at
    test_video_panel.py:347-349): assert `is_vid_src_shots("aiuivid:srcshotsgo:x")
    is False` and `is_vid_options("aiuivid:optionsback:x") is False`. The safety
    of the whole routing chain depends on every new prefix keeping its trailing
    colon; this test locks that in.
  - KEEP `build_generate_row` exported (test_video_panel.py imports it at module
    top, :6-7; removing it fails every test at import). Reuse it inside
    `build_generate_step_components` rather than deleting it.
  - Update the old 5-row assertion (test_studio_components..., :314-325) to the
    new builders. If `build_studio_components` is removed, also fix the top-level
    import so the module still imports.
- test_video_routing.py: the new custom_ids dispatch to the right handlers with
  the right ack type (srcurl -> MODAL; srcshots/optionsback -> UPDATE_MESSAGE;
  options -> DEFERRED_UPDATE_MESSAGE; srcshotsgo -> UPDATE_MESSAGE + spawns a
  channel post).
- test_video_runners.py: run_video_capture and run_video_add (first add) post the
  Describe step; run_video_add on a non-empty draft does NOT post Describe again;
  run_video_set_details posts the Generate step via the newly-wired poster (assert
  a posted card, not ctx.respond text). Update :35, :85, :242 accordingly.
- test_video_intake.py: a dropped image still routes to run_video_add (unchanged
  contract); auto-advance is covered by the runner test.
- Add/extend a test that the capture-modal and details-modal submit contexts now
  carry a working component poster (the BLOCKING wiring fix), so the next card is
  actually posted.
- Keep all other existing video tests green; update only those that asserted the
  old single-card layout or the old runner replies.

## Rollout

- webhook-handler only (the Discord bot). No tasks-service or DB change.
- Deploy per CLAUDE.md: this is the webhook-handler, NOT covered by the
  orchestrator script. Deploy with per-file scp then rebuild webhook-handler.
- After deploy, re-pin / re-post the #video-generation panel if the embed copy
  changed (the panel message is static; the wizard cards are per-thread).

## Open question for the user

- The output-mode select (Slideshow vs Animated) currently defaults to
  Slideshow. It moves behind the optional Style & voice button. Confirm that is
  fine (it is included there, not removed).
