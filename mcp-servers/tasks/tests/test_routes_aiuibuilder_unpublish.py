"""User-scoped unpublish: DELETE /api/aiuibuilder/{slug}/publish (needs Postgres)."""
from cryptography.fernet import Fernet as _Fernet
_AIUI_TEST_KEY = _Fernet.generate_key().decode()
import os
os.environ.setdefault("AIUI_FERNET_KEY", _AIUI_TEST_KEY)

import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from main import app
from models import PublishedApp, TaskItem


@pytest.fixture
def transport():
    return ASGITransport(app=app)


async def _owner_with_published(db_session, slug, email):
    db_session.add(TaskItem(
        meeting_id=uuid.uuid4(), action_type="BUILD",
        assignee_name=email.split("@")[0], assignee_email=email,
        description="x", priority="NICE_TO_HAVE", status="completed",
        mode="ai", max_attempts=3, built_app_slug=slug,
    ))
    db_session.add(PublishedApp(slug=slug, published_by=email, public_host=f"{slug}.example.com"))
    await db_session.commit()


async def test_owner_can_unpublish(db_session, transport):
    await _owner_with_published(db_session, "alpha", "alice@x.com")
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.delete("/api/aiuibuilder/alpha/publish", headers={"X-User-Email": "alice@x.com"})
    assert r.status_code == 204
    row = (await db_session.execute(select(PublishedApp).where(PublishedApp.slug == "alpha"))).scalar_one_or_none()
    assert row is None


async def test_unpublish_idempotent_when_not_published(db_session, transport):
    db_session.add(TaskItem(
        meeting_id=uuid.uuid4(), action_type="BUILD", assignee_name="a",
        assignee_email="alice@x.com", description="x", priority="NICE_TO_HAVE",
        status="completed", mode="ai", max_attempts=3, built_app_slug="alpha",
    ))
    await db_session.commit()
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.delete("/api/aiuibuilder/alpha/publish", headers={"X-User-Email": "alice@x.com"})
    assert r.status_code == 204


async def test_non_owner_cannot_unpublish(db_session, transport):
    await _owner_with_published(db_session, "alpha", "alice@x.com")
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.delete("/api/aiuibuilder/alpha/publish", headers={"X-User-Email": "mallory@x.com"})
    assert r.status_code == 403
    row = (await db_session.execute(select(PublishedApp).where(PublishedApp.slug == "alpha"))).scalar_one_or_none()
    assert row is not None
