"""Tests for the chat-driven Supabase connect gate in POST /api/tasks.

Three scenarios:
  1. Supabase-required template + storage="supabase" + slug + no link →
     status="awaiting_supabase" + a [ACTION:supabase_connect] chat row.
  2. Same setup BUT a project_supabase row already has linked_project_ref →
     status="pending" (no gate, build kicks off normally).
  3. Static template (storage="none") → status="pending" regardless.
"""
from cryptography.fernet import Fernet as _Fernet
_AIUI_TEST_KEY = _Fernet.generate_key().decode()

import os
import uuid

os.environ.setdefault("AIUI_FERNET_KEY", _AIUI_TEST_KEY)

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from main import app
from models import ChatMessage, ProjectSupabase


ADMIN_HEADERS = {"X-User-Email": "ralph@aiui.com", "X-User-Admin": "true"}


async def test_build_with_supabase_template_and_no_link_gates_on_supabase(db_session):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/api/tasks",
            headers=ADMIN_HEADERS,
            json={
                "description": "Invoice editor for a freelance designer.",
                "action_type": "BUILD",
                "priority": "IMPORTANT",
                "assignee": "self",
                "template_key": "invoice",
                "storage": "supabase",
                "slug": "foo-app",
            },
        )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "awaiting_supabase"
    assert body["built_app_slug"] == "foo-app"

    # Chat message seeded with the [ACTION:supabase_connect] sentinel.
    rows = (await db_session.execute(
        select(ChatMessage).where(
            ChatMessage.slug == "foo-app",
            ChatMessage.user_email == "ralph@aiui.com",
        )
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].role == "assistant"
    assert rows[0].content.startswith("[ACTION:supabase_connect]")


async def test_build_with_supabase_template_and_existing_link_does_not_gate(db_session):
    db_session.add(ProjectSupabase(
        slug="foo-app",
        configured_by="ralph@aiui.com",
        linked_project_ref="abcdefghijklmno",
    ))
    await db_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/api/tasks",
            headers=ADMIN_HEADERS,
            json={
                "description": "Invoice editor for a freelance designer.",
                "action_type": "BUILD",
                "priority": "IMPORTANT",
                "assignee": "self",
                "template_key": "invoice",
                "storage": "supabase",
                "slug": "foo-app",
            },
        )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "pending"

    # No assistant chat message should have been written.
    rows = (await db_session.execute(
        select(ChatMessage).where(
            ChatMessage.slug == "foo-app",
            ChatMessage.role == "assistant",
        )
    )).scalars().all()
    assert rows == []


async def test_build_with_static_template_does_not_gate(db_session):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/api/tasks",
            headers=ADMIN_HEADERS,
            json={
                "description": "Landing page for a coffee shop.",
                "action_type": "BUILD",
                "priority": "IMPORTANT",
                "assignee": "self",
                "template_key": "landing",
                "storage": "none",
                "slug": "bean-there",
            },
        )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "pending"

    rows = (await db_session.execute(
        select(ChatMessage).where(ChatMessage.slug == "bean-there")
    )).scalars().all()
    assert rows == []


async def test_build_with_supabase_template_but_user_picked_none_does_not_gate(db_session):
    """User explicitly chose `storage=none` even on a DB-leaning template —
    they want the localStorage version. No gate."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/api/tasks",
            headers=ADMIN_HEADERS,
            json={
                "description": "Invoice editor.",
                "action_type": "BUILD",
                "priority": "IMPORTANT",
                "assignee": "self",
                "template_key": "invoice",
                "storage": "none",
                "slug": "ls-invoice",
            },
        )
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "pending"