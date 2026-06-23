"""Tests for the shared screenshot blob-store helper and the capture-from-url
endpoint. Helper tests use a tmp dir (no DB). Endpoint guard tests that fire
before any DB call run offline; the happy/ownership paths need Postgres and are
skipped offline (run at deploy/CI)."""
import io
import os

import pytest
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient
from PIL import Image

os.environ.setdefault("AIUI_FERNET_KEY", Fernet.generate_key().decode())

import routes_video  # noqa: E402
from main import app  # noqa: E402
from routes_video import _store_screenshot_blobs  # noqa: E402

_DB_URL = os.environ.get("DATABASE_URL", "")
_HAVE_DB = bool(_DB_URL) and "nowhere" not in _DB_URL

HEAD = {"X-User-Email": "ralph@aiui.com", "X-User-Admin": "true"}


def _png() -> bytes:
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


# ---- capture-from-url endpoint ---------------------------------------------


async def _post_capture(url_body, headers=HEAD):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        return await c.post(
            "/api/video-jobs/00000000-0000-0000-0000-000000000000/capture-from-url",
            json=url_body, headers=headers)


async def test_capture_endpoint_blocks_ssrf_before_db():
    r = await _post_capture({"url": "http://127.0.0.1/admin"})
    assert r.status_code == 400


async def test_capture_endpoint_rejects_bad_scheme():
    r = await _post_capture({"url": "file:///etc/passwd"})
    assert r.status_code == 400


async def test_capture_endpoint_503_when_capture_disabled(monkeypatch):
    monkeypatch.setenv("VIDEO_CAPTURE_ENABLED", "false")
    r = await _post_capture({"url": "https://example.com"})
    assert r.status_code == 503


async def test_capture_endpoint_requires_auth():
    r = await _post_capture({"url": "https://example.com"}, headers={})
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
