"""A collective word inside a request does not summon every agent.

2026-11-06. Ralph typed, naming nobody:

    "can you check clickup and create space and create me a task asigned
     for me name the space aiui team and make the task fix ai buildder"

Nine agents answered: Cutter, Crane, Mia, cronss, Rex, Iris, Ada, Vera,
Nora and Kai. Each ran seven rounds of tool calls, most declined because
they are read only, and nothing was created.

The word was "team", inside the name of the space he was asking for.
`match_agents` returns EVERY agent when a collective word appears
anywhere, and the main chat treats whatever it returns as "named".

This is the same complaint as 2026-10-28, when "what is the richest man
in the world" was handed to Vera. The fix then turned off three rungs
that reach an agent without a mention: Jev's pick, the skill owner and
the subject owner. It left this one on, because a collective word looked
like a mention. It is not one. Nobody was named.

So in the MAIN CHAT a collective word alone reaches nobody. Naming an
agent still works, naming two still works, and "@Ada and everyone" still
reaches the room, because a real name was used. The panel and the office
are untouched: asking the room is what those surfaces are for.
"""
import pytest

import agent_routing
import routes_agent_turn as R

AGENTS = [
    {"id": "a1", "name": "Ada", "role": "Project manager"},
    {"id": "a2", "name": "Cutter", "role": "Video editor"},
    {"id": "a3", "name": "Rex", "role": "Engineer"},
]

RALPHS_MESSAGE = ("can you check clickup and create space and create me a "
                  "task asigned for me name the space aiui team and make "
                  "the task fix ai buildder")


# --- the thing that happened --------------------------------------------

def test_the_old_behaviour_is_what_it_was():
    """Pinning the cause, so the fix below is read as deliberate: the
    router really does return everyone for this sentence."""
    everyone = agent_routing.match_agents(RALPHS_MESSAGE, AGENTS)
    assert len(everyone) == len(AGENTS)
    assert agent_routing.addresses_everyone(RALPHS_MESSAGE) is True


def test_nobody_is_summoned_by_a_word_inside_a_request():
    assert R._mentioned(RALPHS_MESSAGE, AGENTS, route_only=True) == []


@pytest.mark.parametrize("text", [
    "name the space aiui team",
    "create a team space in clickup",
    "what did the team ship this week",
    "add everyone to the list",
    "put the guys on the invite",
])
def test_a_collective_word_in_content_reaches_nobody(text):
    assert R._mentioned(text, AGENTS, route_only=True) == []


# --- what must still work -----------------------------------------------

def test_naming_an_agent_still_reaches_it():
    out = R._mentioned("Ada, can you check clickup", AGENTS, route_only=True)
    assert [a["name"] for a in out] == ["Ada"]


def test_naming_two_agents_still_reaches_both():
    out = R._mentioned("Ada and Rex, take a look", AGENTS, route_only=True)
    assert {a["name"] for a in out} == {"Ada", "Rex"}


def test_a_name_with_a_collective_word_still_reaches_the_room():
    """"Ada and everyone" is a real mention, so it keeps its old meaning."""
    out = R._mentioned("Ada and everyone, stand up please", AGENTS,
                       route_only=True)
    assert len(out) == len(AGENTS)


def test_the_panel_and_the_office_are_untouched():
    """Asking the room is what those surfaces are for. route_only is what
    marks the main chat."""
    out = R._mentioned(RALPHS_MESSAGE, AGENTS, route_only=False)
    assert len(out) == len(AGENTS)


def test_the_switch_puts_it_back():
    """One line to restore the old behaviour, like the 2026-10-28 guard."""
    import os
    os.environ["AGENTS_ANSWER_UNNAMED"] = "1"
    try:
        out = R._mentioned(RALPHS_MESSAGE, AGENTS, route_only=True)
        assert len(out) == len(AGENTS)
    finally:
        os.environ.pop("AGENTS_ANSWER_UNNAMED", None)


def test_an_empty_or_odd_message_is_not_a_summons():
    for text in ("", None, "   "):
        assert R._mentioned(text, AGENTS, route_only=True) == []
