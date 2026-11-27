"""A caller's own MCP tools, added to what THAT caller can search, describe
and call, and to nobody else's.

The /meta/* routes are public and are where the anonymous-caller hole was
(test_meta_access.py). So the most important tests here are the isolation
ones: person B, using person A's exact words and tool names, gets exactly
what B would get if A's tools did not exist.

Design: docs/superpowers/specs/2026-11-26-own-mcp-servers-design.md, section 5.
"""
import asyncio
import json

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

import main
import own_tools
import tenants

A = "a@x.com"
B = "b@x.com"
SECRET = "internal-secret-for-tests"

A_TOOLS = {
    "own-acme_create_invoice": {
        "name": "own-acme_create_invoice", "description": "Create an invoice in Acme",
        "request_body": {"content": {"application/json": {"schema": {"type": "object"}}}},
        "server_id": "own-acme", "server_name": "Acme", "read_only": False},
    "own-acme_list_customers": {
        "name": "own-acme_list_customers", "description": "List Acme customers",
        "request_body": {"content": {"application/json": {"schema": {"type": "object"}}}},
        "server_id": "own-acme", "server_name": "Acme", "read_only": True},
}

BUILT = {"tool_name": "github_list_repos", "server_id": "github",
         "display_name": "list_repos", "description": "List repositories",
         "relevance_score": 0.61}


class _User:
    def __init__(self, email):
        self.email = email
        self.entra_groups = None


@pytest.fixture
def proxy(monkeypatch):
    seen = {"forwarded": [], "own_asked": []}

    async def who(request):
        email = request.headers.get("x-user-email")
        return _User(email) if email else None

    async def tenants_of(email, groups=None):
        return seen.get("tenants", ["github"])

    async def search(pool, query, allowed, limit):
        if seen.get("search_raises"):
            raise RuntimeError("no db")
        return [dict(BUILT)]

    async def pool():
        return object()

    async def for_caller(email):
        seen["own_asked"].append(email)
        return dict(A_TOOLS) if email == A else {}

    async def forward(email, name, arguments):
        seen["forwarded"].append((email, name, arguments))
        return {"result": "ran"}

    async def has_access(email, server_id, groups=None):
        return server_id == "github"

    async def run_built(server, path, args, tenant_ids, user_email=None):
        return {"built": path}

    monkeypatch.setattr(main, "extract_user_from_headers_optional", who)
    monkeypatch.setattr(main, "get_user_tenants_async", tenants_of)
    monkeypatch.setattr(main, "search_tools_by_query", search)
    monkeypatch.setattr(main, "get_pool", pool)
    monkeypatch.setattr(main, "user_has_tenant_access_async", has_access)
    monkeypatch.setattr(main, "execute_on_server", run_built)

    class _Server:
        enabled = True
    monkeypatch.setattr(main, "get_server", lambda sid: _Server() if sid == "github" else None)
    monkeypatch.setattr(own_tools, "for_caller", for_caller)
    monkeypatch.setattr(own_tools, "call", forward)
    monkeypatch.setattr(own_tools, "_embed", lambda texts: None)
    monkeypatch.setitem(main.TOOLS_CACHE, "github_list_repos", {
        "tenant_id": "github", "tenant_name": "GitHub", "original_name": "list_repos",
        "original_path": "/list_repos", "description": "List repositories",
        "request_body": {}, "parameters": []})
    monkeypatch.setenv("INTERNAL_CALLBACK_SECRET", SECRET)
    monkeypatch.delenv("OWN_MCP", raising=False)
    client = TestClient(main.app)
    return client, seen


def _h(email, secret=None):
    h = {"X-User-Email": email} if email else {}
    if secret:
        h["X-Internal-Secret"] = secret
    return h


def _search(c, email, query="create invoice acme", secret=None):
    return c.post("/meta/search_tools", headers=_h(email, secret),
                  json={"query": query, "limit": 10})


def _describe(c, email, names):
    return c.post("/meta/describe_tools", headers=_h(email), json={"tool_names": names})


def _call(c, email, name, secret=None):
    return c.post("/meta/call_tool", headers=_h(email, secret),
                  json={"tool_name": name, "arguments": {"n": 1}})


# --- the namespace ---------------------------------------------------------

