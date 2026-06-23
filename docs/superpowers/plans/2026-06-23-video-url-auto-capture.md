# Video URL Auto-Capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a Discord user get screenshots for a video by giving a site URL — the `tasks` service drives headless Chromium, scrolls the page into N frames, and stores them on the draft. Manual upload stays as fallback.

**Architecture:** New `video_capture.py` engine in the tasks service (SSRF-guarded, one-browser-at-a-time) + a `POST /{job_id}/capture-from-url` endpoint that reuses a shared blob-store helper. In the bot: a `run_video_capture` runner reached two ways — a pasted URL in the video thread (gateway `on_message`) and a "Capture from website" button → modal.

**Tech Stack:** Python 3.11, FastAPI, Playwright (Chromium), httpx, pytest (asyncio), discord.py gateway (existing).

All paths are in the `IO-integrate` worktree (`C:/Users/alama/Desktop/Lukas Work/IO-integrate`), branch `fix/video-thread-image-intake`.

---

## File Structure

**tasks service (`mcp-servers/tasks/`)**
- Create `video_capture.py` — SSRF guard (`is_blocked_ip`, `assert_capturable`), `capture_enabled()`, `capture_site()` engine. No FastAPI imports.
- Modify `routes_video.py` — `_job_lock`, `_store_screenshot_blobs` helper, `POST /{job_id}/capture-from-url`; route the byte endpoints through the helper.
- Modify `requirements.txt` — add `playwright`.
- Modify `Dockerfile` — `playwright install --with-deps chromium`.
- Tests: `tests/test_video_capture.py` (new), `tests/test_routes_video_capture.py` (new).

**bot (`webhook-handler/`)**
- Modify `clients/tasks.py` — `capture_video_screenshots()`.
- Modify `handlers/commands.py` — `run_video_capture()`.
- Modify `handlers/video_panel.py` — capture modal + button + ids/predicates.
- Modify `handlers/video_intake.py` — `extract_url_message()` + `handle_url_paste()`.
- Modify `handlers/discord_commands.py` — button→modal, modal→capture, studio copy.
- Modify `voice_bot.py` — `on_message` URL branch.
- Tests: extend `tests/test_video_intake.py`, `tests/test_video_runners.py`, `tests/test_video_routing.py`, `tests/test_video_panel*`/`tests/test_tasks_client_video.py`.

---

## Task 1: SSRF guard (pure) in `video_capture.py`

**Files:**
- Create: `mcp-servers/tasks/video_capture.py`
- Test: `mcp-servers/tasks/tests/test_video_capture.py`

- [ ] **Step 1: Write the failing test**

```python
# mcp-servers/tasks/tests/test_video_capture.py
"""Unit tests for the URL-capture SSRF guard and helpers. The real-browser
capture test is skipped unless Playwright+Chromium are installed locally."""
import pytest

from video_capture import CaptureError, assert_capturable, capture_enabled, is_blocked_ip


@pytest.mark.parametrize("ip", [
    "127.0.0.1", "10.0.0.5", "172.16.3.4", "192.168.1.1", "169.254.169.254",
    "0.0.0.0", "::1", "fc00::1", "fe80::1", "::ffff:127.0.0.1", "not-an-ip",
])
def test_is_blocked_ip_blocks_internal(ip):
    assert is_blocked_ip(ip) is True


@pytest.mark.parametrize("ip", ["1.1.1.1", "8.8.8.8", "93.184.216.34", "2606:2800:220:1::1"])
def test_is_blocked_ip_allows_public(ip):
    assert is_blocked_ip(ip) is False


@pytest.mark.parametrize("url", [
    "ftp://example.com", "file:///etc/passwd", "http://localhost/x",
    "http://app.localhost/x", "http://127.0.0.1/x", "http://10.0.0.1/x",
    "http://169.254.169.254/latest/meta-data/",
])
def test_assert_capturable_rejects(url):
    with pytest.raises(CaptureError):
        assert_capturable(url)


def test_assert_capturable_allows_public_ip_literal():
    # A public IP literal resolves to itself — no DNS needed, safe offline.
    assert assert_capturable("https://1.1.1.1/") == "https://1.1.1.1/"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_video_capture.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'video_capture'`.

- [ ] **Step 3: Write minimal implementation**

```python
# mcp-servers/tasks/video_capture.py
"""Headless-Chromium screenshot capture for video jobs.

Drives a short-lived, one-at-a-time headless Chromium to screenshot a user's
live site (scrolled into N viewport-height frames), so users don't have to
upload screenshots by hand. SSRF-guarded: only http/https public hosts —
loopback, private, link-local and reserved addresses are refused so the browser
can never be pointed at internal services or the cloud metadata endpoint.

No FastAPI imports here; the endpoint in routes_video.py wraps this.
"""
from __future__ import annotations

import asyncio
import ipaddress
import math
import os
import socket
from urllib.parse import urlparse


class CaptureError(Exception):
    """Capture could not be performed (bad/blocked URL, timeout, nav failure)."""


# One browser at a time — the box has ~3.8GB RAM, so captures are serialized.
_CAPTURE_LOCK = asyncio.Lock()


def capture_enabled() -> bool:
    """Independent kill switch (defaults on). Set VIDEO_CAPTURE_ENABLED=false to
    disable site capture instantly without disabling the rest of video."""
    return os.environ.get("VIDEO_CAPTURE_ENABLED", "true").strip().lower() == "true"


def is_blocked_ip(ip_str: str) -> bool:
    """True if an address must not be fetched: unparseable, loopback, private,
    link-local, reserved, multicast or unspecified (v4, v6, and v4-mapped v6)."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return (
        ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_reserved or ip.is_multicast or ip.is_unspecified
    )


def assert_capturable(url: str) -> str:
    """Return the URL if it is safe to capture, else raise CaptureError. Scheme
    must be http/https; the host must not be localhost and must not resolve to
    any blocked address. Resolves the host (literal IPs resolve to themselves)."""
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        raise CaptureError("only http/https URLs can be captured")
    host = (p.hostname or "").strip()
    low = host.lower()
    if not host or low == "localhost" or low.endswith(".localhost"):
        raise CaptureError("that host can't be captured")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise CaptureError("could not resolve that host") from e
    for info in infos:
        if is_blocked_ip(info[4][0]):
            raise CaptureError("that host resolves to a blocked address")
    return url
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_video_capture.py -q`
Expected: PASS (all parametrized cases).

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/video_capture.py mcp-servers/tasks/tests/test_video_capture.py
git commit -m "feat(video-capture): SSRF guard + kill switch for URL capture

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `capture_site()` engine + Playwright in the image

