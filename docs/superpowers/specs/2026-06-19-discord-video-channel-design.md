# Discord Video Generation Channel — Design

- **Date:** 2026-06-19
- **Status:** Approved (design); pending implementation plan
- **Branch:** `feat/discord-video-channel` (off `fork/main`)
- **Author:** Jacint (via Claude)

## 1. Summary

Add a `#video-generation` Discord channel whose bot lets a user generate a narrated
slideshow video **at full parity with the web Video Studio** — create, refine,
version history / revert, and list — by driving the **existing** `tasks`-service
video pipeline (`/api/video-jobs/*`). The render pipeline, styles, voices, plan
generation, storage, capability links, and cleanup are reused **unchanged**.

The only server-side work is a thin **URL-based intake** so the bot can hand
Discord CDN image URLs to the server (Discord modals cannot carry files), plus a
`collecting` draft state so a multi-step "details first" wizard can accumulate
inputs before rendering.

The bot is **interactions-only** (buttons, modals, selects, slash commands). It does
**not** depend on the Discord Gateway (which in this codebase exists only inside the
voice bot and only runs when `ELEVENLABS_API_KEY` is set). This keeps a core feature
decoupled from whether voice is enabled.

## 2. Background (how things work today)

### Video backend — `mcp-servers/tasks`
- Router `routes_video.py`: `APIRouter(prefix="/api/video-jobs")`, mounted in
  `main.py` with no extra prefix; container listens on port **8210**.
- Edge: Caddy has no `/api/video-jobs` block → catch-all → API Gateway
  (`api-gateway/main.py`) maps `/api/video-jobs*` → `http://tasks:8210` verbatim.
  The gateway **strips** client identity headers and **injects** `X-User-Email` /
  `X-User-Admin` from the validated JWT.
- Auth: `current_user` (`auth.py`) reads `X-User-Email` (lowercased), 401 if missing.
  **Ownership key = `user_email` string**, checked on every read/mutate:
  `if not user.is_admin and job.user_email != user.email: 403`.
- Existing endpoints:
  - `POST /api/video-jobs/upload` (multipart: `title` 1–200, `prompt` 1–2000,
    `style`, `voice`, `files` 1–12 images) → `{id, status:"queued"}` (201).
  - `GET /api/video-jobs` → caller's jobs.
  - `GET /api/video-jobs/voices` (**no auth**) → voice catalog with `sample_url`.
  - `GET /api/video-jobs/{id}` → status, `queue_position`, `output_available`,
    `conversation`, `current_version_no`, `pending`, `plan`.
  - `GET /api/video-jobs/{id}/download` (capability **or** member auth) → MP4.
  - `POST /api/video-jobs/{id}/refine` `{message}` → `{action:"ask"|"propose",
    message, can_apply}`.
  - `POST /api/video-jobs/{id}/apply` → re-queue.
  - `POST /api/video-jobs/{id}/screenshots` (multipart) → add shots.
  - `GET /api/video-jobs/{id}/versions`, `POST /api/video-jobs/{id}/revert`.
- Worker (`video_worker.py`): single async loop, picks oldest `queued`, gated by
  free-disk/free-RAM, `build_in_flight`, and the **shared** Postgres advisory lock
  `heavy_job` (renders and app-builds never run at once). Render is fully async
  (~1–5 min) via ffmpeg + Piper TTS; user text never reaches a shell.
- Statuses (DB CHECK, `migrations/021_video_jobs.sql`): `queued, scripting,
  voicing, rendering, done, failed`.
- Styles (`templates_video/style_config.py`): `clean_product_demo` (default),
  `cinematic`, `snappy_social`.
- Voices (`video_voices.py`): `amy` (default), `ryan`, `lessac`, `joe`, `alan`,
  `alba`; each has a pre-rendered sample at `/tasks/static/voices/<id>.mp3`.
- Limits: `VIDEO_MAX_PER_USER_PER_DAY=10`, 10 MiB/file, 50 MiB & 12 files/batch,
  `VIDEO_MIN_FREE_DISK_MB`, `VIDEO_RENDER_TIMEOUT=600s`, plan forced to 720p,
  total ≤ 60 s.
