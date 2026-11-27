"""Talking to a person's own MCP server.

The address and token are the person's, and the server is not ours, so the
client is written against three ways it could hurt somebody: reaching our
own network (a private address, or a public one that redirects into it),
handing one person's session to another, and repeating a secret back into a
chat. Everything that goes wrong comes back as a sentence naming the
server by the person's own label, never by its address.
"""
import json
import os

import httpx
import pytest
import respx

os.environ.setdefault("AIUI_FERNET_KEY",
                      "SFNQQkFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=")

import own_mcp_client as client  # noqa: E402

URL = "https://mcp.example.com/k/abc123/mcp"
TOKEN = "sk-SECRET123"
KEY = ("a@x.com", "srv-1")


@pytest.fixture(autouse=True)
def public(monkeypatch):
    async def fine(url, *a, **k):
        return ""
    monkeypatch.setattr(client.host_guard, "problem", fine)
    client._SESSIONS.clear()
    yield


def _rpc(result, session="sess-1", sse=False, status=200):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "result": result})
    if sse:
        return httpx.Response(status, text="event: message\ndata: " + body + "\n\n",
                              headers={"content-type": "text/event-stream",
                                       "mcp-session-id": session})
    return httpx.Response(status, text=body, headers={"content-type": "application/json",
                                                      "mcp-session-id": session})


def _server(tools=None, call_result=None, sse=False):
    """A fake MCP server answering by JSON-RPC method."""
    calls = []

    def answer(request):
        msg = json.loads(request.content)
        calls.append((msg.get("method"), dict(request.headers)))
        method = msg.get("method")
        if method == "initialize":
            return _rpc({"protocolVersion": "2025-03-26", "capabilities": {}}, sse=sse)
        if method == "notifications/initialized":
            return httpx.Response(202)
        if method == "tools/list":
            return _rpc({"tools": tools or []}, sse=sse)
        if method == "tools/call":
            return _rpc(call_result or {"content": [{"type": "text", "text": "ok"}]}, sse=sse)
        return httpx.Response(400)
    return answer, calls


# --- refused before anything is sent ---------------------------------------

@respx.mock
async def test_http_is_refused_before_any_request():
    route = respx.post("http://mcp.example.com/mcp")
    with pytest.raises(client.Refused):
        await client.list_tools("http://mcp.example.com/mcp", "", label="Acme")
    assert route.call_count == 0


@respx.mock
async def test_a_private_answer_is_refused(monkeypatch):
    async def private(url, *a, **k):
        return "Only public addresses can be used."
    monkeypatch.setattr(client.host_guard, "problem", private)
    route = respx.post(URL)
    with pytest.raises(client.Refused) as e:
        await client.list_tools(URL, TOKEN, label="Acme")
    assert route.call_count == 0
    assert "abc123" not in str(e.value)


@respx.mock
async def test_the_address_is_checked_before_every_call(monkeypatch):
    answer, _ = _server()
    respx.post(URL).mock(side_effect=answer)
    await client.call(KEY, URL, TOKEN, "list", {}, "Acme")
    async def private(url, *a, **k):
        return "Only public addresses can be used."
    monkeypatch.setattr(client.host_guard, "problem", private)
    with pytest.raises(client.Refused):
        await client.call(KEY, URL, TOKEN, "list", {}, "Acme")


# --- redirects and secrets -------------------------------------------------

@respx.mock
async def test_a_redirect_is_not_followed():
    route = respx.post(URL).mock(return_value=httpx.Response(
        302, headers={"location": "http://10.0.0.5/admin"}))
    inner = respx.post("http://10.0.0.5/admin")
    with pytest.raises(client.Refused) as e:
        await client.list_tools(URL, TOKEN, label="Acme")
    said = str(e.value)
    assert "somewhere else" in said and "10.0.0.5" not in said
    assert route.call_count == 1 and inner.call_count == 0


@respx.mock
async def test_the_token_goes_as_a_bearer_and_never_into_a_sentence():
    seen = {}

    def answer(request):
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(400, text=f"bad key {TOKEN} for /k/abc123/mcp/{TOKEN} " + "x" * 400)
    respx.post(URL).mock(side_effect=answer)
    with pytest.raises(client.Refused) as e:
        await client.list_tools(URL, TOKEN, label="Acme")
    said = str(e.value)
    assert seen["auth"] == "Bearer " + TOKEN
    assert TOKEN not in said and "abc123" not in said
    assert said.startswith("Your Acme server said: ")
    assert len(said) <= len("Your Acme server said: ") + 160 + 1


