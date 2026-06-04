"""User-scoped publish endpoint POST /api/aiuibuilder/{slug}/publish.

DB-backed (needs Postgres + the db_session fixture). Mirrors
test_publish_access_gate.py's harness.
"""
from cryptography.fernet import Fernet as _Fernet
_AIUI_TEST_KEY = _Fernet.generate_key().decode()

import os
os.environ.setdefault("AIUI_FERNET_KEY", _AIUI_TEST_KEY)

import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

import routes_projects
from main import app
from models import PublishedApp, TaskItem


@pytest.fixture
def transport():
    return ASGITransport(app=app)


def _stage_app(tmp_path, slug):
    d = tmp_path / "apps" / slug
    d.mkdir(parents=True)
    (d / "index.html").write_text("<html><body>app</body></html>")


async def _make_owner_task(db_session, slug, email):
    """Insert a completed BUILD task so `email` is the implicit owner of slug."""
    db_session.add(TaskItem(
        meeting_id=uuid.uuid4(), action_type="BUILD",
        assignee_name=email.split("@")[0], assignee_email=email,
        description="x", priority="NICE_TO_HAVE", status="completed",
        mode="ai", max_attempts=3, built_app_slug=slug,
    ))
    await db_session.commit()


async def test_owner_can_publish(db_session, transport, tmp_path, monkeypatch):
    monkeypatch.setattr(routes_projects, "REPO_ROOT", str(tmp_path))
    _stage_app(tmp_path, "alpha")
    await _make_owner_task(db_session, "alpha", "alice@x.com")

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/aiuibuilder/alpha/publish",
                         headers={"X-User-Email": "alice@x.com"})
    assert r.status_code == 200
    body = r.json()
    assert body["published"] is True
    assert body["public_url"] == "https://ai-ui.coolestdomain.win/apps/alpha/"
    row = (await db_session.execute(
        select(PublishedApp).where(PublishedApp.slug == "alpha")
    )).scalar_one_or_none()
    assert row is not None


async def test_non_owner_rejected(db_session, transport, tmp_path, monkeypatch):
    monkeypatch.setattr(routes_projects, "REPO_ROOT", str(tmp_path))
    _stage_app(tmp_path, "alpha")
    await _make_owner_task(db_session, "alpha", "alice@x.com")

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/aiuibuilder/alpha/publish",
                         headers={"X-User-Email": "mallory@x.com"})
    assert r.status_code == 403
    assert "alpha.ai-ui" not in r.text


async def test_missing_index_html_400(db_session, transport, tmp_path, monkeypatch):
    monkeypatch.setattr(routes_projects, "REPO_ROOT", str(tmp_path))
    await _make_owner_task(db_session, "alpha", "alice@x.com")

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/aiuibuilder/alpha/publish",
                         headers={"X-User-Email": "alice@x.com"})
    assert r.status_code == 400


async def test_publish_is_idempotent(db_session, transport, tmp_path, monkeypatch):
    monkeypatch.setattr(routes_projects, "REPO_ROOT", str(tmp_path))
    _stage_app(tmp_path, "alpha")
    await _make_owner_task(db_session, "alpha", "alice@x.com")

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r1 = await c.post("/api/aiuibuilder/alpha/publish", headers={"X-User-Email": "alice@x.com"})
        r2 = await c.post("/api/aiuibuilder/alpha/publish", headers={"X-User-Email": "alice@x.com"})
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["public_url"] == r2.json()["public_url"]
