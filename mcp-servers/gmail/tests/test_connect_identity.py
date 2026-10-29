"""The connect flow stores an address, or it fails where you can see it.

Before this, a Google consent carrying an Open WebUI user id wrote that id
into gmail_tokens, gdrive_tokens and calendar_tokens and told the person
"Gmail Connected!". Every later read asks by address and found nothing. These
tests pin both halves: an id that can be resolved is stored as the address,
and an id that cannot is refused instead of being stored.
"""
import base64
import importlib.util
import os
import pathlib
import urllib.parse

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault(
    "AIUI_FERNET_KEY", base64.urlsafe_b64encode(b"0" * 32).decode())
# Read at import time by oauth_state, so it must be set before main.py loads.
os.environ.setdefault("OAUTH_STATE_SECRET", "test-secret-for-signing-states")

MAIN_PATH = pathlib.Path(__file__).resolve().parents[1] / "main.py"

EMAIL = "someone@example.com"
USER_ID = "d741f063-d6b4-4d28-9abb-9bf30b43fa9e"


def _load_main():
    spec = importlib.util.spec_from_file_location("gmail_main", MAIN_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def main():
    return _load_main()


@pytest.fixture
def connected(main, monkeypatch):
    """A consent that always succeeds, recording what identity was stored."""
    stored: dict = {}

    async def fake_id_lookup(user_id):
        return EMAIL if user_id == USER_ID else None

    async def fake_save(user_email, token_data):
        stored["gmail"] = user_email

    async def fake_save_all(user_email, access, refresh):
        stored["all"] = user_email

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
    monkeypatch.setattr(main.httpx, "AsyncClient", lambda *a, **kw: _Client())
    return stored


# --- the callback, which is where the bad rows came from ---------------------
#
# Every case here now arrives through a SIGNED state. Accepting an unsigned
# one is a separate flaw with its own file (test_signed_connect_state.py);
# what these pin is that whatever identity a verified state carries, the
# address is what ends up as the key.


def _signed(owner):
    import oauth_state
    return oauth_state.sign_state(owner)


def test_a_consent_carrying_an_address_stores_that_address(main, connected):
    client = TestClient(main.app)
    r = client.get("/auth/google/callback",
                   params={"code": "c", "state": _signed(EMAIL)})
    assert r.status_code == 200
    assert connected["gmail"] == EMAIL


def test_a_consent_carrying_a_user_id_stores_the_address_instead(main, connected):
    """The repair, and still a live path: the bot signs whatever owner it
    holds, which can be an id. The id resolves, so the connection lands where
    every read will look for it."""
    client = TestClient(main.app)
    r = client.get("/auth/google/callback",
                   params={"code": "c", "state": _signed(USER_ID)})
    assert r.status_code == 200
    assert connected["gmail"] == EMAIL, "the id was stored as the key again"


def test_a_unified_consent_keys_all_three_services_by_the_address(main, connected):
    """One consent writes gmail, drive and calendar. The bug put the id in all
    three at once, so the fix has to cover all three at once."""
    client = TestClient(main.app)
    r = client.get("/auth/google/callback",
                   params={"code": "c",
                           "state": _signed(main.UNIFIED_PREFIX + USER_ID)})
    assert r.status_code == 200
    assert connected["gmail"] == EMAIL
    assert connected["all"] == EMAIL


def test_an_unresolvable_identity_is_refused_not_stored(main, connected):
    """Signed, so it gets past the signature check, and still refused: an id
    that resolves to no account is not something to key a token by. Nothing is
    written and the page says so. The old behaviour wrote the row and said
    'Gmail Connected!'."""
    client = TestClient(main.app)
    r = client.get("/auth/google/callback",
                   params={"code": "c",
                           "state": _signed("00000000-0000-0000-0000-000000000000")})
    assert r.status_code == 400
    assert "was not connected" in r.text
    assert "gmail" not in connected, "a token was stored under an unknown key"


def test_the_refusal_page_does_not_claim_success(main, connected):
    client = TestClient(main.app)
    r = client.get("/auth/google/callback",
                   params={"code": "c",
                           "state": _signed("00000000-0000-0000-0000-000000000000")})
    assert "Connected!" not in r.text


# --- the start of the flow, so the refusal comes before the consent ----------

def test_link_with_an_unresolvable_id_refuses_before_google(main, connected):
    """Better to stop here than after the person has signed in to Google and
    been told it worked. The identity comes from the gateway header now, so
    that is what carries the id."""
    client = TestClient(main.app)
    r = client.get("/auth/google/link",
                   headers={"X-User-Email": "00000000-0000-0000-0000-000000000000"},
                   follow_redirects=False)
    assert r.status_code == 400


def test_link_with_a_user_id_signs_the_address(main, connected):
    """A client still sending an id reaches the right account, and the id
    never travels in the state."""
    import oauth_state
    client = TestClient(main.app)
    r = client.get("/auth/google/link", params={"connect": "all"},
                   headers={"X-User-Email": USER_ID}, follow_redirects=False)
    assert r.status_code in (302, 307)
    loc = r.headers["location"]
    assert "accounts.google.com" in loc
    state = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query)["state"][0]
    assert oauth_state.verify_state(state) == main.UNIFIED_PREFIX + EMAIL
    assert USER_ID not in loc


