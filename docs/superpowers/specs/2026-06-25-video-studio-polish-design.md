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
Add `@router.delete("/{job_id}")` (DELETE is a distinct method from the existing
`GET /{job_id}`, so no route shadowing):
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
  the card element from the DOM (and show the empty state if it was the last one).
  On failure, a small inline error/alert.
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
- Install a real font package in `mcp-servers/tasks/Dockerfile` via apt (e.g.
  `fonts-inter`, or a distinctive grotesk) so the existing CSS font-family
  actually resolves in the container instead of falling back. No woff2 binary in
  the repo, no network at render time. Verify the package name exists in the base
  image's apt repo during the build.
- Use a clear type hierarchy in build_composition: small uppercase EYEBROW/kicker,
  bold HEADLINE (tight tracking), optional subtext.

### 2. Kinetic typography
- Replace the single whole-block headline fade with a staggered reveal: split the
  headline into words (or lines) and offset each one's fade+rise by a small delay
  derived from the scene progress `p` in `window.__seek` (deterministic, seek-safe
  - the offset is a pure function of word index + p, no timers).

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
  command; keep libx264/yuv420p/faststart as-is.

### 6. Wiring site_context into the composition
- `render_animated_job` loads `site_context.json` from the job dir (same path the
  worker writes: `<apps>/<slug>/.video/<job_id>/site_context.json`), defaulting
  to `{}` if missing, and passes it to `build_composition(plan, shots,
  site_context=...)`. The composition uses `site_context.title`/host for the
  address pill + a kicker. New keyword arg with a default so existing callers/tests
  keep working.

### Testing (Part A)
- Structural (offline, no Chromium/ffmpeg): build_composition output contains the
  browser-frame markup (dots/address element), the @font-face or font-family, the
  eyebrow element, and per-word headline spans; site_context host appears in the
  address pill when provided and is omitted when not.
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
