# AI Video Generator — Design Spec

**Date:** 2026-06-15
**Status:** Draft for review
**Feature:** Third user-facing capability on the IO Platform, after App Builder and the Cron/Scheduler.

## 1. Summary

Users upload screenshots of their app (or any images) plus a text prompt. The platform produces a short narrated explainer/demo video (MP4) by:

1. Having Claude pick a fixed Remotion template and fill it in (script, captions, scene order, timing).
2. Generating a voiceover with a free, self-hosted TTS engine (Piper).
3. Rendering the video with Remotion on the existing agent VM.
4. Delivering the finished MP4 back to the user with a capability-gated download link.

This is **programmatic video assembly**, not AI video generation. No diffusion/text-to-video model is involved. Claude controls content (words, ordering, timing), never raw render code.

## 2. Goals and non-goals

### Goals
- Web-upload entry point for v1, reusing the existing "Upload your app" flow.
- Template-driven video: a small set of fixed, hand-built Remotion templates.
- Free, self-hosted voiceover (no per-character API cost).
- A queue with a strict concurrency cap so renders never starve app builds.
- Reuse existing platform patterns: filesystem + Postgres storage, SSH+rsync off-box compute, capability-token auth. No new external services, no object storage, no new cloud provider.

### Non-goals (explicitly out of scope for v1)
- AI text-to-video / image-to-video generation (Runway, Veo, Sora, etc.).
- AI-written Remotion code executed per request (security and reliability risk).
- Discord/Slack screenshot upload (those platforms have no attachment handlers today; web-only for v1).
- Object storage (S3/R2/MinIO). The platform has none and we are not adding it.
- A dedicated render VM (we reuse the existing agent VM; a dedicated box is a future, non-breaking option).
- Per-frame / timeline editing UI, background music selection, multi-language voices (future toggles).

## 3. Constraints that shaped this design

Verified live and via codebase recon on 2026-06-15:

- **Main VPS is maxed:** 2 CPU, 3.7GB RAM (~1.4GB free), disk 94% full (~2.5GB free), ~30 containers, no ffmpeg. Rendering cannot run on the orchestrator box.
- **Reclaimable headroom exists:** ~7.9GB of stale Docker images can be pruned to relieve the disk pressure for small installs (e.g. Piper if it ran here).
- **No object storage anywhere:** all storage is a Docker bind-mount volume at `/workspace/ai_ui/apps/<slug>/` plus the Postgres `tasks` schema.
- **An off-box compute pattern already exists:** the `tasks` service rsyncs app files to a **dedicated Hetzner CAX21 agent VM** (ARM64, ~4 vCPU / ~8GB RAM, Node 20 + Python 3.11 + Claude Code CLI installed), runs the build over SSH, then rsyncs artifacts back. It has **no Chromium and no ffmpeg** today.
- **User isolation** is enforced by `assignee_email` on `tasks.items`, the `tasks.project_members` table, and HMAC capability tokens (`X-Edit-Capability`, signed with `OAUTH_STATE_SECRET`).

## 4. User flow (v1, web)

1. User opens the video tool in the web UI, selects an existing app (slug) or a fresh job, uploads screenshots, and types a prompt describing the video they want.
2. The `tasks` service validates the upload, stores the screenshots, and creates a `video_jobs` row with status `queued`.
3. A worker picks the job up (respecting the concurrency cap):
   - **scripting:** Claude reads the prompt + screenshot list and returns a validated JSON plan (template, scene order, captions, narration script).
   - **voicing:** Piper turns the narration script into `voice.mp3`.
   - **rendering:** screenshots + `voice.mp3` + the plan JSON are rsynced to the agent VM, Remotion renders `out.mp4`, which is rsynced back.
4. Job status moves to `done`; the user sees the video in the web UI and can download it via a capability-gated link. (Optional: a Discord/Slack DM notification, reusing the existing post-back pattern.)

## 5. Architecture

