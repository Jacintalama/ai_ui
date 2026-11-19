"""n8n runs ONE AIUI tool with the person's own connection (2026-11-19).

    POST /api/tasks/tools/run
    Authorization: Bearer iok_...      (a key with the `tools` scope)
    {"app": "github", "tool": "list_my_repos", "args": {}}

What has to hold: the vendor credential never leaves AIUI, a key made to
run agents cannot run tools, a read always runs, a write runs only once
the person approved a workflow AIUI built with that step, nothing that
changes n8n itself can be reached from a key sitting in n8n, every failure
is a status n8n marks as failed, and nothing a tool read or was given is
written to a log.
"""
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import automation_keys
import mytools
import routes_tool_run as rt

AUTH = {"Authorization": "Bearer iok_" + "a" * 32}
OWNER = "a@example.com"


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(rt.router)
    return TestClient(app)


@pytest.fixture
def owner(monkeypatch):
    def set_owner(**kw):
        row = {"id": "k", "email": OWNER, "scopes": ["tools"],
               "allowed_writes": [], "n8n_credential_id": "c"}
        row.update(kw)

        async def owner_for(key):
            return row
        monkeypatch.setattr(automation_keys, "owner_for", owner_for)
    return set_owner


@pytest.fixture
def secrets(monkeypatch):
    holder = {"value": {"token": "t" * 20}}

    async def secrets_for(email, provider):
        return holder["value"]
    monkeypatch.setattr(mytools, "_secrets_for", secrets_for)

    def set_secrets(value):
        holder["value"] = value
    return set_secrets


class _Call:
    def __init__(self):
        self.calls = []
        self.result = {"ok": True}

    def returns(self, result):
        self.result = result


@pytest.fixture
def call(monkeypatch, secrets):
    c = _Call()

    async def fake_call(provider_id, tool, email, args):
        c.calls.append((provider_id, tool.name, email, args))
        return c.result
    monkeypatch.setattr(mytools, "_call", fake_call)
    return c


class _Google:
    def __init__(self):
        self.calls = []
        self.status = 200
        self.payload = {}
        self.error = None

    def returns(self, status, payload):
        self.status, self.payload = status, payload

    def raises(self, error):
        self.error = error


@pytest.fixture
def google(monkeypatch):
    g = _Google()

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            g.calls.append({"url": url, "headers": headers or {}, "json": json})
            if g.error:
                raise g.error
            return httpx.Response(g.status, json=g.payload,
                                  request=httpx.Request("POST", url))
    monkeypatch.setattr(rt.httpx, "AsyncClient", _Client)
    return g


def _post(client, app, tool, args=None):
    return client.post("/tools/run", headers=AUTH,
                       json={"app": app, "tool": tool, "args": args or {}})


REVIEW = {"owner": "o", "repo": "r", "number": 1, "event": "APPROVE"}


def test_no_key_is_401(client):
    r = client.post("/tools/run", json={"app": "github", "tool": "list_my_repos"})
    assert r.status_code == 401


def test_a_revoked_or_unknown_key_is_401(client, monkeypatch):
    async def owner_for(key):
        return None
    monkeypatch.setattr(automation_keys, "owner_for", owner_for)
    assert _post(client, "github", "list_my_repos").status_code == 401


def test_an_agents_only_key_is_403(client, owner, call):
    owner(scopes=["agents"])
    r = _post(client, "github", "list_my_repos")
    assert r.status_code == 403 and "cannot run tools" in r.text
    assert not call.calls


def test_a_read_runs_and_returns_the_tool_result(client, owner, call):
    owner()
    call.returns({"ok": True, "result": [1]})
    r = _post(client, "github", "list_my_repos")
    assert r.status_code == 200 and r.json()["result"] == [1]
    assert call.calls[0][:3] == ("github", "list_my_repos", OWNER)


def test_an_unapproved_write_is_403_and_never_called(client, owner, call):
    owner()
    r = _post(client, "github", "review_pull_request", REVIEW)
    assert r.status_code == 403 and "not approved in AIUI" in r.text
    assert not call.calls


def test_an_approved_write_runs(client, owner, call):
    owner(allowed_writes=["github.review_pull_request"])
    assert _post(client, "github", "review_pull_request", REVIEW).status_code == 200
    assert call.calls[0][1] == "review_pull_request"


def test_an_approval_for_one_app_does_not_cover_another(client, owner, call):
    owner(allowed_writes=["github.create_issue"])
    r = _post(client, "trello", "create_card", {"list_id": "l", "name": "n"})
    assert r.status_code == 403 and not call.calls


