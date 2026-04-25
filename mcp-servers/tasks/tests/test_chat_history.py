"""Tests for chat history endpoints."""
import os
import uuid

os.environ.setdefault("AIUI_FERNET_KEY", "v3KGZ9ZpQAQ-HeaR_R-nXvI3T8cPOFYYJQHe3VJYJpw=")

import pytest
from httpx import ASGITransport, AsyncClient

from main import app
from models import ChatMessage, ProjectMember, TaskItem

OWNER_HDR = {"X-User-Email": "ralph@aiui.com", "X-User-Admin": "true"}
BOB_HDR   = {"X-User-Email": "bob@aiui.com",   "X-User-Admin": "true"}


@pytest.fixture
def transport():
    return ASGITransport(app=app)


def _setup_member(db_session, slug="alpha", email="ralph@aiui.com", role="owner"):
    db_session.add(TaskItem(
        meeting_id=uuid.uuid4(), action_type="BUILD",
        assignee_name="X", assignee_email=email,
        description="x", priority="IMPORTANT", status="completed",
        built_app_slug=slug,
    ))
    db_session.add(ProjectMember(slug=slug, user_email=email, role=role,
                                  added_by=email))


async def test_get_chat_returns_empty_list_for_new_project(db_session, transport):
    _setup_member(db_session)
    await db_session.commit()
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/projects/alpha/chat", headers=OWNER_HDR)
    assert r.status_code == 200
    assert r.json() == []


async def test_post_then_get_returns_message_in_order(db_session, transport):
    _setup_member(db_session)
    await db_session.commit()
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/projects/alpha/chat", headers=OWNER_HDR,
                         json={"role": "user", "content": "hello"})
        assert r.status_code == 201
        r = await c.post("/api/projects/alpha/chat", headers=OWNER_HDR,
                         json={"role": "assistant", "content": "hi back"})
        assert r.status_code == 201

        r = await c.get("/api/projects/alpha/chat", headers=OWNER_HDR)
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) == 2
        assert rows[0]["role"] == "user" and rows[0]["content"] == "hello"
        assert rows[1]["role"] == "assistant" and rows[1]["content"] == "hi back"


async def test_chat_history_isolated_per_user(db_session, transport):
    _setup_member(db_session, email="ralph@aiui.com")
    _setup_member(db_session, email="bob@aiui.com", role="editor")
    await db_session.commit()
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/projects/alpha/chat", headers=OWNER_HDR,
                     json={"role": "user", "content": "ralph msg"})
        await c.post("/api/projects/alpha/chat", headers=BOB_HDR,
                     json={"role": "user", "content": "bob msg"})

        rr = await c.get("/api/projects/alpha/chat", headers=OWNER_HDR)
        assert len(rr.json()) == 1
        assert rr.json()[0]["content"] == "ralph msg"

        rb = await c.get("/api/projects/alpha/chat", headers=BOB_HDR)
        assert len(rb.json()) == 1
        assert rb.json()[0]["content"] == "bob msg"


async def test_non_member_get_chat_403(db_session, transport):
    _setup_member(db_session, email="ralph@aiui.com")
    await db_session.commit()
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/projects/alpha/chat",
                        headers={"X-User-Email": "stranger@aiui.com",
                                 "X-User-Admin": "true"})
    assert r.status_code == 403


async def test_post_invalid_role_400(db_session, transport):
    _setup_member(db_session)
    await db_session.commit()
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/projects/alpha/chat", headers=OWNER_HDR,
                         json={"role": "BADROLE", "content": "x"})
    assert r.status_code == 422  # Pydantic enum reject