**Files:**
- Modify: `mcp-servers/tasks/video_capture.py`
- Modify: `mcp-servers/tasks/requirements.txt`
- Modify: `mcp-servers/tasks/Dockerfile`
- Test: `mcp-servers/tasks/tests/test_video_capture.py`

- [ ] **Step 1: Write the failing test (real browser, skipped if absent)**

Append to `tests/test_video_capture.py`:

```python
import pytest as _pytest

playwright_async = _pytest.importorskip("playwright.async_api")


@_pytest.mark.asyncio
async def test_capture_site_real_example():
    """Real headless-Chromium capture of a public page. Skipped if Playwright or
    its Chromium build is not installed (so the suite stays green offline); run
    locally after `python -m playwright install chromium`."""
    from video_capture import CaptureError, capture_site
    try:
        frames = await capture_site("https://example.com", max_frames=2)
    except CaptureError as e:
        _pytest.skip(f"chromium not available: {e}")
    assert 1 <= len(frames) <= 2
    assert frames[0][:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_video_capture.py::test_capture_site_real_example -q`
Expected: SKIP if Playwright not installed, else FAIL with `ImportError: cannot import name 'capture_site'`.

- [ ] **Step 3: Write minimal implementation**

Append to `video_capture.py`:

```python
_BLOCK_LITERAL_HOSTS = {"localhost"}


def _host_is_literal_blocked(host: str) -> bool:
    """Cheap synchronous check for the in-browser route guard: block localhost
    and any IP-literal host that is private/internal. Hostnames are allowed here
    because the top-level URL was already pre-resolved by assert_capturable."""
    low = (host or "").lower()
    if low in _BLOCK_LITERAL_HOSTS or low.endswith(".localhost"):
        return True
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False  # a name, not a literal — pre-resolve already vetted the top URL
    return is_blocked_ip(host)


async def capture_site(
    url: str,
    *,
    max_frames: int = 5,
    viewport: tuple[int, int] = (1280, 800),
    nav_timeout_ms: int = 20000,
) -> list[bytes]:
    """Capture a live site as up to `max_frames` viewport-height PNG frames by
    scrolling top-to-bottom. Serialized to one browser at a time. Raises
    CaptureError on a blocked URL, missing engine, timeout, or zero frames."""
    assert_capturable(url)
    try:
        from playwright.async_api import async_playwright
    except ImportError as e:
        raise CaptureError("capture engine unavailable") from e

    vw, vh = viewport
    frames: list[bytes] = []
    async with _CAPTURE_LOCK:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
            )
            try:
                context = await browser.new_context(
                    viewport={"width": vw, "height": vh},
                    user_agent="Mozilla/5.0 (compatible; AIUI-VideoCapture)",
                )
                page = await context.new_page()

                async def _route(route):
                    host = urlparse(route.request.url).hostname or ""
                    if _host_is_literal_blocked(host):
                        await route.abort()
                    else:
                        await route.continue_()

                await page.route("**/*", _route)
                try:
                    await page.goto(url, wait_until="load", timeout=nav_timeout_ms)
                except Exception as e:  # noqa: BLE001 - playwright TimeoutError etc.
                    raise CaptureError(f"could not load the page: {e}") from e
                # A redirect may have landed somewhere internal — re-check.
                assert_capturable(page.url)
                height = int(await page.evaluate("document.body.scrollHeight") or vh)
                n = max(1, min(max_frames, math.ceil(height / vh)))
                for i in range(n):
                    await page.evaluate(f"window.scrollTo(0, {i * vh})")
                    await page.wait_for_timeout(400)
                    frames.append(await page.screenshot(
                        clip={"x": 0, "y": 0, "width": vw, "height": vh}))
            finally:
                await browser.close()
    if not frames:
        raise CaptureError("no frames captured")
    return frames
```

- [ ] **Step 4: Add Playwright to the build**

`mcp-servers/tasks/requirements.txt` — add a line:
```
playwright
```

`mcp-servers/tasks/Dockerfile` — add a RUN after `pip install` (line 13), before `COPY . .`:
```dockerfile
RUN pip install --no-cache-dir -r requirements.txt
RUN python -m playwright install --with-deps chromium
COPY . .
```

- [ ] **Step 5: Run the suite (offline: real-browser test SKIPs)**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_video_capture.py -q`
Expected: SSRF tests PASS; `test_capture_site_real_example` SKIP (offline) — or PASS after a local `pip install playwright && python -m playwright install chromium`.

- [ ] **Step 6: Commit**

```bash
git add mcp-servers/tasks/video_capture.py mcp-servers/tasks/tests/test_video_capture.py mcp-servers/tasks/requirements.txt mcp-servers/tasks/Dockerfile
git commit -m "feat(video-capture): headless Chromium scroll-capture engine + image deps

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Shared blob-store helper + per-job lock in `routes_video.py`

**Files:**
- Modify: `mcp-servers/tasks/routes_video.py` (imports near line 31; helpers after `_next_screenshot_index` ~line 117; refactor `/screenshots-by-url` ~line 696 and `/screenshots` write ~line 612)
- Test: `mcp-servers/tasks/tests/test_routes_video_capture.py` (new; helper-only part here)

- [ ] **Step 1: Write the failing test**

