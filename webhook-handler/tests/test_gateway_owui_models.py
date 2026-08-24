"""Listing the models the caller can see.

/api/v1/models/list is the only endpoint that keeps user_id and meta on the
row. /api/models nests the row under `info` and deletes params server side,
which is what made the Agents page show an empty list for a whole deploy. It
also pages at 30, so a user with more than 30 agents silently loses the rest
unless this pages through.
"""
import httpx
import pytest

from gateway.owui import OWUIError, OWUIUserClient


def _client(handler) -> OWUIUserClient:
    """An OWUIUserClient whose HTTP is served by `handler`, no socket."""
    client = OWUIUserClient("https://example.test", "tok")
    transport = httpx.MockTransport(handler)

    async def _request(method, path, **kwargs):
        async with httpx.AsyncClient(transport=transport) as http:
            resp = await http.request(method, f"https://example.test{path}",
                                      **kwargs)
        if resp.status_code >= 400:
            raise OWUIError(resp.status_code, resp.text[:400])
        return resp

    client._request = _request
    return client


def _row(mid: str) -> dict:
    return {"id": mid, "name": mid, "meta": {"description": "d"},
            "base_model_id": "gpt-4o-mini"}


async def test_it_returns_the_rows():
    def handler(request):
        return httpx.Response(200, json={"items": [_row("agent-a-0001")],
                                         "total": 1})

    got = await _client(handler).list_models()

    assert [m["id"] for m in got] == ["agent-a-0001"]


async def test_it_pages_until_it_has_everything():
    seen = []

    def handler(request):
        page = int(dict(request.url.params).get("page", "1"))
        seen.append(page)
        rows = [_row("agent-%02d" % i) for i in range((page - 1) * 30, page * 30)]
        rows = rows[:30] if page == 1 else rows[:5]
        return httpx.Response(200, json={"items": rows, "total": 35})

    got = await _client(handler).list_models()

    assert seen == [1, 2], "it did not ask for the second page"
    assert len(got) == 35


async def test_an_empty_page_stops_the_loop():
    """A total that never matches must not spin forever."""
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json={"items": [], "total": 999})

    got = await _client(handler).list_models()

    assert got == []
    assert len(calls) == 1
