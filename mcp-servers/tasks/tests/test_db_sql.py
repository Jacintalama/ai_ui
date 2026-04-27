"""Tests for the SQL execution endpoint POST /api/projects/{slug}/db/sql."""
from cryptography.fernet import Fernet as _Fernet
_AIUI_TEST_KEY = _Fernet.generate_key().decode()

import os
import uuid

os.environ.setdefault("AIUI_FERNET_KEY", _AIUI_TEST_KEY)

import pytest
from httpx import ASGITransport, AsyncClient

import crypto_utils
from main import app
from models import ProjectMember, ProjectSupabase, TaskItem


OWNER_HDR = {"X-User-Email": "ralph@aiui.com", "X-User-Admin": "true"}


@pytest.fixture
def transport():
    return ASGITransport(app=app)


def _setup(db_session, slug="alpha", db_uri=None):
    db_session.add(TaskItem(
        meeting_id=uuid.uuid4(), action_type="BUILD",
        assignee_name="Ralph", assignee_email="ralph@aiui.com",
        description="x", priority="IMPORTANT", status="completed",
        built_app_slug=slug,
    ))
    db_session.add(ProjectMember(
        slug=slug, user_email="ralph@aiui.com",
        role="owner", added_by="ralph@aiui.com",
    ))
    if db_uri is not None:
        db_session.add(ProjectSupabase(
            slug=slug,
            supabase_url="https://refxyz.supabase.co",
            anon_key_encrypted=crypto_utils.encrypt("anon"),
            db_uri_encrypted=crypto_utils.encrypt(db_uri),
            configured_by="ralph@aiui.com",
        ))


async def test_sql_returns_409_when_no_db_uri(db_session, transport):
    _setup(db_session, db_uri=None)
    await db_session.commit()
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/projects/alpha/db/sql",
                         headers=OWNER_HDR,
                         json={"sql": "SELECT 1"})
    assert r.status_code == 409
    assert "no database" in r.json()["detail"].lower() or "not configured" in r.json()["detail"].lower()


async def test_sql_rejects_non_owner(db_session, transport):
    _setup(db_session, db_uri="postgresql://x:y@host/db")
    await db_session.commit()
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/projects/alpha/db/sql",
                         headers={"X-User-Email": "stranger@aiui.com",
                                  "X-User-Admin": "true"},
                         json={"sql": "SELECT 1"})
    assert r.status_code == 403


async def test_sql_against_test_postgres_returns_rows(db_session, transport, monkeypatch):
    """Use the live local Postgres as the 'Supabase' so we exercise real asyncpg."""
    raw_url = os.environ["DATABASE_URL"]  # postgresql+asyncpg://… or postgresql://…
    plain_uri = raw_url.replace("postgresql+asyncpg://", "postgresql://")
    _setup(db_session, db_uri=plain_uri)
    await db_session.commit()

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/projects/alpha/db/sql",
                         headers=OWNER_HDR,
                         json={"sql": "SELECT 42 AS answer"})
    assert r.status_code == 200
    body = r.json()
    assert body["rowcount"] == 1
    assert body["rows"][0]["answer"] == 42
    assert "executed_ms" in body


async def test_sql_postgres_error_returns_400(db_session, transport):
    raw_url = os.environ["DATABASE_URL"]
    plain_uri = raw_url.replace("postgresql+asyncpg://", "postgresql://")
    _setup(db_session, db_uri=plain_uri)
    await db_session.commit()
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/projects/alpha/db/sql",
                         headers=OWNER_HDR,
                         json={"sql": "SELECT * FROM table_that_does_not_exist"})
    assert r.status_code == 400
    detail = r.json()["detail"].lower()
    assert "table_that_does_not_exist" in detail or "does not exist" in detail


async def test_sql_can_create_and_drop_table(db_session, transport):
    """End-to-end: CREATE TABLE / INSERT / SELECT / DROP all work in one flow."""
    raw_url = os.environ["DATABASE_URL"]
    plain_uri = raw_url.replace("postgresql+asyncpg://", "postgresql://")
    _setup(db_session, db_uri=plain_uri)
    await db_session.commit()

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # Create a temp schema-prefixed table to avoid colliding with anything.
        r = await c.post("/api/projects/alpha/db/sql", headers=OWNER_HDR,
                         json={"sql": "CREATE TABLE IF NOT EXISTS public.aiui_test_t (id INT, name TEXT)"})
        assert r.status_code == 200

        r = await c.post("/api/projects/alpha/db/sql", headers=OWNER_HDR,
                         json={"sql": "INSERT INTO public.aiui_test_t VALUES (1, 'hello')"})
        assert r.status_code == 200

        r = await c.post("/api/projects/alpha/db/sql", headers=OWNER_HDR,
                         json={"sql": "SELECT * FROM public.aiui_test_t WHERE id = 1"})
        assert r.status_code == 200
        assert r.json()["rows"][0]["name"] == "hello"

        # Cleanup so subsequent test runs don't leave junk.
        r = await c.post("/api/projects/alpha/db/sql", headers=OWNER_HDR,
                         json={"sql": "DROP TABLE IF EXISTS public.aiui_test_t"})
        assert r.status_code == 200