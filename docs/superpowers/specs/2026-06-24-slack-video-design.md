# Slack Video Generation (URL path) Design

Date: 2026-06-24
Status: Approved design (user approved URL-only scope; Slack app works; channel ready), pending implementation
Branch: feat/slack-video (off origin/main)

## Goal

Bring video generation to Slack in the `#video-generation` channel (id
`C0BCRE20JNR`), URL path only: a user clicks a button, fills one modal (website
URL + description, optional style/voice/mode), and the bot screenshots the site
and renders a narrated video, posting the result back in the channel with a
Refine option. Reuses the entire existing capture + render backend; this is a
Slack-UI port only.

## Non-goals

- No Slack screenshot upload path (file_shared / files:read) in this spec. URL only.
- No change to the tasks service, capture, or render pipeline.
- No DMs (avoids the im:write scope reinstall); everything posts in the channel.

## Approved decisions

- URL path only (single source -> a single modal, not a multi-step wizard).
- Slack app already has interactivity + chat:write + modal support (open_modal,
  view_submission are used by the schedule and recruiting panels).
- Deliver results in the channel as a LINK (no files:write needed).

## Key Slack constraints (verified)

- `trigger_id` expires ~3s after the interaction. The button handler MUST call
  `slack.open_modal(trigger_id, view)` with NO awaited network call before it.
  Therefore the modal's style/voice/output-mode option lists are STATIC in the
  builder (hardcoded, mirroring Discord's `STYLES` constant in video_panel.py),
  not fetched from `/voices`. The known voices (amy, ryan, lessac, joe, alan,
  alba) are listed in the builder.
- `view_submission` must return within ~3s. So the handler validates input,
  returns an immediate ack/clear response, and runs the heavy work (create draft
  -> set fields -> capture -> queue -> watch -> deliver) in a background task,
  exactly as the existing Slack flows spawn `asyncio.create_task`.

## Architecture

### New: webhook-handler/handlers/slack_video_panel.py (pure builders)
Block Kit builders + action_id constants (namespace `aiuivid_slack:` or reuse a
short prefix consistent with other slack panels). No I/O.
- `build_video_panel()` -> the channel panel blocks: a header + a
  `New video from a website` button (action_id e.g. `slackvid_new`) and a
  `My videos` button (`slackvid_list`).
- `build_video_modal()` -> the `view` for views.open: a modal with
  - URL (plain_text_input, required, block_id `url`)
  - Description (plain_text_input multiline, required, block_id `prompt`)
  - Title (plain_text_input, optional, block_id `title`)
  - Style (static_select, optional, hardcoded options: clean_product_demo
    [default], cinematic, snappy_social)
  - Voice (static_select, optional, hardcoded 6 voices, amy default)
  - Output mode (static_select, optional: slideshow [default], animated)
  - `callback_id` e.g. `slackvid_create` so view_submission routes here.
- `parse_video_modal(view)` -> dict {url, prompt, title, style, voice, mode}
  reading the submitted state values (mirror app-builder's
  description-extraction helper).
- `build_result_blocks(job, share_url)` -> the done message blocks with a
  `Refine` button (`slackvid_refine:<job_id>`).
- `build_refine_modal(job_id)` -> modal with a "what should change?" input
  (`callback_id slackvid_refine_submit`, private_metadata carries job_id).
- `build_proposal_blocks(job_id)` / apply button (`slackvid_apply:<job_id>`).
- `build_list_blocks(jobs)` -> the My videos list (recent jobs + a Refine on each).

### Handlers: webhook-handler/handlers/slack_interactions.py (extend)
- block_actions:
  - `slackvid_new` -> `open_modal(trigger_id, build_video_modal())` immediately
    (NO await before). 
  - `slackvid_list` -> spawn a task: fetch the user's videos via tasks-client and
    post `build_list_blocks` (this is not trigger-bound, so awaits are fine; it
    posts a message, not a modal).
  - `slackvid_refine:<job>` -> open_modal(build_refine_modal(job)) immediately.
  - `slackvid_apply:<job>` -> spawn apply + watch.
- view_submission:
  - `slackvid_create` -> parse modal, validate URL present; return an immediate
    empty/clear ack; spawn `_run_slack_video(...)`.
  - `slackvid_refine_submit` -> parse, spawn refine; if a proposal returns, post
    the Apply button.

### Slack runner + deliver (slack_interactions.py or a small helper)
`_run_slack_video(user_id, channel_id, fields)`:
1. Resolve the user's email (existing Slack->email mapping used by other flows).
2. `create_video_draft(email, title, prompt, style, voice)` (tasks-client; add
   render_mode if the client method supports it, else draft-set it).
3. If style/voice/mode need setting beyond create, call `set_video_draft_fields`.
4. Post "Working on it: capturing {host}..." to the channel.
5. `capture_video_screenshots(email, job_id, url)`.
6. `queue_video(email, job_id)`.
7. Poll `get_video(email, job_id)` until done/failed (a Slack version of the
   Discord `_watch_video` loop). On done, post `build_result_blocks(job,
   share_url)` to the channel; on failed, post a clean error.
All tasks-client methods already exist (used by Discord). Reuse them; do not
duplicate. The only Slack-specific code is the posting/formatting + the poll
loop's delivery target (slack.post_message instead of Discord).

### Setup: webhook-handler/scripts/setup_slack_video_channel.py
Posts `build_video_panel()` into `#video-generation` via chat.postMessage. Takes
the channel id from an env/arg (default the known `C0BCRE20JNR`), mirroring
setup_video_channel.py (Discord). Idempotent enough: it just posts the panel
message; re-running posts another (operator runs once). The bot must be a member
of the channel (it is: AIUI-Automation joined).

## Error handling

- Missing/invalid URL in the modal: return a Slack `response_action: errors`
  on the URL block (Slack's native modal validation), so the user sees the
  error inline.
- Capture/queue/render failures: post a clean "Couldn't make the video: <reason>"
  in the channel (never raw tracebacks). The disk-guard 507 surfaces as a
  friendly "the render box is low on storage, try again later".
- Slack API errors (not_in_channel, etc.): log; if the panel post fails because
  the bot is not in the channel, the setup script reports it clearly.

## Testing

- test_slack_video_panel.py: builders return well-formed blocks/views; the modal
  has the required inputs with the right block_ids; parse_video_modal round-trips
  a sample view_submission payload; action_id/callback_id constants.
- test_slack_video_interactions.py: `slackvid_new` opens a modal (mock
  slack.open_modal, assert called with NO preceding tasks-client await);
  `slackvid_create` view_submission parses + spawns the runner (mock tasks
  client); refine/apply dispatch.
- Mirror the existing slack panel test style (the app-builder/schedule tests).
- No real Slack or tasks calls in tests (mock the slack client + tasks client).

## Rollout

- webhook-handler only (the bot). NOT covered by the orchestrator script: deploy
  via per-file scp of the new/changed handler files + the setup script, then
  `docker compose -f docker-compose.unified.yml up -d --build webhook-handler`.
  Use the working key `~/.ssh/aiui_vps`.
- After deploy, run the setup script (or a one-off chat.postMessage) to post the
  panel into `#video-generation` (C0BCRE20JNR). Verify the bot is in the channel.
- Verify end to end: click New video, submit a URL, confirm the video link posts.

## Open questions for the user

- Confirm the bot user that posts is the same Slack app whose token the
  webhook-handler holds (SLACK_BOT_TOKEN). The channel shows AIUI-Automation +
  aiui app present; the build will use the configured bot token.
