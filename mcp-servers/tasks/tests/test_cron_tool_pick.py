# -*- coding: utf-8 -*-
"""A cron run is offered the tools its prompt needs, not every tool there is.

Measured 2026-11-26 over 14 days: "give me the best quote" runs used 27,000
to 49,000 input tokens. Every run was offered all 17 of the owner's tool
groups, and the 16 declared directly cost about 7,200 tokens of descriptions
on every round, needed or not. The main chat stopped doing that on
2026-10-28 (routes_agent_turn._auto_tools: Jev picks per message); a
schedule never did.

A cron run now asks the same question about its own prompt. Two things
differ from the chat, because nobody is watching a cron run to notice a
missing tool:

  - the connected-apps gateway (server:mcp-proxy) always stays. It costs
    about 1,000 tokens, it is how the web is reached, and Jev answered "no
    tools" for "the best quote ... and news update today", which would have
    taken the news part's web search away;
  - CRON_TOOL_PICK=0 turns the pick off without a deploy.

And as in the chat: Jev unavailable means every tool, so a run never does
worse than before.
"""
import os
from unittest.mock import AsyncMock

import pytest

os.environ.setdefault("AIUI_FERNET_KEY",
                      "SFNQQkFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=")

import agent_jev  # noqa: E402
import agent_memory  # noqa: E402
import agent_runner  # noqa: E402
import routes_agent_turn  # noqa: E402

#: The 17 a real person had on 2026-11-26, in the order the service lists them.
EVERY = ["account", "agent_builder", "agents", "automations", "calendar",
         "code", "colleague", "documents", "excel_creator",
         "executive_dashboard", "gdrive", "gmail", "remember", "schedules",
         "skills", "video", "server:mcp-proxy"]


class _Sched:
    id = "s1"
    agent_id = "agent-1"
    user_email = "o@example.com"
    prompt = "Check my Gmail inbox and say what needs a reply."
    last_result = ""
    last_run_status = None
    tool_mode = "read_only"
    name = "Inbox check"


@pytest.fixture
def run(monkeypatch):
    seen = {"asked": []}

    async def fake_chat(**kwargs):
        seen.update(kwargs)
        return "report", []

    async def fake_pick(email, text, tools, context=""):
        seen["asked"].append((email, text, list(tools)))
        result = seen.get("pick")
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(agent_runner, "_owui_user_id_for", AsyncMock(return_value="u1"))
    monkeypatch.setattr(agent_runner, "_list_agents",
                        AsyncMock(return_value=([{"id": "agent-1", "name": "Ada",
                                                  "meta": {"toolIds": []}}], False)))
    monkeypatch.setattr(agent_runner, "mint_owui_token", lambda *a, **k: "tok")
    monkeypatch.setattr(agent_runner, "session_stamp_for", AsyncMock(return_value=None))
    monkeypatch.setattr(agent_runner, "_chat", fake_chat)
    monkeypatch.setattr(agent_runner.agent_activity, "start_run",
                        AsyncMock(return_value=None))
    monkeypatch.setattr(agent_runner.agent_activity, "finish_run", AsyncMock())
    monkeypatch.setattr(agent_memory, "recall_block", AsyncMock(return_value=""))
    monkeypatch.setattr(agent_runner.agent_graph, "graph_block",
                        AsyncMock(return_value=""))
    monkeypatch.setattr(routes_agent_turn, "tools_for_agent",
                        AsyncMock(return_value=list(EVERY)))
    monkeypatch.setattr(agent_jev, "pick_tools", fake_pick)
    monkeypatch.setattr(routes_agent_turn, "_PICKS", {})
    monkeypatch.delenv("CRON_TOOL_PICK", raising=False)
    return seen


async def test_a_run_is_offered_what_its_prompt_needs(run):
    run["pick"] = ["gmail"]
    status, _result, _ = await agent_runner.run_agent(_Sched())
    assert status == "completed"
    assert run["tool_ids"] == ["colleague", "gmail", "remember", "skills",
                               "server:mcp-proxy"], \
        "the pick, the core every agent keeps, and the gateway, in list order"


async def test_jev_is_asked_about_the_schedules_own_prompt(run):
    run["pick"] = []
    await agent_runner.run_agent(_Sched())
    assert run["asked"] == [("o@example.com", _Sched.prompt, EVERY)]


async def test_needing_nothing_still_keeps_the_gateway_and_the_core(run):
    """Live 2026-11-26 Jev answered [] for "give me the best quote for this
    day and send give me news update today": the news needs the web, and
    the web is behind the gateway."""
    run["pick"] = []
    await agent_runner.run_agent(_Sched())
    assert run["tool_ids"] == ["colleague", "remember", "skills",
                               "server:mcp-proxy"]


async def test_jev_unavailable_offers_every_tool_as_before(run):
    run["pick"] = None
    await agent_runner.run_agent(_Sched())
    assert run["tool_ids"] == EVERY


async def test_a_broken_pick_offers_every_tool_and_never_costs_the_run(run):
    run["pick"] = RuntimeError("jev exploded")
    status, _result, _ = await agent_runner.run_agent(_Sched())
    assert status == "completed"
    assert run["tool_ids"] == EVERY


async def test_the_switch_turns_it_off_without_asking_jev(run, monkeypatch):
    monkeypatch.setenv("CRON_TOOL_PICK", "0")
    run["pick"] = ["gmail"]
    await agent_runner.run_agent(_Sched())
    assert run["tool_ids"] == EVERY
    assert run["asked"] == []


async def test_a_prompt_less_run_is_not_narrowed(run):
    class Blank(_Sched):
        prompt = ""
    run["pick"] = ["gmail"]
    await agent_runner.run_agent(Blank())
    assert run["tool_ids"] == EVERY
