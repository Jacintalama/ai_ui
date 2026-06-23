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
