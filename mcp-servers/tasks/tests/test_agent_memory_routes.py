"""What a person may read and forget about their own agents' memory.

Owner only, the same rule /speak applies: an agent that is not in the
caller's own list is not theirs to read or to empty. There is no admin path
here on purpose. An admin's model listing carries everybody's agents, and
one person's notes about their own work are not an operator's to page
through.
"""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

import routes_agents


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
    assert one == {"forgotten": True}
    assert every == {"forgotten": 3}
    forget.assert_awaited_once_with("o@example.com", "agent-1", "n1")
    clear.assert_awaited_once_with("o@example.com", "agent-1")


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
    assert out == {"forgotten": False}


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
