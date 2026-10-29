"""A Drive consent is stored against whoever signed in.

Same flaw as the Gmail service had, and worth its own tests because this is an
independent way in: /auth/google/start took `user_email` off the query string
and the callback fell back to believing an unsigned state, so anyone could
bind their own Google account to somebody else's address and replace their
Drive connection. Fixing only the Gmail service would have left this as the
bypass.
"""
import base64
import importlib.util
import os
import pathlib
import urllib.parse

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("AIUI_FERNET_KEY",
                      base64.urlsafe_b64encode(b"0" * 32).decode())
# Read at import time by oauth_state, so it must be set before main.py loads.
os.environ.setdefault("OAUTH_STATE_SECRET", "test-secret-for-signing-states")

MAIN_PATH = pathlib.Path(__file__).resolve().parents[1] / "main.py"

OWNER = "owner@example.com"
VICTIM = "victim@example.com"


def _load_main():
    spec = importlib.util.spec_from_file_location("gdrive_main", MAIN_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def main():
    return _load_main()


@pytest.fixture
def stored(main, monkeypatch):
    """A consent that always succeeds, recording who it was stored against."""
    seen = {}

    async def fake_save(user_email, _token):
        seen["drive"] = user_email

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"access_token": "at", "refresh_token": "rt"}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **kw):
            return _Resp()

    monkeypatch.setattr(main, "save_token", fake_save)
    monkeypatch.setattr(main.httpx, "AsyncClient", lambda *a, **kw: _Client())
    return seen


def _state_of(location):
    return urllib.parse.parse_qs(
        urllib.parse.urlparse(location).query)["state"][0]


# --- the attack ---------------------------------------------------------------

def test_naming_someone_on_the_start_url_no_longer_connects_them(main, stored):
    client = TestClient(main.app)
    r = client.get("/auth/google/start", params={"user_email": VICTIM},
                   follow_redirects=False)
    assert r.status_code == 400
    assert "accounts.google.com" not in r.headers.get("location", "")


def test_an_unsigned_address_as_state_is_refused(main, stored):
    client = TestClient(main.app)
    r = client.get("/auth/google/callback",
                   params={"code": "c", "state": VICTIM})
    assert r.status_code == 400
    assert stored == {}, "a Drive consent was stored against an unsigned address"


def test_a_tampered_state_is_refused(main, stored):
    import oauth_state
    good = oauth_state.sign_state(OWNER)
    bad = good[:-1] + ("A" if good[-1] != "A" else "B")
    client = TestClient(main.app)
    r = client.get("/auth/google/callback", params={"code": "c", "state": bad})
    assert r.status_code == 400
    assert stored == {}


def test_a_callback_with_no_state_is_refused(main, stored):
    client = TestClient(main.app)
    assert client.get("/auth/google/callback",
                      params={"code": "c"}).status_code == 400
    assert stored == {}


# --- what must still work ------------------------------------------------------

def test_a_signed_state_connects_its_owner(main, stored):
    import oauth_state
    client = TestClient(main.app)
    r = client.get("/auth/google/callback",
                   params={"code": "c",
                           "state": oauth_state.sign_state(OWNER)})
    assert r.status_code == 200
    assert stored["drive"] == OWNER


def test_the_bot_flow_still_starts(main, stored):
    import oauth_state
    client = TestClient(main.app)
    r = client.get("/auth/google/start",
                   params={"state": oauth_state.sign_state(OWNER)},
                   follow_redirects=False)
    assert r.status_code in (302, 307)
    assert "accounts.google.com" in r.headers["location"]


# --- the browser's way in ------------------------------------------------------

def test_link_signs_the_session_identity(main, stored):
    import oauth_state
    client = TestClient(main.app)
    r = client.get("/auth/google/link", headers={"X-User-Email": OWNER},
                   follow_redirects=False)
    assert r.status_code in (302, 307)
    assert oauth_state.verify_state(_state_of(r.headers["location"])) == OWNER


def test_link_refuses_when_nobody_is_signed_in(main, stored):
    client = TestClient(main.app)
    assert client.get("/auth/google/link",
                      follow_redirects=False).status_code == 400


def test_link_ignores_an_address_on_its_own_url(main, stored):
    import oauth_state
    client = TestClient(main.app)
    r = client.get("/auth/google/link", params={"user_email": VICTIM},
                   headers={"X-User-Email": OWNER}, follow_redirects=False)
    assert oauth_state.verify_state(_state_of(r.headers["location"])) == OWNER
    assert VICTIM not in r.headers["location"]
