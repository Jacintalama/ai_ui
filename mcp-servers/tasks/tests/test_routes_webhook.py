import os
import uuid

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from main import app
from models import TaskItem


async def test_webhook_creates_task_per_item(db_session, monkeypatch):
    monkeypatch.setenv("TASKS_ASSIGNEE_MAP", "ralph:ralph@x,lukas:lukas@x")
    mid = str(uuid.uuid4())
    payload = {
        "meeting_id": mid,
        "items": [
            {
                "action_type": "BUILD",
                "assignee": "Ralph Benitez",
                "description": "Fix routing",
                "priority": "CRITICAL",
            },
            {
                "action_type": "RESEARCH",
                "assignee": "Lukas",
                "description": "Compare X vs Y",
                "priority": "IMPORTANT",
            },
        ],
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/webhooks/meeting-action-items", json=payload)
        assert r.status_code == 201
        assert r.json()["created"] == 2

    rows = (await db_session.execute(select(TaskItem))).scalars().all()
    by_email = {r.assignee_email for r in rows}
    assert by_email == {"ralph@x", "lukas@x"}


async def test_webhook_idempotent_on_duplicate_post(db_session):
    mid = str(uuid.uuid4())
    payload = {
        "meeting_id": mid,
        "items": [
            {
                "action_type": "BUILD",
                "assignee": "team",
                "description": "Same task",
                "priority": "IMPORTANT",
            }
        ],
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r1 = await c.post("/webhooks/meeting-action-items", json=payload)
        r2 = await c.post("/webhooks/meeting-action-items", json=payload)
    assert r1.json()["created"] == 1
    assert r2.json()["created"] == 0
    rows = (await db_session.execute(select(TaskItem))).scalars().all()
    assert len(rows) == 1
