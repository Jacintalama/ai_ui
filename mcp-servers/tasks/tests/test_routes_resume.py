"""Tests for POST /api/tasks/{id}/resume.

Covers three paths:
  - skip=true on awaiting_supabase → pending + localStorage marker + chat msg
  - skip=false but no Supabase linked → 412
  - resume on a task that's not awaiting_supabase → 409

We monkey-patch `routes_execution._run_execution` to a no-op so the test
doesn't try to spawn the real Claude subprocess.
"""
from cryptography.fernet import Fernet as _Fernet
_AIUI_TEST_KEY = _Fernet.generate_key().decode()

import os
import uuid

os.environ.setdefault("AIUI_FERNET_KEY", _AIUI_TEST_KEY)

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from main import app
import routes_execution
from models import ChatMessage, ProjectMember, ProjectSupabase, TaskItem


ADMIN_HEADERS = {"X-User-Email": "ralph@aiui.com", "X-User-Admin": "true"}


@pytest.fixture(autouse=True)
def _stub_run_execution(monkeypatch):
    """Replace the background runner with a no-op so /resume returns
    cleanly without trying to spawn Claude."""
    async def _noop(*args, **kwargs):
        return None
    monkeypatch.setattr(routes_execution, "_run_execution", _noop)


def _make_awaiting_task(db_session, slug="foo-app", description="USER REQUEST: build x"):
    item = TaskItem(
        meeting_id=uuid.uuid4(),
        action_type="BUILD",
        assignee_name="Ralph",
        assignee_email="ralph@aiui.com",
        description=description,
        priority="IMPORTANT",
        status="awaiting_supabase",
        built_app_slug=slug,
    )
    db_session.add(item)
    db_session.add(ProjectMember(
        slug=slug, user_email="ralph@aiui.com", role="owner", added_by="ralph@aiui.com",
    ))
    return item


async def test_resume_skip_true_transitions_and_appends_marker(db_session):
    item = _make_awaiting_task(db_session)
    await db_session.commit()
    await db_session.refresh(item)
    task_id = str(item.id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            f"/api/tasks/{task_id}/resume",
            headers=ADMIN_HEADERS,
            json={"skip": True},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "running"
    assert "localStorage only" in body["description"]

    # Chat message appended.
    chat_rows = (await db_session.execute(
        select(ChatMessage).where(
            ChatMessage.slug == "foo-app",
            ChatMessage.role == "assistant",
        )
    )).scalars().all()
    assert any("frontend-only" in m.content for m in chat_rows)


async def test_resume_skip_false_without_link_returns_412(db_session):
    item = _make_awaiting_task(db_session)
    await db_session.commit()
    await db_session.refresh(item)
    task_id = str(item.id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            f"/api/tasks/{task_id}/resume",
            headers=ADMIN_HEADERS,
            json={"skip": False},
        )
    assert r.status_code == 412
    assert "not linked" in r.json()["detail"].lower()


async def test_resume_skip_false_with_link_kicks_off_build(db_session):
    item = _make_awaiting_task(db_session)
    db_session.add(ProjectSupabase(
        slug="foo-app",
        configured_by="ralph@aiui.com",
        linked_project_ref="abcdefghijklmno",
    ))
    await db_session.commit()
    await db_session.refresh(item)
    task_id = str(item.id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            f"/api/tasks/{task_id}/resume",
            headers=ADMIN_HEADERS,
            json={"skip": False},
        )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "running"

    chat_rows = (await db_session.execute(
        select(ChatMessage).where(
            ChatMessage.slug == "foo-app",
            ChatMessage.role == "assistant",
        )
    )).scalars().all()
    assert any("connected" in m.content.lower() for m in chat_rows)


async def test_resume_on_non_awaiting_task_returns_409(db_session):
    item = TaskItem(
        meeting_id=uuid.uuid4(),
        action_type="BUILD",
        assignee_name="Ralph",
        assignee_email="ralph@aiui.com",
        description="x",
        priority="IMPORTANT",
        status="pending",
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)
    task_id = str(item.id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            f"/api/tasks/{task_id}/resume",
            headers=ADMIN_HEADERS,
            json={"skip": True},
        )
    assert r.status_code == 409