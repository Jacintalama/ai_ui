"""Tests for the per-user video studio Discord thread endpoints:

    GET  /discord-links/{discord_id}/video-thread
    POST /discord-links/{discord_id}/video-thread

These mirror the existing /builder-thread endpoints but persist to the
video_thread_id column. Authed with X-Internal-Secret (INTERNAL_CALLBACK_SECRET).

DB tests (marked skipif not _HAVE_DB) insert DiscordLink rows and require a
real Postgres. They run at deploy/CI where DATABASE_URL points at aiui_test.
Offline tests exercise guards that fire BEFORE any DB call and run anywhere.
"""
from cryptography.fernet import Fernet as _Fernet

_AIUI_TEST_KEY = _Fernet.generate_key().decode()

import os

os.environ.setdefault("AIUI_FERNET_KEY", _AIUI_TEST_KEY)
os.environ.setdefault("INTERNAL_CALLBACK_SECRET", "test-internal-secret")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from main import app
from models import DiscordLink


SECRET = os.environ["INTERNAL_CALLBACK_SECRET"]
INTERNAL_HDR = {"X-Internal-Secret": SECRET}
DISCORD_ID = "video-thread-test-user"

# conftest sets a dummy DATABASE_URL ("postgresql://nobody@nowhere/nobody") via
# setdefault so no-DB modules import cleanly. Treat that sentinel (and an unset
# var) as "no real database here" so the DB tests SKIP offline and only run at
# deploy/CI where DATABASE_URL points at a real Postgres.
_DB_URL = os.environ.get("DATABASE_URL", "")
_HAVE_DB = bool(_DB_URL) and "nowhere" not in _DB_URL


@pytest.fixture
def transport():
    return ASGITransport(app=app)


async def _seed_link(db_session) -> None:
    # discord_links is not in conftest's TRUNCATE set — clean our row explicitly.
    await db_session.execute(
        delete(DiscordLink).where(DiscordLink.discord_id == DISCORD_ID)
    )
    db_session.add(DiscordLink(
        discord_id=DISCORD_ID,
        discord_username="video-tester",
        email="video@aiui.com",
        status="approved",
    ))
    await db_session.commit()


# ---- DB tests (skipped offline) ----


@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_get_video_thread_none_initially(db_session, transport):
    await _seed_link(db_session)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.get(
                f"/discord-links/{DISCORD_ID}/video-thread", headers=INTERNAL_HDR,
            )
        assert r.status_code == 200, r.text
        assert r.json() == {"thread_id": None}
    finally:
        await db_session.execute(
            delete(DiscordLink).where(DiscordLink.discord_id == DISCORD_ID)
        )
        await db_session.commit()


@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_post_then_get_video_thread_roundtrip(db_session, transport):
    await _seed_link(db_session)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            post = await c.post(
                f"/discord-links/{DISCORD_ID}/video-thread",
                headers=INTERNAL_HDR,
                json={"thread_id": "111222333"},
            )
            assert post.status_code == 200, post.text
            assert post.json() == {"status": "ok"}

            get = await c.get(
                f"/discord-links/{DISCORD_ID}/video-thread", headers=INTERNAL_HDR,
            )
        assert get.status_code == 200, get.text
        assert get.json() == {"thread_id": "111222333"}
    finally:
        await db_session.execute(
            delete(DiscordLink).where(DiscordLink.discord_id == DISCORD_ID)
        )
        await db_session.commit()


# ---- Offline tests (no DB required) ----


async def test_video_thread_requires_internal_secret(transport):
    """_require_internal raises 403 before any DB call — runs entirely offline."""
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        get = await c.get(f"/discord-links/{DISCORD_ID}/video-thread")
        post = await c.post(
            f"/discord-links/{DISCORD_ID}/video-thread",
            json={"thread_id": "1"},
        )
    assert get.status_code == 403
    assert post.status_code == 403
