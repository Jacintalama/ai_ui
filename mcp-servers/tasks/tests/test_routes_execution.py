import asyncio
import uuid

from httpx import ASGITransport, AsyncClient

from main import app
from models import TaskItem

ADMIN = {"X-User-Email": "ralph@aiui.com", "X-User-Admin": "true"}


async def _fake_completed(prompt):
    yield "Read Caddyfile\n"
    yield "COMPLETED: Updated and reloaded.\n"


async def _fake_needs_input(prompt):
    yield "NEEDS_INPUT: What is the API key?\n"


async def test_execute_completed_path(db_session, monkeypatch):
    import claude_executor
    import routes_execution

    monkeypatch.setattr(claude_executor, "run_claude_subprocess", _fake_completed)
    monkeypatch.setattr(routes_execution, "run_claude_subprocess", _fake_completed)
    item = TaskItem(
        meeting_id=uuid.uuid4(),
        action_type="BUILD",
        assignee_name="Ralph",
        assignee_email="ralph@aiui.com",
        description="d",
        priority="CRITICAL",
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(f"/api/tasks/{item.id}/execute", headers=ADMIN)
    assert r.status_code == 200
    for _ in range(50):
        await db_session.refresh(item)
        if item.status == "completed":
            break
        await asyncio.sleep(0.1)
    assert item.status == "completed"
    assert "Updated and reloaded" in (item.result or "")


async def test_execute_needs_input_path(db_session, monkeypatch):
    import claude_executor
    import routes_execution

    monkeypatch.setattr(claude_executor, "run_claude_subprocess", _fake_needs_input)
    monkeypatch.setattr(routes_execution, "run_claude_subprocess", _fake_needs_input)
    item = TaskItem(
        meeting_id=uuid.uuid4(),
        action_type="INTEGRATE",
        assignee_name="Ralph",
        assignee_email="ralph@aiui.com",
        description="d",
        priority="IMPORTANT",
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        await c.post(f"/api/tasks/{item.id}/execute", headers=ADMIN)
    for _ in range(50):
        await db_session.refresh(item)
        if item.status == "awaiting_input":
            break
        await asyncio.sleep(0.1)
    assert item.status == "awaiting_input"
    assert "API key" in (item.result or "")
