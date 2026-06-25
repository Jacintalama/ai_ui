# Sub-project 1: Pro Auto-Edit Brain (vision + site context + kinetic script)

Date: 2026-06-25
Status: Approved design, pending spec review
Branch: feat/video-pro-brain (off origin/main)

## Goal

Make a paste-URL video feel professionally edited instead of like a slideshow,
by giving the script generator three things it lacks today: (1) it actually
SEES the captured screenshots (vision), (2) it reads the page title and key
text, and (3) it writes a pro kinetic motion-graphics script (hook to CTA, best
shots only, motion + caption + music choreography). All backend (tasks service),
so it improves both Discord and Slack at once.

This is the brain. The Default/Custom UI buttons (Sub-project 3) and any
animated-renderer polish (Sub-project 2) are separate specs.

## Why this is the right lever

Verified in the current code: `generate_plan` / `generate_anim_plan` pass only
screenshot FILENAMES and the user prompt to the model. The model never sees the
pixels and gets no page text. With an empty prompt (paste-URL Default), it falls
back to a one-scene-per-screenshot plan. That is the PowerPoint feeling. Feeding
real images + page text + a stronger brief is the highest-ROI change.

## Approved decisions

- Default brain: agent reads the site (vision + text), then scripts it.
- Default look: kinetic animated (render_mode="animated").
- Custom path: user free-text creative direction steers the same pro editor.
- Also capture page title + key text during the existing Playwright capture.

## Non-goals

- No animated-renderer rewrite here (Sub-project 2). We drive the EXISTING
  animated renderer with a much better plan.
- No Default/Custom UI buttons here (Sub-project 3). Testable now by choosing
  "Animated" mode and pasting a URL.
- No new model. Reuse claude-opus-4-8 with the existing structured-output schema.

## Architecture (all in mcp-servers/tasks/)

### 1. Capture page context (video_capture.py)
During the existing Playwright `capture_site` run, also collect a small
`site_context`:
- `title` = page.title()
- `headings` = text of the first N h1/h2/h3 (cap count + length)
- `meta_description` if present
Bound the total to ~1500 chars. Persist it to the job dir as
`<APPS_DIR>/<slug>/.video/<job_id>/site_context.json` next to `screenshots/`,
and return it from the capture function. If extraction fails, write `{}` and
continue (never fail the capture over context).

### 2. Vision message builder (new module video_vision.py)
One pure, testable responsibility: turn screenshot files + site_context into a
multimodal user-content list for the Anthropic SDK.
- `build_vision_content(screenshot_paths, site_context, brief) -> list[dict]`:
  - For each screenshot (cap at MAX_VISION_IMAGES = 8, in rank order): open with
    Pillow, downscale so the long edge <= VISION_MAX_EDGE = 1568 px (keeps image
    token cost ~1.6k, not the ~4.8k full-res costs), re-encode as JPEG quality
    ~80, base64-encode, and emit
    `{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
    "data": <b64>}}` immediately followed by a small text block naming the file
    (`"screenshot-01.png (page 1)"`) so the model can reference exact filenames.
  - Prepend a text block with the site_context (title, headings, meta) and the
    brief (the user's creative direction, or the Default director instruction).
  - This downscaled copy is ONLY for the model to understand the page; the final
    render still uses the full-resolution captured PNGs on disk.
- Helpers downscale in-memory only (no disk writes), one image at a time (bounded
  memory). Skip any unreadable image rather than failing.

### 3. Vision-enabled plan generation (video_plan.py + the animated planner)
- Change the animated planner (`generate_anim_plan`) and `generate_plan` to
  accept the screenshot PATHS (not just names) and the `site_context`, build the
  message via `build_vision_content`, and call claude-opus-4-8 with the EXISTING
  structured-output schema (ANIM_PLAN_SCHEMA / PLAN_SCHEMA). Use adaptive
  thinking (`thinking={"type":"adaptive"}`); do NOT pass temperature/top_p/
  budget_tokens (removed on opus-4-8). Keep the existing retry + deterministic
  fallback.
- Build the helper so both planners share `build_vision_content`; the creative
  brief text differs per planner (animated gets the kinetic brief below).
- FALLBACK: if the vision call fails after retries, fall back to the current
  behavior (filenames-only prompt, then the deterministic plan) so a job never
  hard-fails.

### 4. The pro kinetic creative brief (animated planner system prompt)
Replace the mechanical ANIM_BEST_PRACTICES checklist with a creative-director
brief that instructs the model to:
- Read the product from the screenshots + page text; identify what it is and who
  it is for.
- Structure a tight arc: hook (what/why-care) -> 2-4 key features/benefits ->
  short CTA. 20-40s total. Pick only the strongest shots; do NOT use every
  screenshot.
- Choreograph motion per scene from the existing animated motion vocabulary
  (zoom-in, zoom-out, pan-up, pan-left, rise, fade): zoom toward the relevant UI
  area, pan across long content, rise for text scenes.
- Captions/headlines: short, punchy, benefit-led; complement (not repeat) the
  narration. Narration conversational, one idea per scene, speakable in the
  scene duration (~2.5 wps).
- Pacing: vary scene length; avoid a run of identical durations; keep it kinetic.
- Output ONLY the existing ANIM_PLAN_SCHEMA (no schema change in this sub-project).
Keep the slideshow brief as-is but it now also benefits from vision.

### 5. Default vs custom brief (prompt handling)
- Custom: the user's free-text direction is the `brief`.
- Default (empty prompt): synthesize a director instruction, e.g. "No brief was
  given. You are the director: study these pages and make the best ~20-40s
  product video. Decide the story, pick the strongest shots, and choreograph it."
- The URL host/title from site_context grounds names either way.

### 6. Worker integration (video_worker.py)
The scripting stage already lists the screenshots dir. Change it to pass the full
PATHS and load `site_context.json` (default `{}` if missing), and pass both into
the planner. No status-flow change.

## Cost / memory

- Images go to the Anthropic API, not held on the box beyond one in-memory
  downscale at a time, so no OOM risk. MAX_VISION_IMAGES=8 at <=1568px long edge
  bounds tokens (~1.6k each, ~13k for images + a small text payload per job).
- The final render is unchanged and still 720p from the full-res captures.

## Testing

- video_capture: site_context extraction returns title/headings/meta (mock the
  Playwright page object); failure writes `{}` and does not raise.
- video_vision.build_vision_content: returns N image blocks + filename labels +
  a leading context/brief text block; downscales a tall/large test image so the
  emitted base64 decodes to an image with long edge <= 1568; caps at
  MAX_VISION_IMAGES; skips an unreadable file; Default vs custom brief text.
- generate_anim_plan / generate_plan (mock the Anthropic client): a successful
  call produces a schema-valid plan and the request carried image blocks; on API
  failure it falls back to the deterministic plan (no raise). No real API calls
  in tests.
- worker: passes paths + loaded site_context into the planner (planner mocked).

## Rollout

- tasks service: covered by the deploy flow for mcp-servers (orchestrator or
  per-file scp + rebuild tasks). Uses the host ANTHROPIC API key already
  configured for video_plan.
- No DB change. No new env var (reuses the existing Anthropic credentials).
- Verify on host: paste a real URL with Animated mode + no prompt, confirm the
  rendered video reflects real product understanding (named features, sensible
  shot selection, varied motion) rather than one-slide-per-shot.

## Open question

- Apply vision to the slideshow planner too (recommended, low marginal cost via
  the shared helper) or animated-only for now? Default: both, since the helper
  is shared and slideshow also benefits.
