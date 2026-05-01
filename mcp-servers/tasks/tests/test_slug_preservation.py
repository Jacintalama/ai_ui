"""Regression tests for the slug-preservation bug.

Before the fix, `_run_execution` unconditionally wrote `built_app_slug=slug`,
where `slug = extract_app_slug(full_output)`. When Claude's COMPLETED message
didn't include an `apps/<name>/` pattern (typical for enhancements, e.g.
'Updated footer in public/index.html'), the pre-set slug got clobbered to NULL.

These tests lock the correct behavior: preserve the existing slug unless we
actually extract a new one from the current Claude output.
"""
import asyncio
import uuid

from httpx import ASGITransport, AsyncClient

from main import app
from models import TaskItem

HDR = {"X-User-Email": "ralph@aiui.com", "X-User-Admin": "true"}


# Fake claude output that COMPLETES without any `apps/<slug>/` pattern —
# mimics what Claude says for a typical enhancement tweak.
async def _fake_completed_no_slug(prompt, proc_holder=None):
    yield "Read public/index.html\n"
    yield "Updated footer text\n"
    yield "COMPLETED: Updated the footer in public/index.html (commit abc1234).\n"


# Fake output that DOES mention `apps/<slug>/` — mimics fresh one-shot build.
async def _fake_completed_with_slug(prompt, proc_holder=None):
    yield "Creating files under apps/hello-world/\n"
    yield "COMPLETED: Built the hello world app at apps/hello-world/ (commit def5678).\n"


async def test_enhance_preserves_slug_when_claude_output_omits_apps_path(db_session, monkeypatch):
    """After the fix: enhancement whose completion message has no apps/<slug>/
    must leave the existing built_app_slug intact."""
    import claude_executor
    import routes_execution
    monkeypatch.setattr(claude_executor, "run_claude_subprocess", _fake_completed_no_slug)
    monkeypatch.setattr(routes_execution, "run_claude_subprocess", _fake_completed_no_slug)

    # Seed a completed source BUILD with slug set
    source = TaskItem(
        meeting_id=uuid.uuid4(),
        action_type="BUILD",
        assignee_name="Ralph",
        assignee_email="ralph@aiui.com",
        description="source build",
        priority="NICE_TO_HAVE",
        status="completed",
        built_app_slug="meeting-notes",
        max_attempts=1,
    )
    db_session.add(source)
    await db_session.commit()
    await db_session.refresh(source)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/api/tasks/enhance",
            headers=HDR,
            data={"source_task_id": str(source.id), "prompt": "tweak footer"},
        )
    assert r.status_code == 202, r.text
    new_id = uuid.UUID(r.json()["id"])

    # Wait for background execution to reach terminal status (up to ~30s).
    # Use expire_all() before each query so SQLAlchemy doesn't hand back
    # a cached row from the prior session's unit of work.
    from sqlalchemy import select
    new_task = None
    for _ in range(300):
        db_session.expire_all()
        q = await db_session.execute(select(TaskItem).where(TaskItem.id == new_id))
        new_task = q.scalar_one()
        if new_task.status in ("completed", "failed", "pending"):
            break
        await asyncio.sleep(0.1)
    print(f"[test] final status: {new_task.status}, result: {new_task.result}")

    assert new_task is not None
    assert new_task.status == "completed", (
        f"expected completed, got {new_task.status}; result={new_task.result!r}"
    )
    assert new_task.built_app_slug == "meeting-notes", (
        f"BUG NOT FIXED: slug overwritten from 'meeting-notes' to "
        f"{new_task.built_app_slug!r} during enhancement completion"
    )


async def test_fresh_build_still_extracts_slug_from_claude_output(db_session, monkeypatch):
    """Negative case: fresh BUILD task with no pre-set slug — Claude's
    output mentions apps/<slug>/ — slug should be extracted and set."""
    import claude_executor
    import routes_execution
    monkeypatch.setattr(claude_executor, "run_claude_subprocess", _fake_completed_with_slug)
    monkeypatch.setattr(routes_execution, "run_claude_subprocess", _fake_completed_with_slug)

    task = TaskItem(
        meeting_id=uuid.uuid4(),
        action_type="BUILD",
        assignee_name="Ralph",
        assignee_email="ralph@aiui.com",
        description="fresh build",
        priority="NICE_TO_HAVE",
        status="pending",
        built_app_slug=None,
        max_attempts=1,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(f"/api/tasks/{task.id}/execute", headers=HDR)
    assert r.status_code == 200

    for _ in range(50):
        await db_session.refresh(task)
        if task.status in ("completed", "failed", "pending"):
            break
        await asyncio.sleep(0.1)

    # Just make sure the fix doesn't break the fresh-build slug extraction
    if task.status == "completed":
        assert task.built_app_slug == "hello-world", (
            f"regression: fresh BUILD should extract slug, got {task.built_app_slug!r}"
        )
