"""In the main chat, an agent answers only when the person named it.

Asked for on 2026-10-28, with a screenshot of the chat: "what is the richest
man in the world" was handed to an agent. That was not a bug in the routing,
it was the routing working as built. The row is in `tasks.agent_decision`,
read off production the same day:

    chat_id=dc659a43-...  path=one_agent  agent_id=agent-vera-a104
    agent_confidence=0.92  kind=answer  kind_confidence=0.98

Jev read a general-knowledge question as a research question and picked Vera,
the Researcher. Reasonable from Jev's side; wrong from the person's, who had
named nobody and wanted the free model.

Three rungs could reach an agent without a mention: Jev's pick, the skill
owner and the subject owner. In the main chat all three are now off, and the
switch to put them back is `AGENTS_ANSWER_UNNAMED=1`. The panel and the office
are untouched: asking the room is what that surface is for.
"""
from unittest.mock import AsyncMock

import pytest

import agent_graph
import agent_routing
import routes_agent_turn as rt


SECRET = "s3cret"
AGENTS = [
    {"id": "agent-vera-a104", "name": "Vera", "meta": {"role": "Researcher"}},
    {"id": "agent-mia-2201", "name": "Mia", "meta": {"role": "Receptionist"}},
]


class _Body:
    """Only what _route_chat reads."""

    def __init__(self, text, route_only=True):
        self.messages = [{"role": "user", "content": text}]
        self.user_email = "owner@example.com"
        self.chat_id = "chat-1"
        self.agent_id = None
        self.route_only = route_only
        self.first_only = False


@pytest.fixture
def chat(monkeypatch):
    """_route_chat with everything around it stubbed, and a record of which
    rungs were consulted."""
    seen = {"jev": 0, "skill": 0, "subject": 0, "io": 0, "turn": 0}

    monkeypatch.setattr(rt, "_require_internal", lambda s: None)
    monkeypatch.setattr(rt, "_agents_for", AsyncMock(return_value=AGENTS))
    monkeypatch.setattr(rt, "_read_pin", AsyncMock(return_value=None))
    monkeypatch.setattr(rt, "_write_pin", AsyncMock(return_value=None))
    monkeypatch.setattr(rt, "_clear_pin", AsyncMock(return_value=None))
    monkeypatch.setattr(rt, "_jev_release", AsyncMock(return_value=False))
    # The Brain is read before an agent takes a turn, and it is a real
    # request: unstubbed it reaches DNS and the test fails on the network
    # rather than on the routing.
    monkeypatch.setattr(agent_graph, "graph_block", AsyncMock(return_value=""))

    async def jev(body, text, agents):
        seen["jev"] += 1
        return AGENTS[0]                      # Jev is always sure, to be loud

    # Both return nothing on purpose. The ladder short-circuits: the first
    # rung that names an agent ends it, so a stub that answered would hide
    # whether the rungs below it were reached at all.
    def skill(text, agents, skills):
        seen["skill"] += 1
        return None

    def subject(text, agents):
        seen["subject"] += 1
        return None

    async def io(email, messages):
        seen["io"] += 1
        return "the free model answered"

    async def turn_for(email, agent, messages, names, **kw):
        seen["turn"] += 1
        return {"answer": "%s answered" % agent["name"], "notes": []}

    monkeypatch.setattr(rt, "_jev_decision", jev)
    monkeypatch.setattr(rt, "_jev_answer",
                        AsyncMock(return_value={"turns": [{"agent": AGENTS[0],
                                                           "answer": "Vera answered",
                                                           "notes": []}]}))
    monkeypatch.setattr(rt, "_tool_pick", AsyncMock(return_value=[]))
    monkeypatch.setattr(rt, "_assistant_reply", AsyncMock(return_value=None))
    monkeypatch.setattr(agent_routing, "skill_owner", skill)
    monkeypatch.setattr(agent_routing, "domain_owner", subject)
    monkeypatch.setattr(rt, "_answer_as_io", io)
    monkeypatch.setattr(rt, "_turn_for", turn_for)
    return seen


# --- the main chat -----------------------------------------------------------

async def test_an_unnamed_question_reaches_no_agent(chat, monkeypatch):
    """The reported case. Nobody named, so nobody answers but the free model,
    and none of the three rungs is even consulted."""
    monkeypatch.delenv("AGENTS_ANSWER_UNNAMED", raising=False)
    await rt._route_chat(_Body("what is the richest man in the world"), SECRET)
    assert chat["jev"] == 0, "Jev was asked to pick an agent"
    assert chat["skill"] == 0, "the skill owner was consulted"
    assert chat["subject"] == 0, "the subject owner was consulted"
    assert chat["turn"] == 0, "an agent took an unnamed question"


async def test_naming_an_agent_still_reaches_it(chat, monkeypatch):
    """The guard on the guard. Turning the three rungs off must not make the
    chat deaf to a name, which is the one way left to reach an agent."""
    monkeypatch.delenv("AGENTS_ANSWER_UNNAMED", raising=False)
    out = await rt._route_chat(_Body("Mia, anything unread?"), SECRET)
    assert chat["turn"] == 1, out
    assert "Mia" in str(out)


async def test_the_switch_puts_all_three_back(chat, monkeypatch):
    """One line to restore the old behaviour, so this is a decision and not a
    deletion."""
    monkeypatch.setenv("AGENTS_ANSWER_UNNAMED", "1")
    await rt._route_chat(_Body("what is the richest man in the world"), SECRET)
    assert chat["skill"] == 1
    assert chat["subject"] == 1
    assert chat["jev"] == 1


# --- the panel and the office, which are not the main chat -------------------

async def test_the_panel_still_lets_the_room_answer(chat, monkeypatch):
    """route_only is the main chat's flag. Asking the room is what the panel
    is for, and an agent speaking there surprises nobody."""
    monkeypatch.delenv("AGENTS_ANSWER_UNNAMED", raising=False)
    await rt._route_chat(_Body("anything unread in my inbox", route_only=False),
                         SECRET)
    assert chat["skill"] == 1, "the panel lost the skill owner"
    assert chat["subject"] == 1, "the panel lost the subject owner"


# --- the switch itself -------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("1", True), ("true", True), ("TRUE", True), ("yes", True), ("on", True),
    ("0", False), ("false", False), ("no", False), ("", False), ("  ", False),
])
def test_the_switch_reads_the_usual_words(monkeypatch, value, expected):
    monkeypatch.setenv("AGENTS_ANSWER_UNNAMED", value)
    assert rt._agents_may_take_unnamed() is expected


def test_off_is_the_default(monkeypatch):
    """Unset means named-only. The person asked for that, so it must not
    depend on anybody remembering to set a variable."""
    monkeypatch.delenv("AGENTS_ANSWER_UNNAMED", raising=False)
    assert rt._agents_may_take_unnamed() is False
