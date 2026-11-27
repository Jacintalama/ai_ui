"""The routes a person uses to add, test, list, refresh and remove their own
MCP servers, and the two routes only mcp-proxy may call.

The store is replaced by an in-memory one with the same rules (every lookup
by email first), so these run anywhere; the SQL is proved live on the box.
"""
import os
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("AIUI_FERNET_KEY",
                      "SFNQQkFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=")

import crypto_utils  # noqa: E402
import own_mcp  # noqa: E402
import own_mcp_client  # noqa: E402
import routes_own_mcp as R  # noqa: E402

A = "a@x.com"
B = "b@x.com"
URL = "https://mcp.example.com/k/abc123/mcp"
TOKEN = "sk-SECRET123"
SECRET = "internal-secret-for-tests"
LISTED = {"tools": [
    {"name": "list_customers", "description": "Lists customers",
     "annotations": {"readOnlyHint": True}},
    {"name": "create_invoice", "description": "Makes an invoice"}]}


class FakeStore:
    """tasks.own_mcp_servers in memory, keyed the same way."""

    def __init__(self):
        self.rows = {}

    async def list_for(self, email):
        return [self._public(r) for r in self.rows.values() if r["email"] == email]

    async def all_rows(self):
        return [dict(self._public(r), email=r["email"]) for r in self.rows.values()]

    async def by_slug(self, email, slug):
        for r in self.rows.values():
            if r["email"] == email and r["slug"] == slug:
                return self._public(r)
        return None

    async def secrets_of(self, email, server_id):
        r = self.rows.get(server_id)
        if not r or r["email"] != email:
            return None
        import json
        return json.loads(crypto_utils.decrypt(r["secrets_encrypted"]))

    async def add(self, email, slug, label, host, url, token, tools):
        import json
        sid = str(uuid.uuid4())
        self.rows[sid] = {"id": sid, "email": email, "slug": slug, "label": label,
                          "host": host, "tools": tools, "check_ok": True, "fails": 0,
                          "checked_at": None,
                          "secrets_encrypted": crypto_utils.encrypt(
                              json.dumps({"url": url, "token": token}))}
        return sid

    async def set_tools(self, email, server_id, tools):
        r = self.rows.get(server_id)
        if not r or r["email"] != email:
            return False
        r.update(tools=tools, check_ok=True, fails=0)
        return True

    async def record_check(self, email, server_id, ok):
        r = self.rows.get(server_id)
        if not r or r["email"] != email:
            return
        if ok:
            r.update(check_ok=True, fails=0)
        else:
            r["fails"] += 1
            r["check_ok"] = r["fails"] < 3

    async def remove(self, email, server_id):
        r = self.rows.get(server_id)
        if not r or r["email"] != email:
            return False
        del self.rows[server_id]
        return True

    @staticmethod
    def _public(r):
        return {k: v for k, v in r.items() if k not in ("secrets_encrypted", "email")}


@pytest.fixture
def env(monkeypatch):
    store = FakeStore()
    for name in ("list_for", "all_rows", "by_slug", "secrets_of", "add",
                 "set_tools", "record_check", "remove"):
        monkeypatch.setattr(R.store, name, getattr(store, name))
    seen = {"list": [], "call": []}

    async def fake_list(url, token, *, label="MCP", key=None, timeout=15.0):
        seen["list"].append((url, token))
        result = seen.get("list_result", LISTED)
        if isinstance(result, Exception):
            raise result
        return result

    async def fake_call(key, url, token, tool, arguments, label, timeout=20.0):
        seen["call"].append((key, url, token, tool, arguments))
        result = seen.get("call_result", "done")
        if isinstance(result, Exception):
            raise result
        return result

    async def public(url, *a, **k):
        return seen.get("guard", "")

    monkeypatch.setattr(R.own_mcp_client, "list_tools", fake_list)
    monkeypatch.setattr(R.own_mcp_client, "call", fake_call)
    monkeypatch.setattr(R.host_guard, "problem", public)
    monkeypatch.setenv("INTERNAL_CALLBACK_SECRET", SECRET)
    app = FastAPI()
    app.include_router(R.router)
    app.include_router(R.router, prefix="/api/tasks")
    with TestClient(app) as c:
        yield c, store, seen


