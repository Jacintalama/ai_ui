"""AIUI links itself into a person's n8n, and builds steps that use their
connections (2026-11-19).

`link_aiui` makes an AIUI key with the `tools` scope and stores it in the
person's own n8n as a credential called "AIUI", using the n8n connection
they already have. The key never comes back in the answer: a chat must
never show it. A workflow AIUI builds then calls
`/api/tasks/tools/run` through an httpRequest node holding that
credential, and approving the workflow approves its write steps on the
key, which is the only way a write becomes runnable from n8n.
"""
import asyncio
import json
import types

import httpx
import pytest

import aiui_link
import automation_keys
import mytools
import n8n_nodes

OWNER = "a@example.com"
AUTH = types.SimpleNamespace(base_url="https://n8n.example.com",
                             headers={"X-N8N-API-KEY": "n8n-key"},
                             params={})


def _step(app, tool, cred="c1"):
    node = {"id": "s1", "name": "AIUI " + tool,
            "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.4,
            "position": [0, 0],
            "parameters": {"method": "POST", "url": aiui_link.RUN_URL,
                           "jsonBody": json.dumps({"app": app, "tool": tool,
                                                   "args": {}})}}
    if cred:
        node["credentials"] = {"httpHeaderAuth": {"id": cred, "name": "AIUI"}}
    return node


def _http(url):
    return {"id": "h", "name": "Call", "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.4, "position": [0, 0],
            "parameters": {"url": url}}


class _Keys:
    def __init__(self):
        self.made_scopes = None
        self.revoked = []
        self.last_id = None
        self.current = None
        self.allowed = {}
        self.allowed_calls = []
        self.remembered = {}
        self.made_key = None

    def existing(self, credential_id, key_id="old", allowed=None):
        self.current = {"id": key_id, "email": OWNER, "scopes": ["tools"],
                        "allowed_writes": list(allowed or []),
                        "n8n_credential_id": credential_id}


@pytest.fixture
def fake_keys(monkeypatch):
    k = _Keys()

    async def create(email, label, scopes=("agents",)):
        k.made_scopes = tuple(scopes)
        k.last_id = "new"
        k.made_key = "iok_" + "n" * 32
        return {"id": "new", "label": label, "key": k.made_key}

    async def revoke(email, key_id):
        k.revoked.append(key_id)
        return True

    async def n8n_key(email):
        return k.current

    async def remember(email, key_id, credential_id):
        k.remembered[key_id] = credential_id

    async def allow(email, key_id, steps):
        k.allowed_calls.append((key_id, list(steps)))
        k.allowed.setdefault(key_id, []).extend(steps)

    monkeypatch.setattr(automation_keys, "create", create)
    monkeypatch.setattr(automation_keys, "revoke", revoke)
    monkeypatch.setattr(automation_keys, "n8n_key", n8n_key)
    monkeypatch.setattr(automation_keys, "remember_n8n_credential", remember)
    monkeypatch.setattr(automation_keys, "allow_writes", allow)
    return k


class _N8n:
    def __init__(self):
        self.posted = None
        self.url = None
        self.headers = None
        self.status = 200
        self.error = None


@pytest.fixture
def fake_n8n(monkeypatch):
    n = _N8n()

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            if n.error:
                raise n.error
            n.posted, n.url, n.headers = json, url, headers
            return httpx.Response(n.status, json={"id": "cred-42",
                                                  "name": "AIUI"},
                                  request=httpx.Request("POST", url))
    monkeypatch.setattr(aiui_link.httpx, "AsyncClient", _Client)
    return n


# --- the step itself ----------------------------------------------------------

def test_the_aiui_step_shape_is_in_the_catalogue_and_points_at_our_url():
    shape = n8n_nodes.NODES["aiuiTool"]
    assert shape.type == "n8n-nodes-base.httpRequest"
    assert shape.parameters["url"] == aiui_link.RUN_URL
    assert shape.parameters["genericAuthType"] == "httpHeaderAuth"
    assert "link_aiui" in shape.summary


def test_the_run_url_is_ours_and_not_from_a_request():
    assert aiui_link.RUN_URL.endswith("/api/tasks/tools/run")
    assert aiui_link.RUN_URL.startswith("https://")


def test_step_target_reads_app_and_tool():
    assert aiui_link.step_target(_step("github", "review_pull_request")) == (
        "github", "review_pull_request")


