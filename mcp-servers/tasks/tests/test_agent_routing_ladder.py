"""Who answers a message, rung by rung.

One ladder decides this for the panel and for the Discord and Telegram
gateway, so the same question reaches the same agent wherever it is asked.
Every rung here comes from something seen live rather than imagined.
"""
import pytest

import agent_routing as r

ADA = {"id": "agent-a", "name": "Ada", "meta": {"toolIds": ["code", "schedules"]}}
MIA = {"id": "agent-m", "name": "Mia", "meta": {"toolIds": ["gmail"]}}
NORA = {"id": "agent-n", "name": "Nora", "meta": {"toolIds": ["calendar"]}}
REX = {"id": "agent-r", "name": "Rex", "meta": {"toolIds": ["code"]}}
ROOM = [ADA, MIA, NORA]


def _ids(agents):
    return [a["id"] for a in agents]


# --- 1. an answer to a question that is waiting ----------------------------
# Live 2026-09-18, in Ralph's own screenshot: Rex asked to apply a change,
# Ralph typed "Yes", and because "yes" names nobody it went to all seven
# agents. All seven passed, the panel said nobody had anything to add, and the
# change he had just approved was never applied.

@pytest.mark.parametrize("said", ["yes", "Yes", "yes please", "ok", "go ahead",
                                  "do it", "approve", "YES.", "sure"])
def test_a_yes_goes_to_the_agent_that_asked(said):
    who, may_pass, why = r.choose_speakers(said, ROOM, last_speaker=REX,
                                           has_pending=True)
    assert _ids(who) == [REX["id"]], said
    assert may_pass is False, "it answered you, it does not get to pass"
    assert why == r.ROUTE_APPROVAL


@pytest.mark.parametrize("said", ["no", "nope", "cancel", "No thanks"])
def test_a_no_goes_there_too(said):
    who, _, why = r.choose_speakers(said, ROOM, last_speaker=REX,
                                    has_pending=True)
    assert _ids(who) == [REX["id"]] and why == r.ROUTE_APPROVAL


def test_yes_with_a_subject_of_its_own_is_not_a_bare_answer():
    """"yes, but do the other app" is an instruction. Reading it as a bare
    approval would apply something the person was in the middle of changing."""
    who, _, why = r.choose_speakers("yes but use the other app instead please",
                                    ROOM, last_speaker=REX, has_pending=True)
    assert why != r.ROUTE_APPROVAL


def test_a_yes_with_nothing_waiting_is_not_an_approval():
    who, _, why = r.choose_speakers("yes", ROOM, last_speaker=REX,
                                    has_pending=False)
    assert why != r.ROUTE_APPROVAL


# --- 2. naming somebody ----------------------------------------------------

def test_naming_an_agent_asks_that_agent_and_it_cannot_pass():
    who, may_pass, why = r.choose_speakers("mia what is in my inbox", ROOM)
    assert _ids(who) == [MIA["id"]] and may_pass is False
    assert why == r.ROUTE_NAMED


def test_a_name_wins_over_a_question_that_is_waiting():
    """Naming somebody changes the subject on purpose. The waiting question
    stays waiting rather than being answered by a message about something
    else."""
    who, _, why = r.choose_speakers("nora what is on tomorrow", ROOM,
                                    last_speaker=REX, has_pending=True)
    assert _ids(who) == [NORA["id"]] and why == r.ROUTE_NAMED


def test_two_names_answer_in_the_order_they_were_said():
    who, may_pass, _ = r.choose_speakers("nora then mia please", ROOM)
    assert _ids(who) == [NORA["id"], MIA["id"]] and may_pass is False


# --- 3. the whole room -----------------------------------------------------

def test_a_collective_word_reaches_everyone_and_lets_them_pass():
    who, may_pass, why = r.choose_speakers("hi team", ROOM)
    assert _ids(who) == _ids(ROOM)
    assert may_pass is True, "seven hellos is what this prevents"
    assert why == r.ROUTE_COLLECTIVE


def test_an_open_question_goes_to_the_room():
    who, may_pass, why = r.choose_speakers(
        "what do you all reckon about the plan for next quarter overall", ROOM)
    assert _ids(who) == _ids(ROOM) and may_pass is True
    assert why == r.ROUTE_ROOM


# --- 4. carrying on with whoever is mid job --------------------------------

@pytest.mark.parametrize("said", ["go ahead", "carry on", "try again",
                                  "and then what", "why", "make it blue"])
def test_a_short_follow_on_goes_back_to_whoever_spoke(said):
    who, may_pass, why = r.choose_speakers(said, ROOM, last_speaker=REX)
    assert _ids(who) == [REX["id"]], said
    assert may_pass is False and why == r.ROUTE_CONTINUATION


def test_a_long_message_is_a_new_subject_even_if_it_opens_like_a_follow_on():
    """It opens with "and also", which reads like carrying on, and it is not:
    it asks for a whole new site. So it must not be handed to whoever happened
    to speak last. Where it goes instead is the ladder's business, and here
    that is Ada, the only agent in this room that can touch an app."""
    said = ("and also I want a completely new site for the shop, with a "
            "gallery, a contact form and somewhere to put opening hours")
    who, _, why = r.choose_speakers(said, ROOM, last_speaker=REX)
    assert why != r.ROUTE_CONTINUATION
    assert REX["id"] not in _ids(who)


def test_a_follow_on_with_nobody_speaking_yet_goes_to_the_room():
    who, _, why = r.choose_speakers("go ahead", ROOM, last_speaker=None)
    assert why in (r.ROUTE_ROOM, r.ROUTE_OWNER)


# --- 5. the one agent that owns the subject --------------------------------

def test_the_only_agent_with_the_calendar_takes_a_calendar_question():
    who, may_pass, why = r.choose_speakers("when is my next meeting", ROOM)
    assert _ids(who) == [NORA["id"]] and may_pass is False
    assert why == r.ROUTE_OWNER


def test_the_only_agent_with_email_takes_an_email_question():
    who, _, why = r.choose_speakers("anything unread in my inbox", ROOM)
    assert _ids(who) == [MIA["id"]] and why == r.ROUTE_OWNER


def test_two_agents_with_the_same_tool_means_the_room_decides():
    """Guessing between two agents that both read code is exactly what the
    room is for: they hear it and the one with something to say answers."""
    who, may_pass, why = r.choose_speakers("the app is broken", [ADA, REX, MIA])
    assert why == r.ROUTE_ROOM and may_pass is True


def test_a_message_about_two_subjects_goes_to_the_room():
    who, _, why = r.choose_speakers(
        "put my inbox summary in the calendar for tomorrow morning", ROOM)
    assert why == r.ROUTE_ROOM


# --- shapes that arrive from over the wire ---------------------------------

def test_nobody_to_ask_is_answered_with_nobody():
    who, may_pass, why = r.choose_speakers("anything at all", [])
    assert who == [] and may_pass is True and why == r.ROUTE_ROOM


@pytest.mark.parametrize("junk", [None, 123, {"not": "a list"}])
def test_a_wrong_shape_never_raises(junk):
    who, _, _ = r.choose_speakers("hello", junk)
    assert who == []


def test_a_wrong_shaped_message_never_raises():
    who, _, _ = r.choose_speakers(None, ROOM)
    assert _ids(who) == _ids(ROOM)
