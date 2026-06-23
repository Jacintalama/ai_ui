# Animated video generation (HTML composition) — design

**Date:** 2026-06-23
**Branch:** `fix/video-thread-image-intake`
**Status:** Approved design (phased; build Phase 1 first)
**Depends on / reuses:** the existing video job pipeline (`mcp-servers/tasks/`:
`video_worker.py`, `video_executor.py`, `video_render.py`, `video_plan.py`,
`video_voices.py`, `video_capture.py`), confirmed by the engine-analysis workflow.

## Goal

Add real prompt-driven **animation** (kinetic text, animated callouts/transitions,
motion choreographed around the user's screenshots) — not just the current
ffmpeg screenshot slideshow. Decided with the user: a **second `render_mode`
("animated")**, slideshow stays the default + deterministic fallback; animated
videos **embed the user's real screenshots** and animate around them.

## How the current engine works (from analysis)

`generate_plan` (Claude → JSON slideshow plan) → `VideoRenderExecutor.render` →
captions/cards baked to Pillow PNGs, rsynced to the **agent VM**, where **Piper**
makes narration and **one ffmpeg filtergraph** turns the still screenshots into a
Ken-Burns + xfade + faded-caption MP4. Render is **pure ffmpeg over stills** — no
HTML/Chromium anywhere in the render. Chromium/Playwright lives **in the tasks
container** but is used only for screenshot *capture*. Constraints: ~3.8 GB box,
no GPU, `heavy_lock` (one heavy job at a time), RAM/disk gates, 720p cap, 60 s /
600 s timeouts.

## Architecture

A `render_mode` field on the video job: `"slideshow"` (today; default/fallback)
or `"animated"`.

### Animated render path (new, IN the tasks container)
1. **Composition:** a self-contained, deterministic HTML/CSS/JS file (the
   HyperFrames model: a single paused timeline, seek-safe). It embeds the job's
   screenshots as local assets and choreographs kinetic text / callouts /
   transitions / motion cards. A global `window.__seek(t_seconds)` advances the
   timeline deterministically (no wall-clock, no `Math.random` at runtime).
2. **Frame capture:** Playwright (the in-container Chromium) loads the file, then
   for frame `i` calls `__seek(i/fps)` and `page.screenshot()` → PNG frames
   written to a temp dir (streamed/encoded incrementally, never the whole
   sequence held in memory).
3. **Encode + mux:** **ffmpeg** (added to the tasks container) encodes the frame
   sequence (libx264 veryfast crf 21 yuv420p, `-threads 2`, target fps) and muxes
   the **Piper** narration → `out.mp4`, mirroring the slideshow encoder settings.
4. **Reuse:** the worker, `heavy_lock`, RAM/disk gates, `video_voices` (Piper),
   versions, and `_grant`/done bookkeeping are all reused. The executor **branches
   on `render_mode`**: `animated` → in-container path; `slideshow` → the existing
   SSH-to-agent-VM ffmpeg path, unchanged.

New module `video_anim.py` owns the pure pieces: building the composition HTML
and the frame-capture+encode orchestration, so it is unit-testable and isolated.

### The Remotion/HyperFrames skill (#6)
For `animated` mode, the `VIDEO_BEST_PRACTICES` injection point in `video_plan.py`
(today: "ffmpeg + Piper, NOT Remotion") is swapped for **HyperFrames-animation +
Remotion best-practices** guidance, so the LLM authors motion-aware compositions.
A "Remotion best practices" entry is also added to the Open WebUI Skills page for
visibility; the functional wiring is this prompt hook.

## Phasing (de-risk first)

### Phase 1 — prove the runtime (NO LLM yet) — THIS BUILD
- Add **ffmpeg** to the tasks container (`Dockerfile`: `apt-get install ffmpeg`).
- `video_anim.py`: `build_demo_composition(screenshot_paths, title) -> html` (a
  HARDCODED kinetic composition: animated title → a screenshot pan with a sliding
  caption → outro) and `render_html_to_mp4(html, out_path, *, fps, duration_s,
  audio_path=None)` (Playwright frame-capture + ffmpeg).
- **Local de-risk first:** render the demo composition to a real MP4 on the dev
  machine (Playwright+Chromium present; ffmpeg local or the frame-capture half
  local + encode verified in-container) — assert a valid, multi-frame, visually
  changing MP4. Proves the model before any prod churn.
- **In-container proof:** a minimal `render_mode="animated"` branch wired into the
  executor so a job with that mode renders the demo composition end-to-end through
  the existing pipeline, in-container. Deploy; render one animated job → MP4;
  verify it fits the RAM/`heavy_lock`/timeout budget.
- Guardrails baked in from the start: cap `duration_s` ≤ 40 and `fps` ≤ 24
  (bounds frames ≤ ~960); stream frames; 720p; composition HTML written to a file
  (no prompt/caption text in shell argv — preserves the existing security
  discipline).

### Phase 2 — LLM authoring (next build)
An `animated` plan schema (motion scenes referencing the screenshots), a
`generate_plan` branch, the skill injection (#6), and a composition author that
turns the plan into the HTML (validated/linted before render; deterministic).

### Phase 3 — surface it
Expose `animated` mode in the web create page + Discord (slideshow stays default;
mode chosen by a toggle or by the prompt).

## Testing

- **Phase 1 local:** unit-test `build_demo_composition` (pure: returns HTML
  embedding the given screenshot + a `__seek` timeline). A real-render test
  (skipif no Playwright/ffmpeg) that renders the demo to MP4 and asserts: file
  exists, > a few KB, ffprobe reports video stream + expected duration, and ≥2
  sampled frames differ (motion). Mirrors the `video_capture` test pattern.
- **Phase 1 in-container:** after deploy, render one animated job and confirm a
  valid MP4 within budget; healthz stays green.

## Constraints / risks

- Memory: in-container Chromium + ffmpeg under the existing RAM gate + `heavy_lock`
  (one heavy job at a time, so capture/build/animated-render never collide).
- Frame count bounded by the duration/fps caps; frames streamed to ffmpeg, temp
  dir cleaned in `finally`.
- ffmpeg added to the tasks image (~mild size bump; build-time only).
- Egress: the tasks container already reaches the internet (capture works); no new
  external dependency for Phase 1 (Playwright+Chromium already present; ffmpeg via
  apt).

## Out of scope (this build = Phase 1)

- LLM authoring / plan schema (Phase 2).
- Web/Discord surfacing of the mode (Phase 3).
- Any change to the slideshow engine (untouched; remains default + fallback).
