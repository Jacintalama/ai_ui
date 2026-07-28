import uuid
from httpx import ASGITransport, AsyncClient
from main import app
from models import TaskItem

HDR = {"X-User-Email": "ralph@aiui.com", "X-User-Admin": "true"}


def _make_done_task(*, slug, email="ralph@aiui.com", description="x"):
    return TaskItem(
        meeting_id=uuid.uuid4(),
        action_type="BUILD",
        assignee_name="Ralph",
        assignee_email=email,
        description=description,
        priority="NICE_TO_HAVE",
        status="completed",
        built_app_slug=slug,
    )


async def test_list_tasks_filters_by_slug(db_session):
    """When ?slug=alpha is passed, only tasks with that slug come back."""
    db_session.add(_make_done_task(slug="alpha", description="alpha task"))
    db_session.add(_make_done_task(slug="beta", description="beta task"))
    await db_session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/tasks?status=done&slug=alpha", headers=HDR)
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["built_app_slug"] == "alpha"
    assert body[0]["description"] == "alpha task"


async def test_list_tasks_no_slug_returns_all(db_session):
    """No ?slug= filter returns all matching status."""
    db_session.add(_make_done_task(slug="alpha"))
    db_session.add(_make_done_task(slug="beta"))
    await db_session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/tasks?status=done", headers=HDR)
    assert r.status_code == 200
    assert len(r.json()) == 2


async def test_list_tasks_unknown_slug_returns_empty(db_session):
    """?slug= that matches nothing returns [] (no error)."""
    db_session.add(_make_done_task(slug="alpha"))
    await db_session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/tasks?status=done&slug=nonexistent", headers=HDR)
    assert r.status_code == 200
    assert r.json() == []


async def test_is_project_hides_sched_artifacts_keeps_real_and_slugless(db_session):
    """The app-builder page (is_project=true) must not show sched-* schedule
    runs; real apps and not-yet-slugged builds stay visible."""
    db_session.add(_make_done_task(slug="my-real-app", description="real app"))
    db_session.add(_make_done_task(slug="sched-abc12345", description="schedule run"))
    db_session.add(_make_done_task(slug=None, description="queued build no slug"))
    await db_session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/tasks?is_project=true&limit=200", headers=HDR)
    assert r.status_code == 200
    slugs = [t["built_app_slug"] for t in r.json()]
    assert "my-real-app" in slugs
    assert None in slugs                      # slugless build still listed
    assert "sched-abc12345" not in slugs      # schedule artifact hidden
