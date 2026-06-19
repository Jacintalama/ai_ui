"""Tests for POST /api/video-jobs/{job_id}/screenshots-by-url.

OFFLINE tests (no DB required):
  - rejects a non-allowlisted host (400) — no DB work, no HTTP fetch
  - rejects a non-https URL (400)         — no DB work, no HTTP fetch

Both URL-rejection tests pass any random UUID as job_id; the SSRF guard fires
before _coerce_job_id / any DB call, so no real job is needed.

DB tests (skipif not _HAVE_DB):
  - happy path: 2 allowlisted URLs → 200, count==2, files written to disk
  - count-cap: existing 0 + MAX_FILES+1 urls → 400 before any fetch
  - oversized stream: a body exceeding MAX_FILE_BYTES → 413 mid-stream (OOM guard)
"""
import io
import os
import uuid

import pytest
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("AIUI_FERNET_KEY", Fernet.generate_key().decode())

from main import app  # noqa: E402
from routes_video import MAX_FILES, MAX_FILE_BYTES  # noqa: E402

HEAD = {"X-User-Email": "ralph@aiui.com", "X-User-Admin": "true"}

_DB_URL = os.environ.get("DATABASE_URL", "")
_HAVE_DB = bool(_DB_URL) and "nowhere" not in _DB_URL

# ---- helpers ----------------------------------------------------------------


def _make_png() -> bytes:
    """Build a valid 8x8 RGB PNG with Pillow (fast, no disk I/O)."""
    from PIL import Image

    img = Image.new("RGB", (8, 8), color=(100, 149, 237))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class _FakeStream:
    """Async context manager standing in for httpx.AsyncClient.stream(...).

    Yields the given chunks from aiter_bytes(); `headers` lets a test exercise
    (or skip) the Content-Length fast-reject path."""

    def __init__(self, chunks: list[bytes], headers: dict | None = None) -> None:
        self._chunks = chunks
        self.headers = headers or {}

    async def __aenter__(self) -> "_FakeStream":
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    def raise_for_status(self) -> None:
        pass  # no-op: pretend 200 OK

    async def aiter_bytes(self):
        for chunk in self._chunks:
            yield chunk


# ---- OFFLINE tests (no DB needed) ------------------------------------------


async def test_rejects_non_allowlisted_host_400():
    """An evil host (not Discord CDN) is rejected 400 before any DB work.
    monkeypatch makes AsyncClient.get raise AssertionError to prove no fetch ran."""
    job_id = str(uuid.uuid4())

    async def _no_get(self, url, *a, **k):
        raise AssertionError("HTTP fetch must not happen for a bad-host URL")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        # Monkeypatch at module level so the running AsyncClient is covered.
        import httpx

        original = httpx.AsyncClient.get
        httpx.AsyncClient.get = _no_get
        try:
            r = await c.post(
                f"/api/video-jobs/{job_id}/screenshots-by-url",
                json={"urls": ["https://evil.example.com/screenshot.png"]},
                headers=HEAD,
            )
        finally:
            httpx.AsyncClient.get = original

    assert r.status_code == 400
    assert "host not allowed" in r.json().get("detail", "")


async def test_rejects_non_https_url_400(monkeypatch):
    """A plain http:// URL for a CDN host is rejected 400 (scheme guard).
    monkeypatch ensures no fetch is attempted."""
    job_id = str(uuid.uuid4())

    async def _no_get(self, url, *a, **k):
        raise AssertionError("HTTP fetch must not happen for a non-https URL")

    monkeypatch.setattr("httpx.AsyncClient.get", _no_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            f"/api/video-jobs/{job_id}/screenshots-by-url",
            json={"urls": ["http://cdn.discordapp.com/attachments/123/456/img.png"]},
            headers=HEAD,
        )

    assert r.status_code == 400
    assert "host not allowed" in r.json().get("detail", "")


# ---- DB tests (skipped offline) --------------------------------------------


