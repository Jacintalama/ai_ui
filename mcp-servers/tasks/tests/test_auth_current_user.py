"""current_user — non-admin sibling of current_admin.

Used by list-my-* endpoints in routes_projects so non-admin Discord
users can fetch their own project list.
"""
import os
import sys

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://nope/nope")
if not os.environ.get("AIUI_FERNET_KEY"):
    from cryptography.fernet import Fernet as _Fernet
    os.environ["AIUI_FERNET_KEY"] = _Fernet.generate_key().decode()

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi import Depends


def test_current_user_returns_email():
    from auth import current_user, CurrentUser
    app = FastAPI()

    @app.get("/whoami")
    def whoami(u: CurrentUser = Depends(current_user)):
        return {"email": u.email}

    client = TestClient(app)
    r = client.get("/whoami", headers={"X-User-Email": "ALICE@X.COM"})
    assert r.status_code == 200
    assert r.json() == {"email": "alice@x.com"}


def test_current_user_no_admin_required():
    """Crucially, current_user must NOT require X-User-Admin=true."""
    from auth import current_user, CurrentUser
    app = FastAPI()

    @app.get("/whoami")
    def whoami(u: CurrentUser = Depends(current_user)):
        return {"email": u.email}

    client = TestClient(app)
    # No X-User-Admin header — must still succeed.
    r = client.get("/whoami", headers={"X-User-Email": "alice@x.com"})
    assert r.status_code == 200


def test_current_user_missing_email_401():
    from auth import current_user, CurrentUser
    app = FastAPI()

    @app.get("/whoami")
    def whoami(u: CurrentUser = Depends(current_user)):
        return {"email": u.email}

    client = TestClient(app)
    r = client.get("/whoami")
    assert r.status_code == 401