def _as(email):
    return {"X-User-Email": email}


def _proxy(email, secret=SECRET):
    h = {"X-User-Email": email}
    if secret is not None:
        h["X-Internal-Secret"] = secret
    return h


def _save(c, email=A, label="Acme"):
    return c.post("/own-mcp/servers", headers=_as(email),
                  json={"label": label, "url": URL, "token": TOKEN})


# --- test ------------------------------------------------------------------

def test_test_shows_the_tools_and_stores_nothing(env):
    c, store, seen = env
    r = c.post("/own-mcp/servers/test", headers=_as(A),
               json={"label": "Acme", "url": URL, "token": TOKEN})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["tools"] == [{"name": "list_customers", "read_only": True},
                             {"name": "create_invoice", "read_only": False}]
    assert store.rows == {}
    assert seen["list"] == [(URL, TOKEN)]


def test_a_refused_test_says_why_in_a_sentence(env):
    c, _, seen = env
    seen["list_result"] = own_mcp_client.Refused("Your Acme server did not answer in 15 seconds.")
    r = c.post("/own-mcp/servers/test", headers=_as(A),
               json={"label": "Acme", "url": URL, "token": TOKEN})
    assert r.status_code == 200
    assert r.json() == {"ok": False,
                        "problem": "Your Acme server did not answer in 15 seconds."}


def test_a_bad_label_or_address_is_refused_before_any_request(env):
    c, _, seen = env
    for body in ({"label": "", "url": URL}, {"label": "!!!", "url": URL},
                 {"label": "x" * 41, "url": URL},
                 {"label": "Acme", "url": "http://mcp.example.com/mcp"},
                 {"label": "Acme", "url": "https://localhost/mcp"}):
        if "localhost" in body["url"]:
            seen["guard"] = "That address is not reachable from the public internet."
        r = c.post("/own-mcp/servers/test", headers=_as(A), json=body)
        assert r.json()["ok"] is False, body
        seen["guard"] = ""
    assert seen["list"] == []


def test_a_server_with_no_usable_tools_is_not_saved(env):
    c, store, seen = env
    seen["list_result"] = {"tools": []}
    r = _save(c)
    assert r.status_code == 400 and "no tools" in r.json()["detail"].lower()
    assert store.rows == {}


def test_no_session_means_401(env):
    c, _, _ = env
    assert c.get("/own-mcp/servers").status_code == 401


# --- save ------------------------------------------------------------------

def test_save_checks_again_and_stores_the_address_encrypted(env):
    c, store, seen = env
    r = _save(c)
    assert r.status_code == 200, r.text
    [row] = store.rows.values()
    assert row["slug"] == "acme" and row["host"] == "mcp.example.com"
    assert URL not in str({k: v for k, v in row.items() if k != "secrets_encrypted"})
    assert TOKEN not in row["secrets_encrypted"]
    assert seen["list"] == [(URL, TOKEN)]
    assert own_mcp.read_only(A, "own-acme_list_customers") is True


def test_a_second_server_with_the_same_name_gets_its_own_slug(env):
    c, store, _ = env
    _save(c)
    _save(c)
    assert sorted(r["slug"] for r in store.rows.values()) == ["acme", "acme2"]


def test_a_sixth_server_is_refused_with_a_sentence(env):
    c, store, _ = env
    for i in range(5):
        assert _save(c, label=f"S{i}").status_code == 200
    r = _save(c, label="Six")
    assert r.status_code == 400 and "5" in r.json()["detail"]
    assert len(store.rows) == 5


