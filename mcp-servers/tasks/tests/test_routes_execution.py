import asyncio
import uuid

from httpx import ASGITransport, AsyncClient

from main import app
from models import TaskItem

ADMIN = {"X-User-Email": "ralph@aiui.com", "X-User-Admin": "true"}


class _FakeExecutor:
    """Stand-in for BaseExecutor that yields a scripted output stream.

    Mirrors the LocalExecutor / RemoteExecutor signature exactly so the
    routes_execution._stream_claude orchestrator can drive it without
    knowing it's a stub.
    """

    def __init__(self, chunks):
        self._chunks = list(chunks)

    async def run(self, prompt, slug=None, execution_id="", user_jwt=None):
        for c in self._chunks:
            yield c

    async def stop(self):
        return None


def _fake_completed_executor():
    return _FakeExecutor([
        "Read Caddyfile\n",
        "COMPLETED: Updated and reloaded.\n",
    ])


def _fake_needs_input_executor():
    return _FakeExecutor([
        "NEEDS_INPUT: What is the API key?\n",
    ])


async def test_execute_completed_path(db_session, monkeypatch):
    import routes_execution

    monkeypatch.setattr(routes_execution, "get_executor", _fake_completed_executor)
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
    import routes_execution

    monkeypatch.setattr(routes_execution, "get_executor", _fake_needs_input_executor)
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