def test_no_built_server_id_starts_with_own():
    ids = [getattr(s, "id", s) for s in getattr(tenants, "ALL_SERVERS", {})]
    assert ids, "the catalogue was read"
    assert not [i for i in ids if str(i).startswith("own-")]


# --- isolation -------------------------------------------------------------

def test_person_b_never_finds_person_a_s_tools(proxy):
    c, _ = proxy
    found = [r["tool_name"] for r in _search(c, B).json()["results"]]
    assert not [n for n in found if n.startswith("own-")]
    assert found == ["github_list_repos"]


def test_person_a_finds_their_own_tools_with_the_built_ones(proxy):
    c, _ = proxy
    found = [r["tool_name"] for r in _search(c, A).json()["results"]]
    assert "own-acme_create_invoice" in found and "github_list_repos" in found


def test_describe_and_call_of_someone_elses_tool_match_a_missing_tool(proxy):
    c, seen = proxy
    theirs = _describe(c, B, ["own-acme_create_invoice"]).json()["tools"][0]
    nothing = _describe(c, B, ["own-nothing_here"]).json()["tools"][0]
    assert theirs == {"tool_name": "own-acme_create_invoice", "error": "Tool not found"}
    assert nothing == {"tool_name": "own-nothing_here", "error": "Tool not found"}
    r1 = _call(c, B, "own-acme_create_invoice", SECRET)
    r2 = _call(c, B, "own-nothing_here", SECRET)
    assert r1.status_code == r2.status_code == 404
    assert r1.json()["detail"].replace("own-acme_create_invoice", "X") == \
        r2.json()["detail"].replace("own-nothing_here", "X")
    assert seen["forwarded"] == []


def test_an_unidentified_caller_is_refused_before_own_tools_are_asked(proxy):
    c, seen = proxy
    assert _search(c, None).status_code == 401
    assert _describe(c, None, ["own-acme_create_invoice"]).status_code == 401
    assert _call(c, None, "own-acme_create_invoice").status_code == 401
    assert seen["own_asked"] == []


# --- search ----------------------------------------------------------------

def test_own_tools_are_found_with_no_built_servers(proxy):
    c, seen = proxy
    seen["tenants"] = []
    body = _search(c, A).json()
    assert [r["tool_name"] for r in body["results"]][:1] == ["own-acme_create_invoice"]
    seen["tenants"] = []
    assert _search(c, B).json()["results"] == []


def test_own_and_built_results_are_merged_by_score():
    built = [{"tool_name": "b1", "relevance_score": 0.9},
             {"tool_name": "b2", "relevance_score": 0.3}]
    own = [{"tool_name": "o1", "relevance_score": 0.5}]
    assert [r["tool_name"] for r in own_tools.merge(built, own, 10)] == ["b1", "o1", "b2"]
    assert [r["tool_name"] for r in own_tools.merge(built, own, 2)] == ["b1", "o1"]


def test_the_keyword_fallback_includes_own_tools(proxy):
    c, seen = proxy
    seen["search_raises"] = True
    found = [r["tool_name"] for r in _search(c, A, "invoice").json()["results"]]
    assert "own-acme_create_invoice" in found


def test_ranking_by_embedding_uses_cosine(monkeypatch):
    vectors = {"q": [1.0, 0.0], "own-acme_create_invoice": [1.0, 0.0],
               "own-acme_list_customers": [0.0, 1.0]}

    def embed(texts):
        return [vectors["q"] if t == "q" else
                vectors["own-acme_create_invoice"] if "invoice" in t else
                vectors["own-acme_list_customers"] for t in texts]
    monkeypatch.setattr(own_tools, "_embed", embed)
    own_tools._VECTORS.clear()
    ranked = own_tools.rank("q", A_TOOLS, 5)
    assert [r["tool_name"] for r in ranked] == ["own-acme_create_invoice",
                                                "own-acme_list_customers"]
    assert ranked[0]["relevance_score"] == 1.0 and ranked[0]["server_id"] == "own-acme"


def test_the_vector_cache_is_bounded(monkeypatch):
    monkeypatch.setattr(own_tools, "_embed", lambda texts: [[1.0] for _ in texts])
    own_tools._VECTORS.clear()
    many = {f"own-x_t{i}": {"name": f"own-x_t{i}", "description": f"d{i}",
                            "server_id": "own-x"} for i in range(own_tools.MAX_VECTORS + 10)}
    own_tools.rank("q", many, 5)
    assert len(own_tools._VECTORS) <= own_tools.MAX_VECTORS


