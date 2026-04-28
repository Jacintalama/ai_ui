"""Tests for the Supabase OAuth auto-link + create-project endpoints (Phase A)."""
from cryptography.fernet import Fernet as _Fernet
_AIUI_TEST_KEY = _Fernet.generate_key().decode()

import os
import uuid
from datetime import datetime, timedelta, timezone

os.environ.setdefault("AIUI_FERNET_KEY", _AIUI_TEST_KEY)

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

import crypto_utils
from main import app
from models import ProjectMember, ProjectSupabase, TaskItem


OWNER_HDR = {"X-User-Email": "ralph@aiui.com", "X-User-Admin": "true"}


@pytest.fixture
def transport():
    return ASGITransport(app=app)


def _seed_owner(db_session, slug: str = "alpha") -> None:
    db_session.add(TaskItem(
        meeting_id=uuid.uuid4(), action_type="BUILD",
        assignee_name="Ralph", assignee_email="ralph@aiui.com",
        description="x", priority="IMPORTANT", status="completed",
        built_app_slug=slug,
    ))
    db_session.add(ProjectMember(
        slug=slug, user_email="ralph@aiui.com",
        role="owner", added_by="ralph@aiui.com",
    ))


def _seed_oauth_row(db_session, slug: str = "alpha") -> None:
    db_session.add(ProjectSupabase(
        slug=slug,
        configured_by="ralph@aiui.com",
        oauth_access_token_encrypted=crypto_utils.encrypt("fake-access-token"),
        oauth_refresh_token_encrypted=crypto_utils.encrypt("fake-refresh-token"),
        oauth_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    ))


class _FakeResponse:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = "" if isinstance(payload, (dict, list)) else str(payload)

    def json(self) -> object:
        return self._payload


def _install_httpx_mock(monkeypatch, routes: dict) -> list[tuple[str, str]]:
    """Replace httpx.AsyncClient with a stub whose .get/.post look up `routes`.

    `routes` maps (METHOD, url) -> _FakeResponse.
    Returns a list that records every (method, url) call for assertions.
    """
    calls: list[tuple[str, str]] = []

    class _StubClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None, **kw):
            calls.append(("GET", url))
            key = ("GET", url)
            if key not in routes:
                raise AssertionError(f"Unexpected GET {url}")
            return routes[key]

        async def post(self, url, headers=None, json=None, data=None, auth=None, **kw):
            calls.append(("POST", url))
            key = ("POST", url)
            if key not in routes:
                raise AssertionError(f"Unexpected POST {url}")
            return routes[key]

    monkeypatch.setattr(httpx, "AsyncClient", _StubClient)
    return calls


# ---------------------------------------------------------------------------
# A1 — auto-link
# ---------------------------------------------------------------------------

async def test_auto_link_zero_projects_returns_create(db_session, transport, monkeypatch):
    """0 Supabase projects -> action: 'create' with orgs + regions + suggested name."""
    _seed_owner(db_session, "alpha")
    _seed_oauth_row(db_session, "alpha")
    await db_session.commit()

    routes = {
        ("GET", "https://api.supabase.com/v1/projects"):
            _FakeResponse(200, []),
        ("GET", "https://api.supabase.com/v1/organizations"):
            _FakeResponse(200, [{"slug": "ralph-org", "name": "Ralph's Org"}]),
    }
    _install_httpx_mock(monkeypatch, routes)

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/projects/alpha/supabase/oauth/auto-link",
                         headers=OWNER_HDR)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["action"] == "create"
    assert body["organizations"] == [{"slug": "ralph-org", "name": "Ralph's Org"}]
    assert "us-east-1" in body["regions"]
    assert body["suggested_name"] == "alpha"


async def test_auto_link_one_project_auto_links(db_session, transport, monkeypatch):
    """Exactly one Supabase project -> action: 'linked' (anon key fetched + persisted)."""
    _seed_owner(db_session, "alpha")
    _seed_oauth_row(db_session, "alpha")
    await db_session.commit()

    ref = "abcdefghijklmnop"
    routes = {
        ("GET", "https://api.supabase.com/v1/projects"):
            _FakeResponse(200, [{"id": ref, "name": "My App",
                                  "region": "us-east-1",
                                  "organization_id": "org-1"}]),
        ("GET", f"https://api.supabase.com/v1/projects/{ref}"):
            _FakeResponse(200, {"id": ref, "name": "My App"}),
        ("GET", f"https://api.supabase.com/v1/projects/{ref}/api-keys"):
            _FakeResponse(200, [{"name": "anon", "api_key": "eyJanonkey"}]),
    }
    _install_httpx_mock(monkeypatch, routes)

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/projects/alpha/supabase/oauth/auto-link",
                         headers=OWNER_HDR)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["project_ref"] == ref
    assert body["project_name"] == "My App"
    assert body["supabase_url"] == f"https://{ref}.supabase.co"

    # Sanity: row was updated, anon key encrypted not plaintext.
    from sqlalchemy import select
    row = (await db_session.execute(
        select(ProjectSupabase).where(ProjectSupabase.slug == "alpha")
    )).scalar_one()
    assert row.linked_project_ref == ref
    assert row.supabase_url == f"https://{ref}.supabase.co"
    assert row.anon_key_encrypted and row.anon_key_encrypted != "eyJanonkey"