```python
# mcp-servers/tasks/tests/test_routes_video_capture.py
"""Tests for the shared screenshot blob-store helper and the capture-from-url
endpoint. Helper tests use a tmp dir (no DB). Endpoint guard tests that fire
before any DB call run offline; the happy/ownership paths need Postgres and are
skipped offline (run at deploy/CI)."""
import os
import uuid

import pytest
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("AIUI_FERNET_KEY", Fernet.generate_key().decode())

import routes_video  # noqa: E402
from routes_video import _store_screenshot_blobs  # noqa: E402

_DB_URL = os.environ.get("DATABASE_URL", "")
_HAVE_DB = bool(_DB_URL) and "nowhere" not in _DB_URL


def _png() -> bytes:
    import io
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (60, 60), "blue").save(b, "PNG")
    return b.getvalue()


async def test_store_blobs_numbers_after_existing(tmp_path, monkeypatch):
    monkeypatch.setenv("APPS_DIR", str(tmp_path))
    slug, jid = "vid-abc", "11111111-1111-1111-1111-111111111111"
    first = await _store_screenshot_blobs(slug, jid, [("a.png", _png())])
    assert first == ["screenshot-1.png"]
    second = await _store_screenshot_blobs(slug, jid, [("b.png", _png()), ("c.png", _png())])
    assert second == ["screenshot-1.png", "screenshot-2.png", "screenshot-3.png"]


async def test_store_blobs_enforces_count_cap(tmp_path, monkeypatch):
    from fastapi import HTTPException
    monkeypatch.setenv("APPS_DIR", str(tmp_path))
    slug, jid = "vid-cap", "22222222-2222-2222-2222-222222222222"
    blobs = [(f"{i}.png", _png()) for i in range(routes_video.MAX_FILES + 1)]
    with pytest.raises(HTTPException) as ei:
        await _store_screenshot_blobs(slug, jid, blobs)
    assert ei.value.status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_routes_video_capture.py -q`
Expected: FAIL — `ImportError: cannot import name '_store_screenshot_blobs'`.

- [ ] **Step 3: Write minimal implementation**

In `routes_video.py`, add `import asyncio` to the stdlib imports (near line 31, after `import logging`).

After `_next_screenshot_index` (after line 117), add:

```python
# Per-job write locks make screenshot-index assignment atomic across the
# concurrent writers (/screenshots, /screenshots-by-url, /capture-from-url),
# fixing the index-reuse race where two near-simultaneous batches could both
# compute the same screenshot-N and overwrite each other.
_JOB_LOCKS: dict[str, asyncio.Lock] = {}


def _job_lock(jid: str) -> asyncio.Lock:
    lock = _JOB_LOCKS.get(jid)
    if lock is None:
        lock = asyncio.Lock()
        _JOB_LOCKS[jid] = lock
    return lock


async def _store_screenshot_blobs(slug: str, jid: str, blobs: list[tuple[str, bytes]]) -> list[str]:
    """Validate and write already-in-memory screenshot bytes onto a job, under
    the per-job lock. Enforces the count cap (400), cumulative byte cap (413) and
    per-file validation (400), then writes screenshot-N continuing the existing
    numbering. Returns the full screenshot list. Callers do disk/ownership/auth."""
    shots_dir = _apps_dir() / slug / ".video" / jid / "screenshots"
    async with _job_lock(jid):
        existing = _list_screenshots(slug, jid)
        if len(existing) + len(blobs) > MAX_FILES:
            raise HTTPException(400, f"max {MAX_FILES} screenshots per job")
        total = sum(
            (shots_dir / name).stat().st_size
            for name in existing
            if (shots_dir / name).is_file()
        )
        validated: list[bytes] = []
        for fname, data in blobs:
            total += len(data)
            if total > MAX_TOTAL_BYTES:
                raise HTTPException(413, "batch too large")
            try:
                validate_screenshot(fname or "x.png", data)
            except ScreenshotRejected as e:
                raise HTTPException(400, str(e))
            validated.append(data)
        start = _next_screenshot_index(existing)
        shots_dir.mkdir(parents=True, exist_ok=True)
        for i, data in enumerate(validated):
            (shots_dir / f"screenshot-{start + i}.png").write_bytes(data)
        return _list_screenshots(slug, jid)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_routes_video_capture.py -q`
Expected: PASS (both helper tests).

- [ ] **Step 5: Route `/screenshots-by-url` through the helper**

In `add_screenshots_by_url` (~line 658-700), replace the block from `shots_dir = _apps_dir()...` through the write loop and `return` with: keep the early count pre-check and per-URL streaming size cap, collect `(filename, bytes)` pairs, then delegate. Replace lines 658-700 body with:

```python
    existing = _list_screenshots(slug, str(jid))
    if len(existing) + len(body.urls) > MAX_FILES:
        raise HTTPException(400, f"max {MAX_FILES} screenshots per job")
    blobs: list[tuple[str, bytes]] = []
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
        for url in body.urls:
            try:
                async with client.stream("GET", url) as resp:
                    resp.raise_for_status()
                    declared = resp.headers.get("content-length")
                    if declared is not None and declared.isdigit() and int(declared) > MAX_FILE_BYTES:
                        raise HTTPException(413, "screenshot too large (max 10 MB)")
                    buf = bytearray()
                    async for chunk in resp.aiter_bytes():
                        buf.extend(chunk)
                        if len(buf) > MAX_FILE_BYTES:
                            raise HTTPException(413, "screenshot too large (max 10 MB)")
            except httpx.HTTPError:
                raise HTTPException(400, "could not fetch screenshot URL")
            fname = urlparse(url).path.rsplit("/", 1)[-1] or "x.png"
            blobs.append((fname, bytes(buf)))
    shots = await _store_screenshot_blobs(slug, str(jid), blobs)
    return {"screenshots": shots, "count": len(shots)}
```

- [ ] **Step 6: Make `/screenshots` numbering atomic via the same lock**

In `add_screenshots` (~line 612), wrap the existing numbering+write tail in the per-job lock. Replace the tail (from `shots_dir.mkdir(...)` / the `for i, body in enumerate(raw)` write loop and `return`) so the index is read+written under the lock:

```python
    async with _job_lock(str(jid)):
        existing = _list_screenshots(slug, str(jid))
        if existing_count != len(existing):
            existing_count = len(existing)
            start = _next_screenshot_index(existing)
        shots_dir.mkdir(parents=True, exist_ok=True)
        for i, body in enumerate(raw):
            (shots_dir / f"screenshot-{start + i}.png").write_bytes(body)
    return {"screenshots": _list_screenshots(slug, str(jid))}
```

(Note: `start`/`existing_count` were computed earlier; recompute under the lock so a concurrent writer that landed between cannot collide.)

