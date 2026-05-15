"""Test that Authorization: Bearer <jwt> from the HTTP request reaches executor.run().

The orchestrator extracts the JWT in the route handler and threads it through
_run_execution -> _stream_claude -> executor.run(user_jwt=...).  This test
verifies the full plumbing without a real DB run: the FakeExecutor captures
whatever user_jwt it receives so we can assert on it.
"""
import asyncio
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from main import app
from models import TaskItem

ADMIN = {"X-User-Email": "ralph@aiui.com", "X-User-Admin": "true"}


class _CapturingExecutor:
    """Fake executor that records the user_jwt it was called with."""

    def __init__(self):
        self.captured_jwt: str | None = _CapturingExecutor._sentinel

    # sentinel distinct from None so we can distinguish "not called" vs "called with None"
    _sentinel = object()

    async def run(self, prompt, slug=None, execution_id="", user_jwt=None):
        self.captured_jwt = user_jwt
        yield "COMPLETED: ok\n"

    async def stop(self):
        return None


@pytest.mark.asyncio
async def test_jwt_from_request_reaches_executor(db_session, monkeypatch):
    """When /execute receives Authorization: Bearer xyz the executor receives user_jwt='xyz'."""
    import routes_execution

    executor_instance = _CapturingExecutor()

    def _factory():
        return executor_instance

    monkeypatch.setattr(routes_execution, "get_executor", _factory)

    item = TaskItem(
        meeting_id=uuid.uuid4(),
        action_type="BUILD",
        assignee_name="Ralph",
        assignee_email="ralph@aiui.com",
        description="build something",
        priority="CRITICAL",
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)

    headers = {**ADMIN, "Authorization": "Bearer test-jwt-xyz"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(f"/api/tasks/{item.id}/execute", headers=headers)
    assert r.status_code == 200

    # Wait for background execution to finish
    for _ in range(50):
        await db_session.refresh(item)
        if item.status == "completed":
            break
        await asyncio.sleep(0.1)

    assert item.status == "completed", f"Task status: {item.status}"
    assert executor_instance.captured_jwt == "test-jwt-xyz", (
        f"Expected user_jwt='test-jwt-xyz', got {executor_instance.captured_jwt!r}"
    )


@pytest.mark.asyncio
async def test_no_auth_header_passes_none_jwt(db_session, monkeypatch):
    """When /execute has no Authorization header the executor receives user_jwt=None (not missing)."""
    import routes_execution

    executor_instance = _CapturingExecutor()

    def _factory():
        return executor_instance

    monkeypatch.setattr(routes_execution, "get_executor", _factory)

    item = TaskItem(
        meeting_id=uuid.uuid4(),
        action_type="BUILD",
        assignee_name="Ralph",
        assignee_email="ralph@aiui.com",
        description="build something",
        priority="CRITICAL",
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)

    # No Authorization header — existing behavior must be preserved
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(f"/api/tasks/{item.id}/execute", headers=ADMIN)
    assert r.status_code == 200

    for _ in range(50):
        await db_session.refresh(item)
        if item.status == "completed":
            break
        await asyncio.sleep(0.1)

    assert item.status == "completed", f"Task status: {item.status}"
    assert executor_instance.captured_jwt is None, (
        f"Expected user_jwt=None, got {executor_instance.captured_jwt!r}"
    )