def test_n8n_tools_are_never_run_from_a_key(client, owner, call):
    owner(allowed_writes=["n8n.delete_workflow"])
    r = _post(client, "n8n", "delete_workflow", {"workflow_id": "1"})
    assert r.status_code == 403 and not call.calls


def test_n8n_reads_are_not_run_from_a_key_either(client, owner, call):
    owner()
    assert _post(client, "n8n", "list_workflows").status_code == 403


def test_unknown_tool_is_404_and_lists_the_apps_tools(client, owner):
    owner()
    r = _post(client, "github", "merge_everything")
    assert r.status_code == 404 and "list_my_repos" in r.text


def test_unknown_app_is_404_and_lists_the_apps(client, owner):
    owner()
    r = _post(client, "myspace", "post")
    assert r.status_code == 404 and "github" in r.text


def test_a_missing_required_argument_is_422_before_the_vendor(client, owner, call):
    owner(allowed_writes=["github.review_pull_request"])
    r = _post(client, "github", "review_pull_request", {"owner": "o"})
    assert r.status_code == 422 and "repo" in r.text and "number" in r.text
    assert not call.calls


def test_not_connected_is_409(client, owner, call, secrets):
    owner()
    secrets({})
    r = _post(client, "trello", "list_my_boards")
    assert r.status_code == 409 and "not connected your Trello" in r.text
    assert not call.calls


def test_a_tool_refusal_is_422_with_its_words(client, owner, call):
    owner()
    call.returns({"ok": False, "error": "No such board."})
    r = _post(client, "trello", "list_my_boards")
    assert r.status_code == 422 and "No such board." in r.text


def test_args_that_are_not_an_object_are_422(client, owner, call):
    owner()
    r = client.post("/tools/run", headers=AUTH,
                    json={"app": "github", "tool": "list_my_repos", "args": "{}"})
    assert r.status_code == 422 and "JSON object" in r.text
    assert not call.calls


def test_a_sheet_is_read_through_drive_as_the_owner(client, owner, google):
    owner()
    google.returns(200, {"content": "a,b"})
    r = _post(client, "gdrive", "gdrive_read_file", {"file_id": "x"})
    assert r.status_code == 200 and r.json() == {"content": "a,b"}
    sent = google.calls[-1]
    assert sent["headers"]["X-User-Email"] == OWNER
    assert sent["url"].endswith("/gdrive_read_file")
    assert sent["json"] == {"file_id": "x"}


def test_a_google_write_is_404(client, owner, google):
    owner()
    assert _post(client, "gdrive", "gdrive_create_file").status_code == 404
    assert not google.calls


def test_google_not_connected_is_409(client, owner, google):
    owner()
    google.returns(401, {"detail": "Not authenticated with Google"})
    r = _post(client, "gmail", "gmail_search_emails", {"query": "x"})
    assert r.status_code == 409 and "not connected" in r.text


def test_google_down_is_502(client, owner, google):
    owner()
    google.raises(httpx.ConnectError("x"))
    r = _post(client, "gdrive", "gdrive_read_file", {"file_id": "x"})
    assert r.status_code == 502 and "did not answer" in r.text


def test_arguments_and_results_are_not_logged(client, owner, call, caplog):
    owner()
    call.returns({"ok": True, "result": "SECRET-RESULT"})
    with caplog.at_level("DEBUG"):
        _post(client, "github", "list_my_repos", {"q": "SECRET-ARG"})
    assert "SECRET" not in caplog.text
    assert OWNER not in caplog.text


def test_the_route_is_mounted_under_api_tasks():
    import pathlib
    src = (pathlib.Path(rt.__file__).parent / "main.py").read_text(encoding="utf-8")
    assert "routes_tool_run" in src


def test_google_saying_not_connected_in_a_200_is_409(client, owner, google):
    """mcp-gdrive answers a person with no token 200 {"error": "Google Drive
    is not connected. Please visit..."}: a 200 a workflow would treat as
    success. It is a 409 here, in our words, not theirs."""
    owner()
    google.returns(200, {"error": "Google Drive is not connected. Please "
                                  "visit the following URL to connect: x"})
    r = _post(client, "gdrive", "gdrive_read_file", {"file_id": "x"})
    assert r.status_code == 409 and "Please visit" not in r.text


def test_google_any_other_error_in_a_200_is_422(client, owner, google):
    owner()
    google.returns(200, {"error": "File not found"})
    r = _post(client, "gdrive", "gdrive_read_file", {"file_id": "x"})
    assert r.status_code == 422 and "File not found" in r.text
