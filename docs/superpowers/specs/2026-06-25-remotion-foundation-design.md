# Remotion Render Foundation (Sub-project 1 of 3)

Date: 2026-06-25
Status: Approved design, pending spec review
Branch: feat/remotion-foundation (off main)

## Context

The video generator currently renders animated output with a custom pipeline:
a deterministic HTML/CSS/JS composition (`mcp-servers/tasks/video_anim.py`
`build_composition`) is screenshotted frame-by-frame by Playwright headless
Chromium, then ffmpeg encodes the PNG sequence (+ Piper narration + a synthesized
ambient music bed). It is live and produces pro output.

The user wants to migrate the engine to **Remotion** (React-based video) to enable
an animated **click-then-navigate cursor** and a **curated set of user-pickable
themes**. That is a large effort, decomposed into three sub-projects built in
order:

1. **Remotion render foundation** (THIS spec) - stand up the Remotion engine and
   reach visual PARITY with today's animated look, behind a new render_mode.
2. Cursor + click-navigate (planner emits per-shot cursor targets + flow).
3. Curated themes + picker wiring (Discord/Slack/web).

This spec is ONLY sub-project 1. No cursor, no extra themes. Parity is the goal so
the toolchain (Node/React, headless render, ffmpeg mux, fonts, audio, memory on
the 3.7GB box) is proven before the interesting features land.

Decision record: [[project_video_branches_2026-06-24]] (Remotion = GO, in-container,
click-then-navigate cursor, curated themes user-picks).

## Goals / non-goals

- GOAL: a new `video-remotion` container that renders a job's plan to an mp4 that
  visually matches the current `animated` look (the "parity" theme).
- GOAL: wire it into the existing job/queue/worker flow as `render_mode = "remotion"`,
  opt-in, leaving `animated` and `slideshow` untouched and working.
- GOAL: reuse the entire upstream pipeline (URL capture, the vision brain, Piper
  narration + voices, the ducked ambient bed, Discord/Slack/web delivery, delete,
  versioning).
- NON-GOAL: cursor animation, additional themes, Remotion Lambda, replacing the
  existing engines, a live preview UI. Those are later sub-projects / out of scope.

## Architecture

### New container: `video-remotion`
- New top-level dir `video-remotion/` containing a Remotion (React/TypeScript)
  project, a small Fastify HTTP service, and a Dockerfile.
- New service in `docker-compose.unified.yml` named `video-remotion`, on the
  `backend` network only (NOT published to the host / Caddy; internal callers
  only). It shares the same repo bind-mount the tasks service uses
  (`./:/workspace/ai_ui`) so it can read `apps/<slug>/.video/<job_id>/screenshots/*`
  and write the rendered mp4 into the same job dir. (Confirmed: tasks mounts
  `./:/workspace/ai_ui` and `CLAUDE_WORKSPACE=/workspace/ai_ui`, so `apps/` is on
  that bind mount and shareable.)
- Concurrency = 1: an in-service async mutex serializes renders so two headless
  Chromium renders never run at once (bounds RAM on the 3.7GB box).

### Why a separate container (not baking Node into the tasks image)
Keeps the heavy Node/React/Chromium toolchain out of the Python `tasks` image,
matches the platform's multi-container compose pattern, and isolates render
crashes / OOM from the tasks API. The worker just swaps its render call for
`remotion` jobs.

## Components

### `video-remotion/` (Node)
- `src/Root.tsx` - registers a single `Video` composition.
- `src/Video.tsx` + `src/themes/parity/*` - the parity theme: a React/Remotion
  reproduction of the current look, driven by `useCurrentFrame()` +
  `interpolate()` (Remotion is natively frame-deterministic). Visual elements to
  match `video_anim.py build_composition`:
  - dark radial-gradient background + soft glow + vignette,
  - browser-chrome frame around the screenshot with a top bar (3 dots + a faux
    address pill showing the site host), CAPPED height so a tall full-page
    screenshot does not fill the frame (overflow clipped to the hero/top),
  - uppercase eyebrow (site title), bold headline with a kinetic per-word reveal,
    subtext,
  - always-on Ken Burns (scale ~1.0->1.06 + drift) layered on the scene motion
    (zoom-in/out, pan-up, pan-left, rise, fade),
  - smootherstep easing and a fade-through between scenes.
  - eyebrow hidden on screenshot scenes (matches the shipped tuning).
- `inputProps` schema: `{ theme: "parity", fps, width, height, host, title,
  scenes: [{ kind, screenshot (abs path or staticFile), headline, subtext,
  motion, durInFrames }] }`. The host/title feed the address pill + eyebrow.
- `server.ts` (Fastify): `POST /render` and `GET /healthz`.
  - `POST /render` body: `{ jobDir, theme, fps, width, height, host, title,
    scenes, outFile }` (outFile defaults to `<jobDir>/remotion-video.mp4`).
  - Validates input, acquires the mutex, calls `@remotion/renderer`
    `bundle()` + `selectComposition()` + `renderMedia()` to render a VIDEO-ONLY
    mp4 (no audio) to `outFile`, returns `{ ok: true, outPath, frames }`.
  - On failure returns 4xx (bad input) / 5xx (render error) with a short stderr
    tail; logs the full error.
