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
