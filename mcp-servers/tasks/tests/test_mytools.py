"""Tools that run as YOU, not as the platform.

The vendor MCP containers take one token from boot-time env, so every ClickUp
call the platform makes is made as whoever owns that token. On this deployment
that is one specific person: the shared ClickUp credential belongs to Lukas
Herajt, so a tool call by any user creates tasks as him. Connecting your own
account stored a credential but changed none of that, because execution still
went through those containers.

This is the layer that closes it. mcp-proxy already forwards the resolved
end-user email to local servers (that is how Gmail and Drive load the right
person's OAuth), so a server hosted here can look up THAT user's credential and
call the vendor's REST API directly as them.

What these tests pin down:

  - a caller who never connected gets a sentence telling them to connect, not
    an unsigned request and a confusing vendor 401
  - one user's call never picks up another user's credential
  - the credential is never echoed into a tool result, which matters more here
    than at connect time because tool results are fed straight to a model and
    then rendered into a chat
  - every tool is discoverable by mcp-proxy, which reads a plain OpenAPI
    document and indexes POST paths
"""
import json

import pytest
from fastapi.testclient import TestClient

import mytools


@pytest.fixture
def app_and_creds(monkeypatch):
    """The tool app, with the credential store and the vendor both faked."""
    creds = {}          # (email, provider) -> dict
    calls = []          # every outbound vendor request
    reply = {"response": None}

    async def _fake_secrets(email, provider):
        return creds.get((email, provider), {})

    monkeypatch.setattr(mytools, "_secrets_for", _fake_secrets)

    class _Resp:
        def __init__(self, status_code=200, payload=None, text=""):
            self.status_code = status_code
            self._payload = payload if payload is not None else {}
            self.text = text or json.dumps(self._payload)

        def json(self):
            return self._payload

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def request(self, method, url, headers=None, params=None,
                          json=None):
            calls.append({"method": method, "url": url,
                          "headers": headers or {}, "params": params or {},
                          "json": json})
            r = reply["response"]
            if isinstance(r, Exception):
                raise r
            return r if r is not None else _Resp(200, {"ok": True})

    monkeypatch.setattr(mytools.httpx, "AsyncClient", _FakeClient)

    return mytools.build_app(), creds, calls, reply, _Resp


def _post(app, path, email, body=None):
    with TestClient(app) as c:
        return c.post(path, json=body or {},
                      headers={"X-User-Email": email})


# --- discoverability: mcp-proxy reads an OpenAPI document -----------------

def test_each_provider_serves_its_own_openapi(app_and_creds):
    app, _, _, _, _ = app_and_creds
    with TestClient(app) as c:
        for pid in mytools.PROVIDER_TOOLS:
            r = c.get("/" + pid + "/openapi.json")
            assert r.status_code == 200, pid
            assert r.json().get("paths"), pid


def test_every_tool_is_a_post_path_so_the_proxy_indexes_it(app_and_creds):
    """refresh_tools_cache only picks up POST paths. A GET tool would be
    invisible: present, callable, and never found by search."""
    app, _, _, _, _ = app_and_creds
    with TestClient(app) as c:
        for pid, tools in mytools.PROVIDER_TOOLS.items():
            paths = c.get("/" + pid + "/openapi.json").json()["paths"]
            assert len(paths) == len(tools), pid
            for path, methods in paths.items():
                assert set(methods) == {"post"}, (pid, path)


def test_every_tool_says_what_it_does(app_and_creds):
    """The description is what semantic search matches against. A tool with no
    summary is indexed as its own name and is effectively unfindable."""
    app, _, _, _, _ = app_and_creds
    with TestClient(app) as c:
        for pid in mytools.PROVIDER_TOOLS:
            for path, m in c.get("/" + pid + "/openapi.json").json()["paths"].items():
                summary = m["post"].get("summary") or m["post"].get("description")
                assert summary and len(summary) > 15, (pid, path)


