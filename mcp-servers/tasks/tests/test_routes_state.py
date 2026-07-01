"""Tests for the generic bot-state KV endpoints:

    GET    /state/{key}
    PUT    /state/{key}   {"value": <any>, "ttl_seconds": <int|null>}
    DELETE /state/{key}

Authed with X-Internal-Secret (INTERNAL_CALLBACK_SECRET). Mirrors the
/discord-links test style. Runs against the test DB (AIUI_TEST_DB=1)."""
from cryptography.fernet import Fernet as _Fernet

_AIUI_TEST_KEY = _Fernet.generate_key().decode()

import os

os.environ.setdefault("AIUI_FERNET_KEY", _AIUI_TEST_KEY)
os.environ.setdefault("INTERNAL_CALLBACK_SECRET", "test-internal-secret")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from main import app
from models import BotState


SECRET = os.environ["INTERNAL_CALLBACK_SECRET"]
INTERNAL_HDR = {"X-Internal-Secret": SECRET}
KEY = "test:bot-state:key1"


@pytest.fixture
def transport():
    return ASGITransport(app=app)


async def _cleanup(db_session) -> None:
    await db_session.execute(delete(BotState).where(BotState.state_key == KEY))
    await db_session.commit()


async def test_get_absent_returns_null(db_session, transport):
    await _cleanup(db_session)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get(f"/state/{KEY}", headers=INTERNAL_HDR)
    assert r.status_code == 200, r.text
    assert r.json() == {"value": None}


async def test_put_then_get_roundtrip(db_session, transport):
    await _cleanup(db_session)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            put = await c.put(
                f"/state/{KEY}", headers=INTERNAL_HDR,
                json={"value": {"intent": "build_app", "detail": "a shop"}})
            assert put.status_code == 200, put.text
            get = await c.get(f"/state/{KEY}", headers=INTERNAL_HDR)
        assert get.json() == {"value": {"intent": "build_app", "detail": "a shop"}}
    finally:
        await _cleanup(db_session)


async def test_expired_reads_as_absent(db_session, transport):
    await _cleanup(db_session)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            put = await c.put(
                f"/state/{KEY}", headers=INTERNAL_HDR,
                json={"value": "x", "ttl_seconds": -1})  # already expired
            assert put.status_code == 200, put.text
            get = await c.get(f"/state/{KEY}", headers=INTERNAL_HDR)
        assert get.json() == {"value": None}
    finally:
        await _cleanup(db_session)


async def test_delete_idempotent(db_session, transport):
    await _cleanup(db_session)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.put(f"/state/{KEY}", headers=INTERNAL_HDR, json={"value": 1})
        d1 = await c.delete(f"/state/{KEY}", headers=INTERNAL_HDR)
        d2 = await c.delete(f"/state/{KEY}", headers=INTERNAL_HDR)  # already gone
        get = await c.get(f"/state/{KEY}", headers=INTERNAL_HDR)
    assert d1.status_code == 200 and d2.status_code == 200
    assert get.json() == {"value": None}


async def test_requires_internal_secret(transport):
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        g = await c.get(f"/state/{KEY}")
        p = await c.put(f"/state/{KEY}", json={"value": 1})
        d = await c.delete(f"/state/{KEY}")
    assert g.status_code == 403 and p.status_code == 403 and d.status_code == 403
