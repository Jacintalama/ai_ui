# Sub-project 3: Default vs Custom video flow (Discord + Slack)

Date: 2026-06-25
Status: Approved design, pending spec review
Branch: feat/video-default-custom (off origin/main)

## Goal

After a source is ready (URL captured, or screenshots uploaded), let the user
choose between Default (the AI directs the whole video, no input) and Custom (the
user gives free-text creative direction). The brain (already live) turns an empty
prompt into a real kinetic video, so Default is "Generate now". webhook-handler
only; the tasks service is untouched.

## Approved decisions

- Discord: ONE card after the source is ready, two buttons: "Generate now" (Default)
  and "Add direction" (Custom). Applies to BOTH the website and screenshot paths.
- Default forces kinetic Animated render mode.
- Custom = the existing description-modal -> Generate path, unchanged.
- Slack: keep the single modal; make Description OPTIONAL with a hint (blank =
  Default), and default the output-mode select to Animated.

## Non-goals

- No tasks-service change (the brain already handles an empty prompt). No DB
  default change. No new env var.
- No change to the capture/render pipeline or the brain.

## Discord changes

### video_panel.py
- Add `build_choice_components(job_id)` -> one ACTION_ROW with two buttons:
  - "Generate now" -> `GENNOW_PREFIX = "aiuivid:gennow:"` + job_id (STYLE_SUCCESS)
  - "Add direction" -> the EXISTING `DETAILS_PREFIX` + job_id (STYLE_SECONDARY)
    (reuse the existing details button id, which already opens the description modal)
- Add predicate/extractor: `is_vid_gennow`, `job_from_gennow` (trailing-colon
  prefix, disjoint from existing ids - confirm no startswith collision).
- Keep `build_describe_components` exported if any test imports it; it is simply
  no longer posted by the runners (replaced by build_choice_components). If
  removing it, update its tests.

### commands.py (runners that post the next card)
- `run_video_capture`: after a successful capture it currently posts
  `build_describe_components`; change to post `build_choice_components(job_id)`.
- `run_video_add` (first add): same change -> post `build_choice_components`.
- `run_video_set_details` (Custom path): unchanged - still posts
  `build_generate_step_components` after the user submits their direction.

### discord_commands.py (handler)
- New routing branch: `vid.is_vid_gennow(custom_id)` -> Default path. It must:
  1. set the job to animated: `run_video_set_field(ctx, job_id, render_mode="animated")`
     (or the tasks-client `set_video_draft_fields(email, job_id, render_mode="animated")`
     used by the existing select handlers) - this is a bot-side call to the
     existing endpoint, no tasks redeploy.
  2. then queue + watch + deliver via the existing `run_video_generate(ctx, job_id)`.
  Ack type + context: mirror the existing generate-button handler
  (`is_vid_generate` -> `_handle_video_route` -> run_video_generate). The gennow
  handler does the same, with the render_mode set first.
- The existing "Add direction" (details) handler is unchanged.

## Slack changes (slack_video_panel.py)
- In `build_video_modal(channel_id)`: make the Description input `optional` (not
  required) and add a hint line in its label/placeholder: "Leave blank to let the
  AI direct it." Change the output-mode static_select `initial_option` from
  slideshow to ANIMATED.
- `parse_video_modal`: already returns prompt; an empty string is fine.
- `_run_slack_video`: already passes the (possibly empty) prompt to
  create_video_draft; the brain directs when empty. No change needed beyond
  confirming it tolerates an empty prompt (it does). The view_submission handler
  for create must NOT reject an empty description (today the modal makes it
  required; once optional, Slack allows blank submit). Keep the URL validation.

## Error handling
- gennow on a job with no screenshots: should not happen (the choice card is only
  posted after capture/upload), but if it does, the worker's deterministic
  fallback still renders. No special-case needed.
- All existing error paths (capture fail, render fail) unchanged.

## Testing
- test_video_panel.py: build_choice_components returns the two buttons with the
  right ids (gennow + details); is_vid_gennow/job_from_gennow round-trip;
  disjointness (gennow vs other aiuivid prefixes).
- test_video_runners.py: run_video_capture and run_video_add (first add) post
  build_choice_components (not the old describe card).
- test_video_routing.py: gennow custom_id dispatches to the Default handler;
  assert it sets render_mode=animated then calls generate (mock the tasks client
  + run_video_generate).
- test_slack_video_panel.py: build_video_modal's description block is optional and
  the mode select defaults to animated.
- Update any test that asserted run_video_capture/add post build_describe_components.

## Rollout
- webhook-handler only. NOT covered by the orchestrator: deploy via per-file scp
  of the changed handler files + `docker compose -f docker-compose.unified.yml up
  -d --build webhook-handler`, key ~/.ssh/aiui_vps. Drift-check first (compare
  the running container's copies, normalized, vs HEAD).
- After deploy: in #video-generation click New video -> From a website -> paste a
  URL -> on the choice card click "Generate now" -> confirm a kinetic video is
  produced with no description. Then test "Add direction" (Custom). On Slack,
  submit the modal with a blank description and confirm it generates.

## Open question
- "Add direction" reuses the existing details button id. Confirm the details modal
  still posts build_generate_step_components on submit (Custom then hits Generate).
  If a more direct "enter direction then auto-generate" is wanted later, that is a
  follow-up; for now Custom keeps the explicit Generate step.
