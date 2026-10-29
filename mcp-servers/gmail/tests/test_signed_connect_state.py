"""A consent is stored against whoever signed in, not whoever opened the link.

The flaw this pins, found on 2026-10-29: /auth/google/start was public,
unauthenticated, and took the account from a `user_email` query parameter,
which it then put into an unsigned `state`. The callback believed it. So
anyone who knew a platform user's address could start the flow naming them,
consent with a Google account of their own, and have those tokens written
under the named person's address. save_token does ON CONFLICT DO UPDATE, so an
existing connection is replaced rather than skipped: being already connected
was the exposed case, not a protection. Their agents would then be acting in a
mailbox that was not theirs, and the Connections panel would still say
"Connected".

A browser holds no secret, so it cannot sign a state. It now asks
/auth/google/link, which takes the address from the header the api-gateway
injects after authenticating the session, and signs it here.
"""
import base64
import hashlib
import hmac
import importlib.util
import os
import pathlib
import time
import urllib.parse

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault(
    "AIUI_FERNET_KEY", base64.urlsafe_b64encode(b"0" * 32).decode())
# Read at import time by oauth_state, so it must be set before main.py loads.
os.environ["OAUTH_STATE_SECRET"] = "test-secret-for-signing-states"

MAIN_PATH = pathlib.Path(__file__).resolve().parents[1] / "main.py"

OWNER = "owner@example.com"
VICTIM = "victim@example.com"


def _load_main():
    spec = importlib.util.spec_from_file_location("gmail_main", MAIN_PATH)
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

    async def fake_id_lookup(_uid):
        return None

    async def fake_save(user_email, _token):
        seen["gmail"] = user_email

    async def fake_save_all(user_email, _a, _r):
        seen["all"] = user_email

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

    monkeypatch.setattr(main, "_email_for_user_id", fake_id_lookup)
    monkeypatch.setattr(main, "save_token", fake_save)
    monkeypatch.setattr(main, "_save_token_all_services", fake_save_all)
    monkeypatch.setattr(main, "DATABASE_URL", "postgres://x/y")
    monkeypatch.setattr(main.httpx, "AsyncClient", lambda *a, **kw: _Client())
    return seen


def _state_of(location):
    return urllib.parse.parse_qs(
        urllib.parse.urlparse(location).query)["state"][0]


# --- the attack, which must no longer work -----------------------------------

def test_naming_someone_on_the_start_url_no_longer_connects_them(main, stored):
    """The reported flaw. `user_email` is not a parameter any more, so this is
    a start with no signed state, refused before Google is involved."""
    client = TestClient(main.app)
    r = client.get("/auth/google/start",
                   params={"user_email": VICTIM, "connect": "all"},
                   follow_redirects=False)
    assert r.status_code == 400
    assert "accounts.google.com" not in r.headers.get("location", "")


def test_an_unsigned_unified_state_is_refused_at_the_callback(main, stored):
    """The other half: even with a code in hand, "all::victim@example.com"
    carries no signature, so nothing is stored."""
    client = TestClient(main.app)
    r = client.get("/auth/google/callback",
                   params={"code": "c", "state": "all::" + VICTIM})
    assert r.status_code == 400
    assert stored == {}, "a consent was stored against an unsigned address"


def test_a_bare_address_as_state_is_refused(main, stored):
    """The legacy fallback the callback used to accept."""
    client = TestClient(main.app)
    r = client.get("/auth/google/callback",
                   params={"code": "c", "state": VICTIM})
    assert r.status_code == 400
    assert stored == {}


def test_a_callback_with_no_state_is_refused(main, stored):
    client = TestClient(main.app)
    assert client.get("/auth/google/callback",
                      params={"code": "c"}).status_code == 400
    assert stored == {}


def test_a_tampered_state_is_refused(main, stored):
    """Flip one character of a real signature."""
    import oauth_state
    good = oauth_state.sign_state(OWNER)
    bad = good[:-1] + ("A" if good[-1] != "A" else "B")
    client = TestClient(main.app)
    r = client.get("/auth/google/callback", params={"code": "c", "state": bad})
    assert r.status_code == 400
    assert stored == {}


