"""What a person may read and forget about their own agents' memory.

Owner only, the same rule /speak applies: an agent that is not in the
caller's own list is not theirs to read or to empty. There is no admin path
here on purpose. An admin's model listing carries everybody's agents, and
one person's notes about their own work are not an operator's to page
through.

Two layers here on purpose. The direct-call tests below pin what each
handler decides. The ASGI tests at the bottom drive the real router through
a real request, because that is the layer that runs: a handler can be
correct and still be unreachable, unmounted, or wide open, and only the
request proves otherwise.
"""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

import routes_agents
from auth import CurrentUser, current_user


class _User:
    email = "o@example.com"
    is_admin = False


def _mine():
    return [{"id": "agent-1", "name": "Ada"}]


async def test_counts_are_for_the_callers_agents():
    with patch.object(routes_agents.agent_memory, "note_counts",
                      new=AsyncMock(return_value={"agent-1": 2})):
        out = await routes_agents.memory_counts(user=_User())
    assert out == {"counts": {"agent-1": 2}}


async def test_counts_are_asked_for_the_caller_not_for_everybody():
    """The count query folds the email itself, but it can only scope to the
    address it is given, so the route must hand it the caller's own."""
    with patch.object(routes_agents.agent_memory, "note_counts",
                      new=AsyncMock(return_value={})) as counts:
        await routes_agents.memory_counts(user=_User())
    counts.assert_awaited_once_with("o@example.com")


async def test_listing_someone_elses_agent_is_403():
    with patch.object(routes_agents, "_agents_for", new=AsyncMock(return_value=_mine())), \
         pytest.raises(HTTPException) as err:
        await routes_agents.memory_list("agent-9", user=_User())
    assert err.value.status_code == 403


async def test_listing_and_forgetting_your_own():
    with patch.object(routes_agents, "_agents_for", new=AsyncMock(return_value=_mine())), \
         patch.object(routes_agents.agent_memory, "list_notes",
                      new=AsyncMock(return_value=[{"id": "n1", "content": "x"}])), \
         patch.object(routes_agents.agent_memory, "delete_note",
                      new=AsyncMock(return_value=True)) as forget, \
         patch.object(routes_agents.agent_memory, "clear_notes",
                      new=AsyncMock(return_value=3)) as clear:
        listed = await routes_agents.memory_list("agent-1", user=_User())
        one = await routes_agents.memory_forget("agent-1", "n1", user=_User())
        every = await routes_agents.memory_forget_all("agent-1", user=_User())
    assert listed == {"notes": [{"id": "n1", "content": "x"}]}
    assert one == {"forgotten": 1}
    assert every == {"forgotten": 3}
    forget.assert_awaited_once_with("o@example.com", "agent-1", "n1")
    clear.assert_awaited_once_with("o@example.com", "agent-1")


async def test_both_deletes_answer_in_the_same_shape():
    """delete_note answers True or False and clear_notes answers a count.
    The page reads one key from both, so the route converts rather than
    making the page cope with two types. Checked for int and not bool,
    because True == 1 in Python and an equality assertion alone would pass
    on the shape this is here to rule out.
    """
    with patch.object(routes_agents, "_agents_for", new=AsyncMock(return_value=_mine())), \
         patch.object(routes_agents.agent_memory, "delete_note",
                      new=AsyncMock(return_value=True)), \
         patch.object(routes_agents.agent_memory, "clear_notes",
                      new=AsyncMock(return_value=3)):
        one = await routes_agents.memory_forget("agent-1", "n1", user=_User())
        every = await routes_agents.memory_forget_all("agent-1", user=_User())
    for out in (one, every):
        assert isinstance(out["forgotten"], int)
        assert not isinstance(out["forgotten"], bool), out


async def test_forgetting_one_note_on_someone_elses_agent_is_403():
    """The ownership check has to come before the delete, not after it: a
    note deleted and then refused is still deleted."""
    with patch.object(routes_agents, "_agents_for", new=AsyncMock(return_value=_mine())), \
         patch.object(routes_agents.agent_memory, "delete_note",
                      new=AsyncMock(return_value=True)) as forget:
        with pytest.raises(HTTPException) as err:
            await routes_agents.memory_forget("agent-9", "n1", user=_User())
    assert err.value.status_code == 403
    forget.assert_not_awaited()


async def test_forgetting_everything_on_someone_elses_agent_is_403():
    with patch.object(routes_agents, "_agents_for", new=AsyncMock(return_value=_mine())), \
         patch.object(routes_agents.agent_memory, "clear_notes",
                      new=AsyncMock(return_value=9)) as clear:
        with pytest.raises(HTTPException) as err:
            await routes_agents.memory_forget_all("agent-9", user=_User())
    assert err.value.status_code == 403
    clear.assert_not_awaited()


