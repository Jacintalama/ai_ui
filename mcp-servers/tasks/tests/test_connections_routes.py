"""Connecting an account: the endpoint, the vendor check, and the secret.

connections.py decides what a provider needs and how to ask the vendor. This
covers what the route does with the answer, which is where the two ways this
feature could go wrong actually live.

Storing a credential nobody checked. That produces a card reading "Connected"
for a token that was mistyped, revoked, or lacking a scope, and the user finds
out later when a tool fails with something unhelpful. So no row is written
until the vendor confirms the credential and names the account.

Leaking the credential back out. It arrives over HTTP, gets encrypted, and must
never appear again: not in a response body, not in an error message, not in a
log line. Trello is the sharp case, because its credential travels in the query
string, so an exception carrying the URL carries the token.
"""
import json

import pytest
from fastapi.testclient import TestClient

import connections as C
import routes_connections as R
from auth import CurrentUser, current_user

EMAIL = "ralph@example.com"
SECRET = "pk_SUPERSECRET_TOKEN_VALUE_12345"


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


class _FakeConn:
    """Just enough asyncpg to watch what the route tries to persist."""

    def __init__(self, store):
        self.store = store

    async def fetch(self, sql, *args):
        return [{"provider": p, "account_label": v["account_label"],
                 "updated_at": _Stamp()} for p, v in self.store.items()]

    async def fetchrow(self, sql, *args):
        hit = self.store.get(args[1]) if len(args) > 1 else None
        return {"secrets_encrypted": hit["blob"]} if hit else None

    async def execute(self, sql, *args):
        if sql.strip().upper().startswith("DELETE"):
            self.store.pop(args[1], None)
            return
        _email, provider, blob, label = args
        self.store[provider] = {"blob": blob, "account_label": label}

    async def close(self):
        pass


class _Stamp:
    def isoformat(self):
        return "2026-08-19T10:00:00+00:00"


@pytest.fixture
def client(monkeypatch):
    # A bare app carrying only this router. Importing main would drag in the
    # service lifespan, which runs migrations against a real database, and
    # these assertions are about route behaviour, not about Postgres.
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(R.router)
    app.dependency_overrides[current_user] = lambda: CurrentUser(
        email=EMAIL, is_admin=False)

    store = {}

    async def _fake_connect():
        return _FakeConn(store)

    monkeypatch.setattr(R, "_connect", _fake_connect)

    sent = []
    reply = {"response": _FakeResponse(200, {"user": {"username": "ralph"}})}

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def request(self, method, url, headers=None, params=None,
                          json=None):
            sent.append({"method": method, "url": url,
                         "headers": headers or {}, "params": params or {},
                         "json": json})
            resp = reply["response"]
            if isinstance(resp, Exception):
                raise resp
            return resp

    monkeypatch.setattr(R.httpx, "AsyncClient", _FakeClient)

    with TestClient(app) as c:
        yield c, store, sent, reply

    app.dependency_overrides.pop(current_user, None)


# --- listing --------------------------------------------------------------

def test_the_dialog_is_told_about_every_provider(client):
    c, _, _, _ = client
    body = c.get("/connections").json()
    ids = {x["provider"] for x in body["connections"]}
    assert ids == set(C.PROVIDERS)


def test_nothing_is_connected_before_anyone_connects(client):
    c, _, _, _ = client
    body = c.get("/connections").json()
    assert all(x["connected"] is False for x in body["connections"])


def test_the_dialog_is_told_where_to_find_the_credential(client):
    """A form saying "paste your API token" is useless if you do not know
    where the vendor keeps it."""
    c, _, _, _ = client
    for x in c.get("/connections").json()["connections"]:
        assert x["where"].strip(), x["provider"]
        assert x["fields"]


# --- a credential is checked before it is believed ------------------------

def test_connecting_calls_the_vendor_before_storing(client):
    c, store, sent, _ = client
    r = c.post("/connections/clickup", json={"values": {"token": SECRET}})
    assert r.status_code == 200
    assert sent and sent[0]["url"].startswith("https://api.clickup.com/")
    assert "clickup" in store


def test_the_card_shows_the_account_the_vendor_named(client):
    c, _, _, _ = client
    r = c.post("/connections/clickup", json={"values": {"token": SECRET}})
    assert r.json()["account_label"] == "ralph"


def test_a_rejected_credential_is_not_stored(client):
    """The whole point. A 401 from ClickUp must not become a green card."""
    c, store, _, reply = client
    reply["response"] = _FakeResponse(401, {})
    r = c.post("/connections/clickup", json={"values": {"token": "wrong"}})
    assert r.status_code == 400
    assert store == {}


def test_a_rejected_credential_says_what_to_do(client):
    c, _, _, reply = client
    reply["response"] = _FakeResponse(403, {})
    detail = c.post("/connections/clickup",
                    json={"values": {"token": "wrong"}}).json()["detail"]
    assert "ClickUp" in detail


def test_an_unreachable_vendor_is_not_a_rejected_credential(client):
    """502, not 400. Telling a user their token is wrong when the vendor was
    simply down sends them off to regenerate a perfectly good credential."""
    c, store, _, reply = client
    reply["response"] = RuntimeError("connect timeout")
    r = c.post("/connections/clickup", json={"values": {"token": SECRET}})
    assert r.status_code == 502
    assert store == {}


def test_an_incomplete_two_field_form_is_refused_before_any_request(client):
    c, _, sent, _ = client
    r = c.post("/connections/trello", json={"values": {"api_key": "K"}})
    assert r.status_code == 400
    assert sent == []


def test_an_unknown_provider_is_a_404_not_an_invention(client):
    c, _, _, _ = client
    assert c.post("/connections/myspace",
                  json={"values": {"token": "x"}}).status_code == 404


