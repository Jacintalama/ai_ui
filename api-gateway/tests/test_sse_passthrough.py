"""A live stream has to arrive live.

The gateway read every upstream body in full before answering. For a page
that streams, that turns "each answer as it lands" into "everything at once
at the end": the agent panel's bubbles all appear together when the last
agent finishes, and the line saying who is working is written and cleared
inside the same payload, so it is never on screen. The Fusion chat page has
had the same problem since 2026-07-15.

The passthrough is scoped to Server-Sent Events, so these tests check both
halves: that an event stream is handed on piece by piece, and that every
other body still takes the path it always took.

Sync tests around asyncio.run, matching test_trust_headers: this package has
no async plugin configured.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402
from starlette.requests import Request  # noqa: E402

import main  # noqa: E402


def _request(method="GET", path="/tasks/agents/chat/stream", query=b""):
    return Request({"type": "http", "method": method, "path": path,
                    "root_path": "", "headers": [], "query_string": query})


def _use(monkeypatch, handler):
    """Point the gateway's client at a fake backend, transport and all.

    A real httpx.AsyncClient over a MockTransport, not a hand-written double,
    so the streaming behaviour under test is httpx's own.
    """
    real = httpx.AsyncClient

    def factory(**kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(**kwargs)

    monkeypatch.setattr(main.httpx, "AsyncClient", factory)


async def _stream(*chunks):
    """An upstream body that really is a stream.

    httpx treats a Response built from plain bytes as already consumed, so
    aiter_raw() cannot walk one. A real event stream is never that.
    """
    for chunk in chunks:
        yield chunk


async def _collect(response):
    out = b""
    async for chunk in response.body_iterator:
        out += chunk if isinstance(chunk, bytes) else chunk.encode()
    return out


def test_an_event_stream_is_handed_on_before_it_finishes(monkeypatch):
    """The whole point. The backend holds the second event back until the
    gateway has already delivered the first, so a gateway that read the body
    in full would sit here until the timeout rather than pass."""
    async def check():
        delivered_first = asyncio.Event()

        async def upstream_body():
            yield b"event: message\ndata: <div>Ada</div>\n\n"
            await asyncio.wait_for(delivered_first.wait(), timeout=5)
            yield b"event: message\ndata: <div>Mia</div>\n\n"

        def handler(request):
            return httpx.Response(
                200, headers={"content-type": "text/event-stream"},
                content=upstream_body())

        _use(monkeypatch, handler)
        response = await main.forward_request(
            _request(), "http://tasks:8210", "/tasks/agents/chat/stream", {})
        assert isinstance(response, StreamingResponse)

        chunks = response.body_iterator
        first = await asyncio.wait_for(chunks.__anext__(), timeout=5)
        assert b"Ada" in first, "the first event did not arrive on its own"
        delivered_first.set()
        second = await asyncio.wait_for(chunks.__anext__(), timeout=5)
        assert b"Mia" in second
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(chunks.__anext__(), timeout=5)

    asyncio.run(check())


def test_a_streamed_response_keeps_its_content_type(monkeypatch):
    async def check():
        def handler(request):
            return httpx.Response(200,
                                  headers={"content-type": "text/event-stream",
                                           "cache-control": "no-cache",
                                           "x-accel-buffering": "no"},
                                  content=_stream(b"data: hi\n\n"))

        _use(monkeypatch, handler)
        response = await main.forward_request(
            _request(), "http://tasks:8210", "/tasks/agents/chat/stream", {})
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["cache-control"] == "no-cache"
        # sse_starlette sends this so nginx-shaped proxies do not buffer either.
        assert response.headers["x-accel-buffering"] == "no"
        assert await _collect(response) == b"data: hi\n\n"

    asyncio.run(check())


def test_a_streamed_response_promises_no_length(monkeypatch):
    """Content-Length on a body sent in pieces is a promise the browser acts
    on: it stops reading there and the rest of the round never renders."""
    async def check():
        def handler(request):
            return httpx.Response(200,
                                  headers={"content-type": "text/event-stream",
                                           "content-length": "9"},
                                  content=_stream(b"data: hi\n\n"))

        _use(monkeypatch, handler)
        response = await main.forward_request(
            _request(), "http://tasks:8210", "/tasks/agents/chat/stream", {})
        assert "content-length" not in response.headers
        await _collect(response)

    asyncio.run(check())


def test_a_streamed_response_carries_every_set_cookie(monkeypatch):
    async def check():
        def handler(request):
            return httpx.Response(
                200,
                headers=[(b"content-type", b"text/event-stream"),
                         (b"set-cookie", b"a=1; Path=/"),
                         (b"set-cookie", b"b=2; Path=/")],
                content=_stream(b"data: hi\n\n"))

        _use(monkeypatch, handler)
        response = await main.forward_request(
            _request(), "http://tasks:8210", "/tasks/agents/chat/stream", {})
        cookies = response.headers.getlist("set-cookie")
        assert cookies == ["a=1; Path=/", "b=2; Path=/"], cookies
        await _collect(response)

    asyncio.run(check())


def test_a_streamed_response_drops_hop_by_hop_headers(monkeypatch):
    async def check():
        def handler(request):
            return httpx.Response(200,
                                  headers={"content-type": "text/event-stream",
                                           "connection": "keep-alive"},
                                  content=_stream(b"data: hi\n\n"))

        _use(monkeypatch, handler)
        response = await main.forward_request(
            _request(), "http://tasks:8210", "/tasks/agents/chat/stream", {})
        assert "connection" not in response.headers
        await _collect(response)

    asyncio.run(check())


# --- everything that is not an event stream ------------------------------
# The regression half. A page, a JSON body and a redirect must come back
# exactly as they did before: read in full, same headers, same object.

def test_an_ordinary_body_is_still_returned_whole(monkeypatch):
    async def check():
        def handler(request):
            return httpx.Response(200, headers={"content-type": "text/html"},
                                  content=b"<html>hello</html>")

        _use(monkeypatch, handler)
        response = await main.forward_request(
            _request(path="/tasks/agents"), "http://tasks:8210",
            "/tasks/agents", {})
        assert not isinstance(response, StreamingResponse)
        assert response.body == b"<html>hello</html>"
        assert response.headers["content-type"].startswith("text/html")
        assert response.status_code == 200

    asyncio.run(check())


def test_an_ordinary_body_still_carries_every_set_cookie(monkeypatch):
    async def check():
        def handler(request):
            return httpx.Response(
                200,
                headers=[(b"content-type", b"application/json"),
                         (b"set-cookie", b"token=abc; Path=/"),
                         (b"set-cookie", b"other=def; Path=/")],
                content=b'{"ok": true}')

        _use(monkeypatch, handler)
        response = await main.forward_request(
            _request(path="/api/v1/auths"), "http://open-webui:8080",
            "/api/v1/auths", {})
        cookies = response.headers.getlist("set-cookie")
        assert cookies == ["token=abc; Path=/", "other=def; Path=/"], cookies
        assert response.body == b'{"ok": true}'

    asyncio.run(check())


def test_an_ordinary_body_still_drops_hop_by_hop_headers(monkeypatch):
    async def check():
        def handler(request):
            return httpx.Response(200, headers={"content-type": "text/plain",
                                                "connection": "keep-alive"},
                                  content=b"ok")

        _use(monkeypatch, handler)
        response = await main.forward_request(
            _request(path="/whatever"), "http://open-webui:8080", "/whatever",
            {})
        assert "connection" not in response.headers

    asyncio.run(check())


def test_a_redirect_is_not_followed_and_keeps_its_location(monkeypatch):
    async def check():
        def handler(request):
            return httpx.Response(302, headers={"location": "/auth"},
                                  content=b"")

        _use(monkeypatch, handler)
        response = await main.forward_request(
            _request(path="/"), "http://open-webui:8080", "/", {})
        assert response.status_code == 302
        assert response.headers["location"] == "/auth"

    asyncio.run(check())


def test_the_query_string_and_body_still_reach_the_backend(monkeypatch):
    async def check():
        seen = {}

        def handler(request):
            seen["url"] = str(request.url)
            seen["method"] = request.method
            return httpx.Response(200, headers={"content-type": "text/plain"},
                                  content=b"ok")

        _use(monkeypatch, handler)
        await main.forward_request(
            _request(method="GET", path="/tasks/x", query=b"a=1&b=2"),
            "http://tasks:8210", "/tasks/x", {})
        assert seen["url"] == "http://tasks:8210/tasks/x?a=1&b=2"
        assert seen["method"] == "GET"

    asyncio.run(check())


def test_only_an_event_stream_takes_the_streamed_path():
    """The guard itself, since it is what bounds the blast radius."""
    def r(content_type):
        return httpx.Response(200, headers={"content-type": content_type})

    assert main.is_event_stream(r("text/event-stream"))
    assert main.is_event_stream(r("text/event-stream; charset=utf-8"))
    assert main.is_event_stream(r("TEXT/EVENT-STREAM"))
    assert not main.is_event_stream(r("text/html"))
    assert not main.is_event_stream(r("application/json"))
    assert not main.is_event_stream(httpx.Response(200))
