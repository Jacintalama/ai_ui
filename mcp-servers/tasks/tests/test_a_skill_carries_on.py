"""A skill the main chat is following carries on to the next message
(2026-11-27).

Live: "whenever someone fills in my contact form, add them to a list and
tell me on Slack" picked build-a-workflow at 0.98, and its steps went in
front of the assistant. The answer was plain. The person said "use n8n",
which is the moment the skill says to start following it, and it scored
0.89, under the 0.90 cut (and was already named in a reply, so it would
have been dropped anyway). The tools carried over, the steps did not, and
the answer said "form posts to a webhook" to the person the skill is for.
"""
import asyncio

import app_triage
import routes_agent_turn as rt

BODY = "# Build a workflow\n\nNever say trigger, node, webhook."
POOL = {"build-a-workflow": {"name": "build-a-workflow", "tools": ["schedules"],
                             "description": "Build an n8n workflow.",
                             "body": BODY},
        "weekly-review": {"name": "weekly-review", "tools": [],
                          "description": "Review the week.",
                          "body": "# Weekly\n\n1. Ask what shipped."}}


class _Body:
    user_email = "owner@example.com"
    chat_id = "chat-1"
    route_only = True
    first_only = False
    agent_id = None

    def __init__(self, text, context=None):
        self.messages = list(context or []) + [{"role": "user", "content": text}]


def _wire(monkeypatch, pinned=""):
    seen = {"skill_pins": []}

    async def turn_for(user_email, agent, messages, names=(), roster=(),
                       graph="", now=None, tool_ids=None):
        seen["graph"], seen["tool_ids"] = graph, tool_ids
        return {"agent": agent, "answer": "Sure.", "notes": []}

    async def graph_block(_email, _text):
        return "GRAPH"

    async def every_tool(email):
        return ["skills", "schedules", "automations", "server:mcp-proxy"]

    async def write_pin(key, tools):
        seen["pinned"] = list(tools)

    async def read_skill(key):
        return pinned

    async def write_skill(key, name):
        seen["skill_pins"].append(name)

    monkeypatch.setattr(rt, "_turn_for", turn_for)
    monkeypatch.setattr(rt.agent_graph, "graph_block", graph_block)
    monkeypatch.setattr(rt.agent_progress, "say", lambda line: None)
    monkeypatch.setattr(rt, "_every_tool_for", every_tool)
    monkeypatch.setattr(rt, "_write_tools_pin", write_pin)
    monkeypatch.setattr(rt, "_read_skill_pin", read_skill)
    monkeypatch.setattr(rt, "_write_skill_pin", write_skill)
    monkeypatch.setattr(rt.agent_skills, "load_all", lambda: POOL)
    return seen


def _reply(text, picked, triage):
    return asyncio.run(rt._assistant_reply(_Body(text), text, [],
                                           picked=picked, triage=triage))


def test_the_steps_carry_on_to_the_next_message(monkeypatch):
    seen = _wire(monkeypatch, pinned="build-a-workflow")
    triage = {"picks": [], "connected": set(), "skills": [], "pool": POOL}
    out = _reply("use n8n", ["automations", "server:mcp-proxy"], triage)
    assert out is not None
    assert "Never say trigger, node, webhook." in seen["graph"]
    assert "earlier in this chat" in seen["graph"]
    assert "skills" in seen["tool_ids"]
    assert seen["skill_pins"] == ["build-a-workflow"]      # kept going


def test_the_skill_carries_on_when_triage_could_not_be_asked(monkeypatch):
    seen = _wire(monkeypatch, pinned="build-a-workflow")
    out = _reply("use n8n", ["automations"], None)
    assert out is not None
    assert "Never say trigger, node, webhook." in seen["graph"]


def test_a_picked_skill_is_remembered_for_the_chat(monkeypatch):
    seen = _wire(monkeypatch)
    triage = {"picks": [], "connected": set(),
              "skills": [("build-a-workflow", 0.98)], "pool": POOL}
    _reply("automate my contact form", [], triage)
    assert seen["skill_pins"] == ["build-a-workflow"]


def test_a_new_pick_wins_over_the_one_carried(monkeypatch):
    seen = _wire(monkeypatch, pinned="build-a-workflow")
    triage = {"picks": [], "connected": set(),
              "skills": [("weekly-review", 0.95)], "pool": POOL}
    _reply("review my week", [], triage)
    assert "1. Ask what shipped." in seen["graph"]
    assert "Never say trigger" not in seen["graph"]
    assert seen["skill_pins"] == ["weekly-review"]


def test_nothing_is_carried_without_a_pin(monkeypatch):
    seen = _wire(monkeypatch, pinned="")
    triage = {"picks": [], "connected": set(), "skills": [], "pool": POOL}
    _reply("use n8n", ["automations"], triage)
    assert "Never say trigger" not in seen.get("graph", "")


def test_a_pinned_skill_that_no_longer_exists_is_ignored(monkeypatch):
    seen = _wire(monkeypatch, pinned="gone-skill")
    triage = {"picks": [], "connected": set(), "skills": [], "pool": POOL}
    _reply("use n8n", ["automations"], triage)
    assert "earlier in this chat" not in seen.get("graph", "")


def test_no_tools_in_play_means_no_assistant_turn_for_a_carried_skill(monkeypatch):
    """Carrying on only happens inside a turn that runs anyway: with no tool
    and nothing to recommend the free model answers, as before."""
    seen = _wire(monkeypatch, pinned="build-a-workflow")
    triage = {"picks": [], "connected": set(), "skills": [], "pool": POOL}
    assert _reply("thanks!", [], triage) is None
    assert "graph" not in seen


def test_the_brief_says_it_was_being_followed():
    carried = app_triage.carried_skill("build-a-workflow", POOL)
    b = app_triage.brief({"skills": [carried]})
    assert "earlier in this chat" in b and BODY in b
    assert app_triage.carried_skill("gone-skill", POOL) is None