- `Dockerfile`: Node base, install deps, install the Remotion-managed Chromium
  (or use a system Chromium) + the same fonts as the tasks image (Inter +
  fontconfig) so text matches parity, run the Fastify server.

### `mcp-servers/tasks/video_remotion_client.py` (Python)
- `async def render_remotion(job_dir, *, theme, fps, width, height, host, title,
  scenes, base_url) -> str` - thin httpx POST to the `video-remotion` service,
  with a wall-clock timeout; returns the rendered video-only mp4 path or raises a
  clear error. `base_url` from env `VIDEO_REMOTION_URL` (default
  `http://video-remotion:PORT`).

### tasks worker change (`mcp-servers/tasks/video_worker.py` / render dispatch)
- Add a `remotion` branch alongside the existing `animated` / `slideshow` dispatch.
  For a `remotion` job: build the same scene list the brain produced (reuse the
  plan -> scenes mapping), synthesize narration.wav with Piper (existing helper),
  call `render_remotion(...)` to get the video-only mp4, then MUX audio (narration
  + ambient bed) onto it, producing the final `out.mp4` in the job dir, then
  version + mark done exactly as the other modes do.

### audio mux (tasks, reuse Task-6 logic)
- The ambient-bed + narration ffmpeg logic added in the renderer polish
  (`video_anim.py _build_ffmpeg_args`) builds an encode from a PNG sequence. Add a
  sibling pure helper (e.g. `_build_audio_mux_args(video_in, out_path, *,
  audio_path)`) that takes an existing VIDEO file as input 0 (instead of a frames
  pattern), keeps the always-on lavfi ambient bed + ducked-narration mix +
  explicit `-map 0:v -map [aout]` + `-shortest`, and `-c:v copy` (no re-encode of
  the Remotion video). Unit-testable without ffmpeg.

## Data flow

1. Job created (`collecting`) -> screenshots captured (Playwright, tasks) +
   `site_context.json` written (host/title) -> `queued`.
2. Worker picks up a `queued` job with `render_mode = "remotion"`:
   a. run the existing brain (`video_plan`) -> plan (scenes + narration_script),
   b. synthesize `narration.wav` (Piper; voice from the draft) - stays in tasks,
   c. load `site_context.json` for host/title,
   d. POST to `video-remotion` -> `remotion-video.mp4` (video only) in the job dir,
   e. mux narration + ambient bed -> `out.mp4`,
   f. version + status `done`.
3. Everything downstream (share link, studio, Discord/Slack delivery, delete,
   queue, daily limit) unchanged.

## Error handling

- Render failure / timeout / `video-remotion` unreachable -> worker marks the job
  `failed` with a clean message via the existing failed-job path; `animated` and
  `slideshow` jobs are unaffected (remotion is opt-in). No silent fallback in v1.
- Wall-clock timeout on the render HTTP call (mirrors the current renderer's cap)
  so a stuck render cannot hang the worker.
- The service validates inputs and fails closed on a missing screenshot / bad
  scene rather than rendering a broken video.

## How `remotion` mode gets selected (v1)

- `render_mode = "remotion"` is a valid draft value (same mechanism as
  `animated`/`slideshow`). For v1 it is set explicitly (e.g. an admin/dev toggle
  or a draft field) so we can test it without changing the default UX. Flipping it
  on as a default, and the user-facing theme picker, are sub-project 3. (Keeping
  the default unchanged in v1 de-risks the rollout.)

## Testing

- Remotion render-smoke (Node, where Chromium is available): render a ~1s
  composition to mp4, assert a valid file + expected frame count.
- Service: input validation (400 on a bad/missing screenshot), and a `POST
  /render` integration smoke producing an mp4.
- tasks: unit-test the worker's `remotion` branch with the HTTP client mocked
  (asserts it builds the right scene payload, muxes audio, versions, marks done),
  and unit-test `_build_audio_mux_args` (lavfi ambient + amix + `-map` + `-shortest`
  + `-c:v copy`, both narration and no-narration paths).
- Parity check (manual, on the box): render one real job in `animated` and in
  `remotion` mode, extract frames, eyeball that they match closely.

## Rollout

- New container, so the deploy adds `video-remotion` to compose and builds it.
  The Node+Remotion+Chromium image is large (~1-2GB) and the box runs ~85% disk;
  use the prune discipline already in use (`docker builder prune -af` reclaims the
  build-cache hog) before/after the build. Verify the service `/healthz` and a
  real `remotion` render end-to-end before considering it done.
- tasks redeploy for the worker branch + the audio-mux helper + the client.

## Risks

- Image size + disk on the box (mitigated by prune discipline; flag if it does not
  fit and we revisit Lambda).
- Cross-container Chromium overlap (capture in tasks vs render in remotion):
  bounded by single-job worker processing + the service mutex; a shared lock is a
  later hardening if it bites.
- Font/visual parity: Remotion must use the same Inter font and equivalent
  CSS values; parity is judged by viewing real frames, budget a few iterations.
- Determinism: Remotion is frame-based via `useCurrentFrame()`, so it is
  inherently reproducible; avoid any wall-clock/random in the compositions.