def test_tool_names_do_not_collide_across_providers(app_and_creds):
    """mcp-proxy keys its cache on server_id + path, but a duplicate name
    across two of our own servers is still a confusing thing to search."""
    seen = set()
    for pid, tools in mytools.PROVIDER_TOOLS.items():
        for t in tools:
            key = pid + ":" + t.name
            assert key not in seen
            seen.add(key)


# --- not connected is a sentence, not a vendor error ----------------------

def test_a_caller_who_never_connected_is_told_to_connect(app_and_creds):
    app, _, calls, _, _ = app_and_creds
    r = _post(app, "/github/list_my_repos", "nobody@example.com")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "connect" in body["error"].lower()
    assert "GitHub" in body["error"]


def test_nothing_is_sent_to_the_vendor_when_there_is_no_credential(app_and_creds):
    """An unsigned request would come back as a vendor 401, which reads to the
    model as "your GitHub is broken" rather than "you have not connected"."""
    app, _, calls, _, _ = app_and_creds
    _post(app, "/github/list_my_repos", "nobody@example.com")
    assert calls == []


def test_an_identified_caller_is_required(app_and_creds):
    app, _, _, _, _ = app_and_creds
    with TestClient(app) as c:
        assert c.post("/github/list_my_repos", json={}).status_code == 401


# --- the call goes out signed as the right person -------------------------

def test_the_call_is_signed_with_the_callers_own_credential(app_and_creds):
    app, creds, calls, _, _ = app_and_creds
    creds[("ralph@example.com", "github")] = {"token": "RALPH_TOKEN"}
    _post(app, "/github/list_my_repos", "ralph@example.com")
    assert calls[0]["headers"]["Authorization"] == "Bearer RALPH_TOKEN"


def test_one_users_call_never_picks_up_anothers_credential(app_and_creds):
    """The whole point of the feature. Two users, two tokens, no crossover."""
    app, creds, calls, _, _ = app_and_creds
    creds[("a@example.com", "github")] = {"token": "TOKEN_A"}
    creds[("b@example.com", "github")] = {"token": "TOKEN_B"}
    _post(app, "/github/list_my_repos", "a@example.com")
    _post(app, "/github/list_my_repos", "b@example.com")
    assert calls[0]["headers"]["Authorization"] == "Bearer TOKEN_A"
    assert calls[1]["headers"]["Authorization"] == "Bearer TOKEN_B"


def test_the_call_goes_to_the_right_vendor(app_and_creds):
    app, creds, calls, _, _ = app_and_creds
    creds[("ralph@example.com", "github")] = {"token": "T"}
    creds[("ralph@example.com", "clickup")] = {"token": "T"}
    _post(app, "/github/list_my_repos", "ralph@example.com")
    _post(app, "/clickup/list_my_workspaces", "ralph@example.com")
    assert "api.github.com" in calls[0]["url"]
    assert "api.clickup.com" in calls[1]["url"]


def test_a_self_hosted_provider_calls_the_users_own_host(app_and_creds):
    app, creds, calls, _, _ = app_and_creds
    creds[("ralph@example.com", "n8n")] = {
        "base_url": "https://n8n.ralph.example", "api_key": "K"}
    _post(app, "/n8n/list_my_workflows", "ralph@example.com")
    assert calls[0]["url"].startswith("https://n8n.ralph.example/")


# --- the credential does not come back in a tool result -------------------

def test_a_vendor_rejection_does_not_echo_the_credential(app_and_creds):
    """A tool result is handed straight to a model and then rendered into a
    chat, so a leak here is worse than one at connect time."""
    app, creds, _, reply, Resp = app_and_creds
    creds[("ralph@example.com", "trello")] = {"api_key": "KEY123",
                                              "token": "TOK456"}
    reply["response"] = Resp(401, {}, text="invalid key KEY123 token TOK456")
    r = _post(app, "/trello/list_my_boards", "ralph@example.com")
    assert "KEY123" not in r.text and "TOK456" not in r.text