def test_step_target_reads_a_body_given_as_an_object():
    node = _step("trello", "create_card")
    node["parameters"]["jsonBody"] = {"app": "trello", "tool": "create_card"}
    assert aiui_link.step_target(node) == ("trello", "create_card")


def test_step_target_ignores_other_http_nodes():
    assert aiui_link.step_target(_http("https://example.com")) is None


def test_step_target_ignores_a_body_it_cannot_read():
    node = _step("github", "x")
    node["parameters"]["jsonBody"] = "={{ $json.body }}"
    assert aiui_link.step_target(node) is None


def test_a_step_with_no_credential_is_refused_with_the_right_shape():
    with pytest.raises(ValueError) as e:
        aiui_link.check_steps([_step("github", "list_my_repos", cred=None)])
    assert "httpHeaderAuth" in str(e.value) and "link_aiui" in str(e.value)


def test_a_step_with_a_credential_passes():
    aiui_link.check_steps([_step("github", "list_my_repos")])


def test_the_n8n_check_refuses_it_too():
    with pytest.raises(ValueError):
        mytools._n8n_check([_step("github", "list_my_repos", cred=None)], {})


# --- linking ------------------------------------------------------------------

async def test_link_makes_a_tools_key_and_an_n8n_credential(fake_keys, fake_n8n):
    out = await aiui_link.link(OWNER, AUTH, {})
    assert fake_keys.made_scopes == ("tools",)
    assert fake_n8n.url == "https://n8n.example.com/api/v1/credentials"
    assert fake_n8n.headers == AUTH.headers
    assert fake_n8n.posted["type"] == "httpHeaderAuth"
    assert fake_n8n.posted["name"] == "AIUI"
    assert fake_n8n.posted["data"] == {"name": "Authorization",
                                       "value": "Bearer " + fake_keys.made_key}
    assert out["ok"] is True and out["made"] is True
    assert out["credential"] == {"id": "cred-42", "name": "AIUI"}
    assert fake_keys.remembered == {"new": "cred-42"}
    assert "iok_" not in json.dumps(out)


async def test_link_reuses_a_live_credential(fake_keys, fake_n8n):
    fake_keys.existing("c9")
    out = await aiui_link.link(OWNER, AUTH, {})
    assert out["credential"]["id"] == "c9" and out["made"] is False
    assert fake_n8n.posted is None and fake_keys.made_scopes is None


async def test_link_revokes_its_key_when_n8n_refuses(fake_keys, fake_n8n):
    fake_n8n.status = 403
    out = await aiui_link.link(OWNER, AUTH, {})
    assert out["ok"] is False
    assert fake_keys.revoked == ["new"]
    assert "permission to create credentials" in out["error"]
    assert "iok_" not in json.dumps(out)


async def test_link_revokes_its_key_when_n8n_is_unreachable(fake_keys, fake_n8n):
    fake_n8n.error = httpx.ConnectError("down")
    out = await aiui_link.link(OWNER, AUTH, {})
    assert out["ok"] is False and fake_keys.revoked == ["new"]


async def test_link_again_replaces_and_carries_the_approvals(fake_keys, fake_n8n):
    fake_keys.existing("c9", key_id="old",
                       allowed=["github.review_pull_request"])
    out = await aiui_link.link(OWNER, AUTH, {"again": True})
    assert out["made"] is True
    assert fake_keys.allowed["new"] == ["github.review_pull_request"]
    assert fake_keys.revoked == ["old"]


async def test_link_after_the_key_was_revoked_makes_a_new_one(fake_keys, fake_n8n):
    fake_keys.current = None      # a revoked key is not a live one
    out = await aiui_link.link(OWNER, AUTH, {})
    assert out["made"] is True and fake_n8n.posted is not None


async def test_too_many_keys_says_so(fake_keys, fake_n8n, monkeypatch):
    async def create(email, label, scopes=("agents",)):
        raise automation_keys.TooManyKeys()
    monkeypatch.setattr(automation_keys, "create", create)
    out = await aiui_link.link(OWNER, AUTH, {})
    assert out["ok"] is False and "Revoke" in out["error"]
    assert fake_n8n.posted is None


# --- approving steps ------------------------------------------------------------

