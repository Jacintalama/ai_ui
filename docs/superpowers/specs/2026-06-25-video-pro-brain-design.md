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
During the existing async `capture_site` run, also collect a small `site_context`
in the same pass (the Playwright `page` object is in scope at video_capture.py
~:128-161, after the post-redirect SSRF re-check):
- `title` = await page.title()
- `headings` = text of the first N h1/h2/h3 via page.evaluate (cap count + length)
- `meta_description` if present
Bound the total to ~1500 chars. Wrap ALL extraction in try/except so a failure
NEVER turns a successful capture into a failure (fall back to `{}`).

SIGNATURE CHANGE (enumerate every site): `capture_site` returns `list[bytes]`
today (video_capture.py:97-103). Change it to return
`tuple[list[bytes], dict]` (frames, site_context). Update all callers:
- routes_video.py:793 `captured = await asyncio.wait_for(capture_site(...))` ->
  unpack `frames, site_context = ...`; after `_store_screenshot_blobs` writes the
  frames, write `site_context` to `<APPS_DIR>/<slug>/.video/<jid>/site_context.json`
  (slug/jid are already in scope there).
- tests/test_routes_video_capture.py:90 `fake_capture` monkeypatch -> return the
  tuple.
- tests/test_video_capture.py:61 and :106 direct callers -> unpack the tuple.
The job dir layout matches the worker/renderers (video_anim.py:248,
video_render.py:74-75): site_context.json sits next to `screenshots/`.
Note: captured frames are 1280x800 VIEWPORT screenshots (not tall full-page), so
aspect-ratio risk is low; the decode-bomb concern is about uploads (see Cost).

### 2. Vision message builder (new module video_vision.py)
One pure, testable responsibility: turn screenshot files + site_context into a
multimodal user-content list for the Anthropic SDK.
- `build_vision_content(images, site_context, brief) -> list[dict]` where
  `images` is an ordered list of `(basename, abs_path)` pairs (the worker builds
  this from the real on-disk basenames; see Worker integration):
  - For each pair (cap at MAX_VISION_IMAGES = 8, in the order given): open with
    Pillow, downscale so the long edge <= VISION_MAX_EDGE = 1568 px (image token
    cost ~1.6k, vs the ~4.8k full-res costs), re-encode as JPEG quality ~80,
    base64-encode, and emit `{"type": "image", "source": {"type": "base64",
    "media_type": "image/jpeg", "data": <b64>}}` immediately followed by a small
    text block naming the file using its REAL basename (e.g.
    `"<basename> (page N)"`). The label MUST be the exact basename the validator
    and renderers use, because the model echoes it into `scene["screenshot"]`.
    Captured files are named `{host}-{i}.png`, uploads `screenshot-N.png` — do
    NOT assume `screenshot-NN.png`; use whatever the worker passes.
  - Prepend a text block with the site_context (title, headings, meta) and the
    brief (the user's creative direction, or the Default director instruction).
  - This downscaled copy is ONLY for the model to understand the page; the final
    render still uses the full-resolution captured PNGs on disk.
- Downscale in-memory only (no disk writes), one image at a time (bounded
  memory). KEEP Pillow's default `MAX_IMAGE_PIXELS` decompression-bomb guard
  (do not disable it) and wrap `Image.open` in try/except so a corrupt or
  oversize upload is skipped, not raised.

### 3. Vision-enabled plan generation (video_plan.py + the animated planner)
- `generate_anim_plan` (video_plan.py:361) and `generate_plan` (:221) today take
  `(prompt, screenshots, *, attempts=3)` where `screenshots` is a list of BARE
  BASENAMES used for validation (`sc["screenshot"] in set(available)`), scene
  identity, the model's filename instruction, and the deterministic fallback.
  KEEP `screenshots` as basenames unchanged. ADD two keyword-only params with
  defaults so existing callers/tests keep working:
  `generate_anim_plan(prompt, screenshots, *, site_context=None,
  screenshot_paths=None, attempts=3)`. `screenshot_paths` is a `basename -> abs
  path` map (or ordered `(basename, path)` list) consumed ONLY by
  `build_vision_content` to open the image bytes. Everything else stays basenames.
- When `screenshot_paths` is provided, build a multimodal user-content list via
  `build_vision_content(...)` (images + site_context + brief) and call
  claude-opus-4-8 with the EXISTING structured-output schema (output_config
  json_schema). Use adaptive thinking (`thinking={"type":"adaptive"}`); do NOT
  pass temperature/top_p/budget_tokens (the code already passes none — adding
  adaptive thinking introduces no conflict).
- BUMP `max_tokens` from 2048 to ~4096 on the vision/thinking path: adaptive
  thinking tokens count against `max_tokens`, and 2048 risks truncating the JSON
  plan (stop_reason=max_tokens) -> json.loads fail -> forced fallback.
- Both planners share `build_vision_content`; the creative brief text differs
  (animated gets the kinetic brief below; slideshow keeps its brief).
- FALLBACK unchanged and still reachable: if the vision call fails after
  `attempts`, fall back to the current filenames-only prompt, then the
  deterministic `_anim_fallback_plan` / `_fallback_plan` (which build scenes from
  the `screenshots` basenames, so they stay valid and renderable).

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
The scripting stage already lists the screenshots dir as
`sorted(os.listdir(shots_dir))` basenames (video_worker.py:115-116). Keep passing
those basenames as `screenshots` (unchanged). ADDITIONALLY: build the
`basename -> abs path` map from the same listing, load `site_context.json`
(default `{}` if missing), and pass both as the new keyword-only args
(`site_context=..., screenshot_paths=...`). No status-flow change. The new args
are keyword-only with defaults, so `video_refine.py:114` and other callers that
don't pass them are unaffected.

## Cost / memory

- Images go to the Anthropic API, not held on the box beyond one in-memory
  downscale at a time, so no OOM risk. MAX_VISION_IMAGES=8 at <=1568px long edge
  bounds tokens (~1.6k each, ~13k for images + a small text payload per job).
  Vision + adaptive thinking run on every paste-URL job; the slight added
  latency/cost is acceptable for the quality jump.
- The vision builder reads the SAME `screenshots/` dir that user uploads
  (`/screenshots`) and fetched-by-url images (`/screenshots-by-url`) write to.
  Those are the untrusted-size vector (not the viewport captures), so KEEP
  Pillow's default `MAX_IMAGE_PIXELS` guard on and skip-on-error.
- The final render is unchanged and still 720p from the full-res captures.

## Testing

- video_capture: site_context extraction returns title/headings/meta (mock the
  Playwright page object); failure (title/evaluate raises) yields `{}` and does
  not break the capture. Update the existing capture call sites/tests for the new
  tuple return (routes_video.py:793, test_routes_video_capture.py fake_capture,
  test_video_capture.py:61,106).
- New planner params are keyword-only with defaults, so existing
  tests/test_video_plan.py calls (:102,229,253,284) and video_refine.py:114 keep
  passing with no edit.
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
