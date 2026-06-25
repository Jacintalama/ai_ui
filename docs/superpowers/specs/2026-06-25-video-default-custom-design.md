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

### Every site that posts the describe card (ALL FOUR must change)
There are FOUR posters of `build_describe_components`; the choice card must
replace it at all four, or the screenshot path silently keeps the old
describe-only card:
1. `commands.py:2417` `run_video_capture` (wizard "From a website") -> post
   `build_choice_components(draft["id"])`.
2. `commands.py:2375-2381` `run_video_add` (first add only, prior_count==0) ->
   `build_choice_components(draft["id"])`. Subsequent adds (:2384) unchanged.
3. `discord_commands.py:939-949` `_post_video_describe` (called at :495 from the
   "From my screenshots" Continue/auto-advance path) -> post
   `build_choice_components(job_id)` and update its text from "Add a short
   description..." to the choice wording.
4. `discord_commands.py:1085-1089` (`/video new` with pre-attached screenshots)
   -> post `build_choice_components(job_id)`.
- `run_video_set_details` (Custom path): unchanged - still posts
  `build_generate_step_components` after the user submits their direction.

### discord_commands.py (handler)
- New routing branch: `vid.is_vid_gennow(custom_id)` -> Default path. CRITICAL:
  route it through `_handle_video_route` (exactly like the `is_vid_generate`
  handler at discord_commands.py:433-440), NOT the `_run_video_set` context. Only
  `_handle_video_route` binds `notify_channel`/`notify_channel_msg` (:919-921),
  and `run_video_generate` only spawns the result watcher when
  `ctx.notify_channel is not None` (commands.py:2467). If you mirror the select
  handler instead, the render finishes but the MP4 is NEVER delivered.
  Inside that route, the runner must:
  1. set animated first: `await run_video_set_field(ctx, job_id, render_mode="animated")`
     (commands.py:2421-2430; calls set_video_draft_fields). MUST be awaited BEFORE
     queue, because `run_video_generate`/`queue_video` reads render_mode from the
     persisted draft, not from a param.
  2. then `await run_video_generate(ctx, job_id)` (queue + watch + deliver).
  Practically: add a small runner (e.g. `run_video_gennow(ctx, job_id)`) that does
  set-then-generate, and dispatch gennow via `_handle_video_route(payload, lambda
  ctx, j=job_id: self.router.run_video_gennow(ctx, j))`.
  NOTE: `run_video_set_field` swallows errors (logs only, commands.py:2431-2432).
  If the PATCH fails the job renders the DB-default slideshow (degraded, not
  broken). Acceptable; document it.
- The existing "Add direction" (details) handler is unchanged.

## Slack changes (slack_video_panel.py)
- In `build_video_modal(channel_id)`: make the Description input `optional` (not
  required) and add a hint in its label/placeholder: "Leave blank to let the AI
  direct it." For the output-mode default, flip the module constant
  `DEFAULT_MODE` (slack_video_panel.py:38) from "slideshow" to "animated" - it
  drives BOTH the select's initial_option (:119/:221) AND the parse fallback
  (`_sel(..., DEFAULT_MODE)` at :249), so flipping the constant keeps them
  aligned. Do NOT change only the initial_option (the fallback would disagree).
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
- Update test_video_runners.py:36 (asserts first add posts build_describe_components)
  to expect build_choice_components.
- Add coverage for the screenshot path: assert `_post_video_describe` and the
  `/video new` pre-attached block now post build_choice_components (these have no
  existing tests, so the change is otherwise uncaught).
- Keep build_describe_components exported (test_video_panel.py:377 imports it).

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