async def test_building_a_workflow_approves_its_write_steps(fake_keys):
    fake_keys.existing("c1", key_id="k1")
    got = await aiui_link.approve_steps(OWNER, [
        _step("github", "review_pull_request"),
        _step("github", "list_my_repos"),
        _http("https://x")])
    assert got == ["github.review_pull_request"]
    assert fake_keys.allowed_calls == [("k1", ["github.review_pull_request"])]


async def test_a_step_naming_an_unknown_tool_is_not_approved(fake_keys):
    fake_keys.existing("c1", key_id="k1")
    assert await aiui_link.approve_steps(OWNER, [_step("github", "nope")]) == []


async def test_removing_a_step_does_not_shrink_or_crash(fake_keys):
    fake_keys.existing("c1", key_id="k1", allowed=["github.create_issue"])
    assert await aiui_link.approve_steps(OWNER, []) == []
    assert fake_keys.allowed_calls == []


async def test_no_linked_key_approves_nothing(fake_keys):
    fake_keys.current = None
    got = await aiui_link.approve_steps(
        OWNER, [_step("github", "review_pull_request")])
    assert got == [] and fake_keys.allowed_calls == []


# --- wired into mytools ------------------------------------------------------------

def test_link_aiui_is_an_n8n_tool_and_a_write():
    t = {t.name: t for t in mytools.N8N_TOOLS}["link_aiui"]
    assert mytools._writes(t) is True
    assert t.act is aiui_link.link


def _n8n_world(monkeypatch, status=200):
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
            return httpx.Response(status, json={"id": "w1", "name": "x",
                                                "active": False},
                                  request=httpx.Request(method, url))
    monkeypatch.setattr(mytools.httpx, "AsyncClient", _Client)

    async def no_guard(url):
        return ""
    monkeypatch.setattr(mytools.host_guard, "problem", no_guard)


def _workflow():
    trigger = {"id": "t", "name": "Start", "type": "n8n-nodes-base.manualTrigger",
               "typeVersion": 1, "position": [0, 0], "parameters": {}}
    step = _step("github", "review_pull_request")
    return {"name": "Approve PRs", "nodes": [trigger, step],
            "connections": {"Start": {"main": [[{"node": step["name"],
                                                  "type": "main",
                                                  "index": 0}]]}}}


def test_creating_a_workflow_approves_its_steps(monkeypatch):
    _n8n_world(monkeypatch)
    seen = {}

    async def approve(email, nodes):
        seen["email"], seen["nodes"] = email, nodes
        return ["github.review_pull_request"]
    monkeypatch.setattr(aiui_link, "approve_steps", approve)
    tool = {t.name: t for t in mytools.N8N_TOOLS}["create_workflow"]
    out = asyncio.run(mytools._call("n8n", tool, OWNER, _workflow()))
    assert out["ok"] is True
    assert seen["email"] == OWNER and len(seen["nodes"]) == 2
    assert out["approved_steps"] == ["github.review_pull_request"]


def test_a_failed_approval_does_not_fail_the_build(monkeypatch):
    _n8n_world(monkeypatch)

    async def approve(email, nodes):
        raise RuntimeError("db down")
    monkeypatch.setattr(aiui_link, "approve_steps", approve)
    tool = {t.name: t for t in mytools.N8N_TOOLS}["create_workflow"]
    out = asyncio.run(mytools._call("n8n", tool, OWNER, _workflow()))
    assert out["ok"] is True


def test_a_refused_build_approves_nothing(monkeypatch):
    _n8n_world(monkeypatch, status=400)
    called = []

    async def approve(email, nodes):
        called.append(1)
        return []
    monkeypatch.setattr(aiui_link, "approve_steps", approve)
    tool = {t.name: t for t in mytools.N8N_TOOLS}["create_workflow"]
    out = asyncio.run(mytools._call("n8n", tool, OWNER, _workflow()))
    assert out["ok"] is False and not called


def test_calling_link_aiui_through_call_reaches_the_action(monkeypatch):
    _n8n_world(monkeypatch)
    seen = {}

    async def act(email, auth, args):
        seen["email"], seen["base"] = email, auth.base_url
        return {"ok": True, "made": False}
    tool = {t.name: t for t in mytools.N8N_TOOLS}["link_aiui"]
    import dataclasses
    patched = dataclasses.replace(tool, act=act)
    out = asyncio.run(mytools._call("n8n", patched, OWNER, {}))
    assert out == {"ok": True, "made": False}
    assert seen["email"] == OWNER and seen["base"].startswith("https://n8n.example.com")
