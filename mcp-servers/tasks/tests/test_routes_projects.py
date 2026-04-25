"""Tests for routes_projects."""
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from main import app
from models import ProjectMember


@pytest.fixture
def transport():
    return ASGITransport(app=app)


async def test_member_can_leave_project(db_session, transport):
    db_session.add(ProjectMember(slug="alpha", user_email="ralph@aiui.com",
                                  role="owner", added_by="ralph@aiui.com"))
    db_session.add(ProjectMember(slug="alpha", user_email="bob@aiui.com",
                                  role="editor", added_by="ralph@aiui.com"))
    await db_session.commit()

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/projects/alpha/leave",
                         headers={"X-User-Email": "bob@aiui.com",
                                  "X-User-Admin": "true"})
    assert r.status_code == 204

    rows = (await db_session.execute(
        select(ProjectMember).where(ProjectMember.slug == "alpha")
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].user_email == "ralph@aiui.com"


async def test_last_owner_cannot_leave(db_session, transport):
    db_session.add(ProjectMember(slug="alpha", user_email="ralph@aiui.com",
                                  role="owner", added_by="ralph@aiui.com"))
    await db_session.commit()

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/projects/alpha/leave",
                         headers={"X-User-Email": "ralph@aiui.com",
                                  "X-User-Admin": "true"})
    assert r.status_code == 409


async def test_non_member_leave_returns_404(db_session, transport):
    db_session.add(ProjectMember(slug="alpha", user_email="ralph@aiui.com",
                                  role="owner", added_by="ralph@aiui.com"))
    await db_session.commit()

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/projects/alpha/leave",
                         headers={"X-User-Email": "stranger@aiui.com",
                                  "X-User-Admin": "true"})
    assert r.status_code == 404