- Download capability: `video_capability.py` `mint_video_capability` /
  `verify_video_capability` — HMAC over `OAUTH_STATE_SECRET`, TTL
  `VIDEO_DL_TTL_SECONDS=1800`, binds `(owner, slug, job_id)`. Enables no-login links.

### Discord bot — `webhook-handler`
- Pure **HTTP interactions** service: `POST /webhook/discord` (`main.py`)
  Ed25519-verifies, then `DiscordCommandHandler.handle_interaction` switches on
  `type` (PING / APPLICATION_COMMAND / MESSAGE_COMPONENT / MODAL_SUBMIT).
- **Routes by `custom_id` namespace prefix, not channel.** Existing namespaces:
  `aiuibuild:*`, `aiuisched:*`, `aiuiout:*`, `cron:*`, `aiuilink:*`. Component
  routing is one `if is_x(custom_id): …` chain; fall-through is a safe no-op.
- **Modals must open synchronously** (`{type: MODAL}`) — Discord cannot
  defer-then-modal. Modal submits flattened to `{custom_id: value}`.
- Channel recipe: `scripts/setup_<feature>_channel.py` (idempotent) + a pure,
  unit-tested `handlers/<feature>_panel.py` (builders + predicates/extractors) +
  router branches + `CommandRouter` runner methods.
- Long jobs report back three ways: interaction token (15-min TTL) edits;
  **bot-token channel/thread posts** (no TTL); **polling watchers** (`_watch_build`
  polls `get_build_status`, posts on completion). Per-user **private threads**
  (`_get_or_make_thread`, type 12) are the durable surface; thread ids persisted
  in the tasks DB by `kind` (`builder`, `schedules`).
- Identity: `_resolve_email` (static `DISCORD_USER_EMAIL_MAP` → DB link store via
  `aiuilink:*`), `_resolve_email_for_ctx` (platform-aware; `_respond_not_linked`
  on `None`), `_resolve_email_auto` (synthetic `discord-{id}@aiui.local`). The
  resolved email becomes `X-User-Email`.
- `clients/tasks.py` `TasksClient`: per-user calls send **only** `X-User-Email`;
  system calls (`/discord-links/*`) send `X-Internal-Secret`. Base URL
  `settings.tasks_url` (default `http://tasks:8210`). **No video methods exist yet.**
- Existing file intake is the slash-command **ATTACHMENT** option (type 11):
  `DiscordCommandHandler._first_attachment` reads `data.resolved.attachments`
  (currently one file) → `CommandContext.attachment`.
- The Gateway (`voice_bot.py`, `ConversationalVoiceBot`, `intents.message_content`)
  is the only thing that can see plain chat messages; it starts **only** when
  `DISCORD_BOT_TOKEN` **and** `ELEVENLABS_API_KEY` are set (`main.py:223`).

## 3. Goals / non-goals

**Goals**
- Full parity with the web Video Studio: generate, refine, versions/revert, list.
- Interactions-only — no Gateway / voice dependency.
- Reuse the existing render pipeline and all its safety guards untouched.
- Require account linking; videos owned by the user's real email.
- Deliver the finished MP4 inline when possible, else a no-login link.