```
Web UI (upload screenshots + prompt)
   │
   ▼
tasks service ──> Postgres tasks.video_jobs (job state)
   │         └──> Redis (queue + concurrency cap)
   │
   ├─ scripting: Claude → validated plan JSON  (cheap tokens)
   ├─ voicing:   Piper (on agent VM) → voice.mp3  (free, light)
   ├─ rsync inputs ──────────────────────────────┐
   ▼                                              ▼
agent VM (existing): Remotion render (Chromium + ffmpeg) → out.mp4
   │
   └─ rsync out.mp4 back → /workspace/ai_ui/apps/<slug>/.video/<job_id>/out.mp4
   │
   ▼
Web UI download (capability-token gated)  [+ optional chat notification]
```

## 6. Components (each an isolated unit)

### 6.1 Job + queue layer
- **Where:** `tasks` service + Redis (both already running).
- **Responsibility:** own the `video_jobs` lifecycle and enforce a global concurrency cap of 1 active render. Provide queue position to the UI.
- **States:** `queued → scripting → voicing → rendering → done` and `failed` (terminal) from any stage.
- **Interface:** create job, advance state, fetch status, list user jobs.

### 6.2 Upload endpoint
- **Where:** new route in the `tasks` service, mirroring `routes_upload.py` and the enhance-endpoint attachment handling.
- **Responsibility:** validate screenshots (allowlist `image/png|jpeg|webp`; per-file and per-job size caps; path safety via the existing `upload_validation.py` patterns) and write them to the job directory.
- **Storage target:** `/workspace/ai_ui/apps/<slug>/.video/<job_id>/screenshots/*.png`.

### 6.3 AI scripting
- **Where:** `tasks` service, calling Claude.
- **Responsibility:** turn (prompt + screenshot list + optional app metadata) into a **validated plan**. Output is structured JSON constrained by a schema. Invalid output is rejected and repaired, never executed as code.
- **Contract (plan JSON):**
  ```json
  {
    "template_id": "product_demo",
    "title": "string",
    "scenes": [
      {"screenshot": "screenshot-1.png", "caption": "string", "duration_s": 3.5, "transition": "fade"}
    ],
    "narration_script": "full voiceover text",
    "voice": "piper-default"
  }
  ```
- **Validation:** `template_id` must be a known template; every `screenshot` must exist in the job; durations bounded; total length capped (e.g. ≤ 90s for v1).

### 6.4 TTS (Piper)
- **Where:** installed on the agent VM (co-located with the render so all render inputs live in one place; keeps the maxed main VPS untouched).
- **Responsibility:** `narration_script` → `voice.wav` → `voice.mp3` (ffmpeg). One default voice for v1.
- **Future:** Kokoro-ONNX as an optional higher-quality "premium voice" toggle once stable.

### 6.5 Remotion render
- **Where:** a new Remotion project (e.g. `video-renderer/`) deployed onto the agent VM; executed via the existing SSH+rsync mechanism (extend `remote_executor.py` with a render path, or a sibling executor sharing its transport).
- **Responsibility:** given screenshots + `voice.mp3` + plan JSON, render `out.mp4` with the chosen template, then rsync it back.
- **Augmentation needed on the agent VM:** install Chromium (ARM64), ffmpeg, and the Remotion project + its npm deps via `scripts/provision_agent_vm.sh`.
- **Execution:** separate timeout from builds (rendering can run several minutes; default e.g. 900s, configurable). Concurrency capped to 1 so a render does not contend with a build on the shared 8GB VM.

### 6.6 Templates
- **Where:** inside the Remotion project as fixed, hand-built compositions.
- **v1 set (small):** e.g. `product_demo` and `feature_walkthrough`. Each defines slots: title card, per-screenshot scenes with captions, a closing CTA, and a synced `<Audio>` voiceover track.
- **Principle:** Claude selects and fills a template; it does not author template code.

### 6.7 Delivery
- **Where:** `tasks` service (status + download), reusing the capability-token model (`edit_capability.py`) so the user downloads their own video without a web login. The web UI polls job status.
- **Optional:** a Discord/Slack DM with the link, reusing the existing webhook-handler post-back used by cron/recruiting results.

## 7. Data model

