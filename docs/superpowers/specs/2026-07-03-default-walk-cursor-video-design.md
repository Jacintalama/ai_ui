# Default flow = cursor click-through walk

**Date:** 2026-07-03
**Status:** Approved (design)
**Author:** Ralph Benitez

## Summary

When a user starts a video with **just their website URL and no prompt** (the
"Default flow"), the pipeline should produce a video that *walks through several
real pages of the site* with the smart cursor gliding to and clicking the element
that leads to each next page, exactly like the hand-built `animepahe-tour.mp4`
demo. The **Custom flow** (user typed a prompt) is unchanged.

This is achieved with two real additions plus one routing fix:

1. A **multi-page walk capture** (`capture_walk`) that navigates the site and
   records each page's screenshot plus the *real* click coordinate of the element
   it clicked to advance.
2. A **deterministic plan builder** (`build_walk_plan`) that turns the walk into a
   Remotion anim plan (intro card, one clicked page per scene, outro card) using
   the real click coordinates.
3. A **routing override** so the Default flow always renders through the template +
   smart-cursor path, regardless of the global `AI_VIDEO_CODEGEN` flag.

## Background (current state)

- **Default vs Custom** is decided solely by empty-vs-nonempty `prompt`
  (`video_plan._resolve_brief`, `video_plan.py:357-367`). Empty prompt is
  explicitly allowed through `queue_job` (`routes_video.py:983-985`).
- **Capture** today is single-page only: `capture_site`
  (`video_capture.py:124-201`) scrolls one URL into N viewport frames. There is
  no navigation/clicking. Screenshots are written to
  `<APPS_DIR>/<slug>/.video/<job_id>/screenshots/screenshot-N.png` and
  `site_context.json` (title/headings/meta + host/url) sits alongside
  (`routes_video.py:847-863`).
- **Cursor** is already wired end to end in the *template* renderer: a scene with
  a `screenshot` + `click:{x,y,label}` (with `y <= 0.72`) draws an animated
  cursor + click-pulse. Flow: plan `click` -> `sanitize_anim_clicks`
  (`video_plan.py:431-460`) -> `remotion_scene_dict` (`video_remotion_render.py:11-28`)
  -> `render_remotion_job` -> `theme-parity.tsx` / `cursor.ts`.
- **Routing** to AI-codegen is gated by the global env flag `AI_VIDEO_CODEGEN`
  (`video_codegen.ai_codegen_enabled`). On prod it is `1`, so remotion jobs take
  the AI path, which does **not** draw the cursor. `render_remotion_or_ai` already
  accepts an explicit `ai_enabled: bool | None` override
  (`video_codegen.py:54-90`).
- Ambient music is muxed by the tasks pipeline after render
  (`video_anim._build_audio_mux_args`), so Default-flow videos get a music bed for
  free.

## Scope

**In scope:** the `remotion` render mode (already the default) for external-URL
videos started with an empty prompt.

**Out of scope / unchanged:** the Custom flow (non-empty prompt), the
`slideshow`/`animated` modes, and the AI-codegen path (kept as opt-in). No new DB
columns or migrations (walk data lives on disk + in `plan_json`).

## Design

### Component 1: `capture_walk` (video_capture.py)

New async function that navigates the site following **same-origin hyperlinks
only** and captures each page.

```
async def capture_walk(
    url: str,
    *,
    max_pages: int = 4,
    viewport: tuple[int, int] = (1280, 800),
    nav_timeout_ms: int = 30000,
) -> tuple[list[bytes], list[dict], dict]:
    """Returns (frames, walk, site_context).
    frames[i]  = PNG bytes for page i (viewport, pinned to top).
    walk[i]    = {"url", "title", "click": {"x","y","label"} | None}
                 click is the fraction-coordinate of the element clicked to
                 advance FROM page i to page i+1 (None on the last page).
    site_context = extract_site_context(first page) (as today)."""
```

Behaviour:
- Reuses the existing `_CAPTURE_LOCK`, `assert_capturable` (SSRF guard, applied to
  the start URL **and every navigated URL**), route interception, and viewport.
- For each page: pin to top (`window.scrollTo(0,0)`), screenshot, then choose the
  next-page target via a pure helper `pick_walk_target(candidates)` and record its
  center as a fraction (`x = cx/vw`, `y = cy/vh`), clamped to the visible band
  (`0.03 <= y <= 0.72`). Click it, wait for navigation, dedupe visited URLs, repeat
  up to `max_pages`.
- **Safety:** only anchor (`<a href>`) navigations to the same registrable domain,
  scheme http/https, real GET links. Skip `#`, `javascript:`, `mailto:`, `tel:`,
  external hosts, and anything matching a small deny-list of words
  (`logout`, `signout`, `delete`, `remove`, `sign-out`). Never click
  buttons/forms/JS controls, so nothing on the user's site is submitted or mutated.
- **Single-page fallback:** if no same-origin link is found (typical for
  platform-built single-page apps), fall back to `capture_site` scroll frames for
  that one page; `walk` then has one entry, `click` may be a single prominent
  same-origin link if one is visible, else `None`. No regression vs today.
- **Robustness:** a click that does not navigate stops the walk; pages captured so
  far are used. Per-page nav timeout; overall bounded by `max_pages`.

