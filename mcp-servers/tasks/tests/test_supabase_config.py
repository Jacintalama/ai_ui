"""Tests for Supabase config endpoints (GET / POST / DELETE)."""
from cryptography.fernet import Fernet as _Fernet
_AIUI_TEST_KEY = _Fernet.generate_key().decode()

import os
import uuid

# Set the Fernet key BEFORE importing app so crypto_utils initializes cleanly.
os.environ.setdefault("AIUI_FERNET_KEY", _AIUI_TEST_KEY)

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from main import app
from models import ProjectMember, ProjectSupabase, TaskItem


OWNER_HDR = {"X-User-Email": "ralph@aiui.com", "X-User-Admin": "true"}
ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.example.signature"


@pytest.fixture
def transport():
    return ASGITransport(app=app)


def _setup_owner(db_session, slug="alpha"):
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


async def test_get_returns_unconfigured_state(db_session, transport):
    _setup_owner(db_session)
    await db_session.commit()
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/projects/alpha/supabase", headers=OWNER_HDR)
    assert r.status_code == 200
    assert r.json()["configured"] is False


async def test_set_then_get_returns_configured_state(db_session, transport):
    _setup_owner(db_session)
    await db_session.commit()

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/projects/alpha/supabase", headers=OWNER_HDR, json={
            "supabase_url": "https://xyz.supabase.co",
            "anon_key": ANON_KEY,
        })
        assert r.status_code == 200
        body = r.json()
        assert body["configured"] is True
        assert body["supabase_url"] == "https://xyz.supabase.co"
        # Anon key MUST NOT be returned in any field.
        assert "anon_key" not in body
        assert "anon_key_encrypted" not in body

        r = await c.get("/api/projects/alpha/supabase", headers=OWNER_HDR)
        assert r.status_code == 200
        assert r.json()["configured"] is True
        assert r.json()["supabase_url"] == "https://xyz.supabase.co"

    # DB row holds ENCRYPTED key (not the plaintext).
    row = (await db_session.execute(
        select(ProjectSupabase).where(ProjectSupabase.slug == "alpha")
    )).scalar_one()
    assert row.anon_key_encrypted != ANON_KEY


async def test_set_rejects_invalid_url(db_session, transport):
    _setup_owner(db_session)
    await db_session.commit()
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/projects/alpha/supabase", headers=OWNER_HDR,
                         json={"supabase_url": "ftp://nope", "anon_key": ANON_KEY})
    assert r.status_code == 400


async def test_set_rejects_non_owner(db_session, transport):
    _setup_owner(db_session)
    await db_session.commit()
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/projects/alpha/supabase",
                         headers={"X-User-Email": "stranger@aiui.com",
                                  "X-User-Admin": "true"},
                         json={"supabase_url": "https://xyz.supabase.co",
                               "anon_key": ANON_KEY})
    assert r.status_code == 403


async def test_delete_removes_config(db_session, transport):
    _setup_owner(db_session)
    db_session.add(ProjectSupabase(
        slug="alpha", supabase_url="https://xyz.supabase.co",
        anon_key_encrypted="enc", configured_by="ralph@aiui.com",
    ))
    await db_session.commit()
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.delete("/api/projects/alpha/supabase", headers=OWNER_HDR)
        assert r.status_code == 204
        r = await c.get("/api/projects/alpha/supabase", headers=OWNER_HDR)
        assert r.json()["configured"] is False


async def test_set_with_db_uri_encrypts_and_flags(db_session, transport):
    _setup_owner(db_session)
    await db_session.commit()

    db_uri = "postgresql://postgres.refxyz:hunter2@aws-0-us-east-1.pooler.supabase.com:6543/postgres"
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/projects/alpha/supabase", headers=OWNER_HDR, json={
            "supabase_url": "https://refxyz.supabase.co",
            "anon_key": ANON_KEY,
            "db_uri": db_uri,
        })
        assert r.status_code == 200
        body = r.json()
        assert body["has_db_uri"] is True
        # URI must NEVER be returned.
        assert "db_uri" not in body
        assert "db_uri_encrypted" not in body

    row = (await db_session.execute(
        select(ProjectSupabase).where(ProjectSupabase.slug == "alpha")
    )).scalar_one()
    assert row.db_uri_encrypted is not None
    assert row.db_uri_encrypted != db_uri  # encrypted, not plaintext


async def test_set_rejects_non_postgres_db_uri(db_session, transport):
    _setup_owner(db_session)
    await db_session.commit()
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/projects/alpha/supabase", headers=OWNER_HDR, json={
            "supabase_url": "https://refxyz.supabase.co",
            "anon_key": ANON_KEY,
            "db_uri": "mysql://nope",
        })
    assert r.status_code == 400


async def test_get_indicates_has_db_uri(db_session, transport):
    _setup_owner(db_session)
    db_session.add(ProjectSupabase(
        slug="alpha", supabase_url="https://refxyz.supabase.co",
        anon_key_encrypted="enc", db_uri_encrypted="enc-uri",
        configured_by="ralph@aiui.com",
    ))
    await db_session.commit()
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/projects/alpha/supabase", headers=OWNER_HDR)
    assert r.status_code == 200
    assert r.json()["has_db_uri"] is True