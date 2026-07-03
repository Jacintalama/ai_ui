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
from urllib.parse import urlparse


def _registrable_host(host: str) -> str:
    """Lowercased host with a leading 'www.' stripped, for same-site comparison."""
    host = (host or "").lower()
    return host[4:] if host.startswith("www.") else host


def same_origin(base_url: str, href: str) -> bool:
    """True when href is an http(s) link on the same host as base_url."""
    try:
        b = urlparse(base_url)
        h = urlparse(href)
    except ValueError:
        return False
    if h.scheme not in ("http", "https"):
        return False
    return bool(h.netloc) and _registrable_host(h.hostname or "") == _registrable_host(b.hostname or "")


COLLECT_ANCHORS_JS = """() => {
  const out = [];
  document.querySelectorAll('a[href]').forEach((a) => {
    const r = a.getBoundingClientRect();
    if (r.width < 10 || r.height < 10) return;
    out.push({
      href: a.href || "",
      x: r.x + r.width / 2,
      y: r.y + r.height / 2,
      w: r.width,
      h: r.height,
      text: (a.innerText || "").trim().slice(0, 48),
    });
  });
  return out;
}"""

# Hrefs whose path/text suggest a state-changing or dead-end action. Never walk into these.
_WALK_DENY = ("logout", "signout", "sign-out", "log-out", "delete", "remove", "/wp-admin")

# Visible band for a walk target: keep the eventual cursor inside the rendered frame.
_WALK_Y_MIN = 0.03
_WALK_Y_MAX = 0.72


def normalize_url(url: str) -> str:
    """URL without fragment or trailing slash, host lowercased (for dedupe)."""
    p = urlparse(url)
    host = (p.hostname or "").lower()
    netloc = host + (f":{p.port}" if p.port else "")
    path = p.path.rstrip("/")
    base = f"{p.scheme}://{netloc}{path}"
    return base + (f"?{p.query}" if p.query else "")


def pick_walk_target(
    candidates: list[dict],
    base_url: str,
    visited: set[str],
    *,
    vw: int = 1280,
    vh: int = 800,
) -> dict | None:
    """Largest visible same-origin, unvisited, non-denied link in the top 72%."""
    best = None
    best_area = 0.0
    for c in candidates:
        href = c.get("href") or ""
        if not same_origin(base_url, href):
            continue
        if normalize_url(href) in visited:
            continue
        low = href.lower()
        if any(word in low for word in _WALK_DENY):
            continue
        yf = c["y"] / vh
        xf = c["x"] / vw
        if not (_WALK_Y_MIN <= yf <= _WALK_Y_MAX and 0.0 <= xf <= 1.0):
            continue
        area = float(c.get("w", 0)) * float(c.get("h", 0))
        if area > best_area:
            best_area = area
            best = {"href": href, "x": round(xf, 3), "y": round(yf, 3),
                    "label": (c.get("text") or "").strip()}
    return best


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


def _extra_blocked_hosts() -> set[str]:
    """Operator-configured extra host blocklist (e.g. the box's own public IP/
    hostname), comma-separated in VIDEO_CAPTURE_BLOCKED_HOSTS. Empty by default."""
    return {h.strip().lower() for h in
            os.environ.get("VIDEO_CAPTURE_BLOCKED_HOSTS", "").split(",") if h.strip()}


async def _host_blocked(host: str, cache: dict[str, bool] | None = None) -> bool:
    """True if this host must not be fetched: empty/localhost, in the operator
    blocklist, an IP literal in a blocked range, or a name that resolves to any
    blocked address. Resolution is async (never blocks the event loop) and
    fails closed. `cache` memoizes per-capture so a page's many subresource
    requests to the same host resolve once."""
    low = (host or "").strip().lower()
    if not low or low == "localhost" or low.endswith(".localhost"):
        return True
    if low in _extra_blocked_hosts():
        return True
    if cache is not None and low in cache:
        return cache[low]
    try:
        ipaddress.ip_address(low)
        blocked = is_blocked_ip(low)
    except ValueError:
        try:
            loop = asyncio.get_running_loop()
            infos = await loop.getaddrinfo(host, None)
            blocked = any(is_blocked_ip(i[4][0]) for i in infos)
        except Exception:  # noqa: BLE001 - resolution failure -> fail closed
            blocked = True
    if cache is not None:
        cache[low] = blocked
    return blocked


