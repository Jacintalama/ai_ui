from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from auth import AdminUser, current_admin


def _make_app():
    app = FastAPI()

    @app.get("/whoami")
    def whoami(user: AdminUser = Depends(current_admin)):
        return {"email": user.email, "is_admin": user.is_admin}

    return app


def test_returns_admin_when_headers_present():
    client = TestClient(_make_app())
    r = client.get(
        "/whoami",
        headers={"X-User-Email": "ralph@aiui.com", "X-User-Admin": "true"},
    )
    assert r.status_code == 200
    assert r.json() == {"email": "ralph@aiui.com", "is_admin": True}


def test_rejects_when_missing_email():
    client = TestClient(_make_app())
    r = client.get("/whoami")
    assert r.status_code == 401


def test_rejects_when_not_admin():
    client = TestClient(_make_app())
    r = client.get(
        "/whoami",
        headers={"X-User-Email": "guest@aiui.com", "X-User-Admin": "false"},
    )
    assert r.status_code == 403
