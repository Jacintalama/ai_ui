"""The Connections panel can say WHICH account is connected.

"Connected" alone does not say connected as whom, and the Google account that
consented is not necessarily the one signed in to the platform: the token row
is keyed by the PLATFORM address, so showing that would be a confident lie on
the exact screen where somebody is checking.

The label rides on /auth/status, the authenticated route, and deliberately
NOT on /auth/google/status?user_email=, which answers for whatever address it
is handed. That one already says whether an arbitrary person has connected;
naming their Google account on it would turn a small leak into a real one.

Nothing here may cost the poll. The panel reads this to decide whether a card
says Connected, so a label that cannot be fetched must still leave a live
connection reading as live.
"""
import base64
import importlib.util
import os
import pathlib

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault(
    "AIUI_FERNET_KEY", base64.urlsafe_b64encode(b"0" * 32).decode())
os.environ.setdefault("OAUTH_STATE_SECRET", "test-secret-for-signing-states")

MAIN_PATH = pathlib.Path(__file__).resolve().parents[1] / "main.py"

OWNER = "owner@example.com"
GOOGLE = "the.real.one@gmail.com"


def _load_main():
    spec = importlib.util.spec_from_file_location("gmail_main", MAIN_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def main():
    return _load_main()


def _profile(main, monkeypatch, status=200, body=None, calls=None):
    """Stand in for Google's users/me/profile."""
    class _Resp:
        status_code = status

        @staticmethod
        def json():
            return body if body is not None else {"emailAddress": GOOGLE}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **kw):
            if calls is not None:
                calls.append(a[0] if a else "")
            return _Resp()

    monkeypatch.setattr(main.httpx, "AsyncClient", lambda *a, **kw: _Client())


def _connected(main, monkeypatch):
    async def token(_email):
        return {"access_token": "at", "refresh_token": "rt"}

    async def valid(_email):
        return "at"

    monkeypatch.setattr(main, "get_token", token)
    monkeypatch.setattr(main, "get_valid_token", valid)


def test_a_connected_account_is_named(main, monkeypatch):
    _connected(main, monkeypatch)
    _profile(main, monkeypatch)
    r = TestClient(main.app).get("/auth/status",
                                 headers={"X-User-Email": OWNER})
    assert r.json() == {"connected": True, "account": GOOGLE}


def test_the_google_address_is_asked_for_not_assumed(main, monkeypatch):
    """The platform address and the Google account can differ, and the whole
    point of the label is to show which one actually consented."""
    _connected(main, monkeypatch)
    _profile(main, monkeypatch)
    account = TestClient(main.app).get(
        "/auth/status", headers={"X-User-Email": OWNER}).json()["account"]
    assert account == GOOGLE and account != OWNER


def test_nobody_connected_is_said_plainly(main, monkeypatch):
    async def token(_email):
        return None

    monkeypatch.setattr(main, "get_token", token)
    r = TestClient(main.app).get("/auth/status",
                                 headers={"X-User-Email": OWNER})
    assert r.json() == {"connected": False, "account": None}


def test_google_is_asked_once_and_then_remembered(main, monkeypatch):
    """Without the cache the panel asks Google on every poll for an answer
    that cannot change while a connection lasts."""
    _connected(main, monkeypatch)
    calls = []
    _profile(main, monkeypatch, calls=calls)
    client = TestClient(main.app)
    for _ in range(3):
        client.get("/auth/status", headers={"X-User-Email": OWNER})
    assert len(calls) == 1, calls


def test_disconnecting_forgets_the_account(main, monkeypatch):
    """Or reconnecting a DIFFERENT Google account would keep showing the old
    address until the service restarted."""
    _connected(main, monkeypatch)
    _profile(main, monkeypatch)
    client = TestClient(main.app)
    client.get("/auth/status", headers={"X-User-Email": OWNER})
    assert main._account_cache.get(OWNER) == GOOGLE
    monkeypatch.setattr(main, "DATABASE_URL", "")
    client.post("/auth/google/disconnect",
                params={"user_email": OWNER})
    assert OWNER not in main._account_cache


# --- a missing label must never cost the connection ---------------------------

def test_a_refused_profile_call_still_reports_connected(main, monkeypatch):
    _connected(main, monkeypatch)
    _profile(main, monkeypatch, status=403)
    body = TestClient(main.app).get(
        "/auth/status", headers={"X-User-Email": OWNER}).json()
    assert body["connected"] is True, "a display label broke the status poll"
    assert body["account"] is None


def test_a_profile_call_that_blows_up_still_reports_connected(main, monkeypatch):
    _connected(main, monkeypatch)

    class _Boom:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **kw):
            raise RuntimeError("the network went away")

    monkeypatch.setattr(main.httpx, "AsyncClient", lambda *a, **kw: _Boom())
    body = TestClient(main.app).get(
        "/auth/status", headers={"X-User-Email": OWNER}).json()
    assert body["connected"] is True
    assert body["account"] is None


def test_a_profile_with_no_address_is_not_cached_as_nothing(main, monkeypatch):
    """A blank answer must be retried later, not remembered as the label."""
    _connected(main, monkeypatch)
    _profile(main, monkeypatch, body={})
    TestClient(main.app).get("/auth/status", headers={"X-User-Email": OWNER})
    assert OWNER not in main._account_cache


# --- the leaky route is left alone ---------------------------------------------

def test_the_query_route_does_not_name_anybodys_google_account(main, monkeypatch):
    """/auth/google/status answers for whatever address it is given, so it
    must keep saying only whether a connection exists. Putting the account on
    it would let anyone ask which Google account a named person uses."""
    _connected(main, monkeypatch)
    _profile(main, monkeypatch)
    body = TestClient(main.app).get(
        "/auth/google/status", params={"user_email": "someone@else.com"}).json()
    assert "account" not in body
    assert GOOGLE not in str(body)
