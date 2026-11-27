"""The two routes only mcp-proxy calls: a person's own tools, and running one.

tasks shares its network with about 30 containers, and Open WebUI and
pipelines run code admins paste in. Without the internal secret, any of that
could claim a person's email and run tools on that person's own server with
their token. So both routes need the secret as well as the email.
"""
import pytest

import own_mcp_client
from test_own_mcp_routes import A, B, LISTED, SECRET, TOKEN, URL, _proxy, _save, env  # noqa: F401


def test_both_routes_refuse_without_the_secret_even_with_an_email(env, monkeypatch):
    c, store, seen = env
    _save(c)
    calls_before = len(seen["call"])
    for secret in (None, "wrong", ""):
        assert c.get("/own-mcp/tools", headers=_proxy(A, secret)).status_code == 403
        r = c.post("/own-mcp/call", headers=_proxy(A, secret),
                   json={"tool_name": "own-acme_list_customers", "arguments": {}})
        assert r.status_code == 403
    monkeypatch.delenv("INTERNAL_CALLBACK_SECRET")
    assert c.get("/own-mcp/tools", headers=_proxy(A)).status_code == 403
    assert len(seen["call"]) == calls_before


def test_no_email_is_refused(env):
    c, _, _ = env
    assert c.get("/own-mcp/tools", headers={"X-Internal-Secret": SECRET}).status_code == 401


def test_tools_lists_only_the_callers_servers(env):
    c, _, _ = env
    _save(c, email=A)
    mine = c.get("/own-mcp/tools", headers=_proxy(A)).json()["tools"]
    assert [t["name"] for t in mine] == ["own-acme_list_customers", "own-acme_create_invoice"]
    assert mine[0]["server_id"] == "own-acme" and mine[0]["server_name"] == "Acme"
    assert mine[0]["read_only"] is True and mine[1]["read_only"] is False
    assert c.get("/own-mcp/tools", headers=_proxy(B)).json() == {"tools": []}


def test_call_runs_the_tool_on_the_callers_row(env):
    c, store, seen = env
    seen["list_result"] = {"tools": [{"name": "create.invoice"}]}
    _save(c)
    sid = next(iter(store.rows))
    r = c.post("/own-mcp/call", headers=_proxy(A),
               json={"tool_name": "own-acme_create_invoice", "arguments": {"n": 1}})
    assert r.status_code == 200 and r.json() == {"result": "done"}
    assert seen["call"] == [((A, sid), URL, TOKEN, "create.invoice", {"n": 1})]


def test_call_on_another_persons_tool_name_is_not_found(env):
    c, _, seen = env
    _save(c, email=A)
    r = c.post("/own-mcp/call", headers=_proxy(B),
               json={"tool_name": "own-acme_list_customers", "arguments": {}})
    missing = c.post("/own-mcp/call", headers=_proxy(B),
                     json={"tool_name": "own-nothing_here", "arguments": {}})
    assert r.status_code == 404 and r.json() == {
        "detail": "Tool 'own-acme_list_customers' not found"}
    assert missing.status_code == 404
    assert seen["call"] == []


def test_call_on_a_removed_server_is_not_found(env):
    c, store, seen = env
    _save(c)
    sid = next(iter(store.rows))
    c.delete(f"/own-mcp/servers/{sid}", headers={"X-User-Email": A})
    r = c.post("/own-mcp/call", headers=_proxy(A),
               json={"tool_name": "own-acme_list_customers", "arguments": {}})
    assert r.status_code == 404 and seen["call"] == []


def test_a_tool_not_in_the_snapshot_is_not_found(env):
    c, _, seen = env
    _save(c)
    r = c.post("/own-mcp/call", headers=_proxy(A),
               json={"tool_name": "own-acme_delete_everything", "arguments": {}})
    assert r.status_code == 404 and seen["call"] == []


def test_call_re_checks_the_address_each_time(env):
    c, _, seen = env
    _save(c)
    seen["guard"] = "That address is not reachable from the public internet."
    r = c.post("/own-mcp/call", headers=_proxy(A),
               json={"tool_name": "own-acme_list_customers", "arguments": {}})
    assert r.status_code == 200
    assert r.json()["failed"] is True and "public internet" in r.json()["result"]
    assert seen["call"] == []


def test_a_failed_call_is_a_sentence_and_counts_toward_not_answering(env):
    c, store, seen = env
    _save(c)
    sid = next(iter(store.rows))
    seen["call_result"] = own_mcp_client.Refused("Your Acme server did not answer in 20 seconds.")
    r = c.post("/own-mcp/call", headers=_proxy(A),
               json={"tool_name": "own-acme_list_customers", "arguments": {}})
    assert r.status_code == 200
    assert r.json() == {"result": "Your Acme server did not answer in 20 seconds.",
                        "failed": True}
    assert store.rows[sid]["fails"] == 1


def test_arguments_that_are_not_an_object_are_refused(env):
    c, _, seen = env
    _save(c)
    r = c.post("/own-mcp/call", headers=_proxy(A),
               json={"tool_name": "own-acme_list_customers", "arguments": [1, 2]})
    assert r.status_code == 422 and seen["call"] == []
