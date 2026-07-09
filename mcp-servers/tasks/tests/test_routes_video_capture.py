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

    async def fake_capture_walk(url, **kw):
        return [_png(), _png(), _png()], [], {"title": "Example"}

    monkeypatch.setattr(routes_video, "capture_walk", fake_capture_walk)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        draft = await c.post("/api/video-jobs/draft",
                             json={"title": "t", "prompt": "", "style": "clean_product_demo",
                                   "voice": "amy"}, headers=HEAD)
        jid = draft.json()["id"]
        r = await c.post(f"/api/video-jobs/{jid}/capture-from-url",
                         json={"url": "https://example.com", "max_frames": 3}, headers=HEAD)
    assert r.status_code == 200
    assert r.json()["count"] == 3


@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_capture_persists_host_in_site_context(db_session, tmp_path, monkeypatch):
    """The persisted site_context.json carries the site host for the address pill."""
    import json
    from pathlib import Path
    monkeypatch.setenv("APPS_DIR", str(tmp_path))

    async def fake_capture_walk(url, **kw):
        return [_png()], [], {"title": "Example"}

    monkeypatch.setattr(routes_video, "capture_walk", fake_capture_walk)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        draft = await c.post("/api/video-jobs/draft",
                             json={"title": "t", "prompt": "", "style": "clean_product_demo",
                                   "voice": "amy"}, headers=HEAD)
        jid = draft.json()["id"]
        slug = draft.json()["slug"]
        r = await c.post(f"/api/video-jobs/{jid}/capture-from-url",
                         json={"url": "https://example.com/x"}, headers=HEAD)
    assert r.status_code == 200
    ctx = json.loads(
        (Path(str(tmp_path)) / slug / ".video" / str(jid) / "site_context.json").read_text())
    assert ctx["host"] == "example.com"


@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_capture_from_url_writes_walk_json(db_session, tmp_path, monkeypatch):
    """capture-from-url walks multiple pages and persists the walk plan next to
    site_context.json so the worker can build a cursor-driven video."""
    import json
    from pathlib import Path
    monkeypatch.setenv("APPS_DIR", str(tmp_path))

    fake_walk = [
        {"url": "https://s.com/", "title": "Home", "click": {"x": 0.1, "y": 0.4, "label": "A"}},
        {"url": "https://s.com/a", "title": "A", "click": None},
    ]

    async def fake_capture_walk(url, **kw):
        return [b"PNG1", b"PNG2"], fake_walk, {"title": "Home"}

    monkeypatch.setattr(routes_video, "capture_walk", fake_capture_walk)

    # The SSRF/DNS guard is covered by its own tests; a real lookup here makes
    # the test hostage to the container's resolver.
    async def _allow(url):
        return url

    monkeypatch.setattr(routes_video, "assert_capturable", _allow)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        draft = await c.post("/api/video-jobs/draft",
                             json={"title": "t", "prompt": "", "style": "clean_product_demo",
                                   "voice": "amy"}, headers=HEAD)
        jid = draft.json()["id"]
        slug = draft.json()["slug"]
        r = await c.post(f"/api/video-jobs/{jid}/capture-from-url",
                         json={"url": "https://example.com/", "max_frames": 4}, headers=HEAD)
    assert r.status_code == 200
    walk_path = Path(str(tmp_path)) / slug / ".video" / str(jid) / "walk.json"
    assert walk_path.exists()
    assert json.loads(walk_path.read_text())[0]["click"]["label"] == "A"


@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_capture_from_url_recapture_clears_stale_screenshots(db_session, tmp_path, monkeypatch):
    """A recapture of the same job must not leave stale screenshot-N.png files
    behind: walk.json is overwritten on every capture, so on-disk screenshots
    must also restart at 1..N, or the worker's positional walk[i] <->
    screenshot-(i+1) pairing silently drifts against frames left over from the
    previous capture."""
    import json
    from pathlib import Path
    monkeypatch.setenv("APPS_DIR", str(tmp_path))

    first_walk = [
        {"url": "https://s.com/", "title": "Home", "click": {"x": 0.1, "y": 0.2, "label": "A"}},
        {"url": "https://s.com/a", "title": "A", "click": {"x": 0.3, "y": 0.4, "label": "B"}},
        {"url": "https://s.com/b", "title": "B", "click": None},
    ]
    second_walk = [
        {"url": "https://s.com/", "title": "Home", "click": {"x": 0.5, "y": 0.6, "label": "C"}},
    ]

    async def fake_first(url, **kw):
        return [b"PNG1", b"PNG2", b"PNG3"], first_walk, {"title": "Home"}

    async def fake_second(url, **kw):
        return [b"PNG-NEW"], second_walk, {"title": "Home"}

    # The SSRF/DNS guard is covered by its own tests; a real lookup here makes
    # the test hostage to the container's resolver.
    async def _allow(url):
        return url

    monkeypatch.setattr(routes_video, "assert_capturable", _allow)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        draft = await c.post("/api/video-jobs/draft",
                             json={"title": "t", "prompt": "", "style": "clean_product_demo",
                                   "voice": "amy"}, headers=HEAD)
        jid = draft.json()["id"]
        slug = draft.json()["slug"]

        monkeypatch.setattr(routes_video, "capture_walk", fake_first)
        r1 = await c.post(f"/api/video-jobs/{jid}/capture-from-url",
                          json={"url": "https://example.com/", "max_frames": 3}, headers=HEAD)
        assert r1.status_code == 200
        assert r1.json()["count"] == 3

        monkeypatch.setattr(routes_video, "capture_walk", fake_second)
        r2 = await c.post(f"/api/video-jobs/{jid}/capture-from-url",
                          json={"url": "https://example.com/", "max_frames": 1}, headers=HEAD)
    assert r2.status_code == 200
    body = r2.json()
    assert body["count"] == 1
    assert body["screenshots"] == ["screenshot-1.png"]

    shots_dir = Path(str(tmp_path)) / slug / ".video" / str(jid) / "screenshots"
    on_disk = sorted(p.name for p in shots_dir.iterdir())
    assert on_disk == ["screenshot-1.png"]

    walk_path = Path(str(tmp_path)) / slug / ".video" / str(jid) / "walk.json"
    walk = json.loads(walk_path.read_text())
    assert len(walk) == len(on_disk) == 1
    assert walk[0]["click"]["label"] == "C"
