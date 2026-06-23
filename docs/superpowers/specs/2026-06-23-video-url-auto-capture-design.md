# Auto-capture screenshots from a URL (Discord video flow)

**Date:** 2026-06-23
**Branch:** `fix/video-thread-image-intake` (IO-integrate worktree)
**Status:** Approved design

## Problem

Lukas's top ask: stop making users hand-upload screenshots for a video. Instead,
the system should drive a headless browser, open the user's live site, and take
the screenshots itself. Manual drag-and-drop upload (already shipped) stays as a
fallback.

Today the only screenshot paths are: file upload (`POST /{job_id}/screenshots`)
and server-side fetch of Discord-CDN image URLs (`POST /{job_id}/screenshots-by-url`,
SSRF-locked to the Discord CDN). Neither captures an arbitrary live website.

## User experience

Inside the user's private video thread (opened by clicking **New video**):

- **Paste a URL** as a message (e.g. `https://mysite.com`, no image attached) →
  bot captures the site and replies "Added N screenshots from `<host>`" plus a
  Generate button.
- **Capture from website** button on the studio card → modal asks for the URL →
  same result.

Manual upload is unchanged. All three paths add screenshots to the same draft
job (status `collecting`), then the user picks style/voice and hits Generate.

Decisions locked during brainstorming:
- Trigger = **both** paste-URL (auto) and a button (guided).
- Capture scope = **scroll the page into N viewport-height frames** (reliable on
  any site, gives the video multiple distinct frames). Default N = 5, hard cap 12
  (`MAX_FILES`).

## Architecture

Three layers, each independently testable.

### 1. Capture engine — `mcp-servers/tasks/video_capture.py` (new)

Pure-Python module, no FastAPI imports.

- `async def capture_site(url, *, max_frames=5, viewport=(1280, 800), nav_timeout_ms=20000) -> list[bytes]`
  - `assert_capturable(url)` first (see SSRF below).
  - Acquire a **module-level `asyncio.Lock`** — only one Chromium runs at a time.
  - Launch headless Chromium via `playwright.async_api`, args
    `--no-sandbox --disable-dev-shm-usage --disable-gpu`.
  - New context: desktop viewport + UA. Install a `page.route("**/*")` handler
    that aborts any request whose host is blocked (covers redirects/subresources).
  - `goto(url, wait_until="load", timeout=nav_timeout_ms)`; re-assert `page.url`
    host after navigation (redirect target must also be public).
  - Read `document.body.scrollHeight`; frames = `min(max_frames, ceil(height/viewport_h))`,
    at least 1. For each frame i: scroll to `i*viewport_h`, brief settle wait,
    `page.screenshot(clip=viewport)` → PNG bytes.
  - Always close the browser (try/finally). Overall wall-clock cap.
  - Return list of PNG bytes (1..max_frames).
- Errors raise `CaptureError` (timeout, nav failure, zero frames).
- `is_blocked_ip(ip_str) -> bool` — **pure**, unit-tested exhaustively: blocks
  loopback, private (10/8, 172.16/12, 192.168/16), link-local (169.254/16),
  reserved/unspecified/multicast, IPv6 loopback `::1`, ULA `fc00::/7`,
  link-local `fe80::/10`, and IPv4-mapped equivalents.
- `assert_capturable(url) -> str` — scheme must be http/https; resolve the host
  (`socket.getaddrinfo`), reject if any resolved IP is blocked, and reject the
  literal hostnames `localhost`, the server IP, and internal Docker service
  names. Raises `CaptureError` on any violation. Returns the normalized URL.

Runtime requirement: `playwright` in `requirements.txt`; Dockerfile runs
`python -m playwright install --with-deps chromium`.

### 2. Backend endpoint — `mcp-servers/tasks/routes_video.py`

`POST /{job_id}/capture-from-url` body `{ "url": str, "max_frames": int? }`:

Guard order:
1. Video kill switch (`VIDEO_ENABLED`) → 503.
2. New independent `VIDEO_CAPTURE_ENABLED` (default true) → 503 when off.
3. `assert_capturable(url)` → 400 on SSRF/scheme violation (before any DB work).
4. Job lookup (404) + ownership (`is_admin` or `user_email`) → 403.
5. Free-disk check → 507.
6. `capture_site(url, max_frames=...)` → `CaptureError` → 502 "couldn't capture site".
7. Store PNG bytes via the shared store helper (below) → `{screenshots, count}`.

`max_frames` is clamped server-side to `1..MAX_FILES`.

**Shared store helper + TOCTOU fix.** Extract the in-memory-bytes storage path
shared by `/screenshots-by-url` and `/capture-from-url`:
`_store_screenshot_blobs(slug, jid, blobs: list[tuple[str, bytes]]) -> list[str]`
which, **under a per-job `asyncio.Lock`**, lists existing screenshots, enforces
the count cap (`existing + new <= MAX_FILES` → 400), the cumulative byte cap
(`MAX_TOTAL_BYTES` → 413), validates each blob (`validate_screenshot`), then
writes `screenshot-N.png` continuing the existing numbering. The per-job lock
makes index assignment atomic, fixing the pre-existing race where two near-
simultaneous batches could both compute the same index and overwrite. The
`/screenshots` (UploadFile) endpoint keeps its per-file streaming read cap and
also acquires the same per-job lock around its numbering+write section.

