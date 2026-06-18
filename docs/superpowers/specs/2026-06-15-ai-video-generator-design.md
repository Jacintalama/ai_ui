# AI Video Generator — Design Spec

**Date:** 2026-06-15
**Status:** Draft for review (revised after adversarial spec review + live hardware verification)
**Feature:** Third user-facing capability on the IO Platform, after App Builder and the Cron/Scheduler.

## 1. Summary

Users upload screenshots of their app (or any images) plus a text prompt. The platform produces a short narrated explainer/demo video (MP4) by:

1. Having Claude pick a fixed template and fill it in (script, captions, scene order, timing).
2. Generating a voiceover with a free, self-hosted TTS engine (Piper).
3. Rendering the video with **ffmpeg** (slideshow filtergraph: Ken Burns + caption overlays + crossfades + muxed voiceover) on the existing build host.
4. Delivering the finished MP4 back to the user via a capability-gated download link.

This is **programmatic video assembly**, not AI video generation, and not browser-based rendering. No diffusion/text-to-video model and no headless Chromium are involved. Claude controls content (words, ordering, timing), never raw render code.

## 2. Hardware reality (verified live 2026-06-15)

There is **one** server: `ai-ui-dev` at `46.224.193.25`, a **Hetzner CAX11 — 2 vCPU / 4GB RAM / 40GB disk**. It runs ~30 containers, is at ~1.5GB available RAM and 94% disk, and **also hosts the app-build agent** as the `claude-agent` host user (`AGENT_BACKEND=remote`, `AGENT_HOST=172.22.0.1`, which is the Docker bridge gateway, i.e. the same physical host, not a separate VM).

Decision (user): **do not add or resize hardware.** The feature must run on this existing box. Every design choice below follows from that hard constraint.