def test_a_presigned_state_is_left_alone(main, connected):
    """The Discord and Slack flows sign a state and send the person the link.
    That must still work."""
    client = TestClient(main.app)
    state = _signed(EMAIL)
    r = client.get("/auth/google/start", params={"state": state},
                   follow_redirects=False)
    assert r.status_code in (302, 307)
    assert state in r.headers["location"]


def test_a_consent_with_no_identity_at_all_is_refused(main, connected, monkeypatch):
    """No state means nothing to verify, so there is nobody to connect."""
    monkeypatch.setattr(main, "DATABASE_URL", "postgres://x/y")
    client = TestClient(main.app)
    r = client.get("/auth/google/callback", params={"code": "c"})
    assert r.status_code == 400
    assert "gmail" not in connected


def test_without_a_signing_secret_a_connect_fails_closed(main, connected,
                                                         monkeypatch):
    """A box with no OAUTH_STATE_SECRET cannot sign or verify, so it cannot
    connect anybody. That is deliberate: this used to fall back to believing
    an unsigned address, and failing closed is the whole point. It costs the
    dev default its connect, which the local stack does not run anyway.
    """
    import oauth_state
    monkeypatch.setattr(oauth_state, "_SECRET", b"")
    client = TestClient(main.app)
    r = client.get("/auth/google/callback",
                   params={"code": "c", "state": "anything"})
    assert r.status_code == 400
    assert connected == {}
    # And the start of the flow says so rather than silently doing nothing.
    r2 = client.get("/auth/google/link", headers={"X-User-Email": EMAIL},
                    follow_redirects=False)
    assert r2.status_code == 500


# --- whose mailbox is read comes from the gateway, not the caller -------------

@pytest.fixture
def mailbox_reads(main, monkeypatch):
    """Records which account's token an endpoint asked for."""
    asked: list = []

    async def fake_valid_token(user_email):
        asked.append(user_email)
        return None          # "Not connected", so no Gmail call is made

    monkeypatch.setattr(main, "get_valid_token", fake_valid_token)
    return asked


def test_the_attachment_download_ignores_a_named_account(main, mailbox_reads):
    """Confirmed live on 2026-10-29: an unauthenticated caller could name any
    connected address on the query string and this service would call Gmail
    with that person's token. The identity now comes from the header the
    gateway injects, and the gateway strips whatever the client sent."""
    client = TestClient(main.app)
    client.get("/gmail_download_attachment/MSG/ATT",
               params={"user_email": "victim@example.com", "filename": "x"})
    assert mailbox_reads == ["default@local"], (
        "the query parameter still chose whose mailbox was opened")
    assert "victim@example.com" not in mailbox_reads


def test_the_attachment_download_uses_the_gateway_header(main, mailbox_reads):
    client = TestClient(main.app)
    client.get("/gmail_download_attachment/MSG/ATT",
               headers={"X-User-Email": "owner@example.com"})
    assert mailbox_reads == ["owner@example.com"]


def test_a_forged_header_cannot_outrank_the_gateway(main, mailbox_reads):
    """Defence in depth only: the gateway strips client x-user-email before
    this service ever sees it, which is why the header is the trusted one.
    This records the assumption so a change to that stripping shows up here.
    """
    client = TestClient(main.app)
    client.get("/gmail_download_attachment/MSG/ATT",
               headers={"X-User-Email": "owner@example.com"},
               params={"user_email": "victim@example.com"})
    assert mailbox_reads == ["owner@example.com"]
