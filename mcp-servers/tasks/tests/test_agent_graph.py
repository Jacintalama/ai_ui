"""The Brain reaches the agents.

Ralph, 2026-09-18: "make sure the graph connected to the agents so agents use
the graph". It was connected to every ordinary model through an Open WebUI
inlet filter, and to none of the agents, because an agent turn is a direct API
call from this service and never passes through that filter.
"""
import asyncio
import sys
import types

import pytest

import agent_graph


def _fake_graph(monkeypatch, result=None, raises=None, slow=0.0, seen=None):
    """Stands in for routes_knowledge_graph, which pulls in the embedding
    stack and a live database. agent_graph imports it inside the call, so the
    module only has to be in sys.modules."""
    mod = types.ModuleType("routes_knowledge_graph")

    async def context_for(user_email, q="", limit=6, include_team=False):
        if seen is not None:
            seen.append({"email": user_email, "q": q, "limit": limit,
                         "include_team": include_team})
        if slow:
            await asyncio.sleep(slow)
        if raises is not None:
            raise raises
        return result if result is not None else {"context": ""}

    mod.context_for = context_for
    monkeypatch.setitem(sys.modules, "routes_knowledge_graph", mod)
    return mod


async def test_the_block_carries_what_the_person_has(monkeypatch):
    _fake_graph(monkeypatch, {"context": "Apps: 12. Schedules: 3."})
    said = await agent_graph.graph_block("owner@example.com", "how many apps")
    assert "Apps: 12. Schedules: 3." in said
    assert said.startswith(agent_graph.HEADING)


async def test_an_empty_graph_adds_nothing_at_all(monkeypatch):
    """A heading with nothing under it is worse than silence: it tells the
    model a block is there and then shows it an empty one."""
    _fake_graph(monkeypatch, {"context": "   "})
    assert await agent_graph.graph_block("owner@example.com", "anything") == ""


@pytest.mark.parametrize("payload", [None, {}, {"context": None}, "not a dict"])
async def test_a_shape_it_did_not_expect_is_not_a_failed_turn(monkeypatch,
                                                              payload):
    _fake_graph(monkeypatch, payload)
    assert await agent_graph.graph_block("owner@example.com") == ""


async def test_the_question_and_the_person_are_passed_through(monkeypatch):
    seen = []
    _fake_graph(monkeypatch, {"context": "x"}, seen=seen)
    await agent_graph.graph_block("owner@example.com", "what is on today")
    assert seen == [{"email": "owner@example.com", "q": "what is on today",
                     "limit": agent_graph.GRAPH_LIMIT, "include_team": False}]


async def test_an_admin_still_sees_only_their_own(monkeypatch):
    """The route passes an admin's team material because a person asking in
    their own chat is asking as themselves. An agent also runs unattended on
    a schedule, and that block can be delivered straight to a channel."""
    seen = []
    _fake_graph(monkeypatch, {"context": "x"}, seen=seen)
    await agent_graph.graph_block("admin@example.com", "anything")
    assert seen[0]["include_team"] is False


async def test_a_graph_that_fails_costs_the_turn_nothing(monkeypatch, caplog):
    _fake_graph(monkeypatch, raises=RuntimeError("no database"))
    assert await agent_graph.graph_block("owner@example.com", "q") == ""


async def test_a_graph_that_hangs_does_not_hold_the_answer(monkeypatch):
    """A person is waiting. The block improves an answer they are getting
    either way, so it gets a ceiling and not a promise."""
    monkeypatch.setattr(agent_graph, "GRAPH_TIMEOUT_SECONDS", 0.05)
    _fake_graph(monkeypatch, {"context": "late"}, slow=5)
    said = await asyncio.wait_for(
        agent_graph.graph_block("owner@example.com", "q"), timeout=2)
    assert said == ""


async def test_nobody_to_read_for_reads_nothing(monkeypatch):
    seen = []
    _fake_graph(monkeypatch, {"context": "x"}, seen=seen)
    assert await agent_graph.graph_block("", "q") == ""
    assert seen == [], "it opened a database connection for nobody"
