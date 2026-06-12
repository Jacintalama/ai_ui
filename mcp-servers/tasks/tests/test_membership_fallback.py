"""Creator ownership must not depend on the completion prose.

The owner membership insert used to run only when a slug was parsed from the
execution OUTPUT — builds whose completion message didn't mention
``apps/<slug>/`` never appeared in "My apps" (live 2026-06-12: a voice-built
app existed and previewed fine but was invisible to its creator).
"""
import uuid

import pytest
from sqlalchemy import select

from models import ProjectMember, TaskItem
from routes_execution import _grant_creator_membership


async def _make_build_task(db_session, slug, email="owner@x.com"):
    item = TaskItem(
        meeting_id=uuid.uuid4(), action_type="BUILD",
        assignee_name="X", assignee_email=email,
        description="x", priority="NICE_TO_HAVE", status="running",
        built_app_slug=slug,
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)
    return item


async def _member_roles(db_session, slug):
    rows = (await db_session.execute(
        select(ProjectMember).where(ProjectMember.slug == slug)
    )).scalars().all()
    return {(m.user_email, m.role) for m in rows}


@pytest.mark.asyncio
async def test_membership_granted_without_parsed_slug(db_session):
    """No slug in the completion output -> fall back to the creation slug."""
    item = await _make_build_task(db_session, "voice-built-app-1234")
    await _grant_creator_membership(db_session, item.id, parsed_slug=None)
    await db_session.commit()
    assert await _member_roles(db_session, "voice-built-app-1234") == {
        ("owner@x.com", "owner")
    }


@pytest.mark.asyncio
async def test_membership_uses_parsed_slug_when_present(db_session):
    item = await _make_build_task(db_session, "creation-slug-0000")
    await _grant_creator_membership(db_session, item.id, parsed_slug="parsed-slug-9999")
    await db_session.commit()
    assert await _member_roles(db_session, "parsed-slug-9999") == {
        ("owner@x.com", "owner")
    }


@pytest.mark.asyncio
async def test_membership_is_idempotent(db_session):
    item = await _make_build_task(db_session, "twice-app-1111")
    await _grant_creator_membership(db_session, item.id, parsed_slug=None)
    await db_session.commit()
    await _grant_creator_membership(db_session, item.id, parsed_slug=None)
    await db_session.commit()
    assert await _member_roles(db_session, "twice-app-1111") == {
        ("owner@x.com", "owner")
    }


@pytest.mark.asyncio
async def test_membership_skipped_when_no_slug_anywhere(db_session):
    item = await _make_build_task(db_session, None)
    await _grant_creator_membership(db_session, item.id, parsed_slug=None)
    await db_session.commit()
    rows = (await db_session.execute(select(ProjectMember))).scalars().all()
    assert rows == []
