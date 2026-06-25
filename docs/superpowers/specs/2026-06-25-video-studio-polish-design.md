# Video Studio Polish: web delete + kinetic renderer polish

Date: 2026-06-25
Status: Approved design, pending spec review
Branch: feat/video-studio-polish (off origin/main)

Two independent improvements to the video studio, both deploying via a tasks
rebuild. Build Part B (delete) first (small, unblocks the user's immediate ask),
then Part A (renderer polish, iterative/visual).

---

## Part B: Delete icon on the web Video Studio

### Backend (routes_video.py)
Add `import shutil` to routes_video.py (NOT currently imported - the import block
has only asyncio/json/logging/os/re/uuid/datetime/Path/urlparse; rmtree will
NameError without it). Then add `@router.delete("/{job_id}")` (DELETE is a
distinct method from the existing `GET /{job_id}` at :361, so no route shadowing):
- `user: CurrentUser = Depends(current_user)`.
- Load the job (session + select VideoJob by id; `_coerce_job_id` for a bad id ->
  404). If None -> 404.
- Ownership: if `job.user_email != user.email and not user.is_admin` -> 403.
- Delete the on-disk job dir: `shutil.rmtree(_apps_dir()/slug/".video"/str(job_id),
  ignore_errors=True)` (slug from the job row).
- Delete the DB row (the video_job_versions FK is ON DELETE CASCADE per
  video_models.py, so versions go with it; confirm and rely on it).
- Return `{"status": "deleted"}`.
- Wrap disk + DB in try/except so a partial failure returns a clean 500, not a
  stack trace.

### Frontend (static/video.html, the list-card render ~lines 1489-1505)
Each card is a `<button class="video-card">` whose click calls `openJob(v.id)`.
- Add a `<span class="vc-del" title="Delete" role="button">` (a small trash glyph,
  e.g. an inline SVG or a trash emoji) into the `vc-meta` row.
- Its click handler: `ev.stopPropagation();` then `if (!confirm("Delete this
  video?")) return;` then `fetch(API + "/" + encodeURIComponent(v.id), {method:
  "DELETE", headers: authHeaders(), credentials: "include"})`; on `r.ok` remove
  the card element from the DOM. If it was the LAST card, call `showList()` (it
  already routes the zero-video case to resetToCreate at video.html:1525-1527)
  rather than unhiding the textless `listEmpty` div. On failure, a small inline alert.
- MUST be a `<span>` (not a nested `<button>` - invalid inside the card button)
  with stopPropagation so clicking trash does not also open the job.
- CSS: `.vc-del` muted color, hover -> red/danger; small, right-aligned in the meta.

### Testing (Part B)
- Backend: DELETE removes the row + dir for the owner; 403 for a non-owner
  non-admin; 404 for a missing/!uuid id. (DB-gated tests skip offline.)
- Frontend: covered by manual verify (the page is static HTML/JS); confirm the
  trash span is present per card and stopPropagation prevents openJob.

---

## Part A: Kinetic renderer polish (video_anim.py)

The renderer is one hardcoded look (near-black bg, Inter stack that likely
falls back to a generic sans in the container, 66%-wide screenshot with rounded
corners + shadow, bottom headline, 6 simple motions, hard cuts, narration only).
Polish it to read as a pro motion-graphics piece. Visual values (sizes, colors,
timings) are TUNED by rendering a real frame and viewing it; the spec fixes the
structure and approach.

### 1. Reliable font (Dockerfile, not a bundled binary)
- Base image is `python:3.11-slim` (Debian bookworm) with an existing apt-get
  layer (Dockerfile:4-9). EXTEND that same RUN layer with `fonts-inter` (present
  in bookworm; installs family "Inter" so the existing `font-family:Inter`
  resolves), a guaranteed fallback (`fonts-liberation2`), AND `fontconfig`. The
  base slim image has NO fontconfig, so a bare `fc-cache` in that RUN would be
  "command not found" and break the `&&` chain - install `fontconfig` in the same
  apt list FIRST, then `fc-cache -f` registers the new fonts (headless Chromium
  reads via fontconfig). (Playwright's later `install --with-deps chromium` also
  pulls fontconfig, but installing it explicitly here makes font registration
  order-independent.) Verify the package names resolve during the build.
- Use a clear type hierarchy in build_composition: small uppercase EYEBROW/kicker,
  bold HEADLINE (tight tracking), optional subtext.

### 2. Kinetic typography
- Replace the single whole-block headline fade with a staggered reveal. CRITICAL:
  keep headline text OUT of the static HTML markup - it is currently delivered as
  a JSON array + assigned via `textContent` (video_anim.py:107,141), and
  `test_build_composition_is_deterministic_and_safe` asserts no HTML injection
  (test_video_anim.py:45). So split the headline into words IN JS (from the
  JSON-supplied string, building spans at runtime in __seek) and offset each
  word's fade+rise by a delay derived from word index + scene progress `p`
  (deterministic, seek-safe, no timers). Do NOT interpolate words into server-side
  markup.

### 3. Browser-chrome frame around the screenshot
- Wrap the screenshot in a mock browser window: a rounded container with a top
  bar (3 traffic-light dots + a faux address pill showing the site host), the
  screenshot below, a large soft shadow, sitting on a padded stage (so it is not
  full-bleed). The host string comes from site_context (see wiring below); if
  absent, omit the address pill text.

### 4. Background depth + always-on motion
- Background: dark gradient (radial or linear) + a soft radial glow behind the
  frame + a subtle grain/vignette overlay (CSS).
- Every screenshot scene gets a gentle ALWAYS-ON Ken Burns (scale ~1.0->1.06 +
  small drift) layered with its chosen motion, so nothing sits perfectly static.
- Smoother easing (e.g. cubic/quint smoothstep) and a fade-through between scenes
  (tighten the existing fade envelope so scene ends/starts cross through the bg
  rather than hard-cutting).

### 5. Ambient music bed (ffmpeg-synth, ducked)
- In render_html_to_mp4 / render_animated_job, synthesize a soft ambient pad with
  ffmpeg lavfi (layered low sine tones + slow tremolo + lowpass + aecho/reverb +
  fade in/out), trimmed/looped to the video duration. No asset file.
- Mix with the narration: if narration exists, duck the music under the voice
  (sidechaincompress, or music at a low fixed level ~0.12 via amix); if no
  narration, the bed plays at a moderate level. Keep `-shortest`.
- Build this as an extra lavfi input + filter_complex in the existing ffmpeg
  command; keep libx264/yuv420p/faststart as-is. WATCH-OUTS:
  - The command relies on IMPLICIT stream mapping today (no -map). The moment a
    filter_complex produces a named audio label, you MUST add explicit
    `-map 0:v -map "[aout]"` or default mapping breaks.
  - Keep the bed UNCONDITIONAL: ambient must play even with no narration, so add
    the lavfi input/filtergraph INSIDE render_html_to_mp4 regardless of audio_path.
    Do NOT add a new kwarg to render_html_to_mp4 - the test fake_render stubs pin
    its exact signature (test_video_anim.py:77-78,110-111) and a new call kwarg
    would TypeError. Keep passing narration.wav as `audio_path` as today.
  - amix of finite narration + infinite ambient: use amix `duration=longest`
    (or `first`) and rely on `-shortest` against the finite PNG video so output
    stops at video end (the infinite sine never extends it).
  - The current encode only appends `-shortest`/`-c:a` when audio_path is set
    (video_anim.py:204-205). Since the bed is now UNCONDITIONAL, restructure that
    branch so there is ALWAYS an audio stream and ALWAYS `-shortest` (against the
    finite PNG-sequence video), in both the narration and no-narration paths -
    otherwise the infinite lavfi sine has nothing finite to bound it and the
    encode hangs.

### 6. Wiring site_context into the composition
- `render_animated_job` loads `site_context.json` from the job dir (same path the
  worker writes: `<apps>/<slug>/.video/<job_id>/site_context.json`), defaulting
  to `{}` if missing, and passes it to `build_composition(plan, shots,
  site_context=...)`. The composition uses `site_context.title`/host for the
  address pill + a kicker. New keyword arg with a default so existing callers/tests
  keep working.
- BLOCKING DATA GAP: `extract_site_context` (video_capture.py:117-121) returns only
  `{title, headings, meta_description}` - there is NO `host` in the persisted
  site_context. The host is computed at routes_video.py:801 (`urlparse(body.url)
  .hostname`) but used only for screenshot filenames, never written into the dict.
  So the address pill would be permanently empty in prod. FIX: in the capture route,
  set `site_context["host"] = host` (and optionally the full url) BEFORE the
  `ctx_path.write_text(json.dumps(site_context))` at routes_video.py:805-806. The
  composition reads host from there; if absent, omit the pill text (covers
  screenshot-upload jobs that have no URL).

### Testing (Part A)
- Structural (offline, no Chromium/ffmpeg): build_composition output contains the
  browser-frame markup (dots/address element), the font-family, and the eyebrow
  element; site_context host appears in the address pill when provided and is
  omitted when not. Do NOT assert literal per-word `<span>`s in the static HTML
  (they are built in JS at runtime, not in markup - asserting them would conflict
  with the no-injection test); instead assert the word-splitting JS function/marker
  is present.
- Keep `render_html_to_mp4`'s signature unchanged (the fake_render stubs pin it);
  the ambient bed is ffmpeg-internal. Keep the existing no-HTML-injection test
  (test_video_anim.py:45) green - headline still flows through JSON+textContent.
- composition_duration / plan mapping unchanged.
- Music: a unit test that the ffmpeg arg builder includes the lavfi ambient input
  + the duck/mix filter when rendering (factor the arg building into a pure helper
  so it is testable without running ffmpeg).
- VISUAL: render one real job in the container, extract a frame PNG, and view it;
  iterate the CSS until it reads pro. (Not a unit test; a build-time check.)
- Keep the existing video_anim tests green (adapt any that assert the old markup).

---

## Rollout (both parts)
- tasks service: deploy the changed files (routes_video.py, static/video.html,
  video_anim.py, Dockerfile) via per-file scp (<=3 per ssh call) + `docker compose
  -f docker-compose.unified.yml up -d --build tasks` (the Dockerfile font install
  makes the rebuild necessary anyway), key ~/.ssh/aiui_vps. Drift-check first.
  NEVER deploy local templates.py.
- Verify: web page shows the trash icon and delete works; render one animated
  video from a URL and confirm the framed/typeset/music output looks pro (view a
  frame + the final mp4 has an audio stream).

## Notes / risks
- Font apt package name must exist in the base image repo - verify at build.
- ffmpeg ambient synth must not blow up render time or memory (it is cheap; lavfi
  audio is light). Keep the filtergraph simple.
- Visual quality is judged by viewing rendered frames; budget a few iterations.
