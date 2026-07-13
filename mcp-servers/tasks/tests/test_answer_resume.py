"""DB-tier: POST /api/tasks/{id}/answer resumes a paused one-shot build with
the FULL conversation context (the previously-untested path behind bug #2).

Runs in-container against aiui_test. Monkeypatches _run_execution to capture the
resume prompt instead of spawning the real agent.
"""
from cryptography.fernet import Fernet as _Fernet
_AIUI_TEST_KEY = _Fernet.generate_key().decode()

import os

os.environ.setdefault("AIUI_FERNET_KEY", _AIUI_TEST_KEY)

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from main import app
import routes_execution
from models import TaskExecution, TaskItem


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

    prompt = _capture_prompt["prompt"]
    assert prompt, "resume prompt was not captured"
    assert "dark, teal accents" in prompt   # earlier round retained (the bug)
    assert "three pages" in prompt          # latest answer
    assert "apps/portfolio-a1/" in prompt   # continue the existing app
    assert "restart" in prompt.lower()
    assert "build a portfolio site" in prompt  # original request/build context
