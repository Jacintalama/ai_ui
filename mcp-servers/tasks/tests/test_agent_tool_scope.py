"""Whether an agent is limited to the tools somebody picked for it.

Measured on production before this existed: Mia had one tool ticked on the
form and reached twelve. _resolve_agent took whatever was ticked and then
added every tool the owner could reach, so the checkboxes implied a choice
nobody was actually making.

That was deliberate once, and the reason is still good: an agent that cannot
look up its owner's own account guesses, and a guess about somebody's own
things reads as a lie. So "everything" stays the default and stays exactly
what happens today. What changes is that a deliberate narrow choice is now
honoured instead of overridden.
"""
import pytest

import routes_agent_turn as rt


@pytest.fixture
def everything(monkeypatch):
    """The eleven tools this person can reach, as _every_tool_for reports."""
    async def listed(email):
        return ["account", "calendar", "code", "documents", "excel_creator",
                "executive_dashboard", "gdrive", "gmail", "remember",
                "schedules", "server:mcp-proxy", "skills"]
    monkeypatch.setattr(rt, "_every_tool_for", listed)


async def _tools(monkeypatch, meta):
    async def owner(email):
        return "owui-user"

    async def listing(token):
        return [{"id": "agent-1", "name": "Ada", "meta": meta}], False

    monkeypatch.setattr(rt, "_owui_user_id_for", owner)
    monkeypatch.setattr(rt, "_list_agents", listing)
    monkeypatch.setattr(rt, "mint_owui_token", lambda *a, **k: "tok")
    _token, tools, _level = await rt._resolve_agent("who@example.com", "agent-1")
    return tools


async def test_by_default_an_agent_reaches_everything(monkeypatch, everything):
    """Every agent that existed before this setting has no scope, and its
    behaviour must not change by a single tool."""
    tools = await _tools(monkeypatch, {"toolIds": ["gmail"]})
    assert "gmail" in tools
    assert "calendar" in tools
    assert len(tools) >= 12


async def test_all_is_the_same_as_no_setting(monkeypatch, everything):
    a = await _tools(monkeypatch, {"toolIds": ["gmail"]})
    b = await _tools(monkeypatch, {"toolIds": ["gmail"], "toolScope": "all"})
    assert sorted(a) == sorted(b)


async def test_picked_means_picked(monkeypatch, everything):
    """The point of the change. Ralph said yes to this being real: an agent
    limited to Gmail says it cannot check the calendar, rather than quietly
    checking it."""
    tools = await _tools(monkeypatch,
                         {"toolIds": ["gmail"], "toolScope": "picked"})
    assert tools == ["gmail"]


async def test_picking_several_keeps_them_all(monkeypatch, everything):
    tools = await _tools(
        monkeypatch, {"toolIds": ["gmail", "calendar"], "toolScope": "picked"})
    assert sorted(tools) == ["calendar", "gmail"]


async def test_picking_nothing_falls_back_to_everything(monkeypatch, everything):
    """An agent with no tools at all can do nothing and would look broken.
    Somebody who ticks the narrow option and then unticks every box has not
    asked for that; they have not finished choosing."""
    tools = await _tools(monkeypatch, {"toolIds": [], "toolScope": "picked"})
    assert len(tools) >= 12


async def test_the_agents_tool_is_stripped_from_an_agents_own_list(
        monkeypatch, everything):
    """An agent must not reach the tool that runs agents: it is already inside
    a turn, so calling it starts a round inside a round while somebody waits
    on the outer one.

    _every_tool_for has always filtered it, but an agent's OWN toolIds went
    straight through. That did not matter while everything was unioned in
    anyway; with a picked scope it decides what the agent gets, so it is
    filtered at the source now. My first draft of this test stubbed the very
    function that does the filtering and proved nothing."""
    for scope in ("picked", "all", None):
        meta = {"toolIds": ["gmail", "agents"]}
        if scope:
            meta["toolScope"] = scope
        tools = await _tools(monkeypatch, meta)
        assert "agents" not in tools, scope
        assert "gmail" in tools, scope


async def test_junk_in_the_scope_reads_as_everything(monkeypatch, everything):
    """meta comes off a row a model-facing API writes. Anything unrecognised
    has to mean the safe, unchanged behaviour, not an agent silently losing
    its tools."""
    for junk in (None, 5, "PICKED", "some-other-word", [], {"a": 1}):
        tools = await _tools(monkeypatch,
                             {"toolIds": ["gmail"], "toolScope": junk})
        assert len(tools) >= 12, junk
