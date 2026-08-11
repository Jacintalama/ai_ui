"""Round trips against a real database. Container tier.

Deliberately does NOT use the db_session fixture: that fixture TRUNCATEs eight
tasks.* tables, and on 2026-04-27 a careless run of exactly this kind wiped 9
production projects and all chat history. Everything here is namespaced under a
unique platform value and deleted in a finally.
"""
import os
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    "test" not in os.environ.get("DATABASE_URL", "")
    and not os.environ.get("AIUI_CONTAINER_DB"),
    reason="needs a real database; run inside the tasks container",
)

import asyncpg
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import routes_gateway

SECRET = os.environ.get("INTERNAL_CALLBACK_SECRET", "")
HEADERS = {"X-Internal-Secret": SECRET}


@pytest.fixture
def platform():
    """A platform name no real row will ever use, so cleanup is exact."""
    return f"pytest-{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
def fresh_db_engine():
    """db.py caches an engine bound to whichever event loop first used it.

    pytest-asyncio hands every test a fresh loop, so a maker left over from the
    previous test poisons this one with "another operation is in progress".
    Abandon it rather than closing it, because closing would touch the dead
    loop. Same reset tests/conftest.py does, for the same reason, but without
    its db_session fixture, which TRUNCATEs eight tasks.* tables.
    """
    import db

    db._engine = None
    db._session_maker = None
    yield
    db._engine = None
    db._session_maker = None


@pytest.fixture
async def client():
    app = FastAPI()
    app.include_router(routes_gateway.router)
    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://t") as c:
        yield c


async def _cleanup(platform: str) -> None:
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        for table in ("gateway_links", "gateway_pairing_codes", "gateway_sessions"):
            await conn.execute(
                f"DELETE FROM tasks.{table} WHERE platform = $1", platform)
    finally:
        await conn.close()


async def test_unlinked_user_gets_a_code_then_the_same_one_again(client, platform):
    try:
        first = await client.post("/gateway/resolve", headers=HEADERS, json={
            "platform": platform, "platform_user_id": "u1"})
        assert first.status_code == 200
        assert first.json()["linked"] is False
        assert len(first.json()["code"]) == 8

        second = await client.post("/gateway/resolve", headers=HEADERS, json={
            "platform": platform, "platform_user_id": "u1"})
        assert second.json()["linked"] is False

        conn = await asyncpg.connect(os.environ["DATABASE_URL"])
        try:
            rows = await conn.fetchval(
                "SELECT count(*) FROM tasks.gateway_pairing_codes "
                "WHERE platform = $1 AND platform_user_id = $2", platform, "u1")
        finally:
            await conn.close()
        assert rows == 1, "a second message must not create a second code row"
    finally:
        await _cleanup(platform)


async def test_a_linked_user_gets_a_token(client, platform):
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        await conn.execute(
            "INSERT INTO tasks.gateway_links "
            "(platform, platform_user_id, owui_user_id, email) "
            "VALUES ($1, $2, $3, $4)",
            platform, "u2", "owui-user-2", "someone@example.com")
    finally:
        await conn.close()
    try:
        resp = await client.post("/gateway/resolve", headers=HEADERS, json={
            "platform": platform, "platform_user_id": "u2"})
        body = resp.json()
        assert body["linked"] is True
        assert body["email"] == "someone@example.com"
        assert body["owui_token"].count(".") == 2
        assert "code" not in body
    finally:
        await _cleanup(platform)


async def test_session_upsert_is_idempotent_and_readable(client, platform):
    try:
        payload = {"platform": platform, "chat_id": "c1",
                   "owui_chat_id": "owui-chat-1", "owui_user_id": "owui-user-1"}
        assert (await client.put("/gateway/session", headers=HEADERS,
                                 json=payload)).status_code == 200
        payload["owui_chat_id"] = "owui-chat-2"
        assert (await client.put("/gateway/session", headers=HEADERS,
                                 json=payload)).status_code == 200

        got = await client.get("/gateway/session", headers=HEADERS,
                               params={"platform": platform, "chat_id": "c1"})
        assert got.json()["owui_chat_id"] == "owui-chat-2"

        recent = await client.get("/gateway/sessions/recent", headers=HEADERS,
                                  params={"owui_user_id": "owui-user-1"})
        mine = [s for s in recent.json()["sessions"] if s["platform"] == platform]
        assert len(mine) == 1
    finally:
        await _cleanup(platform)


async def test_an_unknown_session_reads_as_null(client, platform):
    got = await client.get("/gateway/session", headers=HEADERS,
                           params={"platform": platform, "chat_id": "nope"})
    assert got.json()["owui_chat_id"] is None


async def test_resolve_no_longer_resets_a_guessers_budget(client, platform):
    """The old bug: an attempt-exhausted code row was invisible to resolve, so
    the next ordinary message minted a fresh row with the counter at zero. There
    is no per-code counter now, so re-resolving must reuse the one row."""
    try:
        first = await client.post("/gateway/resolve", headers=HEADERS, json={
            "platform": platform, "platform_user_id": "u9"})
        assert first.json()["linked"] is False

        second = await client.post("/gateway/resolve", headers=HEADERS, json={
            "platform": platform, "platform_user_id": "u9"})
        assert second.json()["linked"] is False
        assert second.json()["code"] != first.json()["code"], (
            "a resend must re-mint, because only the hash is stored")

        conn = await asyncpg.connect(os.environ["DATABASE_URL"])
        try:
            rows = await conn.fetchval(
                "SELECT count(*) FROM tasks.gateway_pairing_codes "
                "WHERE platform = $1 AND platform_user_id = $2", platform, "u9")
        finally:
            await conn.close()
        assert rows == 1, "resolve must reuse the row, never accumulate rows"
    finally:
        await _cleanup(platform)
