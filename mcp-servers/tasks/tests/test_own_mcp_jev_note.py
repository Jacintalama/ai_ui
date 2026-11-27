"""Jev is told about a person's own MCP servers, and only that person's.

On Auto, the assistant runs only when Jev picks a tool group, and the
gateway's note lists the built apps. Without a line about a person's own
servers, "create an invoice in Acme" goes to the free model, which cannot
run anything. The note is unchanged byte for byte for everybody without
own servers, because the calibrated cut (PURPOSE_TOOLS) was measured on it.
"""
import os
from unittest.mock import AsyncMock

os.environ.setdefault("AIUI_FERNET_KEY",
                      "SFNQQkFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=")

import agent_jev  # noqa: E402
import own_mcp_store  # noqa: E402
import routes_agent_turn  # noqa: E402

GATEWAY = "server:mcp-proxy"
import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(routes_agent_turn, "_OWN_NOTES", {})


ROWS = [{"id": "s1", "slug": "acme", "label": "Acme",
         "tools": [{"tool": "create_invoice"}, {"tool": "list_customers"}]}]


def test_the_question_is_byte_for_byte_unchanged_without_a_note():
    before = agent_jev.tools_request("check my trello", ["gmail", GATEWAY])
    assert agent_jev.tools_request("check my trello", ["gmail", GATEWAY],
                                   notes=None) == before
    assert agent_jev.tools_request("check my trello", ["gmail", GATEWAY],
                                   notes={}) == before
    note = agent_jev.TOOL_NOTES[GATEWAY]
    assert before[1]["t1"]["instructions"] == (
        f"To answer or do what the message asks, is a tool for {note} needed?")


def test_a_note_replaces_the_one_tool_it_names():
    _, questions = agent_jev.tools_request(
        "make an invoice", ["gmail", GATEWAY], notes={GATEWAY: "THE LONGER NOTE"})
    assert "THE LONGER NOTE" in questions["t1"]["instructions"]
    assert agent_jev.TOOL_NOTES["gmail"] in questions["t0"]["instructions"]


async def test_a_person_with_own_servers_gets_the_longer_note(monkeypatch):
    monkeypatch.setattr(own_mcp_store, "list_for", AsyncMock(return_value=ROWS))
    notes = await routes_agent_turn._own_notes("a@x.com", ["gmail", GATEWAY])
    assert notes == {GATEWAY: agent_jev.TOOL_NOTES[GATEWAY]
                     + " and their own servers: Acme (create_invoice, list_customers)"}


async def test_no_own_servers_means_no_note(monkeypatch):
    monkeypatch.setattr(own_mcp_store, "list_for", AsyncMock(return_value=[]))
    assert await routes_agent_turn._own_notes("b@x.com", ["gmail", GATEWAY]) is None


async def test_without_the_gateway_the_store_is_not_read(monkeypatch):
    asked = AsyncMock(return_value=ROWS)
    monkeypatch.setattr(own_mcp_store, "list_for", asked)
    assert await routes_agent_turn._own_notes("a@x.com", ["gmail"]) is None
    asked.assert_not_called()


async def test_a_store_failure_leaves_the_note_alone(monkeypatch):
    monkeypatch.setattr(own_mcp_store, "list_for",
                        AsyncMock(side_effect=RuntimeError("db down")))
    assert await routes_agent_turn._own_notes("a@x.com", [GATEWAY]) is None


async def test_the_agent_pick_hands_jev_the_note(monkeypatch):
    seen = {}

    async def pick(email, text, tools, context="", notes=None):
        seen["notes"] = notes
        return [GATEWAY]
    monkeypatch.setattr(agent_jev, "pick_tools", pick)
    monkeypatch.setattr(routes_agent_turn, "_PICKS", {})
    monkeypatch.setattr(own_mcp_store, "list_for", AsyncMock(return_value=ROWS))
    await routes_agent_turn._auto_tools("a@x.com", "make an Acme invoice", ["gmail", GATEWAY])
    assert "Acme (create_invoice" in seen["notes"][GATEWAY]


async def test_the_note_is_read_once_a_minute(monkeypatch):
    asked = AsyncMock(return_value=ROWS)
    monkeypatch.setattr(own_mcp_store, "list_for", asked)
    await routes_agent_turn._own_notes("a@x.com", [GATEWAY])
    await routes_agent_turn._own_notes("a@x.com", [GATEWAY])
    assert asked.await_count == 1