# --- describe --------------------------------------------------------------

def test_describe_answers_own_tools_from_the_callers_own(proxy):
    c, _ = proxy
    [d] = _describe(c, A, ["own-acme_create_invoice"]).json()["tools"]
    assert d["server_id"] == "own-acme" and d["server_name"] == "Acme"
    assert d["request_body"] == A_TOOLS["own-acme_create_invoice"]["request_body"]


# --- call ------------------------------------------------------------------

def test_a_write_own_tool_from_open_webui_is_refused_and_never_forwarded(proxy):
    c, seen = proxy
    r = _call(c, A, "own-acme_create_invoice")           # no secret: Open WebUI
    assert r.status_code == 200
    said = r.json()["result"]
    assert "Acme" in said and "Switch to Auto (Free)" in said
    assert seen["forwarded"] == []


def test_a_read_only_own_tool_runs_from_open_webui(proxy):
    c, seen = proxy
    r = _call(c, A, "own-acme_list_customers")
    assert r.json() == {"result": "ran"}
    assert seen["forwarded"] == [(A, "own-acme_list_customers", {"n": 1})]


def test_a_write_own_tool_runs_for_the_tasks_loop(proxy):
    c, seen = proxy
    assert _call(c, A, "own-acme_create_invoice", SECRET).json() == {"result": "ran"}


def test_a_wrong_secret_is_treated_as_open_webui(proxy):
    c, seen = proxy
    r = _call(c, A, "own-acme_create_invoice", "nope")
    assert "Switch to Auto" in r.json()["result"] and seen["forwarded"] == []


def test_built_tools_answer_exactly_as_today(proxy):
    c, _ = proxy
    assert _call(c, A, "github_list_repos").json() == {"built": "list_repos"}
    [d] = _describe(c, A, ["github_list_repos"]).json()["tools"]
    assert d["server_id"] == "github"


# --- the switch, and tasks being down --------------------------------------

def test_the_switch_restores_todays_answers(proxy, monkeypatch):
    c, seen = proxy
    monkeypatch.setenv("OWN_MCP", "0")
    seen["own_asked"].clear()
    assert [r["tool_name"] for r in _search(c, A).json()["results"]] == ["github_list_repos"]
    assert _describe(c, A, ["own-acme_create_invoice"]).json()["tools"][0] == {
        "tool_name": "own-acme_create_invoice", "error": "Tool not found"}
    r = _call(c, A, "own-acme_create_invoice", SECRET)
    assert r.status_code == 404 and seen["forwarded"] == []
    assert seen["own_asked"] == [], "switched off, tasks is never asked"
    seen["tenants"] = []
    assert _search(c, A).json()["message"] == "No server access configured for this user"


@respx.mock
async def test_tasks_down_means_no_own_tools_and_no_error(monkeypatch):
    monkeypatch.setenv("INTERNAL_CALLBACK_SECRET", SECRET)
    monkeypatch.delenv("OWN_MCP", raising=False)
    own_tools._CACHE.clear(); own_tools._FAILED.clear()
    respx.get(own_tools.tasks_url() + "/own-mcp/tools").mock(
        side_effect=httpx.ConnectTimeout("down"))
    assert await own_tools.for_caller(A) == {}


@respx.mock
async def test_for_caller_sends_the_secret_and_caches_60_seconds(monkeypatch):
    monkeypatch.setenv("INTERNAL_CALLBACK_SECRET", SECRET)
    monkeypatch.delenv("OWN_MCP", raising=False)
    own_tools._CACHE.clear(); own_tools._FAILED.clear()
    route = respx.get(own_tools.tasks_url() + "/own-mcp/tools").mock(
        return_value=httpx.Response(200, json={"tools": list(A_TOOLS.values())}))
    got = await own_tools.for_caller(A)
    again = await own_tools.for_caller(A)
    assert set(got) == set(A_TOOLS) and again == got
    assert route.call_count == 1
    sent = route.calls[0].request.headers
    assert sent["x-internal-secret"] == SECRET and sent["x-user-email"] == A