@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_happy_path_two_urls(db_session, tmp_path, monkeypatch):
    """POST 2 allowlisted Discord CDN URLs → 200 with count==2 and files on disk."""
    monkeypatch.setenv("APPS_DIR", str(tmp_path))
    png = _make_png()

    # Step 1: create a draft to get a real job_id.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/api/video-jobs/draft",
            json={"title": "URL Test", "prompt": "screenshot via url"},
            headers=HEAD,
        )
    assert r.status_code == 201
    job_id = r.json()["id"]

    # Step 2: monkeypatch httpx.AsyncClient.stream to stream our fake PNG.
    def _stream(self, method, url, *a, **k):
        return _FakeStream([png])

    monkeypatch.setattr("httpx.AsyncClient.stream", _stream)

    urls = [
        "https://cdn.discordapp.com/attachments/1/1/img1.png",
        "https://cdn.discordapp.com/attachments/1/1/img2.png",
    ]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            f"/api/video-jobs/{job_id}/screenshots-by-url",
            json={"urls": urls},
            headers=HEAD,
        )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 2
    assert len(body["screenshots"]) == 2


@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_count_cap_rejects_over_max(db_session, tmp_path, monkeypatch):
    """Server-side count cap: existing (1) + new (MAX_FILES) > MAX_FILES → 400.

    We place 1 screenshot on disk manually (simulating a prior upload), then
    send MAX_FILES URLs. Pydantic allows the list (it is within max_length); the
    server-side check `len(existing) + len(body.urls) > MAX_FILES` fires and
    returns 400 before any HTTP fetch.
    """
    monkeypatch.setenv("APPS_DIR", str(tmp_path))

    def _no_stream(self, method, url, *a, **k):
        raise AssertionError("Fetch must not be reached when count cap fires")

    monkeypatch.setattr("httpx.AsyncClient.stream", _no_stream)

    # Create a draft so we have a real job_id + slug.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/api/video-jobs/draft",
            json={"title": "Cap Test", "prompt": "too many"},
            headers=HEAD,
        )
    assert r.status_code == 201
    body = r.json()
    job_id = body["id"]
    slug = body["slug"]

    # Place 1 existing screenshot on disk so existing count = 1.
    shots_dir = tmp_path / slug / ".video" / job_id / "screenshots"
    shots_dir.mkdir(parents=True, exist_ok=True)
    (shots_dir / "screenshot-1.png").write_bytes(_make_png())

    # Send exactly MAX_FILES new URLs (valid list length); 1 + MAX_FILES > MAX_FILES.
    at_cap = [
        f"https://cdn.discordapp.com/attachments/1/1/img{i}.png"
        for i in range(MAX_FILES)
    ]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            f"/api/video-jobs/{job_id}/screenshots-by-url",
            json={"urls": at_cap},
            headers=HEAD,
        )

    assert r.status_code == 400


@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_oversized_stream_rejected_413(db_session, tmp_path, monkeypatch):
    """A streamed body whose running size exceeds MAX_FILE_BYTES is rejected 413
    mid-stream — the full body is never buffered (the OOM guard from MF-1)."""
    monkeypatch.setenv("APPS_DIR", str(tmp_path))

    # Create a draft to get a real job_id.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/api/video-jobs/draft",
            json={"title": "Big", "prompt": "oversized stream"},
            headers=HEAD,
        )
    assert r.status_code == 201
    job_id = r.json()["id"]

    # No Content-Length header → exercise the streaming-accumulation cap.
    # Two chunks of (cap // 2 + 1) bytes exceed MAX_FILE_BYTES after the 2nd chunk.
    half = MAX_FILE_BYTES // 2 + 1
    chunks = [b"\x00" * half, b"\x00" * half]

    def _stream(self, method, url, *a, **k):
        return _FakeStream(chunks)

    monkeypatch.setattr("httpx.AsyncClient.stream", _stream)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            f"/api/video-jobs/{job_id}/screenshots-by-url",
            json={"urls": ["https://cdn.discordapp.com/attachments/1/1/big.png"]},
            headers=HEAD,
        )

    assert r.status_code == 413, r.text