def test_a_bad_self_hosted_url_never_leaves_the_box(client):
    """n8n's host is user-supplied. Refuse a non-http scheme before any
    outbound request is made with it."""
    c, _, sent, _ = client
    r = c.post("/connections/n8n",
               json={"values": {"base_url": "file:///etc/passwd",
                                "api_key": "K"}})
    assert r.status_code == 400
    assert sent == []


def test_fields_the_provider_did_not_ask_for_are_dropped(client):
    c, store, _, _ = client
    c.post("/connections/clickup",
           json={"values": {"token": SECRET, "evil": "injected"}})
    import crypto_utils
    stored = json.loads(crypto_utils.decrypt(store["clickup"]["blob"]))
    assert stored == {"token": SECRET}


# --- the credential does not come back out --------------------------------

def test_the_secret_is_not_in_the_connect_response(client):
    c, _, _, _ = client
    r = c.post("/connections/clickup", json={"values": {"token": SECRET}})
    assert SECRET not in r.text


def test_the_secret_is_not_in_the_listing(client):
    c, _, _, _ = client
    c.post("/connections/clickup", json={"values": {"token": SECRET}})
    assert SECRET not in c.get("/connections").text


def test_the_secret_is_not_in_a_rejection_message(client):
    c, _, _, reply = client
    reply["response"] = _FakeResponse(401, {})
    r = c.post("/connections/clickup", json={"values": {"token": SECRET}})
    assert SECRET not in r.text


def test_the_secret_is_not_in_an_unreachable_vendor_message(client):
    """Trello puts the credential in the query string, so an exception that
    carries the URL carries the token with it."""
    c, _, _, reply = client
    reply["response"] = RuntimeError(
        "connect failed for https://api.trello.com/1/members/me"
        "?key=KEY123&token=" + SECRET)
    r = c.post("/connections/trello",
               json={"values": {"api_key": "KEY123", "token": SECRET}})
    assert r.status_code == 502
    assert SECRET not in r.text and "KEY123" not in r.text


def test_the_secret_is_not_in_the_log(client, caplog):
    c, _, _, reply = client
    reply["response"] = _FakeResponse(418, {})
    with caplog.at_level("DEBUG"):
        c.post("/connections/clickup", json={"values": {"token": SECRET}})
    assert SECRET not in caplog.text


def test_what_is_stored_is_encrypted_not_the_raw_value(client):
    c, store, _, _ = client
    c.post("/connections/clickup", json={"values": {"token": SECRET}})
    assert SECRET not in store["clickup"]["blob"]


# --- disconnect and round trip --------------------------------------------

def test_disconnecting_removes_it(client):
    c, store, _, _ = client
    c.post("/connections/clickup", json={"values": {"token": SECRET}})
    assert c.delete("/connections/clickup").json()["connected"] is False
    assert store == {}


async def test_the_stored_credential_can_be_read_back_for_use(client,
                                                              monkeypatch):
    """The only reason to decrypt: making a request as that user. Proves the
    round trip so the execution work has a foundation it can trust."""
    c, store, _, _ = client
    c.post("/connections/clickup", json={"values": {"token": SECRET}})
    got = await R.secrets_for(EMAIL, "clickup")
    assert got == {"token": SECRET}


async def test_reading_back_a_credential_nobody_stored_is_empty(client):
    assert await R.secrets_for(EMAIL, "github") == {}


# --- Zapier is the odd one out: its check writes ---------------------------

def test_connecting_zapier_sends_a_test_payload_to_the_users_hook(client):
    """Not a GET, and not to a vendor identity endpoint. The Catch Hook IS the
    credential, and sending it one payload is how Zapier's own setup step
    proves a hook is live."""
    c, store, sent, reply = client
    reply["response"] = _FakeResponse(200, {"status": "success"})
    hook = "https://hooks.zapier.com/hooks/catch/123456/abcdef/"
    r = c.post("/connections/zapier", json={"values": {"webhook_url": hook}})
    assert r.status_code == 200
    assert sent[0]["method"] == "POST"
    assert sent[0]["url"].startswith("https://hooks.zapier.com/hooks/catch/")
    assert sent[0]["json"], "no test payload was sent"


def test_a_url_that_is_not_a_zapier_hook_never_leaves_the_box(client):
    """This posts to an address the user typed. Accepting any URL would make
    the connect form a request-forgery primitive pointed at our own network."""
    c, _, sent, _ = client
    for bad in ("http://169.254.169.254/latest/meta-data/",
                "https://example.com/hooks/catch/1/a/",
                "http://localhost:8210/api/projects"):
        r = c.post("/connections/zapier", json={"values": {"webhook_url": bad}})
        assert r.status_code == 400, bad
    assert sent == []


def test_airtable_is_checked_against_airtable(client):
    c, _, sent, reply = client
    reply["response"] = _FakeResponse(200, {"id": "usr123", "email": "r@example.com"})
    r = c.post("/connections/airtable", json={"values": {"token": "patX"}})
    assert r.status_code == 200
    assert r.json()["account_label"] == "r@example.com"
    assert sent[0]["method"] == "GET"
    assert "api.airtable.com" in sent[0]["url"]


def test_hubspot_is_checked_against_hubspot(client):
    c, _, sent, reply = client
    reply["response"] = _FakeResponse(200, {"portalId": 987654})
    r = c.post("/connections/hubspot", json={"values": {"token": "pat-na1-x"}})
    assert r.status_code == 200
    assert "987654" in r.json()["account_label"]
    assert "api.hubapi.com" in sent[0]["url"]


def test_asana_is_gone(client):
    c, _, _, _ = client
    ids = {x["provider"] for x in c.get("/connections").json()["connections"]}
    assert "asana" not in ids
    assert {"airtable", "hubspot", "zapier"} <= ids