async def assert_capturable(url: str) -> str:
    """Return the URL if it is safe to capture, else raise CaptureError. Scheme
    must be http/https and the host must not be blocked (localhost, blocklist,
    or resolving to a private/loopback/link-local/reserved address)."""
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        raise CaptureError("only http/https URLs can be captured")
    host = (p.hostname or "").strip()
    if not host or await _host_blocked(host):
        raise CaptureError("that host can't be captured")
    return url


async def extract_site_context(page) -> dict:
    """Best-effort page title + first headings + meta description. Never raises;
    a failure on any field yields an empty value so capture never fails over it."""
    try:
        title = await page.title()
    except Exception:  # noqa: BLE001
        title = ""
    try:
        headings = await page.evaluate(
            "Array.from(document.querySelectorAll('h1,h2,h3')).slice(0,8)"
            ".map(e => (e.innerText || '').trim()).filter(Boolean)"
        )
    except Exception:  # noqa: BLE001
        headings = []
    try:
        meta = await page.evaluate(
            "(document.querySelector('meta[name=\"description\"]') || {}).content || ''"
        )
    except Exception:  # noqa: BLE001
        meta = ""
    return {
        "title": (title or "")[:200],
        "headings": [(h or "")[:120] for h in (headings or [])][:8],
        "meta_description": (meta or "")[:400],
    }


async def capture_site(
    url: str,
    *,
    max_frames: int = 5,
    viewport: tuple[int, int] = (1280, 800),
    nav_timeout_ms: int = 20000,
) -> tuple[list[bytes], dict]:
    """Capture a live site as up to `max_frames` viewport-height PNG frames by
    scrolling top-to-bottom. Also extracts best-effort page context (title,
    headings, meta description). Serialized to one browser at a time. Raises
    CaptureError on a blocked URL, missing engine, timeout, or zero frames.
    Returns a (frames, site_context) tuple."""
    await assert_capturable(url)
    try:
        from playwright.async_api import async_playwright
    except ImportError as e:
        raise CaptureError("capture engine unavailable") from e

    vw, vh = viewport
    frames: list[bytes] = []
    site_context: dict = {}
    resolve_cache: dict[str, bool] = {}
    async with _CAPTURE_LOCK:
        try:
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
                        # Abort any request (main frame, subresource, iframe,
                        # redirect hop) whose host is internal — resolving names,
                        # not just IP literals, so a page cannot pull internal
                        # Docker services (n8n, api-gateway, ...) into the render.
                        host = urlparse(route.request.url).hostname or ""
                        try:
                            if await _host_blocked(host, resolve_cache):
                                await route.abort()
                            else:
                                await route.continue_()
                        except Exception:  # noqa: BLE001 - never wedge the route
                            await route.abort()

                    await page.route("**/*", _route)
                    try:
                        await page.goto(url, wait_until="load", timeout=nav_timeout_ms)
                    except Exception as e:  # noqa: BLE001 - playwright TimeoutError etc.
                        raise CaptureError(f"could not load the page: {e}") from e
                    # A redirect may have landed somewhere internal — re-check.
                    await assert_capturable(page.url)
                    height = int(await page.evaluate("document.body.scrollHeight") or vh)
                    n = max(1, min(max_frames, math.ceil(height / vh)))
                    for i in range(n):
                        await page.evaluate(f"window.scrollTo(0, {i * vh})")
                        await page.wait_for_timeout(400)
                        # No clip: a default screenshot captures the *current
                        # viewport* at this scroll position. A clip would be
                        # document-relative (captureBeyondViewport), which can
                        # re-capture the top regardless of scroll on some engine
                        # versions — the viewport screenshot is version-robust.
                        frames.append(await page.screenshot())
                    site_context = await extract_site_context(page)
                finally:
                    await browser.close()
        except CaptureError:
            raise
        except Exception as e:  # noqa: BLE001 - launch/engine failure -> clean error
            raise CaptureError(f"capture failed: {e}") from e
    if not frames:
        raise CaptureError("no frames captured")
    return frames, site_context


