"""Every agent's tools are picked for each message, by the system.

Lukas, 2026-10-27: nobody should have to tick tools on an agent. The main
chat's assistant already got only what Jev picked for the message
(main_assistant); agents got every tool, or a hand-ticked few. Now an agent
reaches everything its owner has, and each turn carries what Jev is sure
the message needs, plus the few an agent needs to follow its own brief.
A hand-ticked list from before is no longer a limit.
"""
import pytest

import agent_access
import agent_brief
import routes_agent_turn as rt

EVERY = ["account", "calendar", "code", "colleague", "documents", "gmail",
         "remember", "schedules", "server:mcp-proxy", "skills"]


@pytest.fixture(autouse=True)
def no_cached_picks():
    rt._PICKS.clear()
    yield
    rt._PICKS.clear()


def _stub(monkeypatch, seen, picks, agent_id="agent-iris"):
    async def resolve(user_email, aid):
        return ("tok", list(EVERY), agent_access.LEVEL_ALL,
                {"id": aid, "name": "Iris"}, [])

    async def chat(**kw):
        seen.setdefault("tools", []).append(kw.get("tool_ids"))
        return ("answered", [])

    async def start_run(agent_id, user_email, source, parent_run_id=None):
        return "run-1"

    async def finish_run(run_id, status, usage=None):
        return None

    async def pick_tools(email, text, tools):
        seen.setdefault("asked", []).append((email, text, list(tools)))
        return picks

    monkeypatch.setattr(rt, "_resolve_agent_row", resolve)
    monkeypatch.setattr(rt, "_chat", chat)
    monkeypatch.setattr(rt.agent_activity, "start_run", start_run)
    monkeypatch.setattr(rt.agent_activity, "finish_run", finish_run)
    monkeypatch.setattr(rt.agent_memory, "schedule_reflection",
                        lambda *a, **k: None)
    monkeypatch.setattr(rt.agent_jev, "pick_tools", pick_tools)


def _said(text):
    return [{"role": "user", "content": text}]


async def test_an_agent_gets_the_tools_jev_picked_for_the_message(monkeypatch):
    seen = {}
    _stub(monkeypatch, seen, ["calendar"])
    await rt._run_turn("me@example.com", "agent-iris",
                       _said("what is on my calendar tomorrow"))
    assert seen["asked"] == [("me@example.com",
                              "what is on my calendar tomorrow", EVERY)]
    # Jev's pick, plus what every agent keeps to follow its own brief.
    assert seen["tools"] == [["calendar", "colleague", "remember", "skills"]]


async def test_none_needed_still_keeps_skills_notes_and_colleagues(monkeypatch):
    """"Run the weekly review" needs the skill looked up, which Jev may not
    call a tool the message needs."""
    seen = {}
    _stub(monkeypatch, seen, [])
    await rt._run_turn("me@example.com", "agent-iris", _said("hi there"))
    assert seen["tools"] == [["colleague", "remember", "skills"]]


async def test_jev_unable_to_pick_offers_every_tool(monkeypatch):
    """No key, a timeout or an unreadable answer: the agent behaves exactly
    as it did before there was a pick."""
    seen = {}
    _stub(monkeypatch, seen, None)
    await rt._run_turn("me@example.com", "agent-iris", _said("check my email"))
    assert seen["tools"] == [EVERY]


async def test_a_round_asks_jev_once_for_one_message(monkeypatch):
    """The room runs every agent over the same words. One pick serves all."""
    seen = {}
    _stub(monkeypatch, seen, ["gmail"])
    for aid in ("agent-ada", "agent-mia", "agent-dev"):
        await rt._run_turn("me@example.com", aid, _said("any new email?"))
    assert len(seen["asked"]) == 1
    assert seen["tools"] == [["colleague", "gmail", "remember", "skills"]] * 3


async def test_a_new_message_is_picked_again(monkeypatch):
    seen = {}
    _stub(monkeypatch, seen, ["gmail"])
    await rt._run_turn("me@example.com", "agent-ada", _said("any new email?"))
    await rt._run_turn("me@example.com", "agent-ada", _said("and tomorrow?"))
    assert len(seen["asked"]) == 2


async def test_another_person_is_never_served_a_cached_pick(monkeypatch):
    seen = {}
    _stub(monkeypatch, seen, ["gmail"])
    await rt._run_turn("a@example.com", "agent-ada", _said("any new email?"))
    await rt._run_turn("b@example.com", "agent-ada", _said("any new email?"))
    assert len(seen["asked"]) == 2


async def test_tools_the_caller_named_are_not_picked_again(monkeypatch):
    """The main chat's assistant arrives with Jev's pick already made."""
    seen = {}
    _stub(monkeypatch, seen, ["gmail"])
    await rt._run_turn("me@example.com", "io-assistant",
                       _said("check my email"), tool_ids=["gmail"])
    assert "asked" not in seen
    assert seen["tools"] == [["gmail"]]


async def test_the_room_picks_on_what_the_person_said(monkeypatch):
    """In a round the last user message is the room's own instruction; the
    person's words come through the intent."""
    seen = {}
    _stub(monkeypatch, seen, ["calendar"])
    with rt.agent_escalation.asking(rt.agent_escalation.Intent(
            person_text="am I free friday", may_pass=True)):
        await rt._run_turn("me@example.com", "agent-ada",
                           _said("Answer only if you have something. PASS."))
    assert seen["asked"][0][1] == "am I free friday"


async def test_a_colleague_is_picked_tools_for_what_it_was_asked(monkeypatch):
    """Ada asks Mia to check the inbox while the person asked Ada to plan
    the week. Mia needs Gmail for the question she got, which the person's
    own words would not have picked."""
    seen = {}
    _stub(monkeypatch, seen, ["gmail"])
    with rt.agent_escalation.asking(rt.agent_escalation.Intent(
            person_text="plan my week")):
        await rt._run_turn("me@example.com", "agent-mia",
                           _said("check the inbox for anything urgent"),
                           surface=agent_access.SURFACE_COLLEAGUE)
    assert seen["asked"][0][1] == "check the inbox for anything urgent"


async def test_a_pick_that_throws_offers_every_tool(monkeypatch):
    seen = {}
    _stub(monkeypatch, seen, None)

    async def boom(email, text, tools):
        raise RuntimeError("jev fell over")

    monkeypatch.setattr(rt.agent_jev, "pick_tools", boom)
    out = await rt._run_turn("me@example.com", "agent-ada", _said("email?"))
    assert out["answer"] == "answered"
    assert seen["tools"] == [EVERY]


# --- a hand-ticked list is no longer a limit --------------------------------

async def test_a_picked_scope_from_before_reaches_everything(monkeypatch):
    async def listed(email):
        return list(EVERY)

    monkeypatch.setattr(rt, "_every_tool_for", listed)
    tools = await rt.tools_for_agent(
        "me@example.com", {"toolIds": ["gmail"], "toolScope": "picked"})
    assert tools[0] == "gmail"
    assert sorted(tools) == sorted(EVERY)


def test_the_brief_says_a_once_narrowed_agent_reaches_everything():
    agent = {"id": "a", "name": "Mia",
             "meta": {"toolIds": ["gmail"], "toolScope": "picked"}}
    assert agent_brief._own_tools(agent) is None
    assert agent_brief._reaches(agent, "calendar")
