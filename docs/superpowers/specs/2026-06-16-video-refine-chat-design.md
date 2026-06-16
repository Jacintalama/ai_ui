# Video Generator: Refine Chat and Studio UI (Design Spec)

**Date:** 2026-06-16
**Status:** Approved (pending spec review + user sign-off)
**Feature area:** `mcp-servers/tasks` video generator (AIUI / IO Platform)

## Goal

Turn the Video Generator page from a one-shot "upload screenshots + prompt -> get an MP4" form into a small **studio**: after a video is generated, the user refines it by chatting with the agent in plain language ("make scene 2 longer", "drop the intro", "rewrite the narration to be calmer", "add this screenshot"). The agent proposes the exact change, the user clicks Apply, and the video re-renders as a new version. The page is redesigned to a professional two-column studio layout that fills the current empty space.

## Background (current state, verified)

The video generator lives in `mcp-servers/tasks` and is deployed live on prod (`VIDEO_ENABLED=true`).

- **Page:** `static/video.html`, a single self-contained file (inline CSS + vanilla JS, dark theme, design tokens). Current layout is a `1fr 1fr` grid with `align-items:start`; the left column holds only a short Example card, leaving a large empty void beside the taller right column (the user's complaint).
- **API (`routes_video.py`, prefix `/api/video-jobs`):**
  - `POST /upload` (multipart slug + prompt + 1..12 images) -> `201 {id, status:'queued'}`.
  - `GET /{job_id}` -> `{id, status, queue_position, error, output_available}`.
  - `GET /{job_id}/download` -> FileResponse mp4 (auth: `current_admin`/member viewer role, OR a `video_dl` HMAC capability token).
- **Data model (`video_models.py`, migration `021_video_jobs.sql`):** table `tasks.video_jobs` = `id` uuid pk, `slug`, `user_email`, `status` (CHECK in `queued`/`scripting`/`voicing`/`rendering`/`done`/`failed`), `prompt`, `plan_json` jsonb, `error`, `output_path`, `created_at`, `updated_at`. Indexed on `(status, created_at)` and `(user_email, created_at DESC)`.
- **Screenshots** are written to disk (NOT the DB) at `<apps_dir>/<slug>/.video/<job_id>/screenshots/screenshot-{i}.png`.
- **Plan (`video_plan.py`):** `generate_plan(prompt, screenshots)` calls Claude (`claude-opus-4-8`, `output_config` json_schema) and returns a plan validated by `validate_plan`. Plan shape (`PLAN_SCHEMA`): `{template_id: 'product_demo'|'feature_walkthrough', title, scenes:[{screenshot, caption, duration_s (0.5..15), transition: 'crossfade'|'cut'}], narration_script (one string for the whole video), resolution?: '720p'|'1080p'}`. `validate_plan` enforces: template in the allowed set, >= 1 scene, every `scene.screenshot` exists on disk, `0.5 <= duration_s <= 15`, `sum(duration_s) <= 60`.
- **Worker (`video_worker.py`):** polls oldest `status='queued'` every 10s, gated by `VIDEO_ENABLED` + disk/RAM guards + `heavy_lock` (renders and app builds are mutually exclusive on the 3.8GB box). `_process_job` runs scripting -> rendering -> done, and **skips scripting when `plan_json` is already present** (`if not plan:`). This skip is the re-render hook.
- **Render (`video_render.py` + `video_executor.py`):** captions are baked to PNGs (Pillow), narration synthesized by Piper (single hardcoded voice `en_US-amy-medium.onnx`), one ffmpeg invocation over SSH to the build host produces `out.mp4`.
- **Cleanup (`video_cleanup.py`):** `prune_inputs` deletes `screenshots/`, `captions/`, `narration.txt`, `voice.*` within ~1 hour of a successful render (hourly sweep); whole job dir + DB row deleted after `VIDEO_RETENTION_DAYS` (default 7). **The 1-hour screenshot prune is the central blocker for re-render and must change.**
- **Auth (`auth.py`):** the api-gateway validates the Open WebUI JWT and injects trusted `X-User-Email` / `X-User-Admin` headers (client copies stripped). `current_admin` reads those; `routes_projects._require_role(s, slug, email, role)` checks project membership (`viewer`/`editor`/`owner`). `video_capability.py` mints/verifies a least-privilege `video_dl:` HMAC token (`verify_video_capability` is already wired into the production `download` endpoint; only `mint_video_capability` is test-only so far).
- **Reusable chat pattern:** `routes_tasks.py chat()` (Haiku, `httpx`, clarify-first, `BUILD_SUGGESTION:` sentinel) and the `preview.html` chat pane (`renderChatBubble`, `submitChat`, `authHeaders` + `credentials:'include'`).
- **Gateway gap:** `api-gateway/main.py` and the repo `Caddyfile` do NOT route `/api/video-jobs/*` to the tasks service (it works live via the host systemd Caddy). A parity branch must be added and verified on the VPS.

## User-facing behavior

1. **Create** (no job): the upload form (project slug, screenshots, prompt, Generate) sits in the left area; the right-rail chat shows a short welcome. This is the existing create flow, restyled.
2. **Generated** (job done): left = large video player + a scene strip (one thumbnail per scene with its caption) + a version bar (v1, v2, ...); right = refine chat.
3. **Refine:** the user types a change. The agent replies with either a clarifying question or a **proposal** (a one-line summary of the change, with an **Apply** button). Nothing renders until Apply.
4. **Apply:** the proposed plan becomes a new version and the video re-renders (~1 min, queued behind any in-flight build/render). The player swaps to the new version when done.
5. **Add screenshots:** a paperclip in the chat uploads new images so the user can ask the agent to add scenes that use them.
6. **Revert:** the version bar lets the user switch back to an earlier version instantly (the file already exists; no re-render).

## Architecture overview

A refine layer on top of the existing pipeline. The chat drives a **structured plan-regeneration loop**: each turn sends the current plan + available screenshots + conversation to Claude, which returns either a clarifying question or a complete, schema-valid revised plan. Applying a proposal writes `plan_json` and sets `status='queued'`; the existing worker re-renders (skipping scripting). Each successful render is snapshotted as a version so the user can revert. New units are small and well-bounded: a refiner module, a versions table, a few endpoints, and surgical worker/cleanup edits.

## Data model (migration `022_video_refine.sql`)

New table:

```sql
CREATE TABLE tasks.video_job_versions (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id      UUID NOT NULL REFERENCES tasks.video_jobs(id) ON DELETE CASCADE,
  version_no  INT  NOT NULL,
  plan_json   JSONB NOT NULL,
  summary     TEXT,                 -- one-line description of the change; NULL for v1
  output_path TEXT,                 -- out-v{N}.mp4 on disk
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (job_id, version_no)
);
CREATE INDEX video_job_versions_job_idx ON tasks.video_job_versions (job_id, version_no DESC);
```

A version row is inserted only **after** a successful render, so it carries no in-flight status; in-flight render status stays on `video_jobs.status`.

Alter `tasks.video_jobs`:

```sql
ALTER TABLE tasks.video_jobs
  ADD COLUMN conversation JSONB NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN current_version_no INT;
```

- `conversation`: ordered list of turns `{role:'user'|'assistant', kind:'message'|'question'|'proposal'|'note', content, version_no?, plan?, applied?}`. The full proposed `plan` is stored only on the **most recent** proposal turn (`{kind:'proposal', plan:{...}, applied:false}`); older proposals keep just their `summary` (their `plan` is stripped) to bound the column size. `apply` finds the most recent proposal turn with `applied:false`, renders it, and flips it to `applied:true`.
- `current_version_no`: the version currently shown (and the base for the next edit).

The existing `status` CHECK is unchanged; re-renders reuse `queued`/`rendering`/`done`/`failed`. The ORM `VideoJob` gains matching columns; a new ORM `VideoJobVersion` maps the table.

## API contracts

All new endpoints sit in `routes_video.py` under `/api/video-jobs`. Auth mirrors `upload`: `Depends(current_admin)` plus `_require_role(s, job.slug, user.email, 'editor', is_admin=user.is_admin)`. Every handler loads the job first and 404s on missing/malformed id (reuse `_coerce_job_id`). All mutating endpoints 503 when `VIDEO_ENABLED != 'true'`.

- **`POST /{job_id}/refine`** body `{message: str (1..2000)}`. Appends the user turn to `conversation`, calls `video_refine.refine_plan(...)`, appends the assistant turn, and returns `{action: 'ask'|'propose', message: str, can_apply: bool}`. On `propose`, the validated plan is stored on the latest proposal turn (server-side); `can_apply=true`.
- **`POST /{job_id}/apply`** no body. Reads the latest un-applied proposal from `conversation`; re-validates its plan with `validate_plan`; sets `video_jobs.plan_json = plan`, `status='queued'`; marks the proposal turn applied and appends a `note` turn ("Applying. Re-rendering as v{N}."). Returns `{status:'queued'}`. **409** if nothing pending; **422** if re-validation fails. The UI then polls the existing `GET /{job_id}`.
- **`POST /{job_id}/screenshots`** multipart `files` (1..k images). Same guards as `upload` (count cap vs existing + new, per-file 10MB, total 50MB, disk guard 507, `validate_screenshot`). Saves as the next `screenshot-{i}.png`. Returns `{screenshots: [filenames]}`.
- **`GET /{job_id}/versions`** -> `{versions: [{version_no, summary, created_at, current: bool, available: bool}]}` (`available` = the version's mp4 still exists on disk).
- **`POST /{job_id}/revert`** body `{version_no: int}`. If the target version file exists: set `plan_json`, `output_path`, `current_version_no` to that version (no re-render); append a `note`. If the file was pruned: set `plan_json` to that version's plan and `status='queued'` (re-render it). **404** if the version is unknown.
- **Extend `GET /{job_id}`** to also return `conversation`, `current_version_no`, and `pending: bool` so the UI rebuilds full state on reload.
- **Extend `GET /{job_id}/download`** with optional `?version=N` (defaults to the current version). Capability/member auth unchanged.

## Refiner module (`video_refine.py`)

`refine_plan(current_plan: dict, screenshots: list[str], conversation: list[dict], message: str) -> dict`.

- Calls `anthropic.Anthropic().messages.create(model='claude-opus-4-8', max_tokens=2048, system=..., output_config={'format':{'type':'json_schema','schema':REFINE_SCHEMA}}, messages=[...])`, mirroring `video_plan.generate_plan`.
- `messages` carries the recent conversation (capped to the last 40 turns) plus the new user message; the system prompt embeds the current plan JSON and the available screenshot filenames.
- `REFINE_SCHEMA = {type:'object', properties:{action:{enum:['ask','propose']}, message:{type:'string'}, plan: PLAN_SCHEMA}, required:['action','message'], additionalProperties:false}`.
- System prompt rules: you are editing an existing narrated screenshot slideshow; only reference screenshots in the provided list; keep total duration <= 60s; change only what the user asked; set `action='ask'` with a brief question only when the request is genuinely ambiguous, otherwise `action='propose'` with a one-line `message` summary and a complete revised `plan`.
- On `action='propose'`, the caller runs the existing `validate_plan(plan, screenshots)`. Because `REFINE_SCHEMA` marks `plan` optional, a `propose` with a missing or partial plan is possible, so the caller treats both a missing/empty plan and ANY exception from `validate_plan` (not only `PlanInvalid`, e.g. an `AttributeError` from a `None` plan) as a downgrade to `{action:'ask', message:"I could not build a valid change (<reason>). Can you rephrase?"}`. The user never sees a 500 and no bad plan reaches the worker.

## Worker changes (`video_worker.py`)

After a successful render (initial or refine), before marking `done`:
1. Compute `version_no = COALESCE(MAX(version_no), 0) + 1` for the job.
2. Copy the rendered `out.mp4` to `out-v{version_no}.mp4` in the job dir.
3. Insert a `video_job_versions` row (`plan_json` = the plan just rendered; `summary` from the applied proposal's summary, NULL for the initial v1, or the revert note text when the render was triggered by a revert-to-pruned-version; `output_path` = the versioned file).
4. Set `video_jobs.output_path` to the versioned file and `current_version_no = version_no`.

The "skip scripting if `plan_json` present" branch already routes refine re-renders straight to rendering; no scripting change is needed.

## Cleanup / retention changes (`video_cleanup.py`)

- `prune_inputs`: **stop deleting `screenshots/`** (re-render and add-scene depend on them). Continue pruning `captions/`, `narration.txt`, `voice.*` (regenerated on every render).
- Add a version-file cap: keep the newest `MAX_VERSIONS` (default 5, env `VIDEO_MAX_VERSIONS`) `out-v*.mp4` per job; delete older version files but keep their rows (a reverted-to pruned version re-renders via the revert fallback).
- The 7-day whole-job retention sweep is unchanged (cascade deletes version rows).

## UI (`static/video.html` -> studio split, Layout A)

Reuse the existing design tokens and `.card`/`.btn`/`.badge`/`.field` components; clone the chat pane from `preview.html` (`renderChatBubble`, "thinking" state, `authHeaders` + `credentials:'include'`, poll loop).

- **Topbar:** brand + project + status pill + "New video".
- **Create state:** upload form in the left area; right-rail chat shows a welcome line.
- **Studio state:** left = large `<video>` (current version) + scene strip (thumbnail per scene built from the screenshots, caption beneath) + version bar (v1, v2, ... with a revert affordance and a "current" marker); right = refine chat with proposal bubbles carrying an **Apply** button, a paperclip to add screenshots, and the prompt input.
- **Flow:** submit refine message -> `POST /refine` -> render question or proposal+Apply; Apply -> `POST /apply` -> poll `GET /{id}` until `done` -> swap `<video src>` with a cache-bust + refresh the version bar; revert -> `POST /revert` -> swap; add screenshots -> `POST /screenshots` -> toast.
- Fix existing rough edges: real empty/placeholder states (no silent black box), matched cache-bust on poster and video, drop the asymmetric void.

## Error handling

- Missing `ANTHROPIC_API_KEY` -> 503 friendly (matches `chat()`).
- Invalid model plan -> downgraded to a friendly re-ask (never a 500, never queued).
- `apply` with no pending proposal -> 409; server-side re-validation failure -> 422.
- Screenshot guards -> 413 (size) / 507 (disk) / 400 (type/count).
- Unknown version on revert/download -> 404; pruned version file -> re-render fallback.
- Render failure: no version row is created; `status='failed'`, `error` surfaced; the previous `current_version` (plan + file) stays intact so the user keeps the last good video.
- Concurrency: refine renders queue behind builds/renders via the existing `heavy_lock`; the UI shows queue position from `GET /{id}`.

## Security / authorization

- Identity comes only from gateway-injected `X-User-Email` / `X-User-Admin` (un-forgeable; client copies stripped). The static page never sees identity; all gating is server-side.
- Every refine/apply/screenshots/versions/revert endpoint requires `current_admin` + `editor` role on the job's slug (same as upload). Cross-tenant access is blocked because the job is loaded and its slug/owner is re-checked on every call.
- No new secrets. The refiner reads `ANTHROPIC_API_KEY` from env like `generate_plan`. User text never reaches a shell (captions are baked to PNGs; narration is read from a file), preserving the existing injection-safe render path.

## Testing strategy (TDD)

- `video_refine.refine_plan`: returns `ask` vs `propose`; invalid model plan is downgraded to `ask`; proposed plans only reference available screenshots; conversation is capped to 40 turns.
- `validate_plan` reuse: proposals that violate duration/screenshot rules are rejected before queueing.
- Routes: auth + cross-tenant 403; happy paths for refine/apply/screenshots/versions/revert; 409 (no pending), 404 (unknown version), 422 (bad apply), 413/507 (screenshot guards); `conversation` persistence and the "plan kept only on latest proposal" trimming.
- Worker: a version row is created on completion; `version_no` increments across reverts; refine re-render skips scripting.
- Cleanup: `screenshots/` survive `prune_inputs`; version-file cap prunes the oldest mp4 but keeps rows.
- Migration 022 applies cleanly; `ON DELETE CASCADE` removes version rows with the job.
- UI: Playwright screenshot smoke of create state, studio state, a proposal bubble, and a post-apply video swap.

## Deploy prerequisites

- Add a `/api/video-jobs` branch to `api-gateway/main.py` for parity, and verify on the VPS that the live host Caddy/gateway forwards `/api/video-jobs/*` to the tasks service (the repo gateway/Caddyfile do not).
- Confirm the tasks startup migration runner picks up `022_video_refine.sql`.
- `ANTHROPIC_API_KEY` present in the tasks service (already true for `generate_plan`).
- Deploy via targeted rebuild of the `tasks` container (git archive | ssh tar -x, then `docker compose up -d --build tasks`), not the orchestrator-all path. `VIDEO_ENABLED` continues to gate the feature.

## Out of scope for v1 (YAGNI)

- Per-scene narration (narration stays one string for the whole video, but the chat can rewrite it).
- Switching narrator voice, visual template, or resolution from the chat (needs extra Piper voices installed and new plan fields).
- Real-time streaming of the chat reply or render progress (reply is request/response; render stays poll-based, as today).

## Decisions log

- **Refine mechanism:** structured plan-regeneration with Opus + the existing `validate_plan` (chosen over a Haiku sentinel clone and over a direct scene editor) for safety and best fit with propose-then-apply.
- **Render trigger:** propose, then explicit Apply (avoids wasted ~1-min renders on misreads).
- **Versioning:** keep full version history with instant revert (file re-point), capped at `MAX_VERSIONS` files on disk.
- **Add screenshots:** in scope for v1 (new `POST /screenshots` endpoint + screenshot retention fix).
- **Layout:** studio split (large video + scene strip on the left, refine chat as a right rail).
- **Authz:** `current_admin` + `editor` role on the slug, consistent with upload.