def test_an_unreachable_vendor_does_not_echo_the_credential(app_and_creds):
    app, creds, _, reply, _ = app_and_creds
    creds[("ralph@example.com", "trello")] = {"api_key": "KEY123",
                                              "token": "TOK456"}
    reply["response"] = RuntimeError(
        "failed https://api.trello.com/1/members/me/boards?key=KEY123&token=TOK456")
    r = _post(app, "/trello/list_my_boards", "ralph@example.com")
    assert "KEY123" not in r.text and "TOK456" not in r.text


def test_any_vendor_error_status_does_not_echo_the_credential(app_and_creds):
    """Not just 401. A 400 or 422 from ClickUp echoes the request it rejected,
    and for Trello the request line contains the key and the token. The first
    version of the test above used 401, which returns before this branch, so
    the generic branch could leak while the suite stayed green."""
    app, creds, _, reply, Resp = app_and_creds
    creds[("ralph@example.com", "trello")] = {"api_key": "KEY123",
                                              "token": "TOK456"}
    for status in (400, 409, 422, 429, 500, 503):
        reply["response"] = Resp(
            status, {"message": "bad request"},
            text="rejected GET /1/members/me/boards?key=KEY123&token=TOK456")
        r = _post(app, "/trello/list_my_boards", "ralph@example.com")
        assert "KEY123" not in r.text, status
        assert "TOK456" not in r.text, status


def test_a_rejection_tells_the_user_the_credential_is_the_problem(app_and_creds):
    app, creds, _, reply, Resp = app_and_creds
    creds[("ralph@example.com", "github")] = {"token": "T"}
    reply["response"] = Resp(401, {})
    body = _post(app, "/github/list_my_repos", "ralph@example.com").json()
    assert body["ok"] is False
    assert "reconnect" in body["error"].lower() or "expired" in body["error"].lower()


def test_a_tool_never_returns_a_5xx_to_the_model(app_and_creds):
    """A model handles {"ok": false, "error": "..."} far better than an HTTP
    error, which surfaces as a tool-call failure with no usable detail."""
    app, creds, _, reply, _ = app_and_creds
    creds[("ralph@example.com", "github")] = {"token": "T"}
    reply["response"] = RuntimeError("boom")
    r = _post(app, "/github/list_my_repos", "ralph@example.com")
    assert r.status_code == 200
    assert r.json()["ok"] is False


# --- results are shaped for a model, not dumped raw -----------------------

def test_a_successful_result_is_marked_ok(app_and_creds):
    app, creds, _, reply, Resp = app_and_creds
    creds[("ralph@example.com", "github")] = {"token": "T"}
    reply["response"] = Resp(200, [{"full_name": "thunder500/ai_ui",
                                    "private": False,
                                    "html_url": "https://github.com/x",
                                    "description": "d",
                                    "updated_at": "2026-08-19"}])
    body = _post(app, "/github/list_my_repos", "ralph@example.com").json()
    assert body["ok"] is True
    assert body["items"][0]["full_name"] == "thunder500/ai_ui"


def test_a_huge_vendor_response_is_trimmed(app_and_creds):
    """Whole API payloads blow a model's context and bury the answer. ClickUp
    alone returns dozens of fields per task."""
    app, creds, _, reply, Resp = app_and_creds
    creds[("ralph@example.com", "github")] = {"token": "T"}
    reply["response"] = Resp(200, [
        {"full_name": "r/" + str(i), "private": False, "html_url": "u",
         "description": "d", "updated_at": "t", "noise": "x" * 500}
        for i in range(200)])
    body = _post(app, "/github/list_my_repos", "ralph@example.com").json()
    assert len(body["items"]) <= mytools.MAX_ITEMS
    assert "noise" not in json.dumps(body)