- [ ] **Step 7: Run the existing screenshot tests — must stay green**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_routes_video_upload.py tests/test_routes_video_refine.py tests/test_routes_video_capture.py -q`
Expected: PASS (DB-gated ones SKIP offline). If any fails, the refactor changed observable behavior — reconcile before continuing.

- [ ] **Step 8: Commit**

```bash
git add mcp-servers/tasks/routes_video.py mcp-servers/tasks/tests/test_routes_video_capture.py
git commit -m "refactor(video): shared blob-store helper + per-job lock (fixes screenshot index race)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: `POST /{job_id}/capture-from-url` endpoint

**Files:**
- Modify: `mcp-servers/tasks/routes_video.py` (import near line 63; new endpoint after `add_screenshots_by_url` ~line 700)
- Test: `mcp-servers/tasks/tests/test_routes_video_capture.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_routes_video_capture.py`:

```python
HEAD = {"X-User-Email": "ralph@aiui.com", "X-User-Admin": "true"}


async def _post(url_body, headers=HEAD):
    from main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        return await c.post(
            "/api/video-jobs/00000000-0000-0000-0000-000000000000/capture-from-url",
            json=url_body, headers=headers)


async def test_capture_endpoint_blocks_ssrf_before_db():
    r = await _post({"url": "http://127.0.0.1/admin"})
    assert r.status_code == 400


async def test_capture_endpoint_rejects_bad_scheme():
    r = await _post({"url": "file:///etc/passwd"})
    assert r.status_code == 400


async def test_capture_endpoint_503_when_capture_disabled(monkeypatch):
    monkeypatch.setenv("VIDEO_CAPTURE_ENABLED", "false")
    r = await _post({"url": "https://example.com"})
    assert r.status_code == 503


async def test_capture_endpoint_requires_auth():
    r = await _post({"url": "https://example.com"}, headers={})
    assert r.status_code == 401


@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_capture_endpoint_stores_frames(db_session, tmp_path, monkeypatch):
    """DB happy path with the browser mocked: a draft owner captures a site and
    the returned frames are stored as screenshots on the job."""
    monkeypatch.setenv("APPS_DIR", str(tmp_path))

    async def fake_capture(url, *, max_frames=5):
        return [_png(), _png(), _png()]

    monkeypatch.setattr(routes_video, "capture_site", fake_capture)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        draft = await c.post("/api/video-jobs/draft",
                             json={"title": "t", "prompt": "", "style": "clean_product_demo",
                                   "voice": "amy"}, headers=HEAD)
        jid = draft.json()["id"]
        r = await c.post(f"/api/video-jobs/{jid}/capture-from-url",
                         json={"url": "https://example.com", "max_frames": 3}, headers=HEAD)
    assert r.status_code == 200
    assert r.json()["count"] == 3
```

