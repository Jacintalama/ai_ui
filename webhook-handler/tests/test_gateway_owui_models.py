"""Listing the models the caller can see.

/api/v1/models/list is the only endpoint that keeps user_id and meta on the
row. /api/models nests the row under `info` and deletes params server side,
which is what made the Agents page show an empty list for a whole deploy. It
also pages at 30, so a user with more than 30 agents silently loses the rest
unless this pages through.
"""
import httpx
import respx

from gateway.owui import OWUIUserClient

BASE = "http://open-webui:8080"


def _client(token: str = "user-token") -> OWUIUserClient:
    return OWUIUserClient(BASE, token)


def _row(mid: str) -> dict:
    return {"id": mid, "name": mid, "meta": {"description": "d"},
            "base_model_id": "gpt-4o-mini"}


@respx.mock
async def test_it_returns_the_rows_and_carries_the_caller_token():
    route = respx.get(f"{BASE}/api/v1/models/list").mock(
        return_value=httpx.Response(200, json={
            "items": [_row("agent-a-0001")], "total": 1}))

    got = await _client("caller-token").list_models()

    assert [m["id"] for m in got] == ["agent-a-0001"]
    # This is what decides which agents the router can see. A shared or wrong
    # token here would mean one user's agents get offered to another.
    assert route.calls[0].request.headers["Authorization"] == "Bearer caller-token"


@respx.mock
async def test_it_pages_until_it_has_everything():
    seen = []

    def handler(request):
        page = int(dict(request.url.params).get("page", "1"))
        seen.append(page)
        rows = [_row("agent-%02d" % i) for i in range((page - 1) * 30, page * 30)]
        rows = rows[:30] if page == 1 else rows[:5]
        return httpx.Response(200, json={"items": rows, "total": 35})

    respx.get(f"{BASE}/api/v1/models/list").mock(side_effect=handler)

    got = await _client().list_models()

    assert seen == [1, 2], "it did not ask for the second page"
    assert len(got) == 35


@respx.mock
async def test_an_empty_batch_ends_the_loop():
    """An empty items list must stop the loop, whatever `total` says."""
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json={"items": [], "total": 999})

    respx.get(f"{BASE}/api/v1/models/list").mock(side_effect=handler)

    got = await _client().list_models()

    assert got == []
    assert len(calls) == 1


@respx.mock
async def test_a_total_that_never_matches_stops_at_the_page_cap():
    """A total that never matches must not spin forever.

    Every page here comes back full (30 non-empty rows), so the `not batch`
    exit never fires and only the page cap can end the loop. This must fail
    (or hang) if that cap is ever removed.
    """
    calls = []

    def handler(request):
        calls.append(1)
        rows = [_row("agent-%03d" % i) for i in range(30)]
        return httpx.Response(200, json={"items": rows, "total": 999999})

    respx.get(f"{BASE}/api/v1/models/list").mock(side_effect=handler)

    got = await _client().list_models()

    assert len(calls) == 25
    assert len(got) == 750
