"""Jev can answer "none of them", so an unaddressed message is not forced
onto whichever agent fits least badly.

2026-11-06. Ralph asked the main chat to create a ClickUp space and a
task. He named nobody. The chat answered "Cutter is answering...".

Cutter is a video editing agent: "plans and edits videos, trimming clips,
ordering scenes, adding transitions". It has no business with ClickUp.

The cause is in the question, not the model. Jev was asked

    "Which one team member is best placed to handle the new message?"

with the criteria built only from the agents' names, so there was no way
to answer "none of them". A forced choice with nothing suitable on the
list returns the least bad one, and confidence was the only brake.

So the list gains an explicit nobody, and picking it means the assistant
answers with the platform's tools, which is what a request to create a
ClickUp space needed in the first place.
"""
import pytest

import agent_decider as D

AGENTS = [
    {"id": "agent-cutter-8dfe", "name": "Cutter", "role": "Video editor"},
    {"id": "agent-ada-a1bc", "name": "Ada", "role": "Project manager"},
]


def _question(agents=AGENTS):
    payload = D.build_request("please create a clickup space", [], agents)
    assert payload is not None, "Jev was not offered the team at all"
    return payload["questions"]["who"]


# --- the option exists --------------------------------------------------

def test_nobody_is_on_the_list():
    criteria = _question()["criteria"]
    assert D.NOBODY in criteria, (
        "Jev cannot answer 'none of them', so it must name an agent")


def test_the_option_says_when_to_pick_it():
    """Jev chooses by reading these descriptions. One that says nothing
    is never chosen, which would leave the bug in place."""
    text = _question()["criteria"][D.NOBODY].lower()
    assert "none" in text or "no " in text
    assert "assistant" in text or "tool" in text


def test_the_real_agents_are_still_offered():
    criteria = _question()["criteria"]
    assert "Cutter" in criteria and "Ada" in criteria


def test_nobody_cannot_be_confused_with_an_agent_of_that_name():
    """Someone will eventually name an agent Nobody. The sentinel must
    not be a name an agent could have."""
    named = [{"id": "x", "name": D.NOBODY, "role": "trap"}]
    criteria = _question(AGENTS + named)["criteria"]
    assert len([k for k in criteria if k == D.NOBODY]) == 1
    assert not D.NOBODY.isalpha(), (
        "the sentinel looks like an ordinary name: " + D.NOBODY)


# --- what picking it means ----------------------------------------------

def _reply(who, conf=0.99, kind="answer"):
    return {"answers": {
        "kind": {"choice": kind, "confidence": conf},
        "who": {"choice": who, "confidence": conf},
        "urgency": {"probabilities": [1.0, 0.0, 0.0]},
    }}


def test_choosing_nobody_hands_it_back_to_the_assistant():
    out = D._read(_reply(D.NOBODY), AGENTS) if hasattr(D, "_read") \
        else D.read_answer(_reply(D.NOBODY), AGENTS)
    assert out.path != D.PATH_ONE_AGENT
    assert out.agent_id in (None, "")


def test_choosing_nobody_says_so_rather_than_looking_like_a_failure():
    """A fallback with no reason reads as Jev being broken. This is Jev
    working: it looked and there was no fit."""
    out = D._read(_reply(D.NOBODY), AGENTS) if hasattr(D, "_read") \
        else D.read_answer(_reply(D.NOBODY), AGENTS)
    assert "no" in (out.reason or "").lower()


def test_choosing_a_real_agent_still_routes_to_it():
    out = D._read(_reply("Ada"), AGENTS) if hasattr(D, "_read") \
        else D.read_answer(_reply("Ada"), AGENTS)
    assert out.path == D.PATH_ONE_AGENT
    assert out.agent_id == "agent-ada-a1bc"


def test_a_name_that_is_not_on_the_list_is_still_refused():
    out = D._read(_reply("Gandalf"), AGENTS) if hasattr(D, "_read") \
        else D.read_answer(_reply("Gandalf"), AGENTS)
    assert out.path == D.PATH_FALLBACK