async def test_an_agent_the_caller_cannot_see_at_all_is_403():
    """_agents_for returns an empty list on any doubt, and an empty list is
    a refusal here rather than a free pass."""
    with patch.object(routes_agents, "_agents_for", new=AsyncMock(return_value=[])), \
         pytest.raises(HTTPException) as err:
        await routes_agents.memory_list("agent-1", user=_User())
    assert err.value.status_code == 403


async def test_a_note_that_was_not_there_is_not_an_error():
    """delete_note returns False for a miss and for a malformed id. The
    page asked for it to be gone and it is gone, so this is a 200 that says
    nothing was removed, not a 404."""
    with patch.object(routes_agents, "_agents_for", new=AsyncMock(return_value=_mine())), \
         patch.object(routes_agents.agent_memory, "delete_note",
                      new=AsyncMock(return_value=False)):
        out = await routes_agents.memory_forget("agent-1", "not-a-uuid", user=_User())
    assert out == {"forgotten": 0}


# --- when the database is down ---------------------------------------------
# note_counts and list_notes raise on a read failure by design: their
# docstrings say the caller catches, and recall_block is the caller that
# does. A route is a caller too, and an unhandled raise here is a 500.
#
# The answer is 503 and never an empty one. A card that says "0 notes"
# beside a Forget button is a lie the person acts on: they see an agent
# that has forgotten them, and the notes are still there.

async def test_counts_say_503_rather_than_zero_when_the_read_fails():
    with patch.object(routes_agents.agent_memory, "note_counts",
                      new=AsyncMock(side_effect=RuntimeError("no database"))), \
         pytest.raises(HTTPException) as err:
        await routes_agents.memory_counts(user=_User())
    assert err.value.status_code == 503
    assert "0" not in str(err.value.detail)


async def test_listing_says_503_when_the_read_fails():
    with patch.object(routes_agents, "_agents_for", new=AsyncMock(return_value=_mine())), \
         patch.object(routes_agents.agent_memory, "list_notes",
                      new=AsyncMock(side_effect=RuntimeError("no database"))), \
         pytest.raises(HTTPException) as err:
        await routes_agents.memory_list("agent-1", user=_User())
    assert err.value.status_code == 503


async def test_forgetting_one_note_says_503_when_the_delete_fails():
    """A delete that failed must not read as a delete that found nothing.
    Both would otherwise reach the page as forgotten: 0."""
    with patch.object(routes_agents, "_agents_for", new=AsyncMock(return_value=_mine())), \
         patch.object(routes_agents.agent_memory, "delete_note",
                      new=AsyncMock(side_effect=RuntimeError("no database"))), \
         pytest.raises(HTTPException) as err:
        await routes_agents.memory_forget("agent-1", "n1", user=_User())
    assert err.value.status_code == 503


async def test_forgetting_everything_says_503_when_the_delete_fails():
    with patch.object(routes_agents, "_agents_for", new=AsyncMock(return_value=_mine())), \
         patch.object(routes_agents.agent_memory, "clear_notes",
                      new=AsyncMock(side_effect=RuntimeError("no database"))), \
         pytest.raises(HTTPException) as err:
        await routes_agents.memory_forget_all("agent-1", user=_User())
    assert err.value.status_code == 503


async def test_a_refusal_is_not_turned_into_a_503():
    """403 is an HTTPException, and HTTPException is an Exception. Only the
    store call may sit inside the try, or a stranger's request would come
    back as "the database is down" and read like our fault, not theirs."""
    with patch.object(routes_agents, "_agents_for", new=AsyncMock(return_value=_mine())), \
         patch.object(routes_agents.agent_memory, "clear_notes",
                      new=AsyncMock(side_effect=RuntimeError("no database"))), \
         pytest.raises(HTTPException) as err:
        await routes_agents.memory_forget_all("agent-9", user=_User())
    assert err.value.status_code == 403


# --- the route table -------------------------------------------------------
# The paths the card UI will call. Asserted here because a route the page
# needs can be renamed or shadowed without any test of the handlers noticing.

def _declared():
    """(path relative to the router prefix, methods), in declaration order.

    The prefix is stripped because router.prefix is already applied to
    route.path by the time the routes are on the router, and the page-facing
    question is about the part after /agents.
    """
    out = []
    for route in routes_agents.router.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", None)
        if methods is None:
            continue
        if path.startswith(routes_agents.router.prefix):
            path = path[len(routes_agents.router.prefix):]
        out.append((path, set(methods)))
    return out


