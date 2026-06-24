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

- Component-button transitions where we hold the card message (source buttons,
  Style & voice, Back): respond with UPDATE_MESSAGE to edit the SAME card in
  place, so there is always exactly one active card and no stale live buttons.
- Transitions that come from a modal submit (capture, details) or from the
  on_message intake (dropped images): POST the next step card as a new message
  (this matches the existing post-after-capture pattern; those interactions do
  not cleanly carry the studio card message to edit). When choosing the URL
  source, edit Step 1 in place first to "Source: website" with no buttons, so
  the resolved step has no dangling controls.

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
- `aiuivid:srcshotsgo:*` (Continue) -> post `build_describe_components(job_id)`.
- `aiuivid:options:*` -> ack UPDATE_MESSAGE, fetch current style/voice/mode via
  get_video, edit the card to `build_options_components(...)`.
- `aiuivid:optionsback:*` -> ack UPDATE_MESSAGE, edit back to
  `build_generate_step_components(job_id)`.
- Existing style/voice/mode select handlers: unchanged (still call
  run_video_set_field). They now appear only on the options view.

## Runner / intake advance (commands.py, video_intake.py)

- `run_video_capture` (commands.py ~2380): after a successful capture it already
  posts a generate row; change it to post `build_describe_components(job_id)`
  instead (Describe is the next wizard step). Keep the progress message.
- `run_video_add` (commands.py ~2349): after a successful screenshot add it
  posts a generate row; change it to post `build_describe_components(job_id)`.
- `run_video_set_details` (commands.py ~2428): after saving details it posts a
  text confirmation; add posting `build_generate_step_components(job_id)`.

## Embed copy (build_video_embed)

Update the how-it-works text to describe the two paths:
"1. Click New video. 2. Choose your source: paste a website link (we screenshot
it) or drag your own images. 3. Add a short description. 4. Generate."

## Testing

- test_video_panel.py: assert the new builders return the expected single-step
  rows and that the new predicates/extractors round-trip the job_id. Update or
  remove assertions that referenced the old `build_studio_components` 5-row shape.
- test_video_routing.py: the new custom_ids dispatch to the right handlers with
  the right ack type (srcurl -> MODAL, srcshots/options/optionsback ->
  UPDATE_MESSAGE, srcshotsgo -> message post).
- test_video_runners.py: run_video_capture and run_video_add post the Describe
  step; run_video_set_details posts the Generate step.
- test_video_intake.py: a dropped image still routes to run_video_add (unchanged
  contract); the auto-advance is covered by the runner test.
- Keep all other existing video tests green; update only those that asserted the
  old single-card layout.

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
