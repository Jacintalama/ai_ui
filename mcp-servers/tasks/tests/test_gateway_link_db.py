"""Redemption and the per-account lockout, against a real database.

Container tier. Deliberately does NOT use the db_session fixture: that fixture
TRUNCATEs eight tasks.* tables, and in April 2026 a careless run of exactly this
kind wiped 9 production projects and all chat history. Everything here is
namespaced under a unique platform value or a synthetic email, and deleted in a
finally.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.skipif(
    "test" not in os.environ.get("DATABASE_URL", "")
    and not os.environ.get("AIUI_CONTAINER_DB"),
    reason="needs a real database; run inside the tasks container",
)

import asyncpg
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import gateway_pairing as gp
import routes_gateway

SECRET = os.environ.get("INTERNAL_CALLBACK_SECRET", "")
HEADERS = {"X-Internal-Secret": SECRET}


@pytest.fixture
def platform():
    """A platform name no real row will ever use, so cleanup is exact."""
    return f"pytest-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def guesser():
    """An address no real account has, for the failure paths."""
    return f"pytest-{uuid.uuid4().hex[:8]}@example.invalid"


@pytest.fixture(autouse=True)
def fresh_db_engine():
    """db.py caches an engine bound to whichever event loop first used it.

    pytest-asyncio hands every test a fresh loop, so a maker left over from the
    previous test poisons this one with "another operation is in progress".
    Abandon it rather than closing it, because closing would touch the dead loop.
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
    app.include_router(routes_gateway.page_router)
    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://t") as c:
        yield c


async def _a_real_email() -> str:
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        return await conn.fetchval(
            'SELECT email FROM public."user" WHERE email IS NOT NULL LIMIT 1')
    finally:
        await conn.close()


async def _cleanup(platform: str, *emails: str) -> None:
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        for table in ("gateway_links", "gateway_pairing_codes"):
            await conn.execute(
                f"DELETE FROM tasks.{table} WHERE platform = $1", platform)
        for email in emails:
            if email:
                await conn.execute(
                    "DELETE FROM tasks.gateway_redeem_budget WHERE email = $1", email)
    finally:
        await conn.close()


async def _budget(email: str):
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        return await conn.fetchrow(
            "SELECT failures, window_started_at, locked_until "
            "FROM tasks.gateway_redeem_budget WHERE email = $1", email)
    finally:
        await conn.close()


async def test_redeem_links_the_account_and_burns_the_code(client, platform):
    email = await _a_real_email()
    try:
        issued = await client.post("/gateway/resolve", headers=HEADERS, json={
            "platform": platform, "platform_user_id": "u1",
            "platform_user_name": "Ralph"})
        code = issued.json()["code"]

        ok = await client.post("/tasks/gateway/link", json={"code": code},
                               headers={"X-User-Email": email})
        assert ok.status_code == 200, ok.text
        assert ok.json()["platform"] == platform

        again = await client.post("/tasks/gateway/link", json={"code": code},
                                  headers={"X-User-Email": email})
        assert again.status_code == 404, "a code must work exactly once"

        now_linked = await client.post("/gateway/resolve", headers=HEADERS, json={
            "platform": platform, "platform_user_id": "u1"})
        assert now_linked.json()["linked"] is True
        assert now_linked.json()["email"] == email
    finally:
        await _cleanup(platform, email)


async def test_an_expired_code_is_refused(client, platform, guesser):
    code = gp.generate_code()
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        await conn.execute(
            "INSERT INTO tasks.gateway_pairing_codes "
            "(code_hash, platform, platform_user_id, expires_at) "
            "VALUES ($1, $2, $3, $4)",
            gp.hash_code(code), platform, "u2",
            datetime.now(timezone.utc) - timedelta(minutes=1))
    finally:
        await conn.close()
    try:
        resp = await client.post("/tasks/gateway/link", json={"code": code},
                                 headers={"X-User-Email": guesser})
        assert resp.status_code == 410
    finally:
        await _cleanup(platform, guesser)


async def test_wrong_codes_lock_the_guesser_and_nobody_else(client, platform,
                                                            guesser):
    """The whole reason the counter moved off the code row.

    Under the old design a wrong guess had to increment every live code, so five
    bad guesses locked out every pending pairing on the platform.
    """
    other = f"pytest-{uuid.uuid4().hex[:8]}@example.invalid"
    try:
        # A real pending code belonging to somebody else.
        issued = await client.post("/gateway/resolve", headers=HEADERS, json={
            "platform": platform, "platform_user_id": "victim"})
        victim_code = issued.json()["code"]

        for _ in range(gp.MAX_REDEEM_ATTEMPTS):
            await client.post("/tasks/gateway/link", json={"code": "ZZZZZZZZ"},
                              headers={"X-User-Email": guesser})

        locked = await client.post("/tasks/gateway/link", json={"code": "ZZZZZZZZ"},
                                   headers={"X-User-Email": guesser})
        assert locked.status_code == 429
        assert "minutes" in locked.json()["detail"]

        row = await _budget(guesser)
        assert row["locked_until"] is not None

        # The bystander is untouched: no budget row, and their code still works
        # far enough to be recognized rather than rejected as unknown.
        assert await _budget(other) is None
        real_email = await _a_real_email()
        used = await client.post("/tasks/gateway/link", json={"code": victim_code},
                                 headers={"X-User-Email": real_email})
        assert used.status_code == 200, (
            "one account's guessing must never lock out another's pairing")
        await _cleanup(platform, real_email)
    finally:
        await _cleanup(platform, guesser, other)


async def test_a_served_lock_starts_a_fresh_window(client, platform, guesser):
    """A lock already waited out must not re-arm on the very next typo.

    Re-locking then would punish an honest user far more than an attacker, who
    simply waits either way.
    """
    now = datetime.now(timezone.utc)
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        await conn.execute(
            "INSERT INTO tasks.gateway_redeem_budget "
            "(email, failures, window_started_at, locked_until) "
            "VALUES ($1, $2, $3, $4)",
            guesser, 0, now - timedelta(minutes=20), now - timedelta(minutes=1))
    finally:
        await conn.close()
    try:
        resp = await client.post("/tasks/gateway/link", json={"code": "ZZZZZZZZ"},
                                 headers={"X-User-Email": guesser})
        assert resp.status_code == 404, "the expired lock must not still bite"

        row = await _budget(guesser)
        assert row["locked_until"] is None
        assert row["failures"] == 1, "a served lock resets the count, not continues it"
    finally:
        await _cleanup(platform, guesser)


async def test_a_success_clears_the_budget(client, platform):
    email = await _a_real_email()
    try:
        await client.post("/tasks/gateway/link", json={"code": "ZZZZZZZZ"},
                          headers={"X-User-Email": email})
        assert await _budget(email) is not None

        issued = await client.post("/gateway/resolve", headers=HEADERS, json={
            "platform": platform, "platform_user_id": "u3"})
        ok = await client.post("/tasks/gateway/link",
                               json={"code": issued.json()["code"]},
                               headers={"X-User-Email": email})
        assert ok.status_code == 200

        assert await _budget(email) is None, "a success means they are not guessing"
    finally:
        await _cleanup(platform, email)
