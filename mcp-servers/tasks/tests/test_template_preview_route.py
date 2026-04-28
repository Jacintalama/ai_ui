"""Smoke test for the /api/template-preview static mount.

Confirms the mount serves index.html, nested CSS/JS files, and returns 404
for non-existent paths. The mount is what the gallery iframes load, so a
regression here breaks the entire preview flow.
"""
import httpx
import pytest
from httpx import ASGITransport

from main import app


@pytest.mark.asyncio
async def test_index_html_serves_for_known_template():
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/template-preview/landing/index.html")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    assert "<html" in r.text.lower()


@pytest.mark.asyncio
async def test_directory_index_redirect_serves_index_html():
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/template-preview/landing/")
    assert r.status_code == 200
    assert "<html" in r.text.lower()


@pytest.mark.asyncio
async def test_nested_asset_serves():
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/template-preview/landing/styles/main.css")
    assert r.status_code == 200
    assert "text/css" in r.headers.get("content-type", "")


@pytest.mark.asyncio
async def test_unknown_template_returns_404():
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/template-preview/no-such-template/index.html")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_path_traversal_does_not_expose_app_files():
    """StaticFiles' default behavior is to reject `..` segments. Verify it
    doesn't accidentally serve the FastAPI source tree."""
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/template-preview/../main.py")
    assert r.status_code != 200