async def test_auto_link_many_projects_returns_pick(db_session, transport, monkeypatch):
    _seed_owner(db_session, "alpha")
    _seed_oauth_row(db_session, "alpha")
    await db_session.commit()

    routes = {
        ("GET", "https://api.supabase.com/v1/projects"): _FakeResponse(200, [
            {"id": "ref-one", "name": "First", "region": "us-east-1",
             "organization_id": "org-1"},
            {"id": "ref-two", "name": "Second", "region": "eu-west-1",
             "organization_id": "org-1"},
        ]),
    }
    _install_httpx_mock(monkeypatch, routes)

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/projects/alpha/supabase/oauth/auto-link",
                         headers=OWNER_HDR)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["action"] == "pick"
    refs = {p["ref"] for p in body["projects"]}
    assert refs == {"ref-one", "ref-two"}


async def test_auto_link_409_when_no_oauth_token(db_session, transport):
    _seed_owner(db_session, "alpha")
    await db_session.commit()
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/projects/alpha/supabase/oauth/auto-link",
                         headers=OWNER_HDR)
    assert r.status_code == 409


async def test_auto_link_rejects_non_owner(db_session, transport):
    _seed_owner(db_session, "alpha")
    _seed_oauth_row(db_session, "alpha")
    await db_session.commit()
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/api/projects/alpha/supabase/oauth/auto-link",
            headers={"X-User-Email": "stranger@aiui.com",
                     "X-User-Admin": "true"},
        )
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# A2 — create-project
# ---------------------------------------------------------------------------

async def test_create_project_happy_path(db_session, transport, monkeypatch):
    _seed_owner(db_session, "alpha")
    _seed_oauth_row(db_session, "alpha")
    await db_session.commit()

    new_ref = "newproject1234567890"
    routes = {
        ("POST", "https://api.supabase.com/v1/projects"): _FakeResponse(
            201, {"id": new_ref, "status": "COMING_UP"}
        ),
    }
    _install_httpx_mock(monkeypatch, routes)

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/api/projects/alpha/supabase/oauth/create-project",
            headers=OWNER_HDR,
            json={
                "name": "my-new-app",
                "region": "us-east-1",
                "organization_id": "org-1",
                "db_password": "supersecret123",
            },
        )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["action"] == "creating"
    assert body["project_ref"] == new_ref

    # linked_project_ref must be persisted NOW so /create-status can poll.
    from sqlalchemy import select
    row = (await db_session.execute(
        select(ProjectSupabase).where(ProjectSupabase.slug == "alpha")
    )).scalar_one()
    assert row.linked_project_ref == new_ref


async def test_create_project_rejects_invalid_name(db_session, transport, monkeypatch):
    _seed_owner(db_session, "alpha")
    _seed_oauth_row(db_session, "alpha")
    await db_session.commit()
    _install_httpx_mock(monkeypatch, {})  # no calls expected

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/api/projects/alpha/supabase/oauth/create-project",
            headers=OWNER_HDR,
            json={
                "name": "has spaces!",
                "region": "us-east-1",
                "organization_id": "org-1",
                "db_password": "supersecret123",
            },
        )
    # Either pydantic rejects the body (422) or our regex check rejects (400).
    assert r.status_code in (400, 422)


async def test_create_project_403_maps_to_422(db_session, transport, monkeypatch):
    _seed_owner(db_session, "alpha")
    _seed_oauth_row(db_session, "alpha")
    await db_session.commit()

    routes = {
        ("POST", "https://api.supabase.com/v1/projects"): _FakeResponse(
            403, {"message": "forbidden"}
        ),
    }
    _install_httpx_mock(monkeypatch, routes)

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/api/projects/alpha/supabase/oauth/create-project",
            headers=OWNER_HDR,
            json={
                "name": "another-app",
                "region": "us-east-1",
                "organization_id": "org-1",
                "db_password": "supersecret123",
            },
        )
    assert r.status_code == 422
    assert "permission" in r.json()["detail"].lower()