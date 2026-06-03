"""Tests for the per-user App Builder Discord thread endpoints:

    GET  /discord-links/{discord_id}/builder-thread
    POST /discord-links/{discord_id}/builder-thread

These mirror the existing /thread (schedules) endpoints but persist to the
builder_thread_id column. Authed with X-Internal-Secret (INTERNAL_CALLBACK_SECRET).
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
DISCORD_ID = "builder-thread-test-user"


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
        discord_username="builder-tester",
        email="builder@aiui.com",
        status="approved",
    ))
    await db_session.commit()


async def test_get_builder_thread_none_initially(db_session, transport):
    await _seed_link(db_session)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.get(
                f"/discord-links/{DISCORD_ID}/builder-thread", headers=INTERNAL_HDR,
            )
        assert r.status_code == 200, r.text
        assert r.json() == {"thread_id": None}
    finally:
        await db_session.execute(
            delete(DiscordLink).where(DiscordLink.discord_id == DISCORD_ID)
        )
        await db_session.commit()


async def test_post_then_get_builder_thread_roundtrip(db_session, transport):
    await _seed_link(db_session)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            post = await c.post(
                f"/discord-links/{DISCORD_ID}/builder-thread",
                headers=INTERNAL_HDR,
                json={"thread_id": "999888777"},
            )
            assert post.status_code == 200, post.text
            assert post.json() == {"status": "ok"}

            get = await c.get(
                f"/discord-links/{DISCORD_ID}/builder-thread", headers=INTERNAL_HDR,
            )
        assert get.status_code == 200, get.text
        assert get.json() == {"thread_id": "999888777"}
    finally:
        await db_session.execute(
            delete(DiscordLink).where(DiscordLink.discord_id == DISCORD_ID)
        )
        await db_session.commit()


async def test_builder_thread_requires_internal_secret(db_session, transport):
    await _seed_link(db_session)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            get = await c.get(f"/discord-links/{DISCORD_ID}/builder-thread")
            post = await c.post(
                f"/discord-links/{DISCORD_ID}/builder-thread",
                json={"thread_id": "1"},
            )
        assert get.status_code == 403
        assert post.status_code == 403
    finally:
        await db_session.execute(
            delete(DiscordLink).where(DiscordLink.discord_id == DISCORD_ID)
        )
        await db_session.commit()