async def _walk_with_page(
    page, start_url: str, *, max_pages: int, guard, vw: int, vh: int, settle_ms: int
) -> tuple[list[bytes], list[dict], dict]:
    """Browser-agnostic walk: goto -> screenshot(top) -> pick next same-origin
    link -> record its click coord -> goto it. Stops on no target, revisit, or
    max_pages. Returns (frames, walk, site_context)."""
    frames: list[bytes] = []
    walk: list[dict] = []
    visited: set[str] = set()
    site_context: dict = {}
    cur = start_url
    for i in range(max_pages):
        await guard(cur)
        await page.goto(cur, wait_until="domcontentloaded", timeout=None)
        if settle_ms:
            await page.wait_for_timeout(settle_ms)
        await page.evaluate("window.scrollTo(0, 0)")
        frames.append(await page.screenshot())
        real_url = page.url or cur
        # A redirect may have landed somewhere internal, so re-check (mirrors
        # capture_site's post-goto assert_capturable(page.url)).
        await guard(real_url)
        visited.add(normalize_url(real_url))
        if i == 0:
            site_context = await extract_site_context(page)
        candidates = await page.evaluate(COLLECT_ANCHORS_JS)
        target = pick_walk_target(candidates or [], real_url, visited, vw=vw, vh=vh)
        walk.append({
            "url": real_url,
            "title": await page.title(),
            "click": (None if not target
                      else {"x": target["x"], "y": target["y"], "label": target["label"]}),
        })
        if not target:
            break
        cur = target["href"]
    if walk:
        walk[-1]["click"] = None  # the last shown page has no next page in the video
    return frames, walk, site_context


async def capture_walk(
    url: str,
    *,
    max_pages: int = 4,
    viewport: tuple[int, int] = (1280, 800),
    nav_timeout_ms: int = 30000,
) -> tuple[list[bytes], list[dict], dict]:
    """Navigate up to max_pages same-origin pages, screenshotting each and
    recording the click that leads to the next. Falls back to a single page when
    the site has no followable link."""
    await assert_capturable(url)
    try:
        from playwright.async_api import async_playwright
    except ImportError as e:
        raise CaptureError("capture engine unavailable") from e

    vw, vh = viewport
    resolve_cache: dict[str, bool] = {}
    async with _CAPTURE_LOCK:
        try:
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
                    page.set_default_navigation_timeout(nav_timeout_ms)

                    async def _route(route):
                        # Same SSRF guard as capture_site: abort any request whose
                        # host is internal, so a followed link can't pull an
                        # internal Docker service into the walk.
                        host = urlparse(route.request.url).hostname or ""
                        try:
                            if await _host_blocked(host, resolve_cache):
                                await route.abort()
                            else:
                                await route.continue_()
                        except Exception:  # noqa: BLE001 - never wedge the route
                            await route.abort()

                    await page.route("**/*", _route)
                    frames, walk, ctx = await _walk_with_page(
                        page, url, max_pages=max_pages, guard=assert_capturable,
                        vw=vw, vh=vh, settle_ms=2500)
                finally:
                    await browser.close()
        except CaptureError:
            raise
        except Exception as e:  # noqa: BLE001 - launch/engine failure -> clean error
            raise CaptureError(f"capture failed: {e}") from e
    if not frames:
        raise CaptureError("no frames captured")
    return frames, walk, ctx