@respx.mock
async def test_without_a_secret_configured_tasks_is_not_asked(monkeypatch):
    monkeypatch.delenv("INTERNAL_CALLBACK_SECRET", raising=False)
    own_tools._CACHE.clear(); own_tools._FAILED.clear()
    route = respx.get(own_tools.tasks_url() + "/own-mcp/tools")
    assert await own_tools.for_caller(A) == {}
    assert route.call_count == 0


def test_the_email_cache_is_bounded():
    own_tools._CACHE.clear(); own_tools._FAILED.clear()
    for i in range(own_tools.MAX_CALLERS + 20):
        own_tools._keep(f"p{i}@x.com", {})
    assert len(own_tools._CACHE) == own_tools.MAX_CALLERS


@respx.mock
async def test_call_forwards_with_the_secret(monkeypatch):
    monkeypatch.setenv("INTERNAL_CALLBACK_SECRET", SECRET)
    route = respx.post(own_tools.tasks_url() + "/own-mcp/call").mock(
        return_value=httpx.Response(200, json={"result": "ok"}))
    assert await own_tools.call(A, "own-acme_list_customers", {"q": "x"}) == {"result": "ok"}
    sent = route.calls[0].request
    assert json.loads(sent.content) == {"tool_name": "own-acme_list_customers",
                                        "arguments": {"q": "x"}}
    assert sent.headers["x-internal-secret"] == SECRET


@respx.mock
async def test_a_404_from_tasks_is_a_404_here(monkeypatch):
    monkeypatch.setenv("INTERNAL_CALLBACK_SECRET", SECRET)
    respx.post(own_tools.tasks_url() + "/own-mcp/call").mock(
        return_value=httpx.Response(404, json={"detail": "Tool 'x' not found"}))
    with pytest.raises(main.HTTPException) as e:
        await own_tools.call(A, "own-acme_gone", {})
    assert e.value.status_code == 404


# --- the final review, 2026-11-27 ------------------------------------------

@respx.mock
async def test_a_failed_lookup_is_remembered_so_search_does_not_wait_each_time(monkeypatch):
    monkeypatch.setenv("INTERNAL_CALLBACK_SECRET", SECRET)
    monkeypatch.delenv("OWN_MCP", raising=False)
    own_tools._CACHE.clear(); own_tools._FAILED.clear()
    route = respx.get(own_tools.tasks_url() + "/own-mcp/tools").mock(
        side_effect=httpx.ConnectTimeout("down"))
    assert await own_tools.for_caller(A) == {}
    assert await own_tools.for_caller(A) == {}
    assert route.call_count == 1
    assert own_tools.LIST_TIMEOUT <= 1.5


@respx.mock
async def test_a_call_that_times_out_says_it_may_have_run(monkeypatch):
    monkeypatch.setenv("INTERNAL_CALLBACK_SECRET", SECRET)
    respx.post(own_tools.tasks_url() + "/own-mcp/call").mock(
        side_effect=httpx.ReadTimeout("slow"))
    out = await own_tools.call(A, "own-acme_create_invoice", {})
    assert out["failed"] is True and "may have" in out["result"]


@respx.mock
async def test_an_unreadable_answer_from_tasks_is_a_sentence(monkeypatch):
    monkeypatch.setenv("INTERNAL_CALLBACK_SECRET", SECRET)
    respx.post(own_tools.tasks_url() + "/own-mcp/call").mock(
        return_value=httpx.Response(200, text="not json"))
    out = await own_tools.call(A, "own-acme_list_customers", {})
    assert out["failed"] is True


def test_the_proxy_waits_longer_than_tasks_does():
    import importlib.util
    import pathlib
    spec = importlib.util.spec_from_file_location(
        "own_mcp_client_for_test",
        pathlib.Path(__file__).resolve().parents[2] / "mcp-servers" / "tasks" / "own_mcp_client.py")
    src = spec.origin and open(spec.origin, encoding="utf-8").read()
    assert "CALL_TIMEOUT = 20.0" in src
    assert own_tools.CALL_TIMEOUT >= 25


def test_a_ranking_error_never_breaks_search(proxy, monkeypatch):
    c, seen = proxy

    def boom(*a, **k):
        raise RuntimeError("embedding failed")
    monkeypatch.setattr(own_tools, "rank", boom)
    r = _search(c, A)
    assert r.status_code == 200
    assert [x["tool_name"] for x in r.json()["results"]] == ["github_list_repos"]
    seen["tenants"] = []
    assert _search(c, A).status_code == 200