@pytest.mark.parametrize("path, methods", [
    ("/memory", {"GET"}),
    ("/{agent_id}/memory", {"GET"}),
    ("/{agent_id}/memory/{note_id}", {"DELETE"}),
    ("/{agent_id}/memory", {"DELETE"}),
])
def test_the_four_memory_routes_are_registered(path, methods):
    # Pinned, because the paths written above the counts route and handed to
    # the page author are the prefix plus these, and a changed prefix would
    # move all four without touching a line below it.
    assert routes_agents.router.prefix == "/agents"
    assert (path, methods) in _declared(), _declared()


def test_the_counts_route_is_declared_before_the_per_agent_one():
    """A literal path is declared before a parameterised one that could
    stand in for it. These two cannot collide today, because /agents/memory
    is one segment after the prefix and /{agent_id}/memory is two, so an
    agent whose id is literally "memory" reaches /agents/memory/memory and
    not the counts route. The order is what keeps the counts route safe if
    somebody later adds a one-segment route like /{agent_id}: the first
    matching route wins, so a literal declared first can never be swallowed.
    """
    paths = [p for p, _ in _declared()]
    assert paths.index("/memory") < paths.index("/{agent_id}/memory")


# --- over HTTP -------------------------------------------------------------
# Everything above calls the handlers directly, which proves what they
# decide and nothing about whether a browser can reach them. These drive the
# same router the app mounts, through a real request, with the same identity
# dependency the gateway feeds.

OWNER = "memory-owner@example.com"
ADA = {"id": "agent-1", "name": "Ada"}


@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    app.include_router(routes_agents.router, prefix="/api/tasks")
    app.dependency_overrides[current_user] = lambda: CurrentUser(email=OWNER)
    monkeypatch.setattr(routes_agents, "_agents_for",
                        AsyncMock(return_value=[ADA]))
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def test_no_identity_reaches_nothing(monkeypatch):
    """A delete is the one that cannot be taken back, so it is the one to
    prove: no token, no route, and the store never called."""
    app = FastAPI()
    app.include_router(routes_agents.router, prefix="/api/tasks")

    def _refuse():
        raise HTTPException(status_code=401, detail="no")
    app.dependency_overrides[current_user] = _refuse
    clear = AsyncMock(return_value=3)
    monkeypatch.setattr(routes_agents.agent_memory, "clear_notes", clear)
    monkeypatch.setattr(routes_agents, "_agents_for", AsyncMock(return_value=[ADA]))
    c = AsyncClient(transport=ASGITransport(app=app), base_url="http://t")
    r = await c.delete("/api/tasks/agents/agent-1/memory")
    assert r.status_code == 401, r.text
    clear.assert_not_awaited()


async def test_deleting_someone_elses_memory_over_http_is_403(client, monkeypatch):
    clear = AsyncMock(return_value=3)
    monkeypatch.setattr(routes_agents.agent_memory, "clear_notes", clear)
    r = await client.delete("/api/tasks/agents/agent-somebody-elses/memory")
    assert r.status_code == 403, r.text
    clear.assert_not_awaited()


async def test_deleting_your_own_memory_over_http_is_200(client, monkeypatch):
    clear = AsyncMock(return_value=3)
    monkeypatch.setattr(routes_agents.agent_memory, "clear_notes", clear)
    r = await client.delete("/api/tasks/agents/agent-1/memory")
    assert r.status_code == 200, r.text
    assert r.json() == {"forgotten": 3}
    clear.assert_awaited_once_with(OWNER, "agent-1")


async def test_forgetting_one_note_over_http_is_200(client, monkeypatch):
    """Three segments, so this is also the proof that the note route is
    reachable and is not swallowed by the two-segment one above it."""
    forget = AsyncMock(return_value=True)
    monkeypatch.setattr(routes_agents.agent_memory, "delete_note", forget)
    r = await client.delete("/api/tasks/agents/agent-1/memory/n1")
    assert r.status_code == 200, r.text
    assert r.json() == {"forgotten": 1}
    forget.assert_awaited_once_with(OWNER, "agent-1", "n1")


async def test_the_counts_route_is_reachable_over_http(client, monkeypatch):
    """One segment, and the route an agent named "memory" was supposed to be
    able to shadow. It cannot, and this is what says so through the router
    rather than through a reading of the table."""
    monkeypatch.setattr(routes_agents.agent_memory, "note_counts",
                        AsyncMock(return_value={"agent-1": 2}))
    r = await client.get("/api/tasks/agents/memory")
    assert r.status_code == 200, r.text
    assert r.json() == {"counts": {"agent-1": 2}}


async def test_a_database_failure_over_http_is_a_503_not_a_500(client, monkeypatch):
    monkeypatch.setattr(routes_agents.agent_memory, "list_notes",
                        AsyncMock(side_effect=RuntimeError("no database")))
    r = await client.get("/api/tasks/agents/agent-1/memory")
    assert r.status_code == 503, r.text
    assert r.json()["detail"] == "Could not read memory just now."
