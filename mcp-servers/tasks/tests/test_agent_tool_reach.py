"""Every agent can reach every feature this person has.

An agent used to be handed only the tools ticked on its own card, so asked
"which apps have I connected" it had nothing to look with and guessed at App
Builder counts instead. A guess about somebody's own account reads as a lie.

Widening what an agent can REACH is not widening what it may DO: the access
level still decides whether a write tool runs, asks first, or is refused.
"""
import importlib

import pytest

import routes_agent_turn as rt


@pytest.fixture(autouse=True)
def _reload():
    importlib.reload(rt)
    yield


def _listed(*ids):
    async def tools_for_email(email):
        return {"tools": [{"id": i, "label": i, "connected": True} for i in ids]}
    return tools_for_email


async def test_an_agent_reaches_every_tool_the_person_has(monkeypatch):
    import routes_agents
    monkeypatch.setattr(routes_agents, "tools_for_email",
                        _listed("account", "gmail", "documents"))
    got = await rt._every_tool_for("owner@example.com")
    assert set(got) == {"account", "gmail", "documents"}


async def test_an_agent_may_not_reach_the_tool_that_runs_agents(monkeypatch):
    """It is already inside a turn. Calling it would start a round inside a
    round while the person waits on the outer one."""
    import routes_agents
    monkeypatch.setattr(routes_agents, "tools_for_email",
                        _listed("account", "agents", "gmail"))
    got = await rt._every_tool_for("owner@example.com")
    assert "agents" not in got
    assert {"account", "gmail"} <= set(got)


async def test_a_failed_listing_costs_the_agent_nothing_it_already_had(monkeypatch):
    """Fails toward the agent's own tools rather than toward none."""
    import routes_agents

    async def broken(email):
        raise RuntimeError("upstream is down")

    monkeypatch.setattr(routes_agents, "tools_for_email", broken)
    assert await rt._every_tool_for("owner@example.com") == []


async def test_the_agents_own_tools_stay_in_front(monkeypatch):
    """An explicitly ticked tool is never lost to a short wider read."""
    import routes_agents
    monkeypatch.setattr(routes_agents, "tools_for_email", _listed("account"))

    async def owui_user(email):
        return "owner-id"

    async def listing(token):
        return ([{"id": "agent-a", "name": "Ada",
                  "meta": {"toolIds": ["server:mcp-proxy"], "access": "ask"}}],
                False)

    monkeypatch.setattr(rt, "_owui_user_id_for", owui_user)
    monkeypatch.setattr(rt, "_list_agents", listing)
    monkeypatch.setattr(rt, "mint_owui_token", lambda *a, **k: "tok")

    _token, tools, _level = await rt._resolve_agent("owner@example.com", "agent-a")
    assert tools[0] == "server:mcp-proxy", "its own tool comes first"
    assert "account" in tools, "and it gains what the person has"


async def test_a_tool_is_never_listed_twice(monkeypatch):
    import routes_agents
    monkeypatch.setattr(routes_agents, "tools_for_email",
                        _listed("gmail", "account"))

    async def owui_user(email):
        return "owner-id"

    async def listing(token):
        return ([{"id": "agent-a", "name": "Ada",
                  "meta": {"toolIds": ["gmail"], "access": "ask"}}], False)

    monkeypatch.setattr(rt, "_owui_user_id_for", owui_user)
    monkeypatch.setattr(rt, "_list_agents", listing)
    monkeypatch.setattr(rt, "mint_owui_token", lambda *a, **k: "tok")

    _token, tools, _level = await rt._resolve_agent("owner@example.com", "agent-a")
    assert tools.count("gmail") == 1
