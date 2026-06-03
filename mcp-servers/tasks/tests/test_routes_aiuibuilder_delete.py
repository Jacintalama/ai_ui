"""User-scoped hard delete: DELETE /api/aiuibuilder/{slug}/app (needs Postgres).

Mirrors test_routes_aiuibuilder_unpublish.py. Owner-only: the build assignee
is treated as an implicit owner by _require_role, so a normal (non-admin) user
can delete their own built app. A non-owner gets 403 and nothing is removed.
The shared _delete_slug core also backs the admin DELETE /api/projects/{slug}
route, so admin behavior is unchanged.
"""
from cryptography.fernet import Fernet as _Fernet
_AIUI_TEST_KEY = _Fernet.generate_key().decode()
import os
os.environ.setdefault("AIUI_FERNET_KEY", _AIUI_TEST_KEY)

import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

import crypto_utils
from main import app
from models import (
    ChatMessage,
    ProjectMember,
    ProjectSupabase,
    PublishedApp,
    TaskItem,
)


@pytest.fixture
def transport():
    return ASGITransport(app=app)


async def _owner_with_full_project(db_session, slug, email):
    """Stage every per-slug row the cascade is expected to remove: a built
    TaskItem (which also makes `email` an implicit owner), a PublishedApp,
    a ProjectSupabase, a ChatMessage, and an explicit owner ProjectMember."""
    db_session.add(TaskItem(
        meeting_id=uuid.uuid4(), action_type="BUILD",
        assignee_name=email.split("@")[0], assignee_email=email,
        description="x", priority="NICE_TO_HAVE", status="completed",
        mode="ai", max_attempts=3, built_app_slug=slug,
    ))
    db_session.add(PublishedApp(
        slug=slug, published_by=email, public_host=f"{slug}.example.com",
    ))
    db_session.add(ProjectSupabase(
        slug=slug,
        supabase_url="https://x.supabase.co",
        anon_key_encrypted=crypto_utils.encrypt("eyJanon"),
        configured_by=email,
    ))
    db_session.add(ChatMessage(slug=slug, user_email=email, role="user", content="hi"))
    db_session.add(ProjectMember(slug=slug, user_email=email, role="owner", added_by=email))
    await db_session.commit()


async def _count(db_session, model, slug):
    field = model.built_app_slug if model is TaskItem else model.slug
    rows = (await db_session.execute(select(model).where(field == slug))).scalars().all()
    return len(rows)


async def test_owner_can_delete(db_session, transport):
    await _owner_with_full_project(db_session, "alpha", "alice@x.com")
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.delete(
            "/api/aiuibuilder/alpha/app",
            headers={"X-User-Email": "alice@x.com"},
        )
    assert r.status_code == 204
    # Every per-slug row is gone.
    assert await _count(db_session, TaskItem, "alpha") == 0
    assert await _count(db_session, PublishedApp, "alpha") == 0
    assert await _count(db_session, ProjectSupabase, "alpha") == 0
    assert await _count(db_session, ChatMessage, "alpha") == 0
    assert await _count(db_session, ProjectMember, "alpha") == 0


async def test_non_owner_cannot_delete(db_session, transport):
    await _owner_with_full_project(db_session, "alpha", "alice@x.com")
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.delete(
            "/api/aiuibuilder/alpha/app",
            headers={"X-User-Email": "mallory@x.com"},
        )
    assert r.status_code == 403
    # Nothing removed.
    assert await _count(db_session, TaskItem, "alpha") == 1
    assert await _count(db_session, PublishedApp, "alpha") == 1
    assert await _count(db_session, ProjectMember, "alpha") == 1


async def test_member_non_owner_cannot_delete(db_session, transport):
    """A project member who isn't an owner is still forbidden."""
    await _owner_with_full_project(db_session, "alpha", "alice@x.com")
    db_session.add(ProjectMember(slug="alpha", user_email="bob@x.com", role="editor", added_by="alice@x.com"))
    await db_session.commit()
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.delete(
            "/api/aiuibuilder/alpha/app",
            headers={"X-User-Email": "bob@x.com"},
        )
    assert r.status_code == 403
    assert await _count(db_session, PublishedApp, "alpha") == 1


async def test_admin_route_still_cascades(db_session, transport):
    """The admin DELETE /api/projects/{slug} route shares the same _delete_slug
    core, so it must still wipe every per-slug row (no behavior change)."""
    await _owner_with_full_project(db_session, "alpha", "alice@x.com")
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.delete(
            "/api/projects/alpha",
            headers={"X-User-Email": "admin@x.com", "X-User-Admin": "true"},
        )
    assert r.status_code == 204
    assert await _count(db_session, TaskItem, "alpha") == 0
    assert await _count(db_session, PublishedApp, "alpha") == 0
    assert await _count(db_session, ProjectMember, "alpha") == 0