def test_a_state_signed_with_another_secret_is_refused(main, stored):
    """Somebody else's HMAC key must not open this door."""
    import oauth_state as os_mod
    ts = str(int(time.time()))
    sig = hmac.new(b"a-different-secret",
                   ("%s:%s" % (OWNER, ts)).encode("utf-8"),
                   hashlib.sha256).digest()
    forged = "%s.%s.%s" % (os_mod._b64(OWNER.encode("utf-8")),
                           os_mod._b64(ts.encode("ascii")),
                           os_mod._b64(sig))
    client = TestClient(main.app)
    r = client.get("/auth/google/callback",
                   params={"code": "c", "state": forged})
    assert r.status_code == 400
    assert stored == {}


def test_an_expired_state_is_refused(main, stored, monkeypatch):
    """The link is good for ten minutes; a leaked one must not work forever."""
    import oauth_state
    state = oauth_state.sign_state(OWNER)
    later = time.time() + oauth_state._TTL_SECONDS + 1
    monkeypatch.setattr(oauth_state.time, "time", lambda: later)
    client = TestClient(main.app)
    r = client.get("/auth/google/callback",
                   params={"code": "c", "state": state})
    assert r.status_code == 400
    assert stored == {}


# --- what must still work ----------------------------------------------------

def test_a_signed_state_connects_its_owner(main, stored):
    import oauth_state
    client = TestClient(main.app)
    r = client.get("/auth/google/callback",
                   params={"code": "c",
                           "state": oauth_state.sign_state(OWNER)})
    assert r.status_code == 200
    assert stored["gmail"] == OWNER


def test_a_signed_unified_state_links_all_three_services(main, stored):
    import oauth_state
    client = TestClient(main.app)
    state = oauth_state.sign_state(main.UNIFIED_PREFIX + OWNER)
    r = client.get("/auth/google/callback",
                   params={"code": "c", "state": state})
    assert r.status_code == 200
    assert stored["gmail"] == OWNER, "the marker leaked into the stored key"
    assert stored["all"] == OWNER


def test_the_bot_flow_still_starts(main, stored):
    """Discord and Slack sign a state and send the person the link."""
    import oauth_state
    client = TestClient(main.app)
    r = client.get("/auth/google/start",
                   params={"state": oauth_state.sign_state(OWNER)},
                   follow_redirects=False)
    assert r.status_code in (302, 307)
    assert "accounts.google.com" in r.headers["location"]


# --- the browser's way in ----------------------------------------------------

def test_link_signs_the_session_identity(main, stored):
    """The address comes from the gateway header, never from the URL."""
    import oauth_state
    client = TestClient(main.app)
    r = client.get("/auth/google/link", params={"connect": "all"},
                   headers={"X-User-Email": OWNER}, follow_redirects=False)
    assert r.status_code in (302, 307)
    owner = oauth_state.verify_state(_state_of(r.headers["location"]))
    assert owner == main.UNIFIED_PREFIX + OWNER


def test_link_ignores_an_address_on_its_own_url(main, stored):
    """Belt and braces: naming somebody here changes nothing."""
    import oauth_state
    client = TestClient(main.app)
    r = client.get("/auth/google/link",
                   params={"connect": "all", "user_email": VICTIM},
                   headers={"X-User-Email": OWNER}, follow_redirects=False)
    owner = oauth_state.verify_state(_state_of(r.headers["location"]))
    assert owner == main.UNIFIED_PREFIX + OWNER
    assert VICTIM not in r.headers["location"]


def test_link_refuses_when_nobody_is_signed_in(main, stored):
    """No header means the gateway authenticated nobody, so there is no
    account to sign for."""
    client = TestClient(main.app)
    r = client.get("/auth/google/link", follow_redirects=False)
    assert r.status_code == 400


def test_link_asks_for_all_three_scopes_on_a_unified_connect(main, stored):
    client = TestClient(main.app)
    r = client.get("/auth/google/link", params={"connect": "all"},
                   headers={"X-User-Email": OWNER}, follow_redirects=False)
    q = urllib.parse.parse_qs(
        urllib.parse.urlparse(r.headers["location"]).query)
    assert "calendar" in q["scope"][0] and "drive" in q["scope"][0]