(Add `from main import app` at the top of the file alongside the other imports.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_routes_video_capture.py -q`
Expected: FAIL — 404 (endpoint not found) on the guard tests.

- [ ] **Step 3: Write minimal implementation**

In `routes_video.py`, add to the local imports (after line 63):

```python
from video_capture import CaptureError, assert_capturable, capture_enabled, capture_site
```

After `add_screenshots_by_url` (~line 700), add:

```python
class CaptureUrlRequest(BaseModel):
    url: str = Field(..., min_length=1, max_length=2048)
    max_frames: int | None = Field(default=None, ge=1, le=MAX_FILES)


@router.post("/{job_id}/capture-from-url")
async def capture_from_url(
    job_id: str,
    body: CaptureUrlRequest,
    user: CurrentUser = Depends(current_user),
) -> dict:
    """Capture screenshots of a live site server-side (headless Chromium) and add
    them to a job. Guard order: video kill switch (503), capture kill switch
    (503), SSRF/scheme (400, before any DB), missing job (404), ownership (403),
    free-disk (507), capture failure (502). Frames are clamped to 1..MAX_FILES
    and stored via the shared blob helper (count/size/validation caps + numbering)."""
    if not _video_enabled():
        raise HTTPException(503, "Video generation is disabled")
    if not capture_enabled():
        raise HTTPException(503, "Site capture is disabled")
    try:
        assert_capturable(body.url)
    except CaptureError as e:
        raise HTTPException(400, str(e))
    jid = _coerce_job_id(job_id)
    async with session() as s:
        job = (await s.execute(
            select(VideoJob).where(VideoJob.id == jid)
        )).scalar_one_or_none()
        if job is None:
            raise HTTPException(404, "Video job not found")
        if not user.is_admin and job.user_email != user.email:
            raise HTTPException(403, "Not authorized for this video")
        slug = job.slug
    if not enough_free_disk(
        str(_apps_dir()), int(os.environ.get("VIDEO_MIN_FREE_DISK_MB", "2000"))
    ):
        raise HTTPException(507, "Insufficient storage; try again later")
    frames = max(1, min(body.max_frames or 5, MAX_FILES))
    try:
        captured = await capture_site(body.url, max_frames=frames)
    except CaptureError as e:
        raise HTTPException(502, f"couldn't capture site: {e}")
    host = urlparse(body.url).hostname or "site"
    blobs = [(f"{host}-{i + 1}.png", data) for i, data in enumerate(captured)]
    shots = await _store_screenshot_blobs(slug, str(jid), blobs)
    return {"screenshots": shots, "count": len(shots)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_routes_video_capture.py -q`
Expected: PASS — the four guard tests pass offline; `test_capture_endpoint_stores_frames` SKIPs offline (runs at deploy/CI).

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/routes_video.py mcp-servers/tasks/tests/test_routes_video_capture.py
git commit -m "feat(video): POST /capture-from-url endpoint (headless Chromium capture)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: `capture_video_screenshots` tasks-client method

**Files:**
- Modify: `webhook-handler/clients/tasks.py` (after `add_video_screenshots_urls` ~line 287)
- Test: `webhook-handler/tests/test_tasks_client_video.py`

- [ ] **Step 1: Write the failing test**

Append to `webhook-handler/tests/test_tasks_client_video.py`:

```python
@pytest.mark.asyncio
async def test_capture_video_screenshots_posts_url():
    from clients.tasks import TasksClient
    tc = TasksClient(base_url="http://t")
    captured = {}

    async def fake_request(method, path, user_email, **kwargs):
        captured.update(method=method, path=path, email=user_email, **kwargs)

        class R:
            def json(self_inner):
                return {"screenshots": ["screenshot-1.png"], "count": 1}
        return R()

    tc._request = fake_request
    out = await tc.capture_video_screenshots("u@x.com", "job1", "https://site.com")
    assert out["count"] == 1
    assert captured["method"] == "POST"
    assert captured["path"] == "/api/video-jobs/job1/capture-from-url"
    assert captured["json"] == {"url": "https://site.com"}
    assert captured["timeout"] == 45.0
```

(Ensure `import pytest` is present at the top of that test file — it is, used by sibling tests.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webhook-handler && python -m pytest tests/test_tasks_client_video.py::test_capture_video_screenshots_posts_url -q`
Expected: FAIL — `AttributeError: 'TasksClient' object has no attribute 'capture_video_screenshots'`.

- [ ] **Step 3: Write minimal implementation**

In `clients/tasks.py`, after `add_video_screenshots_urls` (~line 287):

```python
    async def capture_video_screenshots(self, user_email: str, job_id: str, url: str,
                                        *, max_frames: int | None = None) -> dict[str, Any]:
        """Drive server-side headless-browser capture of `url` onto the job. Uses
        a longer timeout than the default because a capture takes seconds."""
        body: dict[str, Any] = {"url": url}
        if max_frames is not None:
            body["max_frames"] = max_frames
        resp = await self._request("POST", f"/api/video-jobs/{job_id}/capture-from-url",
                                   user_email, json=body, timeout=45.0)
        return resp.json()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd webhook-handler && python -m pytest tests/test_tasks_client_video.py::test_capture_video_screenshots_posts_url -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/clients/tasks.py webhook-handler/tests/test_tasks_client_video.py
git commit -m "feat(video-capture): tasks-client capture_video_screenshots

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: `run_video_capture` runner

**Files:**
- Modify: `webhook-handler/handlers/commands.py` (after `run_video_add` ~line 2378)
- Test: `webhook-handler/tests/test_video_runners.py`

- [ ] **Step 1: Write the failing test**

Append to `webhook-handler/tests/test_video_runners.py` (uses that file's existing `_router`/`_ctx` helpers — match their names; if they differ, mirror the `run_video_set_details` test in the same file):

```python
@pytest.mark.asyncio
async def test_run_video_capture_captures_and_reports(monkeypatch):
    router, tc = _router()  # real CommandRouter + mock tasks client (as in this file)
    tc.get_current_video_draft = AsyncMock(return_value={"id": "job9"})
    tc.capture_video_screenshots = AsyncMock(return_value={"count": 4})
    router._resolve_email_for_ctx = AsyncMock(return_value="u@x.com")
    seen = {}
    ctx = _ctx(respond=_capture_into(seen, "msg"),
               respond_components=_capture_into(seen, "msg", also="components"))
    await router.run_video_capture(ctx, "https://mysite.com")
    tc.capture_video_screenshots.assert_awaited_once_with("u@x.com", "job9", "https://mysite.com")
    assert "4/12" in seen["msg"]


@pytest.mark.asyncio
async def test_run_video_capture_no_draft(monkeypatch):
    router, tc = _router()
    tc.get_current_video_draft = AsyncMock(return_value=None)
    router._resolve_email_for_ctx = AsyncMock(return_value="u@x.com")
    seen = {}
    ctx = _ctx(respond=_capture_into(seen, "msg"))
    await router.run_video_capture(ctx, "https://mysite.com")
    tc.capture_video_screenshots.assert_not_called()
    assert "New video" in seen["msg"]
```

> If `test_video_runners.py` does not expose `_router`/`_ctx`/`_capture_into`, write the two tests using whatever harness that file already uses for `run_video_set_details` / `run_video_add` — the assertions (capture called with email+draft id+url; "no draft" message) are what matter.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webhook-handler && python -m pytest tests/test_video_runners.py -k capture -q`
Expected: FAIL — `AttributeError: ... has no attribute 'run_video_capture'`.

- [ ] **Step 3: Write minimal implementation**

In `handlers/commands.py`, after `run_video_add` (~line 2378):

```python
    async def run_video_capture(self, ctx: CommandContext, url: str) -> None:
        """Paste-a-URL / Capture-from-website: drive server-side headless-browser
        capture of `url` onto the caller's current draft, then reply with the
        running count + a Generate button. Mirrors run_video_add."""
        email = await self._resolve_email_for_ctx(ctx)
        if not email:
            await self._respond_not_linked(ctx)
            return
        try:
            draft = await self._tasks_client.get_current_video_draft(email)
        except TasksAPIError as e:
            await ctx.respond(f"Couldn't load your draft: {e.message}")
            return
        if not draft:
            await ctx.respond("No video in progress — click **New video** first.")
            return
        from urllib.parse import urlparse
        host = urlparse(url).hostname or "your site"
        await ctx.respond(f"Capturing {host}… this takes a few seconds.")
        try:
            res = await self._tasks_client.capture_video_screenshots(email, draft["id"], url)
        except TasksAPIError as e:
            await ctx.respond(
                f"Couldn't capture that site: {e.message}. "
                "You can drag screenshots into this thread instead.")
            return
        count = res.get("count", 0)
        msg = (f"Added screenshots from {host} — {count}/12 so far. "
               "Click **Generate video** when ready.")
        if ctx.respond_components is not None:
            from handlers.video_panel import build_generate_row
            await ctx.respond_components(msg, build_generate_row(draft["id"]))
        else:
            await ctx.respond(msg)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd webhook-handler && python -m pytest tests/test_video_runners.py -k capture -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/handlers/commands.py webhook-handler/tests/test_video_runners.py
git commit -m "feat(video-capture): run_video_capture runner

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Capture modal + button in `video_panel.py`

**Files:**
- Modify: `webhook-handler/handlers/video_panel.py`
- Test: `webhook-handler/tests/test_video_panel.py` (or the file holding the existing `build_studio_components` test — find it in Step 1)

- [ ] **Step 1: Find the studio-components row-count test and write failing tests**

Run: `cd webhook-handler && grep -rln "build_studio_components" tests/`
Locate the assertion `len(rows) == 3`. Update it to `== 4` and add a capture-button assertion. Add tests:

```python
def test_studio_components_has_capture_button():
    from handlers import video_panel as vp
    rows = vp.build_studio_components("job1", [])
    assert len(rows) == 4
    ids = [c.get("custom_id") for row in rows for c in row["components"]]
    assert "aiuivid:capture:job1" in ids


def test_capture_modal_has_url_input():
    from handlers import video_panel as vp
    modal = vp.build_capture_modal("job1")
    assert modal["custom_id"] == "aiuivid:capturemodal:job1"
    inp = modal["components"][0]["components"][0]
    assert inp["custom_id"] == "url"
    assert inp["required"] is True


def test_capture_predicates_and_extractors():
    from handlers import video_panel as vp
    assert vp.is_vid_capture("aiuivid:capture:abc")
    assert vp.is_vid_capture_modal("aiuivid:capturemodal:abc")
    assert vp.job_from_capture("aiuivid:capture:abc") == "abc"
    assert vp.job_from_capture_modal("aiuivid:capturemodal:abc") == "abc"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webhook-handler && python -m pytest tests/test_video_panel.py -q`
Expected: FAIL — `AttributeError: ... has no attribute 'build_capture_modal'` (and the updated row-count assertion fails until impl).

- [ ] **Step 3: Write minimal implementation**

In `video_panel.py`, add ids near the namespace block (after line 16):

```python
CAPTURE_PREFIX = "aiuivid:capture:"
CAPTURE_MODAL_PREFIX = "aiuivid:capturemodal:"
URL_INPUT = "url"
```

Add the modal builder (after `build_details_modal`, ~line 86):

```python
def build_capture_modal(job_id: str) -> dict:
    return {
        "title": "Capture from website"[:45],
        "custom_id": f"{CAPTURE_MODAL_PREFIX}{job_id}",
        "components": [
            {"type": ACTION_ROW, "components": [{
                "type": TEXT_INPUT, "custom_id": URL_INPUT,
                "label": "Your site URL", "style": TEXT_SHORT, "required": True,
                "max_length": 500, "placeholder": "https://yoursite.com",
            }]},
        ],
    }
```

Replace `build_studio_components` (lines 128-135) with a 4-row layout:

```python
def build_studio_components(job_id: str, voices: list[dict]) -> list[dict]:
    return [
        {"type": ACTION_ROW, "components": [build_style_select(job_id)]},
        {"type": ACTION_ROW, "components": [build_voice_select(job_id, voices)]},
        {"type": ACTION_ROW, "components": [
            _button("Capture from website", f"{CAPTURE_PREFIX}{job_id}", STYLE_PRIMARY)]},
        {"type": ACTION_ROW, "components": [
            _button("Add title & description", f"{DETAILS_PREFIX}{job_id}", STYLE_SECONDARY),
            _button("Generate video", f"{GENERATE_PREFIX}{job_id}", STYLE_SUCCESS)]},
    ]
```

Add predicates (after `is_vid_details_modal`, ~line 170) and extractors (after `job_from_details_modal`, ~line 183):

```python
def is_vid_capture(c: str) -> bool: return c.startswith(CAPTURE_PREFIX)
def is_vid_capture_modal(c: str) -> bool: return c.startswith(CAPTURE_MODAL_PREFIX)
```
```python
def job_from_capture(c: str) -> str: return _suffix_after(c, CAPTURE_PREFIX)
def job_from_capture_modal(c: str) -> str: return _suffix_after(c, CAPTURE_MODAL_PREFIX)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd webhook-handler && python -m pytest tests/test_video_panel.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/handlers/video_panel.py webhook-handler/tests/test_video_panel.py
git commit -m "feat(video-capture): Capture-from-website button + modal builders

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: URL-paste intake in `video_intake.py`

**Files:**
- Modify: `webhook-handler/handlers/video_intake.py`
- Test: `webhook-handler/tests/test_video_intake.py`

- [ ] **Step 1: Write the failing test**

Append to `webhook-handler/tests/test_video_intake.py` (reuse that file's existing message/channel/author fakes; if it builds them inline, mirror that):

```python
def test_extract_url_message_finds_url_in_thread():
    from handlers.video_intake import extract_url_message
    msg = _make_message(content="check it https://mysite.com/home", attachments=[],
                        parent_id="999", parent_name="video-generation")
    info = extract_url_message(msg)
    assert info["url"] == "https://mysite.com/home"
    assert info["is_thread"] is True
    assert info["parent_channel_id"] == "999"


def test_extract_url_message_none_when_image_present():
    from handlers.video_intake import extract_url_message
    msg = _make_message(content="https://mysite.com", attachments=[_att("a.png")],
                        parent_id="999", parent_name="video-generation")
    assert extract_url_message(msg) is None


def test_extract_url_message_none_when_no_url():
    from handlers.video_intake import extract_url_message
    msg = _make_message(content="just describing the demo", attachments=[],
                        parent_id="999", parent_name="video-generation")
    assert extract_url_message(msg) is None


@pytest.mark.asyncio
async def test_handle_url_paste_in_thread_calls_capture():
    from handlers.video_intake import VideoThreadIntake
    router = MagicMock()
    router.run_video_capture = AsyncMock()
    intake = VideoThreadIntake(router, MagicMock(), video_channel_name="video-generation")
    await intake.handle_url_paste(
        author_id="1", author_name="al", channel_id="t1", channel_name="thread",
        is_thread=True, parent_channel_id="p", parent_channel_name="video-generation",
        url="https://mysite.com")
    router.run_video_capture.assert_awaited_once()
    assert router.run_video_capture.await_args.args[1] == "https://mysite.com"


@pytest.mark.asyncio
async def test_handle_url_paste_ignored_outside_thread():
    from handlers.video_intake import VideoThreadIntake
    router = MagicMock()
    router.run_video_capture = AsyncMock()
    intake = VideoThreadIntake(router, MagicMock(), video_channel_name="video-generation")
    await intake.handle_url_paste(
        author_id="1", author_name="al", channel_id="c", channel_name="video-generation",
        is_thread=False, parent_channel_id=None, parent_channel_name=None,
        url="https://mysite.com")
    router.run_video_capture.assert_not_called()
```

> If `_make_message` / `_att` don't exist in the file, define them at the top of the test module to build simple namespace objects matching `extract_image_drop`'s attribute reads (`message.attachments[*].url/content_type/filename`, `message.content`, `message.channel.id/name/parent_id/parent`, `message.author.id/name/display_name`).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webhook-handler && python -m pytest tests/test_video_intake.py -k url -q`
Expected: FAIL — `ImportError: cannot import name 'extract_url_message'`.

- [ ] **Step 3: Write minimal implementation**

In `video_intake.py`, add at module level (after the imports, ~line 14):

```python
import re

_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
```

Add the extractor (after `extract_image_drop`, ~line 56):

```python
def extract_url_message(message) -> dict | None:
    """Plain primitives from a discord.py message whose text carries an http(s)
    URL and that has NO image attachment (attachment-bearing messages are handled
    by extract_image_drop). Returns the first URL found, or None. A channel with
    a parent_id is a thread."""
    if getattr(message, "attachments", None):
        return None
    content = getattr(message, "content", "") or ""
    m = _URL_RE.search(content)
    if not m:
        return None
    channel = message.channel
    parent_id = getattr(channel, "parent_id", None)
    parent = getattr(channel, "parent", None)
    author = message.author
    return {
        "author_id": str(author.id),
        "author_name": getattr(author, "display_name", None) or getattr(author, "name", "unknown"),
        "channel_id": str(channel.id),
        "channel_name": getattr(channel, "name", None),
        "is_thread": parent_id is not None,
        "parent_channel_id": str(parent_id) if parent_id else None,
        "parent_channel_name": getattr(parent, "name", None) if parent is not None else None,
        "url": m.group(0),
    }
```

Add the handler method to `VideoThreadIntake` (after `handle_image_drop`, ~line 86):

```python
    async def handle_url_paste(self, *, author_id, author_name, channel_id,
                              channel_name, is_thread, parent_channel_id,
                              parent_channel_name, url) -> None:
        """A URL pasted in a video thread → capture that site onto the draft. A
        URL anywhere else is ignored (the image nudge already directs users)."""
        if is_thread and self._is_video_channel(parent_channel_id, parent_channel_name):
            ctx = self._thread_ctx(author_id, author_name, channel_id)
            await self._router.run_video_capture(ctx, url)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd webhook-handler && python -m pytest tests/test_video_intake.py -q`
Expected: PASS (new + existing intake tests).

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/handlers/video_intake.py webhook-handler/tests/test_video_intake.py
git commit -m "feat(video-capture): paste-URL intake in video thread

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Wire button + modal in `discord_commands.py`

**Files:**
- Modify: `webhook-handler/handlers/discord_commands.py` (component dispatch ~line 407; modal dispatch ~line 1188; new handler near `_handle_video_details_modal` ~line 1043; studio copy ~line 1002)
- Test: `webhook-handler/tests/test_video_routing.py`

- [ ] **Step 1: Write the failing test**

Append to `webhook-handler/tests/test_video_routing.py` (mirror the existing details-modal routing test in that file — it builds the handler with `DiscordCommandHandler.__new__` and a `MagicMock` router; match its helper names):

```python
@pytest.mark.asyncio
async def test_capture_button_returns_modal():
    h = _handler()  # as the details test builds it
    resp = await h._handle_message_component({
        "data": {"custom_id": "aiuivid:capture:job1"},
        "member": {"user": {"id": "1", "username": "al"}},
        "channel_id": "c", "token": "t",
    })
    assert resp["type"] == 9  # MODAL
    assert resp["data"]["custom_id"] == "aiuivid:capturemodal:job1"


@pytest.mark.asyncio
async def test_capture_modal_submit_spawns_runner():
    h = _handler()
    h.router.run_video_capture = AsyncMock()
    resp = await h._handle_modal_submit({
        "data": {"custom_id": "aiuivid:capturemodal:job1",
                 "components": [{"components": [{"custom_id": "url", "value": "https://s.com"}]}]},
        "member": {"user": {"id": "1", "username": "al"}},
        "channel_id": "c", "token": "t",
    })
    assert resp["type"] in (5, 6)  # deferred ack
    await asyncio.sleep(0)  # let the spawned task run
    h.router.run_video_capture.assert_awaited_once()
    assert h.router.run_video_capture.await_args.args[1] == "https://s.com"
```

> Match the exact dispatch method names this file already calls for the details modal/button (e.g. `_handle_message_component` / `_handle_modal_submit`). If the test file uses different entry points, use those.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webhook-handler && python -m pytest tests/test_video_routing.py -k capture -q`
Expected: FAIL — capture button returns the unknown-component fallback, not a modal.

- [ ] **Step 3: Write minimal implementation**

Component dispatch — after the `is_vid_details` block (after line 407):

```python
        if vid.is_vid_capture(custom_id):
            try:
                job_id = vid.job_from_capture(custom_id)
            except ValueError:
                return {"type": DEFERRED_UPDATE_MESSAGE}
            return {"type": MODAL, "data": vid.build_capture_modal(job_id)}
```

Modal dispatch — after the `is_vid_details_modal` block (after line 1188):

```python
        if vid.is_vid_capture_modal(custom_id):
            return await self._handle_video_capture_modal(payload)
```

New handler — after `_handle_video_details_modal` (after line 1043):

```python
    async def _handle_video_capture_modal(self, payload: dict[str, Any]) -> dict[str, Any]:
        """'Capture from website' modal submit → drive server-side capture of the
        submitted URL onto the current draft. ACK ephemeral-deferred within 3s;
        the runner edits the original with progress/result."""
        data = payload.get("data", {})
        custom_id = data.get("custom_id", "")
        try:
            vid.job_from_capture_modal(custom_id)
        except ValueError:
            return {"type": DEFERRED_CHANNEL_MESSAGE, "data": {"flags": 64}}
        url = (self._extract_modal_value(data, vid.URL_INPUT) or "").strip()
        interaction_token = payload.get("token", "")
        member = payload.get("member", {})
        user = member.get("user", payload.get("user", {}))

        async def respond(msg: str) -> None:
            await self.discord.edit_original(interaction_token=interaction_token, content=msg)

        ctx = CommandContext(
            user_id=user.get("id", ""), user_name=user.get("username", "unknown"),
            channel_id=payload.get("channel_id", ""), raw_text="video capture",
            subcommand="video", arguments="", platform="discord", respond=respond)
        self._spawn(self.router.run_video_capture(ctx, url))
        return {"type": DEFERRED_CHANNEL_MESSAGE, "data": {"flags": 64}}
```

Studio copy — update the no-screenshots message (lines 1002-1004) to surface the URL path:

```python
                    "Paste your site's URL here to grab screenshots automatically — "
                    "or drag your own screenshots into this thread (up to 12). Then "
                    "click **Add title & description**, pick a style + voice, and hit "
                    "**Generate video**."
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd webhook-handler && python -m pytest tests/test_video_routing.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/handlers/discord_commands.py webhook-handler/tests/test_video_routing.py
git commit -m "feat(video-capture): wire Capture button + modal -> run_video_capture

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: Gateway URL branch in `voice_bot.py`

**Files:**
- Modify: `webhook-handler/voice_bot.py` (the `on_message` handler — find the existing image-drop branch)

- [ ] **Step 1: Read the on_message handler**

Run: `cd webhook-handler && grep -n "extract_image_drop\|async def on_message\|_video_intake\|author.bot\|message.author" voice_bot.py`
Confirm the bot skips its own messages (e.g. `if message.author.bot: return` or `author == self.user`). The new branch must sit alongside the image branch and after the self-message guard.

- [ ] **Step 2: Add the URL branch**

After the existing image-drop `if self._video_intake is not None and getattr(message, "attachments", None):` block, add a sibling `elif` (no attachments, has text):

```python
            elif self._video_intake is not None and getattr(message, "content", None):
                from handlers.video_intake import extract_url_message
                info = extract_url_message(message)
                if info:
                    try:
                        await self._video_intake.handle_url_paste(**info)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("video url intake failed: %s", exc)
```

(Indent to match the image branch. If the image branch is a standalone `if` rather than the last clause, convert the pair so the URL branch only runs when there are no attachments — `extract_url_message` already returns None when attachments exist, so an independent `if` is also safe.)

- [ ] **Step 3: Verify nothing else broke**

Run: `cd webhook-handler && python -m pytest tests/ -q -k "voice or intake"`
Expected: PASS (the intake unit tests from Task 8 cover the behavior; voice_bot glue mirrors the already-tested image branch).

- [ ] **Step 4: Commit**

```bash
git add webhook-handler/voice_bot.py
git commit -m "feat(video-capture): gateway on_message routes pasted URLs to capture

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: Full verification + real browser run

**Files:** none (verification only)

- [ ] **Step 1: Run the full bot suite**

Run: `cd webhook-handler && python -m pytest -q`
Expected: all PASS (was 928 green; this adds capture tests).

- [ ] **Step 2: Run the full tasks suite (offline; DB + real-browser tests SKIP)**

Run: `cd mcp-servers/tasks && python -m pytest -q`
Expected: PASS; DB-gated and `test_capture_site_real_example` SKIP.

- [ ] **Step 3: Real headless-browser capture (run once, locally)**

Run:
```bash
cd mcp-servers/tasks
pip install playwright
python -m playwright install chromium
python -m pytest tests/test_video_capture.py::test_capture_site_real_example -q
```
Expected: PASS — confirms `capture_site` actually drives Chromium and returns a valid PNG. If `pip install` is undesirable in the repo venv, run it in a throwaway venv; the goal is a real green capture once.

- [ ] **Step 4: Self-review against the spec**

Re-read `docs/superpowers/specs/2026-06-23-video-url-auto-capture-design.md` and confirm every section maps to a task: capture engine (T1-2), endpoint + store helper + TOCTOU (T3-4), client (T5), runner (T6), panel (T7), paste intake (T8), button/modal wiring (T9), gateway (T10). Note any gap.

- [ ] **Step 5: Adversarial code review**

Use superpowers:requesting-code-review on the diff (lenses: SSRF/security, memory/concurrency, Discord-3s-ACK timing, test coverage). Triage findings before deploy.

---

## Deploy (separate, gated on explicit user approval — NOT part of this plan's auto-run)

1. CRLF-normalized drift check: confirm server files match git before overwriting.
2. tasks: `scp` `video_capture.py`, `routes_video.py`, `requirements.txt`, `Dockerfile` → `docker compose -f docker-compose.unified.yml up -d --build tasks` (build downloads Chromium). Smoke `curl -fsS https://ai-ui.coolestdomain.win/tasks/healthz`. In-container capture e2e: create draft → capture a real site → verify screenshots in PG/disk → Generate → MP4.
3. webhook-handler: `scp` `clients/tasks.py`, `handlers/{commands,video_panel,video_intake,discord_commands}.py`, `voice_bot.py` → rebuild. Verify `Up` + gateway reconnect. No `/video` re-register needed (capture is button/modal/paste, not a slash option).
4. Never touch other `.env` values. `VIDEO_CAPTURE_ENABLED` defaults true; no env change required (set `false` only to disable).
5. Push the branch to reconcile git ↔ prod.
6. Update memory `project_discord_video_channel.md`.

---

## Self-Review (filled by author)

- **Spec coverage:** every spec section maps to a task (see T11 Step 4). ✓
- **Placeholders:** none — all steps carry concrete code/commands. The two "if the harness differs" notes (T6/T8/T9) point at existing sibling tests, not unwritten code. ✓
- **Type/name consistency:** `capture_site`, `assert_capturable`, `capture_enabled`, `CaptureError`, `is_blocked_ip`, `_store_screenshot_blobs`, `_job_lock`, `capture_video_screenshots`, `run_video_capture`, `extract_url_message`, `handle_url_paste`, `build_capture_modal`, `CAPTURE_PREFIX`/`CAPTURE_MODAL_PREFIX`/`URL_INPUT`, `is_vid_capture`/`is_vid_capture_modal`, `job_from_capture`/`job_from_capture_modal`, `_handle_video_capture_modal` — used identically across tasks. ✓
