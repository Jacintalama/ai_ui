"""SSRF guard, including redirect-hop revalidation.

assert_safe_url() validated only the submitted URL; the scraper fetched with
follow_redirects=True, so a public URL that 30x-redirects to an internal
target (169.254.169.254 metadata, tasks:8210, n8n:5678, ...) bypassed the
guard. safe_get() follows redirects MANUALLY and re-validates every hop.
(audit 2026-06-15.) Literal IPs keep these tests network-free.
"""
import asyncio
import os
import sys

import httpx
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import url_guard  # noqa: E402

PUBLIC = "93.184.216.34"      # example.com's IP — resolves to itself, public
INTERNAL = "169.254.169.254"  # link-local metadata endpoint — must be blocked


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_safe_get_blocks_redirect_to_internal():
    def handler(request):
        if request.url.host == PUBLIC:
            return httpx.Response(
                302, headers={"location": f"http://{INTERNAL}/latest/meta-data/"})
        raise AssertionError("must never connect to the internal redirect target")

    async def run():
        async with _client(handler) as client:
            await url_guard.safe_get(client, f"http://{PUBLIC}/")

    with pytest.raises(url_guard.UnsafeURLError):
        asyncio.run(run())


def test_safe_get_returns_direct_response():
    def handler(request):
        return httpx.Response(200, text="hello")

    async def run():
        async with _client(handler) as client:
            return await url_guard.safe_get(client, f"http://{PUBLIC}/")

    resp = asyncio.run(run())
    assert resp.status_code == 200 and resp.text == "hello"


def test_safe_get_follows_public_redirect():
    def handler(request):
        if request.url.path == "/start":
            return httpx.Response(301, headers={"location": f"http://{PUBLIC}/end"})
        return httpx.Response(200, text="final")

    async def run():
        async with _client(handler) as client:
            return await url_guard.safe_get(client, f"http://{PUBLIC}/start")

    resp = asyncio.run(run())
    assert resp.status_code == 200 and resp.text == "final"


def test_safe_get_caps_redirect_chains():
    def handler(request):
        # Endless public redirect loop — must stop, not spin forever.
        return httpx.Response(302, headers={"location": f"http://{PUBLIC}/next"})

    async def run():
        async with _client(handler) as client:
            await url_guard.safe_get(client, f"http://{PUBLIC}/", max_redirects=3)

    with pytest.raises(url_guard.UnsafeURLError):
        asyncio.run(run())