### 3. Discord wiring — `webhook-handler/`

- `handlers/video_intake.py`:
  - `extract_url_message(message) -> dict | None` — primitives (author, channel,
    is_thread, parent, and the first `http(s)://` URL in `message.content`) when a
    thread message carries a URL and no image; else None.
  - `VideoThreadIntake.handle_url_paste(**primitives)` — if in a video-channel
    thread, build the thread `CommandContext` and call `router.run_video_capture(ctx, url)`.
    Outside a thread: ignore (the existing image nudge already tells users where
    screenshots go).
- `handlers/commands.py`: `run_video_capture(self, ctx, url)` — resolve email
  (else not-linked), load current draft (else "No video in progress — click
  **New video** first"), call `self._tasks_client.capture_video_screenshots(email,
  draft_id, url)`, reply "Added screenshots — N/12 so far…" with `build_generate_row`.
  Mirrors `run_video_add`.
- `clients/tasks.py`: `async def capture_video_screenshots(self, user_email, job_id, url, *, max_frames=None)`
  → POST `/{job_id}/capture-from-url`, returns the JSON.
- `handlers/video_panel.py`:
  - `CAPTURE_PREFIX = "aiuivid:capture:"`, `CAPTURE_MODAL_PREFIX = "aiuivid:capturemodal:"`,
    `URL_INPUT = "url"`.
  - `build_capture_modal(job_id)` — one required short text input (URL, max 500,
    placeholder `https://yoursite.com`).
  - `build_studio_components` gains a 4th action row: `[Capture from website]`
    (Discord allows up to 5 rows). Predicates `is_vid_capture` / `is_vid_capture_modal`
    and extractors `job_from_capture` / `job_from_capture_modal`.
- `handlers/discord_commands.py`: button (`is_vid_capture`) → return
  `build_capture_modal`; modal submit (`is_vid_capture_modal`) → extract URL →
  spawn `run_video_capture`.
- `voice_bot.py` on_message: after the image-drop branch, add a URL branch — when
  `video_intake` is set and the message has text (no image), call
  `extract_url_message` and `handle_url_paste`. Skip the bot's own messages.

## Data flow

```
User pastes URL in thread (or Capture button -> modal)
  -> webhook-handler: run_video_capture(ctx, url)
     -> tasks: POST /{job}/capture-from-url
        -> assert_capturable(url)   (SSRF)
        -> capture_site(url)        (headless Chromium, scroll N frames)
        -> _store_screenshot_blobs  (caps + validate + numbering, per-job lock)
     <- {screenshots, count}
  <- "Added N screenshots from <host>"  + Generate button
```

## Error handling

- SSRF / bad scheme → 400, bot says "That URL can't be captured."
- Capture failure/timeout → 502, bot says "Couldn't capture that site — try
  again or drag screenshots in instead." (keeps the manual fallback visible).
- Not linked / no draft → existing not-linked + "click New video first" replies.
- Count/size caps → existing 400/413 messages.
- Capture disabled (`VIDEO_CAPTURE_ENABLED=false`) → 503, bot says capture is off,
  drag screenshots in instead.

## Memory / runtime tradeoff (accepted)

Chromium grows the `tasks` image ~300–400 MB. A capture transiently uses
~300–400 MB RAM for a few seconds, **serialized to one at a time**. Steady-state
RAM is unchanged. `VIDEO_CAPTURE_ENABLED=false` disables capture instantly
without touching the rest of video. Caps: nav 20s, frames default 5 / max 12,
overall wall-clock cap. Rejected alternative: external screenshot API (paid key,
not "we drive the browser").

## Testing

- **Unit (offline, in suite):**
  - `is_blocked_ip` truth table; `assert_capturable` blocks localhost / private /
    server IP / docker names, allows public.
  - Endpoint with `capture_site` mocked: auth (401/403), kill switches (503),
    SSRF (400), capture error (502), happy path stores + returns count; caps.
  - `_store_screenshot_blobs` numbering + caps; per-job lock serializes.
  - Discord: `extract_url_message` (detects URL, ignores image/no-URL/non-thread),
    `run_video_capture` runner, panel button + modal build/route, tasks-client body.
- **Real browser (run locally once):** `capture_site("https://example.com")`
  returns >= 1 valid PNG. `@skipif` when Playwright/Chromium absent so the suite
  stays green offline.
- **In-container e2e (after deploy, gated):** draft -> capture a real site ->
  verify screenshots in PG/disk -> Generate -> MP4.

## Deploy (final, gated on explicit approval)

- `tasks`: scp `routes_video.py`, `video_capture.py`, `requirements.txt`,
  `Dockerfile` → rebuild (downloads Chromium at build time) → `/healthz` smoke +
  capture e2e. Set `VIDEO_CAPTURE_ENABLED=true` (default) in server `.env` —
  never edit other `.env` values.
- `webhook-handler`: scp the changed handler/client files → rebuild → verify Up +
  gateway reconnect. Re-register `/video` only if its command shape changed (it
  does not — capture is button/modal/paste, not a slash option).
- Reconcile: branch is still local; push after deploy.

## Out of scope (YAGNI)

- Following nav links / multi-page crawl (chosen scroll-frames instead).
- Full DNS-rebinding defense beyond pre-resolve + route abort (internal tool,
  linked accounts only).
- Authenticated-site capture (login walls).
