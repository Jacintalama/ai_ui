"""Tests for routes_projects."""
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from main import app
from models import ProjectMember, TaskItem


def _seed_project_task(db_session, slug: str, owner: str = "ralph@aiui.com") -> None:
    """Add a TaskItem so the slug is recognized by /members endpoints
    (POST /members has an existence check against tasks.items)."""
    db_session.add(TaskItem(
        meeting_id=uuid.uuid4(),
        action_type="BUILD",
        assignee_name="Ralph",
        assignee_email=owner,
        description="seed",
        priority="NICE_TO_HAVE",
        status="completed",
        built_app_slug=slug,
    ))


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


# ---------------------------------------------------------------------------
# Bug A: case-insensitive email matching
# ---------------------------------------------------------------------------

async def test_require_role_lowercases_email_arg(db_session):
    """Direct unit test: _require_role normalizes its email arg so a mixed-
    case header still matches the lowercased DB row."""
    from routes_projects import _require_role
    db_session.add(ProjectMember(slug="alpha", user_email="alice@example.com",
                                 role="editor", added_by="ralph@aiui.com"))
    await db_session.commit()

    role = await _require_role(db_session, "alpha", "Alice@Example.COM",
                               "editor", is_admin=False)
    assert role == "editor"


async def test_member_endpoint_case_insensitive(db_session, transport):
    """End-to-end: invite Alice@Example.com (server lowercases to alice@…)
    then call a member-only endpoint with both mixed-case and lowercase
    X-User-Email headers — both must succeed thanks to normalization."""
    _seed_project_task(db_session, "alpha")
    db_session.add(ProjectMember(slug="alpha", user_email="ralph@aiui.com",
                                 role="owner", added_by="ralph@aiui.com"))
    await db_session.commit()

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/api/projects/alpha/members",
            headers={"X-User-Email": "ralph@aiui.com", "X-User-Admin": "true"},
            json={"user_email": "Alice@Example.com", "role": "editor"},
        )
        assert r.status_code == 201
        assert r.json()["user_email"] == "alice@example.com"

        # Mixed-case header: should still resolve to the lowercased member row.
        r = await c.get(
            "/api/projects/alpha/members",
            headers={"X-User-Email": "Alice@Example.com", "X-User-Admin": "true"},
        )
        assert r.status_code == 200

        # Lowercase header: also fine.
        r = await c.get(
            "/api/projects/alpha/members",
            headers={"X-User-Email": "alice@example.com", "X-User-Admin": "true"},
        )
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Bug B: PATCH /members/{email} — change role + last-owner guard
# ---------------------------------------------------------------------------

async def test_patch_member_role_promotes(db_session, transport):
    db_session.add(ProjectMember(slug="alpha", user_email="ralph@aiui.com",
                                 role="owner", added_by="ralph@aiui.com"))
    db_session.add(ProjectMember(slug="alpha", user_email="bob@aiui.com",
                                 role="editor", added_by="ralph@aiui.com"))
    await db_session.commit()

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.patch(
            "/api/projects/alpha/members/bob@aiui.com",
            headers={"X-User-Email": "ralph@aiui.com", "X-User-Admin": "true"},
            json={"role": "owner"},
        )
    assert r.status_code == 200
    assert r.json()["role"] == "owner"


async def test_patch_member_role_invalid_value(db_session, transport):
    db_session.add(ProjectMember(slug="alpha", user_email="ralph@aiui.com",
                                 role="owner", added_by="ralph@aiui.com"))
    db_session.add(ProjectMember(slug="alpha", user_email="bob@aiui.com",
                                 role="editor", added_by="ralph@aiui.com"))
    await db_session.commit()

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.patch(
            "/api/projects/alpha/members/bob@aiui.com",
            headers={"X-User-Email": "ralph@aiui.com", "X-User-Admin": "true"},
            json={"role": "supervisor"},
        )
    # Pydantic Literal validation returns 422; explicit validation returns 400.
    assert r.status_code in (400, 422)


async def test_patch_member_role_unknown_member(db_session, transport):
    db_session.add(ProjectMember(slug="alpha", user_email="ralph@aiui.com",
                                 role="owner", added_by="ralph@aiui.com"))
    await db_session.commit()

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.patch(
            "/api/projects/alpha/members/ghost@aiui.com",
            headers={"X-User-Email": "ralph@aiui.com", "X-User-Admin": "true"},
            json={"role": "editor"},
        )
    assert r.status_code == 404


async def test_patch_member_role_blocks_last_owner_demotion(db_session, transport):
    db_session.add(ProjectMember(slug="alpha", user_email="ralph@aiui.com",
                                 role="owner", added_by="ralph@aiui.com"))
    db_session.add(ProjectMember(slug="alpha", user_email="bob@aiui.com",
                                 role="editor", added_by="ralph@aiui.com"))
    await db_session.commit()

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.patch(
            "/api/projects/alpha/members/ralph@aiui.com",
            headers={"X-User-Email": "ralph@aiui.com", "X-User-Admin": "true"},
            json={"role": "editor"},
        )
    assert r.status_code == 409
    assert "last owner" in r.json()["detail"].lower()


async def test_patch_member_role_allows_demotion_when_other_owner_exists(db_session, transport):
    db_session.add(ProjectMember(slug="alpha", user_email="ralph@aiui.com",
                                 role="owner", added_by="ralph@aiui.com"))
    db_session.add(ProjectMember(slug="alpha", user_email="bob@aiui.com",
                                 role="owner", added_by="ralph@aiui.com"))
    await db_session.commit()

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.patch(
            "/api/projects/alpha/members/bob@aiui.com",
            headers={"X-User-Email": "ralph@aiui.com", "X-User-Admin": "true"},
            json={"role": "editor"},
        )
    assert r.status_code == 200
    assert r.json()["role"] == "editor"
