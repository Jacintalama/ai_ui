# Video Generator on Slack, Cron, and App Builder

Date: 2026-07-06
Status: Approved (Approach A: shared server-side template registry, thin per-surface UI)

## Goal

Bring the video generator to parity across surfaces. Today the web Video Studio
has the full experience (Template vs Custom chooser, 4 templates, voice picker,
default walk-cursor flow). Discord has an older panel, the Slack panel exists in
code but is not confirmed live, cron cannot schedule video renders at all, and
App Builder has no video integration. After this work:

1. Slack and Discord panels offer the same 4 templates plus the existing voice
   pick, and the Slack panel is live and pinned.
2. The cron system supports a dedicated `video` schedule kind that renders a
   video on schedule and delivers it to the schedule's thread, with no LLM in
   the loop.
3. Every built app in "My apps" (Slack and Discord) has a one-click
   "Walkthrough video" button that produces the default walk-cursor tour of the
   app's preview URL.

Out of scope: font and background pickers in chat surfaces (AI decides, same as
the web "None" default), NL intent routing for scheduled video prompts, web UI
changes beyond fetching templates from the new endpoint.

## 1. Shared foundation: server-side template registry

- New `mcp-servers/tasks/video_templates.py` with `VIDEO_TEMPLATES`, the same 4
  entries currently hardcoded in `static/video.html` (~line 2021): key, emoji,
  name, optional badge, desc, style, remotion flag, prompt.
  Keys: `walkthrough` (Recommended), `product`, `cinematic`, `social`.
- New endpoint `GET /api/video-jobs/templates` in `routes_video.py`, same auth
  shape as `/api/video-jobs/voices`. Returns `{"templates": [...]}`.
- `static/video.html` fetches the endpoint on load and rebuilds the template
  grid from it; the current inline `VIDEO_TEMPLATES` list stays as a fallback
  used only if the fetch fails. Preview MP4s keep resolving by key
  (`/tasks/static/tpl-previews/<key>.mp4`).
- `webhook-handler/clients/tasks.py`: `get_video_templates()` (cached per
  process for a few minutes, like voices if voices cache; otherwise plain call).

Single source of truth: adding a template server-side makes it appear on web,
Slack, Discord, cron, and App Builder without further edits (a preview MP4 by
key is still needed for the web grid).

## 2. Slack and Discord panels: template + voice

Identical semantics on both platforms:

- A Template select is added with options: Custom (no template, default) plus
  the 4 templates (emoji + name).
- Choosing a template sets the job's style, and when the title/description
  modal opens, the description field is prefilled with the template's prompt
  (editable). Both platforms support initial values in modals.
- At generate time, if a template is selected and the prompt is empty, the
  template's prompt is used. An empty prompt with no template keeps the default
  walk-cursor behavior (backend already handles it).
- Voice selects already exist on both surfaces and are unchanged.

Surface specifics:

- Discord (`handlers/video_panel.py`): template select joins the existing
  options components (style and voice selects). New custom_id prefix
  `aiuivid:tpl:`.
- Slack (`handlers/slack_video_panel.py`): template select block added to the
  create modal above style/voice, with `dispatch_action` enabled. On selection
  the handler calls `views.update` to prefill the prompt input with the
  template's prompt (only when the prompt is still empty or still equal to a
  template prompt, so a user's typed text is never clobbered). Selection is
  also read from modal state on submit, and the empty-prompt fallback applies
  regardless, so the flow works even if the update round trip fails.
- Slack go-live: confirm handlers are registered in the live container, then
  run `scripts/setup_slack_video_channel.py` on the box and pin the panel in
  the Slack video channel.

## 3. Cron: dedicated `video` schedule kind

Data model (`mcp-servers/tasks/models.py`, `tasks.schedules`):

- `kind` Text NOT NULL server_default `'agent'`. Existing rows keep working
  untouched.
- `video_config` JSONB nullable: `{url, template, prompt, voice, title}`.

Migration: additive `ALTER TABLE` (server_default makes it safe on live data).

Creation UX: the existing cron panels (Slack and Discord) gain a
"Schedule a video" button that opens a modal: name, site URL, cron expression
(reusing the existing schedule time UX), template select. Submitting stores a
row with `kind='video'`, `video_config` filled, and the usual
`delivery_channel_id` / `delivery_platform` thread wiring.

Execution (`mcp-servers/tasks/scheduler.py`):

- `_run_scheduled_task` branches on `sched.kind`. `agent` keeps the current
  remote-executor path byte-for-byte.
- `video`: runs the pipeline directly inside the tasks service as
  `sched.user_email`: create draft (title from config or schedule name, prompt
  from config which may be empty for the walk default), `capture-from-url`,
  set voice/style if configured, queue, then poll the job bounded at 15
  minutes.
- Delivery goes through the existing `_deliver_result` seam into the
  schedule's thread: success posts the video link and, where the platform size
  cap allows, the MP4 file itself via the existing post-file path; timeout
  posts "still rendering" with a Video Studio link; failure posts the same
  clean failed-run message agent schedules use.
- Concurrency: renders serialize through the existing video worker queue, so
  overlapping fires wait rather than OOM the 3.8GB box.

## 4. App Builder: "Walkthrough video" in My apps

- The per-project menu in My apps (Slack and Discord) gains a
  "Walkthrough video" button next to Preview and Delete.
- Handler flow (reusing the existing video runner in
  `webhook-handler/handlers/commands.py`): resolve the app's preview URL,
  create a draft (title = app name, prompt = ""), `capture-from-url`, queue,
  poll, then post the finished MP4 (or link when over size caps) back into the
  same thread or DM the menu lives in.
- Empty prompt means the backend takes the default walk-cursor path: the video
  is the clicking-cursor tour of the built app with the music bed. No options
  UI, one click.

## 5. Error handling

- Capture failures (unreachable site, SSRF-blocked URL, no frames) surface the
  existing clean CaptureError message on every surface.
- Cron and App Builder renders that exceed the wait bound post a
  "still rendering" message with a Video Studio link instead of hanging.
- File posting always falls back to link-only when the platform rejects or
  caps the upload.
- Video schedule runs record `last_run_status` like agent runs so the panel
  list stays truthful.

## 6. Testing and deploy

Unit tests, no live renders:

- tasks: template endpoint shape; scheduler dispatch of `kind='video'` with the
  pipeline faked (asserts draft/capture/queue/poll/deliver order, timeout path,
  failure path); model/migration default of `kind`.
- webhook-handler: panel builders emit the template select (Slack and Discord);
  template-selected prefill and empty-prompt fallback at generate time; My apps
  menu includes the button; button handler drives the runner with the preview
  URL and empty prompt.
- web: video.html template fetch falls back to the inline list on error
  (existing UI smoke suite extended).

Deploy: tasks via `deploy_orchestrator.sh`; webhook-handler manually, one scp
per changed file, then rebuild. Verify: `/tasks/healthz`, one real scheduled
video run delivering to its thread, one real App Builder button click, Slack
panel pinned and generating.
