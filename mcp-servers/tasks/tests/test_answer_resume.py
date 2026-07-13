"""DB-tier: POST /api/tasks/{id}/answer resumes a paused one-shot build with
the FULL conversation context (the previously-untested path behind bug #2).

Runs in-container against aiui_test. Monkeypatches _run_execution to capture the
resume prompt instead of spawning the real agent.
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
from models import ProjectMember, TaskExecution, TaskItem


ADMIN_HEADERS = {"X-User-Email": "ralph@aiui.com", "X-User-Admin": "true"}


@pytest.fixture
def _capture_prompt(monkeypatch):
    captured = {}

    async def _capture(task_id, exec_id, prompt, *a, **k):
        captured["prompt"] = prompt
        return None

    monkeypatch.setattr(routes_execution, "_run_execution", _capture)
    return captured


async def test_answer_resumes_one_shot_build_with_full_context(db_session, _capture_prompt):
    item = TaskItem(
        meeting_id=uuid.uuid4(),
        action_type="BUILD",
        assignee_name="Ralph",
        assignee_email="ralph@aiui.com",
        description="<rules>\n\nUSER REQUEST:\nbuild a portfolio site",
        priority="IMPORTANT",
        status="awaiting_input",
        max_attempts=1,  # one-shot — the branch that used to drop context
        built_app_slug="portfolio-a1",
        conversation_history=[
            {"role": "ai", "content": "What colour scheme?"},
            {"role": "admin", "content": "dark, teal accents"},
            {"role": "ai", "content": "How many pages?"},
        ],
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)
    task_id = str(item.id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            f"/api/tasks/{task_id}/answer",
            headers=ADMIN_HEADERS,
            json={"answer": "three pages"},
        )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "running"

    # a new execution row was created for the resume
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
    assert "dark, teal accents" in prompt   # earlier round retained (the bug)
    assert "three pages" in prompt          # latest answer
    assert "apps/portfolio-a1/" in prompt   # continue the existing app
    assert "restart" in prompt.lower()
    assert "build a portfolio site" in prompt  # original request/build context


async def test_execute_from_awaiting_input_preserves_conversation(db_session, _capture_prompt):
    # Resuming via /execute (not /answer) must not drop the clarification the
    # user already gave — it used to fall through to a bare build_prompt.
    item = TaskItem(
        meeting_id=uuid.uuid4(),
        action_type="BUILD",
        assignee_name="Ralph",
        assignee_email="ralph@aiui.com",
        description="<rules>\n\nUSER REQUEST:\nbuild a landing page",
        priority="IMPORTANT",
        status="awaiting_input",
        max_attempts=1,
        built_app_slug="landing-a1",
        conversation_history=[
            {"role": "ai", "content": "What tone?"},
            {"role": "admin", "content": "playful and bold"},
        ],
    )
    db_session.add(item)
    db_session.add(ProjectMember(
        slug="landing-a1", user_email="ralph@aiui.com", role="owner", added_by="ralph@aiui.com",
    ))
    await db_session.commit()
    await db_session.refresh(item)
    task_id = str(item.id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(f"/api/tasks/{task_id}/execute", headers=ADMIN_HEADERS)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "running"

    # _run_execution runs as a background task, so give it a tick to populate.
    for _ in range(20):
        if _capture_prompt.get("prompt"):
            break
        await asyncio.sleep(0.01)
    prompt = _capture_prompt.get("prompt")
    assert prompt, "resume prompt was not captured"
    assert "playful and bold" in prompt      # conversation retained (the bug)
    assert "apps/landing-a1/" in prompt      # continue the existing app
    assert "build a landing page" in prompt
