"""GET /api/projects + GET /api/projects/{slug}/status — caller-scoped views."""
import os
import sys

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://nope/nope")
if not os.environ.get("AIUI_FERNET_KEY"):
    from cryptography.fernet import Fernet as _Fernet
    os.environ["AIUI_FERNET_KEY"] = _Fernet.generate_key().decode()

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient


def test_list_my_projects_requires_email():
    from main import app
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/api/projects")
    assert r.status_code == 401


def test_list_my_projects_no_admin_required(monkeypatch):
    """Caller has only X-User-Email, no X-User-Admin — must still return 200."""
    from main import app
    import routes_projects

    async def fake_list(email):
        return [{"slug": "test", "name": "Test", "role": "viewer",
                 "published": False, "public_url": None}]
    monkeypatch.setattr(routes_projects, "_list_projects_for_email", fake_list, raising=False)

    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/api/projects", headers={"X-User-Email": "alice@x.com"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, list)
    assert body[0]["slug"] == "test"


def test_status_404_for_other_users_project(monkeypatch):
    """Ownership leak prevention: cross-user status returns 404, not 403."""
    from main import app
    import routes_projects

    async def fake_can_see(s, slug, email):
        return False
    monkeypatch.setattr(routes_projects, "_user_can_see_project", fake_can_see)

    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/api/projects/someone-elses-app/status",
                   headers={"X-User-Email": "alice@x.com"})
    assert r.status_code == 404