Two pure, unit-testable helpers are extracted:
- `same_origin(base_url: str, href: str) -> bool`
- `pick_walk_target(candidates: list[dict]) -> dict | None` where each candidate
  is `{href, x, y, w, h, text}` from a single `page.evaluate`; scoring prefers
  larger, higher, visible, same-origin content links in the top 72%.

### Component 2: `build_walk_plan` (new: video_walk_plan.py)

Pure function that turns a walk into a Remotion anim plan, no LLM call.

```
def build_walk_plan(
    walk: list[dict],
    screenshot_names: list[str],
    site_context: dict,
    *,
    fps: int = 24,
    max_duration_s: float = 40.0,
) -> dict:
    """Deterministic plan: intro card -> one screenshot scene per walked page
    (with its real click) -> outro card. Scene shape matches the anim plan the
    template renderer already consumes."""
```

- **Scenes:** intro card (`kind:"intro"`, headline = site host, no screenshot);
  one `kind:"screenshot"` scene per page with `screenshot` = the stored filename,
  `click` = the page's real `{x,y,label}` (omitted when `None` or `y > 0.72`),
  `motion` cycled from `["zoom-in","fade","pan-up","zoom-out"]`, `headline` derived
  from the page `title` (cleaned, first clause), `subtext` = a short label (e.g.
  the URL path or "Home"); outro card (host + tagline).
- **Duration:** cards ~2.6s, pages ~4.0s; if the total exceeds `max_duration_s`,
  drop trailing page scenes (keep intro/outro) so it always fits the 40s cap.
- **Narration:** none in v1 (music-bed only, matching the polished demo feel). The
  existing `ensure_anim_narration` still runs and is a no-op with empty narration.
- Output passes through `sanitize_anim_clicks` for the same guarantees as the AI
  path.

### Component 3: capture route persists the walk (routes_video.py)

`capture_from_url` calls `capture_walk` instead of `capture_site`. It:
- stores frames as `screenshot-N.png` (existing `_store_screenshot_blobs`),
- writes `site_context.json` as today (adds host/url),
- **also writes `walk.json`** = the `walk` list (page order + click coords) next to
  `site_context.json`.
- Capture timeout raised to accommodate multi-page navigation (e.g. 90s).

Because capture always produces `walk.json`, the flow decision is deferred to the
worker; capture does not need to know Default vs Custom.

### Component 4: worker routing (video_worker.py)

In `_process_job`:
- Compute `is_default = not (prompt or "").strip()`.
- **Plan selection** (`:125-146`): when `render_mode == "remotion"` and
  `is_default` and `walk.json` exists -> `plan = build_walk_plan(walk,
  screenshot_names, site_context)`. Otherwise unchanged (`generate_anim_plan` /
  `generate_plan`).
- **Dispatch** (`:163-171`): pass an explicit override
  `ai_enabled = bool((prompt or "").strip()) and ai_codegen_enabled()` to
  `render_remotion_or_ai`. This forces the template + smart-cursor path for the
  Default flow regardless of the global `AI_VIDEO_CODEGEN`, while the Custom flow
  keeps its current behaviour.

### Data flow (Default flow, end to end)

```
URL (no prompt)
  -> draft
  -> capture_from_url: capture_walk -> screenshot-1..N.png + walk.json + site_context.json
  -> queue (empty prompt allowed)
  -> worker: is_default=True
       -> build_walk_plan(walk, names, ctx)  [deterministic, real clicks]
       -> render_remotion_or_ai(..., ai_enabled=False)  [template + cursor]
  -> ffmpeg mux ambient bed
  -> out.mp4
```

## Error handling

- `capture_walk` navigation error / non-navigating click -> stop, use pages so far;
  zero pages -> single-page fallback -> `capture_site`.
- Missing/empty `walk.json` at worker time -> fall back to `generate_anim_plan`
  (current behaviour), so a Default job never fails for lack of walk data.
- `build_walk_plan` with a single page still yields a valid intro/page/outro plan.
- SSRF guard rejects any private/internal navigated URL mid-walk.

## Testing

Pure/unit (no browser):
- `same_origin` — same domain, subdomain, scheme, external, mailto/tel/`#`.
- `pick_walk_target` — scoring, top-72% filter, deny-list, empty candidates.
- `build_walk_plan` — scene count/order, real clicks preserved, `y>0.72` dropped,
  duration cap trims trailing pages, intro/outro present, single-page case,
  `sanitize_anim_clicks` applied.
- Worker routing — Default (empty prompt) + `walk.json` -> `build_walk_plan` +
  `ai_enabled=False`; Custom (prompt) -> unchanged; missing `walk.json` ->
  fallback.

Integration:
- `capture_from_url` route writes `walk.json` alongside screenshots
  (mock `capture_walk`).

Files: add to `tests/test_video_capture.py`, new `tests/test_video_walk_plan.py`,
`tests/test_video_worker.py`, `tests/test_routes_video_capture.py`.

Manual verification on the VPS: run a real Default-flow job for a multi-page site,
extract frames at click moments, confirm the cursor lands on the clicked element
and pages advance (same method used to verify the animepahe demo).

## Decisions (locked, flip on request)

- Up to **4 pages**, capped by the 40s max duration.
- **Same-origin links only** (no button/form clicks) for safety on any URL.
- **Music-bed only**, no narration, in v1.
- Custom flow and AI-codegen path untouched (AI codegen stays opt-in).
- Walk data stored on disk (`walk.json`) + in `plan_json`; **no DB migration**.
