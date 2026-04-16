import uuid

from httpx import ASGITransport, AsyncClient

from main import app
from models import TaskItem

ADMIN_HEADERS = {"X-User-Email": "ralph@aiui.com", "X-User-Admin": "true"}


async def test_list_returns_only_pending_for_current_admin(db_session):
    db_session.add(
        TaskItem(
            meeting_id=uuid.uuid4(),
            action_type="BUILD",
            assignee_name="Ralph",
            assignee_email="ralph@aiui.com",
            description="mine",
            priority="CRITICAL",
        )
    )
    db_session.add(
        TaskItem(
            meeting_id=uuid.uuid4(),
            action_type="BUILD",
            assignee_name="Lukas",
            assignee_email="lukas@aiui.com",
            description="not mine",
            priority="CRITICAL",
        )
    )
    await db_session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/tasks?status=pending", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    descs = [t["description"] for t in r.json()]
    assert descs == ["mine"]


async def test_manual_transition(db_session):
    item = TaskItem(
        meeting_id=uuid.uuid4(),
        action_type="BUILD",
        assignee_name="Ralph",
        assignee_email="ralph@aiui.com",
        description="d",
        priority="IMPORTANT",
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(f"/api/tasks/{item.id}/manual", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    assert r.json()["status"] == "claimed_manual"
    assert r.json()["mode"] == "manual"


async def test_complete_sets_result_and_timestamp(db_session):
    item = TaskItem(
        meeting_id=uuid.uuid4(),
        action_type="BUILD",
        assignee_name="Ralph",
        assignee_email="ralph@aiui.com",
        description="d",
        priority="IMPORTANT",
        status="claimed_manual",
        mode="manual",
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            f"/api/tasks/{item.id}/complete",
            json={"result": "Done it"},
            headers=ADMIN_HEADERS,
        )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "completed"
    assert body["result"] == "Done it"
    assert body["completed_at"] is not None


async def test_history_returns_completed_paginated(db_session):
    for i in range(3):
        db_session.add(
            TaskItem(
                meeting_id=uuid.uuid4(),
                action_type="BUILD",
                assignee_name="Ralph",
                assignee_email="ralph@aiui.com",
                description=f"item-{i}",
                priority="IMPORTANT",
                status="completed",
                mode="ai",
            )
        )
    await db_session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/tasks/history?limit=2", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    assert len(r.json()) == 2


async def test_ask_user_answer_completes_task(db_session):
    item = TaskItem(
        meeting_id=uuid.uuid4(),
        action_type="ASK_USER",
        assignee_name="Ralph",
        assignee_email="ralph@aiui.com",
        description="Confirm preference",
        priority="IMPORTANT",
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            f"/api/tasks/{item.id}/answer",
            json={"answer": "Use Gemini"},
            headers=ADMIN_HEADERS,
        )
    assert r.status_code == 200
    assert r.json()["status"] == "completed"
    assert r.json()["result"] == "Use Gemini"
