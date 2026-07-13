"""DB-tier: user-scoped POST /api/aiuibuilder/build/{id}/answer resumes a paused
build (the Discord/Slack/Voice answer path). Runs in-container against aiui_test.
"""
from cryptography.fernet import Fernet as _Fernet
_AIUI_TEST_KEY = _Fernet.generate_key().decode()

import os

os.environ.setdefault("AIUI_FERNET_KEY", _AIUI_TEST_KEY)

import asyncio
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from main import app
import routes_execution
from models import TaskExecution, TaskItem


HEADERS = {"X-User-Email": "alice@x.com"}


@pytest.fixture
def _capture_prompt(monkeypatch):
    captured = {}

    async def _capture(task_id, exec_id, prompt, *a, **k):
        captured["prompt"] = prompt
        return None

    monkeypatch.setattr(routes_execution, "_run_execution", _capture)
    return captured


def _paused_build(assignee="alice@x.com", slug="disc-a1"):
    return TaskItem(
        meeting_id=uuid.uuid4(),
        action_type="BUILD",
        assignee_name=assignee.split("@")[0],
        assignee_email=assignee,
        description='PROJECT NAME: "disc-a1".\n\nUSER REQUEST:\nbuild a quiz app',
        priority="NICE_TO_HAVE",
        status="awaiting_input",
        max_attempts=3,
        built_app_slug=slug,
        result="Which subject should the quiz cover?",
        conversation_history=[{"role": "ai", "content": "Which subject should the quiz cover?"}],
    )


async def test_answer_build_resumes_paused_build(db_session, _capture_prompt):
    item = _paused_build()
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            f"/api/aiuibuilder/build/{item.id}/answer",
            headers=HEADERS,
            json={"answer": "world capitals"},
        )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "running"

    execs = (await db_session.execute(
        select(TaskExecution).where(TaskExecution.task_id == item.id)
    )).scalars().all()
    assert len(execs) >= 1

    # _run_execution runs as a background task, so give it a tick to populate.
    for _ in range(20):
        if _capture_prompt.get("prompt"):
            break
        await asyncio.sleep(0.01)
    prompt = _capture_prompt.get("prompt")
    assert prompt, "resume prompt was not captured"
    assert "world capitals" in prompt          # the answer is replayed
    assert "apps/disc-a1/" in prompt           # continue the existing app
    assert "build a quiz app" in prompt        # original request/build context


async def test_answer_build_requires_email():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            f"/api/aiuibuilder/build/{uuid.uuid4()}/answer",
            json={"answer": "x"},
        )
    assert r.status_code == 401


async def test_answer_build_not_awaiting_returns_409(db_session, _capture_prompt):
    item = _paused_build()
    item.status = "running"
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            f"/api/aiuibuilder/build/{item.id}/answer",
            headers=HEADERS,
            json={"answer": "x"},
        )
    assert r.status_code == 409


async def test_answer_build_other_user_404(db_session, _capture_prompt):
    item = _paused_build(assignee="bob@x.com", slug="bob-a1")
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            f"/api/aiuibuilder/build/{item.id}/answer",
            headers=HEADERS,  # alice answering bob's build
            json={"answer": "x"},
        )
    assert r.status_code == 404


async def test_answer_build_blocked_when_another_build_live(db_session, _capture_prompt):
    paused = _paused_build(slug="mine-a1")
    other = _paused_build(assignee="carol@x.com", slug="other-a1")
    other.status = "running"  # someone else's live build holds the slot
    db_session.add(paused)
    db_session.add(other)
    await db_session.commit()
    await db_session.refresh(paused)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            f"/api/aiuibuilder/build/{paused.id}/answer",
            headers=HEADERS,
            json={"answer": "x"},
        )
    assert r.status_code == 429
