import uuid

from httpx import ASGITransport, AsyncClient

from main import app
from models import TaskItem

ADMIN_HEADERS = {"X-User-Email": "ralph@aiui.com", "X-User-Admin": "true"}


def _make_task(
    *,
    action_type="BUILD",
    status="completed",
    built_app_slug="meeting-notes",
    assignee_email="ralph@aiui.com",
):
    return TaskItem(
        meeting_id=uuid.uuid4(),
        action_type=action_type,
        assignee_name="Ralph",
        assignee_email=assignee_email,
        description="seed",
        priority="NICE_TO_HAVE",
        status=status,
        built_app_slug=built_app_slug,
    )


async def test_enhance_rejects_missing_source(db_session):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/api/tasks/enhance",
            headers=ADMIN_HEADERS,
            json={"source_task_id": str(uuid.uuid4()), "prompt": "x"},
        )
    assert r.status_code == 404


async def test_enhance_rejects_research_source(db_session):
    t = _make_task(action_type="RESEARCH", built_app_slug=None)
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/api/tasks/enhance",
            headers=ADMIN_HEADERS,
            json={"source_task_id": str(t.id), "prompt": "x"},
        )
    assert r.status_code == 400
    assert "BUILD" in r.json()["detail"]


async def test_enhance_rejects_source_without_slug(db_session):
    t = _make_task(built_app_slug=None)
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/api/tasks/enhance",
            headers=ADMIN_HEADERS,
            json={"source_task_id": str(t.id), "prompt": "x"},
        )
    assert r.status_code == 400


async def test_enhance_returns_202_and_new_task(db_session):
    source = _make_task()
    db_session.add(source)
    await db_session.commit()
    await db_session.refresh(source)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/api/tasks/enhance",
            headers=ADMIN_HEADERS,
            json={"source_task_id": str(source.id), "prompt": "add feature X"},
        )
    assert r.status_code == 202
    body = r.json()
    assert body["id"] != str(source.id)
    assert body["action_type"] == "BUILD"
    assert body["built_app_slug"] == "meeting-notes"
    assert body["plan_status"] == "approved"
    assert "add feature X" in body["description"]


async def test_enhance_rejects_concurrent(db_session):
    source = _make_task()
    in_flight = _make_task(status="running", built_app_slug="meeting-notes")
    db_session.add(source)
    db_session.add(in_flight)
    await db_session.commit()
    await db_session.refresh(source)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/api/tasks/enhance",
            headers=ADMIN_HEADERS,
            json={"source_task_id": str(source.id), "prompt": "x"},
        )
    assert r.status_code == 409


async def test_enhance_requires_auth(db_session):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/api/tasks/enhance",
            json={"source_task_id": str(uuid.uuid4()), "prompt": "x"},
        )
    # auth module returns 401 when headers missing
    assert r.status_code in (401, 403)


async def test_enhance_concurrent_one_succeeds(db_session):
    """Bug C: two parallel /enhance calls for the same slug must not both
    create new running tasks — exactly one wins, the other gets 409."""
    import asyncio

    source = _make_task()
    db_session.add(source)
    await db_session.commit()
    await db_session.refresh(source)

    async def _fire():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            return await c.post(
                "/api/tasks/enhance",
                headers=ADMIN_HEADERS,
                json={"source_task_id": str(source.id), "prompt": "concurrent"},
            )

    results = await asyncio.gather(_fire(), _fire())
    statuses = sorted(r.status_code for r in results)
    assert statuses == [202, 409], f"expected one 202 + one 409, got {statuses}"
    losers = [r for r in results if r.status_code == 409]
    assert "in progress" in losers[0].json()["detail"].lower()