Consequences accepted:
- **ffmpeg, never Chromium/Remotion** (Chromium needs 8GB+; impossible here, and Remotion's multi-tenant license is also paid).
- **Renders run on the host, not in the `tasks` container** (that container is capped at 256MB RAM).
- **Renders and builds are mutually exclusive** (one heavy job at a time on the 4GB box).
- **Pilot-scale**: tight caps on resolution, length, and per-user quota. Scales to a bigger/dedicated box later with no code change (same SSH+rsync pattern).

## 3. Goals and non-goals

### Goals
- Web-upload entry point for v1, reusing the existing "Upload your app" flow.
- Template-driven video using ffmpeg filtergraphs.
- Free, self-hosted voiceover (Piper).
- Run safely on the existing 4GB box: one heavy job at a time, capped resolution/length, disk-safe.
- Reuse existing patterns: filesystem + Postgres storage, SSH+rsync host compute, capability-token auth. No object storage, no new services, no new/larger hardware.

### Non-goals (v1)
- AI text-to-video / image-to-video generation.
- Remotion / React / headless-browser rendering (license cost + RAM infeasible here).
- AI-authored render code executed per request.
- Discord/Slack screenshot upload (web-only for v1).
- Object storage (S3/R2). Rescaling or adding a render box.
- Rich motion graphics, animated typography, background music (future).

## 4. User flow (v1, web)

1. User opens the video tool in the web UI, picks an app (slug), uploads screenshots, and types a prompt.
2. The `tasks` service authenticates the user (project member), validates the upload, stores the screenshots, and creates a `video_jobs` row with status `queued`.
3. The in-process **video worker** advances the job through stages, acquiring the shared agent-VM lock before any heavy step:
   - **scripting:** Claude returns a schema-validated plan (template, scene order, captions, narration). Referenced screenshots are verified to exist.
   - **voicing:** Piper turns the narration into `voice.mp3` (on the host).
   - **rendering:** screenshots + `voice.mp3` + plan are rsynced to the host; ffmpeg renders `out.mp4`; it is rsynced back.
4. Job → `done`; the web UI (polling) shows the video and offers a capability-gated download. Optional: a Discord/Slack DM notification, reusing the existing post-back pattern.

## 5. Architecture

```
Web UI (upload screenshots + prompt)
   │
   ▼
tasks service ── Postgres: tasks.video_jobs (state) + pg_advisory_lock (heavy-job mutex)
   │
   ├─ video worker (in-process async task): orchestrates stages
   ├─ scripting: Claude → validated plan JSON  (cheap tokens)
   │
   ├─ acquire shared lock (renders AND builds use it) ──────────────┐
   ▼                                                                ▼
 host (claude-agent @ 172.22.0.1, via SSH+rsync — same path as builds):
     Piper → voice.mp3        ffmpeg slideshow render → out.mp4
   │
   └─ rsync out.mp4 back → /workspace/ai_ui/apps/<slug>/.video/<job_id>/out.mp4
   │   release lock (in finally — always, even on failure/timeout)
   ▼
Web UI download (video_dl capability-token gated)  [+ optional chat notification]
```

## 6. Components (each an isolated unit)

### 6.1 Video worker + queue
- **Where:** an in-process background async task inside the `tasks` service (no new service; no Redis — the tasks service talks to Postgres, not Redis, today).
- **Queue + state:** `tasks.video_jobs` rows are the queue. The worker polls for the oldest `queued` job, or is signalled on insert. States: `queued → scripting → voicing → rendering → done` and `failed` (terminal).
- **Heavy-job mutex:** a single **Postgres advisory lock** (`pg_advisory_lock`) guards all heavy work on the box. **Both renders and builds acquire it**, so a render and a build can never run at once. The worker also refuses to start a render if disk free is below a threshold (see 6.6).
- **Concurrency:** exactly one heavy job (render or build) at a time. Surfaces queue position to the UI.

### 6.2 Upload endpoint
- **Where:** new route in `tasks`, mirroring `routes_upload.py` + the enhance-endpoint attachment handling.
- **Auth:** the caller must be a **project member** of `slug` (existing `project_members` / `X-User-Email` model), not `current_admin`. This is user-facing.
- **Validation:** allowlist MIME `image/png|jpeg|webp`, verified by **magic-number / PIL `Image.verify()`** (not extension alone); **max dimensions** (e.g. 4096x4096) to stop image bombs; per-file cap (e.g. 10MB) and per-job total (e.g. 50MB) and max file count; filename sanitization via existing helpers.
- **Storage target:** `/workspace/ai_ui/apps/<slug>/.video/<job_id>/screenshots/*.png`.

### 6.3 AI scripting
- **Where:** `tasks` service, calling Claude.
- **Output (schema-validated plan):**
  ```json
  {
    "template_id": "product_demo",
    "title": "string",
    "scenes": [
      {"screenshot": "screenshot-1.png", "caption": "string", "duration_s": 3.5, "transition": "crossfade"}
    ],
    "narration_script": "full voiceover text",
    "resolution": "720p"
  }
  ```
- **Validation:** `template_id` known; **every `screenshot` must exist on disk** for the job (reject hallucinated names); durations bounded; total length ≤ 60s (v1); resolution in {720p, 1080p}. Invalid output triggers one bounded repair retry, then fail. Plans are never executed as code.

### 6.4 TTS (Piper)
- **Where:** installed on the build host (co-located with the render). Pinned to a maintained distribution (prebuilt aarch64 binary or `OHF-Voice/piper1-gpl` at a fixed version; the original `rhasspy/piper` is archived). GPL is fine for self-hosted, no-distribution use; recorded in the provisioning script.
- **Responsibility:** `narration_script` → `voice.wav` → `voice.mp3` (ffmpeg). One default voice for v1; deterministic (re-running on retry yields the same file, so voicing is idempotent).

### 6.5 ffmpeg render
- **Where:** runs as `claude-agent` on the host, dispatched via the existing SSH+rsync mechanism (a render path added alongside `remote_executor.py`, or a `VideoRenderExecutor` sharing its transport).
- **Engine:** raw ffmpeg filtergraph (no MoviePy frame-by-frame numpy pipeline, to keep RAM low). Per scene: `zoompan` (Ken Burns) on the screenshot scaled to the target resolution, with a caption. Scenes joined with `xfade` crossfades; the Piper `voice.mp3` muxed as the audio track.
- **Captions:** pre-rendered to transparent PNG overlays with PIL using a **bundled font** (avoids ffmpeg `drawtext` font-config and escaping pitfalls, and guarantees correct typography on headless Linux). Font + `fontconfig` installed via the provisioning script.
- **Artifact return:** rsync `out.mp4` back. The rsync-back sanity check must look for **`out.mp4`** (not `index.html`), so the render path parameterizes the expected artifact rather than reusing the build check verbatim.
- **Resource caps:** ffmpeg `-threads` limited; 720p default (1080p optional); render-specific timeout (e.g. 600s) separate from build timeouts.
- **Cleanup:** the remote workspace under `/agent/work/<job_id>/` is removed in a **`finally`** block on **every** outcome (success, failure, timeout) so failed jobs never leave another tenant's files behind. (The current build executor only cleans up on success; the render path must not copy that.)

### 6.6 Storage, retention, disk safety
- **Layout:** `/workspace/ai_ui/apps/<slug>/.video/<job_id>/{screenshots/, plan.json, voice.mp3, out.mp4}`.
- **Cleanup:** delete `screenshots/` and `voice.mp3` once `out.mp4` is written. Whole job dir deleted after `RETENTION_DAYS_VIDEOS` (default **7**, given the 40GB disk), by a scheduled task reusing the existing scheduler.
- **Disk guard:** the worker refuses to start a render (job stays `queued`, user told) if free disk is below a threshold (e.g. **2GB**). Phase 0 prunes ~8GB of stale Docker images to create headroom before launch.

### 6.7 Delivery
- **Download auth:** a new **`video_dl:` capability** bound to `(owner, slug, video_job_id)` — a small `video_capability` module mirroring `edit_capability.py` (the existing token binds `task_id`, which would be wrong/colliding for videos). Download route: `GET /api/projects/<slug>/videos/<job_id>/download`, gated by this capability + `project_members`.
- **Status polling:** `GET /api/video-jobs/<job_id>` every ~2s from the web UI. Response: `{ id, status, queue_position, error, output_available, progress_pct? }`. 404 if not found/not authorized.
- **Optional:** Discord/Slack DM with the link, reusing the webhook-handler post-back used by cron/recruiting.

## 7. Data model

New table `tasks.video_jobs` (migration `021_video_jobs.sql` + `VideoJob` ORM model in `models.py`):

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | job id |
| `slug` | TEXT | app the job belongs to |
| `user_email` | TEXT | owner (matches `assignee_email` model) |
| `status` | TEXT | queued / scripting / voicing / rendering / done / failed |
| `prompt` | TEXT | user request |
| `plan_json` | JSONB | validated plan |
| `error` | TEXT NULL | failure reason |
| `output_path` | TEXT NULL | path to `out.mp4` |
| `created_at` / `updated_at` | TIMESTAMPTZ | |

Access gated by `project_members` ACL + the `video_dl` capability.

## 8. Orchestration, idempotency, failure handling

- **One worker owns all stages** for a job, in order. Each stage transition is persisted, so the worker is resumable and crash-safe.
- **Idempotent stages (skip on retry):** if `plan.json` exists and validates, skip scripting; if `voice.mp3` exists, skip voicing; rendering is restarted from inputs (not resumed mid-encode).
- **Per-stage timeouts:** scripting ~30s, voicing ~60s, rendering ~600s. A job stuck in `rendering` past timeout is marked `failed` (lock released in `finally`), never wedged forever.
- **No partial resume across submissions:** a `failed` job requires re-submit; intermediate artifacts of a failed job are cleaned by retention.
- **Retries:** scripting gets one bounded repair retry; rsync uses the existing 2-attempt retry.

## 9. Security

- **Tenant isolation on the shared host:** remote workspace cleaned in `finally` on all outcomes; renders and builds serialized by the shared lock; both run as the unprivileged `claude-agent`.
- **Upload hardening:** magic-number/PIL validation, max dimensions (image-bomb guard), size + count caps, filename sanitization. Disk-threshold guard prevents fill-the-disk DoS.
- **Download isolation:** `video_dl` capability bound to `video_job_id` + `project_members` check; one user cannot fetch another's `out.mp4`.
- **Per-user rate limit:** max N videos/day per user (configurable, e.g. 10), to bound token spend and CPU.
- **No injection:** user text (prompt, captions) never reaches a shell; captions are passed as data to PIL (overlay PNG), and ffmpeg is invoked with an argv list (no shell string). The plan is data, never code.
- **No secrets** in prompts or plan JSON.

## 10. Resource and cost

- **No new hardware, no new services, no object storage.** Reuses the existing box + the build host pattern.
- **RAM:** one heavy job at a time (lock). Raw ffmpeg 720p slideshow render peaks in the hundreds of MB, feasible on the 4GB box when no build is concurrent. Piper ~150MB, transient.
- **Disk:** Phase 0 prunes ~8GB of stale images; per-job inputs deleted after `out.mp4`; 7-day retention; 2GB free-disk guard.
- **Tokens:** scripting only (cents per video). **Voice:** free (Piper). **ffmpeg / Piper:** free (no license cost for this use).
- **Latency tradeoff (documented):** a video waits behind any in-progress build and vice versa; acceptable at pilot volume.

## 11. Testing

Mirror the platform's pytest conventions:
- **Unit:** plan-JSON schema + screenshot-existence validation; upload validation (magic number, dimensions, caps); the template → ffmpeg-argv builders (pure functions); queue state machine; the advisory-lock guard.
- **Integration:** end-to-end render of a fixture (2-3 small screenshots + short script) producing a valid, playable MP4 on the host; cleanup-on-failure leaves no remote files; lock makes render+build mutually exclusive.
- **Benchmark before shipping UX promises:** time a representative 30-60s 720p render on the actual CAX11 and set timeouts/queue messaging from measured numbers.

## 12. Rollout phases (detail in the implementation plan)

- **Phase 0 — Host prep:** prune stale Docker images (reclaim disk); install ffmpeg + fontconfig + a bundled font + Piper on the host via the provisioning script; verify ffmpeg can render a trivial fixture as `claude-agent`.
- **Phase 1 — Data + queue + lock:** `021_video_jobs.sql`, `VideoJob` model, the in-process worker, the shared `pg_advisory_lock` mutex (wire builds onto it too), disk guard.
- **Phase 2 — Upload + scripting:** member-auth upload endpoint with hardened validation; Claude scripting with schema + screenshot-existence checks.
- **Phase 3 — Voice + render:** Piper integration; ffmpeg slideshow render path over SSH+rsync with `finally` cleanup; one template end to end.
- **Phase 4 — Web UI + delivery:** upload/preview/poll UI; `video_dl` capability + download route; optional chat notification.
- **Phase 5 — Hardening:** retention/cleanup scheduled task; per-user rate limit; second template; tests + benchmark; deploy via the documented flow.

## 13. Future (non-breaking) extensions

- Move rendering to a rescaled box or a dedicated render box if volume grows (identical SSH+rsync pattern; no code change).
- Kokoro-ONNX premium voice; Discord/Slack upload; more templates; 1080p default; background music.
