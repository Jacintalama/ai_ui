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
        except CaptureError:
            raise
        except Exception as e:  # noqa: BLE001 - launch/engine failure -> clean error
            raise CaptureError(f"capture failed: {e}") from e
    if not frames:
        raise CaptureError("no frames captured")
    return frames