@respx.mock
async def test_a_timeout_names_the_server_never_its_address():
    respx.post(URL).mock(side_effect=httpx.ReadTimeout("timed out " + URL))
    with pytest.raises(client.Refused) as e:
        await client.call(KEY, URL, TOKEN, "list", {}, "Acme")
    said = str(e.value)
    assert "did not answer in 20 seconds" in said and "Acme" in said
    assert "abc123" not in said and "example.com" not in said


@respx.mock
async def test_a_connection_failure_never_repeats_the_address():
    respx.post(URL).mock(side_effect=httpx.ConnectError("cannot reach mcp.example.com/k/abc123"))
    with pytest.raises(client.Refused) as e:
        await client.list_tools(URL, TOKEN, label="Acme")
    assert "abc123" not in str(e.value) and "example.com" not in str(e.value)


# --- the protocol ----------------------------------------------------------

@respx.mock
@pytest.mark.parametrize("sse", [False, True])
async def test_sse_and_json_answers_both_parse(sse):
    answer, calls = _server(tools=[{"name": "list_customers"}], sse=sse)
    respx.post(URL).mock(side_effect=answer)
    listed = await client.list_tools(URL, TOKEN, label="Acme")
    assert listed == {"tools": [{"name": "list_customers"}]}
    methods = [m for m, _ in calls]
    assert methods == ["initialize", "notifications/initialized", "tools/list"]
    assert calls[2][1].get("mcp-session-id") == "sess-1"


@respx.mock
async def test_a_result_is_text_only_and_cut_at_20000():
    answer, _ = _server(call_result={"content": [
        {"type": "text", "text": "a" * 30000},
        {"type": "image", "data": "iVBORw0KGgo", "mimeType": "image/png"}]})
    respx.post(URL).mock(side_effect=answer)
    out = await client.call(KEY, URL, TOKEN, "get", {}, "Acme")
    assert out.count("a") >= 19000 and len(out) <= 20000 + 200
    assert "image" in out and "iVBORw0KGgo" not in out


@respx.mock
async def test_an_error_result_comes_back_as_a_refusal():
    answer, _ = _server(call_result={"isError": True, "content": [
        {"type": "text", "text": "No such invoice " + TOKEN}]})
    respx.post(URL).mock(side_effect=answer)
    with pytest.raises(client.Refused) as e:
        await client.call(KEY, URL, TOKEN, "get", {}, "Acme")
    assert "No such invoice" in str(e.value) and TOKEN not in str(e.value)


@respx.mock
async def test_a_json_rpc_error_comes_back_as_a_refusal():
    def answer(request):
        msg = json.loads(request.content)
        if msg.get("method") == "initialize":
            return _rpc({})
        if msg.get("method") == "notifications/initialized":
            return httpx.Response(202)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 2,
                                         "error": {"code": -32602, "message": "Unknown tool"}})
    respx.post(URL).mock(side_effect=answer)
    with pytest.raises(client.Refused) as e:
        await client.call(KEY, URL, TOKEN, "nope", {}, "Acme")
    assert "Unknown tool" in str(e.value)


@respx.mock
async def test_sessions_are_per_person_per_server():
    answer, calls = _server()
    respx.post(URL).mock(side_effect=answer)
    await client.call(("a@x.com", "s1"), URL, TOKEN, "t", {}, "Acme")
    await client.call(("a@x.com", "s1"), URL, TOKEN, "t", {}, "Acme")
    await client.call(("b@x.com", "s1"), URL, TOKEN, "t", {}, "Acme")
    assert [m for m, _ in calls].count("initialize") == 2


@respx.mock
async def test_a_404_session_re_initializes_once():
    state = {"calls": 0}
    answer, calls = _server()

    def flaky(request):
        msg = json.loads(request.content)
        if msg.get("method") == "tools/call":
            state["calls"] += 1
            if state["calls"] == 1:
                return httpx.Response(404, text="session gone")
        return answer(request)
    respx.post(URL).mock(side_effect=flaky)
    assert await client.call(KEY, URL, TOKEN, "t", {}, "Acme") == "ok"
    assert [m for m, _ in calls].count("initialize") == 2   # the first, then once more
    assert state["calls"] == 2


@respx.mock
async def test_forget_drops_the_session():
    answer, calls = _server()
    respx.post(URL).mock(side_effect=answer)
    await client.call(KEY, URL, TOKEN, "t", {}, "Acme")
    client.forget(KEY)
    await client.call(KEY, URL, TOKEN, "t", {}, "Acme")
    assert [m for m, _ in calls].count("initialize") == 2


def test_the_session_cache_is_bounded():
    for i in range(client.MAX_SESSIONS + 50):
        client._remember_session((f"p{i}@x.com", "s"), f"id{i}")
    assert len(client._SESSIONS) == client.MAX_SESSIONS