New table `tasks.video_jobs`:

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | job id |
| `slug` | TEXT | app slug the job belongs to |
| `user_email` | TEXT | owner (matches `assignee_email` model) |
| `status` | TEXT | queued / scripting / voicing / rendering / done / failed |
| `prompt` | TEXT | user's request |
| `plan_json` | JSONB | validated plan from the scripting stage |
| `error` | TEXT NULL | failure reason when `status = failed` |
| `output_path` | TEXT NULL | path to `out.mp4` when done |
| `created_at` | TIMESTAMPTZ | |
| `updated_at` | TIMESTAMPTZ | |

Filesystem layout (per job):
```
/workspace/ai_ui/apps/<slug>/.video/<job_id>/
    screenshots/*.png      ← uploaded inputs
    plan.json              ← validated AI plan
    voice.mp3              ← Piper output
    out.mp4                ← rendered video
```

Access is gated by the same `project_members` ACL + capability-token checks already used for the Visual Editor.

## 8. Error handling

- Any stage failure marks the job `failed` with a human-readable `error`, notifies the user, and stops the pipeline.
- **Scripting:** invalid/unparseable plan JSON triggers a bounded repair retry, then fail.
- **Voicing:** Piper failure fails the job with a clear message.
- **Rendering:** render timeout or non-zero exit fails the job; rsync uses the existing retry pattern (2 attempts).
- **Disk safety:** `.video/<job_id>/` directories are garbage-collected after delivery (and screenshots can be removed once `out.mp4` exists), to protect the main VPS disk. A retention policy (e.g. delete inputs after N days, keep `out.mp4` longer) is configurable.

## 9. Security

- Reuse capability tokens (`X-Edit-Capability`, HMAC via `OAUTH_STATE_SECRET`) for download authorization; reuse `project_members` for access control.
- Strict upload validation: image MIME allowlist, size caps, filename sanitization (existing `upload_validation.py`).
- No AI-authored code is executed. Claude only emits a schema-validated content plan.
- Piper and Remotion run on the agent VM as the unprivileged `claude-agent` user, consistent with the build sandbox.
- No secrets in prompts or plan JSON.

## 10. Resource and cost

- **Main VPS:** untouched by rendering. Only lightweight orchestration (queue, job rows) runs here.
- **Agent VM:** gains Chromium (~500MB) + ffmpeg (~100MB) + the Remotion project + Piper (~150MB). A single render uses an estimated 2 to 4GB RAM; the concurrency cap of 1 keeps it within the ~8GB box while builds may also run. Disk freed by pruning stale Docker images covers installs comfortably.
- **Tokens:** scripting only (cents per video). **Voice:** free (Piper). **No new monthly infrastructure cost** (reuses the existing agent VM), matching the "use what we already have" constraint.

## 11. Testing

Mirror the platform's existing pytest conventions:
- **Unit:** plan-JSON schema validation; queue state machine; template builder helpers (pure functions); upload validation.
- **Integration:** end-to-end render of a fixture job (small screenshots + short script) producing a valid MP4 on the agent VM.
- **Guards:** concurrency cap honored under two concurrent submissions; cleanup of `.video/<job_id>/` after delivery.

## 12. Rollout phases (detail deferred to the implementation plan)

- **Phase 0 — Provision:** add Chromium + ffmpeg + Remotion project + Piper to the agent VM via `provision_agent_vm.sh`; prune stale Docker images.
- **Phase 1 — Data + queue:** `video_jobs` migration, Redis queue, state machine, concurrency cap.
- **Phase 2 — Upload + scripting:** upload endpoint + storage; Claude scripting with schema validation.
- **Phase 3 — Voice + render:** Piper integration; Remotion render path over SSH+rsync; one template end to end.
- **Phase 4 — Web UI + delivery:** upload/preview/download UI; capability-gated download; optional chat notification.
- **Phase 5 — Hardening:** tests, cleanup/retention, second template, deploy via the documented flow.

## 13. Future (non-breaking) extensions

- Kokoro-ONNX premium voice toggle.
- Discord/Slack screenshot upload (new attachment handling in webhook-handler).
- Background music; additional templates; longer videos.
- Move rendering to a dedicated render VM if volume grows (identical SSH+rsync pattern, so no architectural change).