def test_no_route_returns_the_token_or_the_full_address(env):
    c, store, _ = env
    bodies = [c.post("/own-mcp/servers/test", headers=_as(A),
                     json={"label": "Acme", "url": URL, "token": TOKEN}).text,
              _save(c).text]
    sid = next(iter(store.rows))
    bodies.append(c.get("/own-mcp/servers", headers=_as(A)).text)
    bodies.append(c.post(f"/own-mcp/servers/{sid}/refresh", headers=_as(A)).text)
    bodies.append(c.get("/own-mcp/tools", headers=_proxy(A)).text)
    bodies.append(c.delete(f"/own-mcp/servers/{sid}", headers=_as(A)).text)
    for text in bodies:
        assert TOKEN not in text and "abc123" not in text


def test_the_card_shows_counts_and_the_host(env):
    c, _, seen = env
    seen["list_result"] = {"tools": LISTED["tools"] + [{"name": "get.item"}, {"name": "get_item"}]}
    saved = _save(c).json()
    assert len(saved["not_used"]) == 1, "what was left out is said when it is saved"
    [card] = c.get("/own-mcp/servers", headers=_as(A)).json()["servers"]
    assert card["label"] == "Acme" and card["host"] == "mcp.example.com"
    assert card["tool_count"] == 3 and card["read_only_count"] == 1
    assert card["tools"] == ["list_customers", "create_invoice", "get.item"]
    assert card["check_ok"] is True


# --- someone else's --------------------------------------------------------

def test_someone_elses_servers_are_not_listed(env):
    c, _, _ = env
    _save(c, email=A)
    assert c.get("/own-mcp/servers", headers=_as(B)).json() == {"servers": []}


def test_someone_elses_id_is_404_on_refresh_and_delete(env):
    c, store, _ = env
    _save(c, email=A)
    sid = next(iter(store.rows))
    assert c.post(f"/own-mcp/servers/{sid}/refresh", headers=_as(B)).status_code == 404
    assert c.delete(f"/own-mcp/servers/{sid}", headers=_as(B)).status_code == 404
    assert sid in store.rows


def test_remove_deletes_the_row_and_forgets_the_session(env, monkeypatch):
    c, store, _ = env
    forgot = []
    monkeypatch.setattr(R.own_mcp_client, "forget", forgot.append)
    _save(c)
    sid = next(iter(store.rows))
    assert c.delete(f"/own-mcp/servers/{sid}", headers=_as(A)).status_code == 200
    assert store.rows == {} and forgot == [(A, sid)]
    assert own_mcp.read_only(A, "own-acme_list_customers") is False


# --- refresh and health ----------------------------------------------------

def test_refresh_updates_the_snapshot(env):
    c, store, seen = env
    _save(c)
    sid = next(iter(store.rows))
    seen["list_result"] = {"tools": [{"name": "only_one"}]}
    r = c.post(f"/own-mcp/servers/{sid}/refresh", headers=_as(A))
    assert r.status_code == 200 and r.json()["tool_count"] == 1
    assert [t["tool"] for t in store.rows[sid]["tools"]] == ["only_one"]


def test_three_failed_refreshes_mark_the_server_not_answering(env):
    c, store, seen = env
    _save(c)
    sid = next(iter(store.rows))
    seen["list_result"] = own_mcp_client.Refused("Your Acme server did not answer in 15 seconds.")
    for _ in range(3):
        r = c.post(f"/own-mcp/servers/{sid}/refresh", headers=_as(A))
        assert r.status_code == 200 and r.json()["problem"]
    assert store.rows[sid]["check_ok"] is False
    assert len(store.rows[sid]["tools"]) == 2, "the tools stay listed"
    seen["list_result"] = LISTED
    c.post(f"/own-mcp/servers/{sid}/refresh", headers=_as(A))
    assert store.rows[sid]["check_ok"] is True and store.rows[sid]["fails"] == 0


def test_the_router_is_reachable_on_both_prefixes(env):
    c, _, _ = env
    assert c.get("/api/tasks/own-mcp/servers", headers=_as(A)).status_code == 200


def test_main_app_mounts_the_router():
    import main
    paths = {getattr(r, "path", "") for r in main.app.routes}
    assert "/own-mcp/servers" in paths and "/api/tasks/own-mcp/servers" in paths
    assert "/own-mcp/tools" in paths and "/own-mcp/call" in paths