**Non-goals**
- No AI text-to-video; no new render engine.
- No inline voice-sample playback (Discord can't bind audio to a select).
- No reorder/rename of screenshots (web has it; Discord has no native equivalent).
- No multi-user collaboration on one video; private-thread, single-owner.

## 4. Decisions (from brainstorming)

| Topic | Decision |
|---|---|
| Scope (v1) | **Full parity** (generate + refine + versions/revert + list) |
| Screenshot transport | **URL-based intake** (new backend endpoint; bot passes Discord CDN URLs) |
| Identity / ownership | **Require account linking** (reuse `aiuilink:*`); owner = real email |
| Delivery | **Attach MP4, fall back to capability link** |
| Entry flow | **Details first**: button → modal (title/prompt) → thread → style/voice selects → add screenshots → Generate |
| Voice picking | **Post the 6 sample MP3s** as attachments + a Style/Voice select |
| Sharing | **Private thread only** (no auto-post to the main channel) |
| Intake model | **Interactions-only** (`/video add` slash for images; Refine via button → modal) |

## 5. Architecture

```
#video-generation (panel: [+ New video] [My videos])
        │  button click (interaction)
        ▼
DiscordCommandHandler  ──route on custom_id (aiuivid:*)──►  CommandRouter.run_video_*
        │  /video add (slash, attachment options)                    │
        │                                                            ▼  X-User-Email
        └────────────────────────────────────────────►  TasksClient (clients/tasks.py)
                                                                     │  http://tasks:8210
                                                                     ▼
                                            tasks routes_video.py  (draft / screenshots-by-url /
                                            queue / get / refine / apply / versions / revert)
                                                                     │
                                                                     ▼
                                            video_worker (unchanged) → ffmpeg + Piper → MP4
```

Per-user **private thread** (`kind="video"`) is the studio: status, refine, versions,
and the finished video all live there. State for a not-yet-rendered video is the
**draft job** itself (`status="collecting"`), which persists across interactions and
bot restarts and becomes the rendered job on Generate (no copy).

### Namespace
All components use the `aiuivid:` prefix:
`aiuivid:new`, `aiuivid:list`, `aiuivid:newmodal`, `aiuivid:style:<job>`,
`aiuivid:voice:<job>`, `aiuivid:generate:<job>`, `aiuivid:refine:<job>`,
`aiuivid:refinemodal:<job>`, `aiuivid:apply:<job>`, `aiuivid:version:<job>`,
`aiuivid:revert:<job>`, `aiuivid:openthread:<job>` (link button).

## 6. Backend changes (`mcp-servers/tasks`)

Isolated additions to `routes_video.py` + one migration. Worker, plan, styles,
voices, capability, cleanup are **untouched**.

1. **Migration `025_video_collecting_status.sql`** — add `"collecting"` to the
   `video_jobs.status` CHECK constraint. The worker only selects `queued`, so
   drafts are ignored automatically. Idempotent; auto-runs on container boot.

2. **`POST /api/video-jobs/draft`** — JSON `{title, prompt, style, voice}`.
   Creates a `collecting` job (0 screenshots), returns `{id, slug}`. Validates
   `title` (1–200), `prompt` (1–2000), `style`/`voice` against existing allowlists.
   Does **not** count against the daily limit (enforced at queue).

3. **`POST /api/video-jobs/{id}/screenshots-by-url`** — JSON `{urls: [...]}`.
   Server fetches each URL and applies the **same** guards as multipart upload:
   `validate_screenshot`, ≤10 MiB/file, cumulative ≤50 MiB & ≤12 total, free-disk.
   **SSRF guard (fail closed):** only allow hosts `cdn.discordapp.com` and
   `media.discordapp.net` (configurable via `VIDEO_URL_INTAKE_ALLOWED_HOSTS`);
   reject anything else, plus any non-`https` scheme, before fetching. Returns
   `{screenshots, count}`. Job must be `collecting` and owned by caller.

4. **`POST /api/video-jobs/{id}/queue`** — validate `collecting` + ≥1 screenshot +
   title/prompt/style/voice present; enforce `VIDEO_MAX_PER_USER_PER_DAY`
   **here** (count only jobs that reached `queued`/`done` in the last 24 h, so
   abandoned drafts don't count); set `status="queued"`. Returns `{status, queue_position}`.

5. **`GET /api/video-jobs/{id}`** — when `status == "done"`, add a short-lived
   **`share_url`** field (a `video_dl` capability link on `tasks_public_url`,
   minted via `mint_video_capability`) so the bot can post a no-login link if the
   MP4 exceeds Discord's upload cap. No change to auth.

6. **`GET /api/video-jobs`** — exclude `collecting` drafts from the returned list
   (or mark them `is_draft: true`; v1 excludes them).

All new endpoints use `current_user` + the standard ownership check.

## 7. Bot changes (`webhook-handler`)

- **`handlers/video_panel.py`** (new, pure/no-I/O, unit-tested):
  - `build_video_embed()`, `build_video_panel()` → channel panel (`[+ New video]`,
    `[My videos]`).
  - `build_video_modal(...)` → Title + Prompt modal (`type 4` text inputs).
  - `build_refine_modal(job_id)` → single paragraph text input.
  - `build_style_select(job_id)`, `build_voice_select(job_id, voices)`.
  - `build_generate_components(job_id, count)`, `build_done_components(job_id, versions)`,
    `build_proposal_components(job_id)`, `build_version_components(job_id, versions)`,
    `build_open_thread_button(guild_id, thread_id, job_id)`.
  - Predicates/extractors (`is_vid_new`, `job_id_from_*`, `_suffix_after`) mirroring
    `app_builder_panel.py`; reuse its component-type/style constants.
- **`clients/tasks.py`** — new `TasksClient` methods (all per-user `X-User-Email`,
  mirroring `start_build`): `get_video_voices`, `create_video_draft`,
  `add_video_screenshots_urls`, `queue_video`, `get_video`, `list_videos`,
  `refine_video`, `apply_video`, `video_versions`, `revert_video`,
  `download_video_bytes` (member-auth GET of the MP4 for inline attach).
- **`handlers/discord_commands.py`** — router branches for `aiuivid:*` components +
  modal submits; `/video` slash subcommands `add` (attachment options) and `list`.
  Extend `_first_attachment` → `_all_attachments(data)` (read every entry of
  `data.resolved.attachments`).
- **`handlers/commands.py`** — runner methods on `CommandRouter`:
  `run_video_new` (resolve email or `_respond_not_linked`; create draft; open thread;
  post selects + voice samples), `run_video_set_style`/`run_video_set_voice`,
  `run_video_add` (push CDN URLs; reply count + Generate button),
  `run_video_generate` (queue; spawn watcher), **`_watch_video`** (poll `get_video`,
  edit status, deliver on done — attach if ≤ cap else `share_url`),
  `run_video_refine`/`run_video_apply`, `run_video_list`, `run_video_revert`. Add a
  `kind="video"` thread slot (`get/set_user_video_thread`) — new `TasksClient`
  method + tasks `discord-links`-style thread store entry.
- **`scripts/register_discord_commands.py`** (repo-root) — register `/video` with
  `add` (attachment options `shot1…shot10`, all optional) and `list`.
- **`webhook-handler/scripts/setup_video_channel.py`** (new, idempotent) — create/find
  `#video-generation` (env `VIDEO_CHANNEL_ID`/`VIDEO_CHANNEL_NAME`), post + pin the
  panel (`VIDEO_PANEL_RESET=1` to repost).

## 8. End-to-end flow

1. Panel **[+ New video]** (`aiuivid:new`) → unlinked → existing Link card; linked →
   return `{type: MODAL}` Title+Prompt.
2. Modal submit (`aiuivid:newmodal`) → `create_video_draft` → open/reuse video
   thread → post Style select, Voice select, the **6 voice sample MP3s**, and a
   how-to. Interaction reply: ephemeral link to the thread.
3. Style/Voice selects update the draft.
4. **`/video add`** in the thread (attachment options) → `add_video_screenshots_urls`
   with the CDN URLs → reply "N/12 added" + **[ Generate ]**. Repeatable.
5. **[ Generate ]** (`aiuivid:generate:<job>`) → `queue_video` → spawn `_watch_video`
   → status message incl. **queue position**.
6. `_watch_video` polls `get_video`, edits status `scripting → rendering → done`.
   On done: attach the MP4 (≤ `VIDEO_DISCORD_ATTACH_MAX_MB`, default 24) else post
   `share_url`; post scene summary, a **[ Refine ]** button, and version chips.
   On failed: post the error.
7. **[ Refine ]** → modal → `refine_video`; if `can_apply`, post proposal +
   **[ Apply ]** → `apply_video` → re-queue → watcher (rerender mode).
8. Version chip/select + **[ Revert ]** → `revert_video`.
9. **[ My videos ]** / `/video list` → `list_videos` → ephemeral list with a link
   button per video to its thread.

## 9. Error handling & edge cases

- 3-s ACK always respected: modals returned synchronously; everything long is
  deferred and reported via the watcher + bot-token thread posts (interaction token
  expires at 15 min; renders can exceed it).
- Over-cap inputs → clear message (which limit; which file failed validation).
- SSRF: non-Discord-CDN or non-https URL rejected before any fetch.
- Render `failed` → post the server error; watcher tolerates a few transient poll
  errors, then a "reload"-style message.
- Heavy-lock contention surfaced as **queue position**, not a silent wait.
- Unknown `custom_id` → safe no-op (existing fall-through).
- One active draft per user: **[+ New video]** supersedes any prior `collecting`
  draft (the previous draft is abandoned and GC'd by the existing 7-day cleanup).
- Not linked → `_respond_not_linked` (existing Link button) on any video flow.

## 10. Testing (TDD)

**Backend** (`mcp-servers/tasks/tests`):
- `test_routes_video_draft.py` — create draft; style/voice validation; 401 no email.
- `test_routes_video_screenshots_by_url.py` — happy path; **SSRF allow-list
  rejection** (non-Discord host, non-https); size/count guards; ownership 403.
- `test_routes_video_queue.py` — collecting→queued; rejects 0-screenshot; daily
  limit enforced at queue; non-collecting rejected.
- Migration `025` applies and accepts `collecting`.
- `share_url` present on done payload, absent otherwise.

**Bot** (`webhook-handler/tests`):
- `test_video_panel.py` — builders, custom_id round-trips, limits.
- `test_tasks_client_video.py` — each method's path/headers/body (fake `_request`,
  like `test_discord_attachment_wiring.py`).
- `test_video_routing.py` — `aiuivid:*` dispatch + `/video` subcommands;
  `_all_attachments` reads multiple files.
- `test_watch_video.py` — status transitions; attach-vs-link delivery by size.
- not-linked gating.

## 11. Deployment

- **tasks** (backend): `ORCH_HOST=46.224.193.25 ./scripts/deploy_orchestrator.sh`
  (or manual per-file `scp` + `docker compose -f docker-compose.unified.yml up -d
  --build tasks` if rsync is unavailable; bump `.deploy-state`). Migration `025`
  auto-runs on boot. Verify `curl -fsS https://ai-ui.coolestdomain.win/tasks/healthz`.
- **webhook-handler** (bot): **manual**, one `scp` per changed file (never `scp -r`)
  + `docker compose -f docker-compose.unified.yml up -d --build webhook-handler`;
  verify `docker compose … ps webhook-handler` is `Up`.
- Post-deploy one-time: run `register_discord_commands` (registers `/video`) and
  `setup_video_channel.py` (creates the channel + panel).
- Commit before deploying. **Never** touch/commit `.env`; **never** deploy the local
  `mcp-servers/tasks/templates.py` (server is ahead).

## 12. Config / env additions

- Bot: `VIDEO_CHANNEL_ID` / `VIDEO_CHANNEL_NAME` (setup), `VIDEO_DISCORD_ATTACH_MAX_MB`
  (default 24).
- Tasks: `VIDEO_URL_INTAKE_ALLOWED_HOSTS` (default
  `cdn.discordapp.com,media.discordapp.net`). Reuses existing
  `OAUTH_STATE_SECRET`, `VIDEO_DL_TTL_SECONDS`, `tasks_public_url`,
  `VIDEO_MAX_PER_USER_PER_DAY`.

## 13. Defaults chosen (override if desired)

- Attach MP4 when ≤ 24 MB (safe under the 25 MB unboosted limit), else capability link.
- `/video add`: 10 attachment slots per call, repeatable to the 12 total cap.
- Scene strip: compact text list (scene N: caption) in the done message — no
  contact-sheet image.
- One active draft per user.

## 14. Open questions

None blocking. To revisit if needed: boosted-guild upload cap (raise
`VIDEO_DISCORD_ATTACH_MAX_MB`); whether `/video list` should also offer re-download
links inline vs thread links only.
