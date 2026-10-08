"""A meeting leaves a trace, so the office can draw one.

agent_routing has always detected a meeting and made every agent answer with
nobody allowed to pass. Nothing recorded it. `source` on tasks.agent_run was
only ever schedule, channel or colleague, so five agents convened in one
meeting were indistinguishable from five asked five separate questions, and
a floor cannot draw a fact it cannot see.

The round is marked rather than passed down: agent_routing decides, start_run
writes, and _turn_for and _run_turn sit in between. That is the same reason
agent_escalation.asking carries the person's words this way.
"""
import agent_activity


def test_a_meeting_has_a_source_of_its_own():
    assert agent_activity.SOURCE_MEETING == "meeting"
    assert agent_activity.SOURCE_MEETING not in (
        agent_activity.SOURCE_CHANNEL,
        agent_activity.SOURCE_SCHEDULE,
        agent_activity.SOURCE_COLLEAGUE)


def test_a_round_is_not_a_meeting_unless_one_was_called():
    assert agent_activity.in_meeting() is False


def test_inside_the_block_it_is():
    with agent_activity.meeting_round():
        assert agent_activity.in_meeting() is True


def test_and_it_stops_being_one_afterwards():
    """Reset rather than set back to False: a nested round must not leave the
    outer one looking like a meeting that ended."""
    with agent_activity.meeting_round():
        pass
    assert agent_activity.in_meeting() is False


def test_it_is_undone_even_when_the_turn_raises():
    """An agent that throws mid meeting must not leave every later run on
    this worker marked as part of it."""
    try:
        with agent_activity.meeting_round():
            raise RuntimeError("the turn fell over")
    except RuntimeError:
        pass
    assert agent_activity.in_meeting() is False


def test_a_meeting_is_watched_on_the_chat_clock_not_the_schedule_one():
    """Somebody is sitting there waiting, exactly as in a channel turn. The
    hour-long schedule window would call a dead meeting healthy."""
    assert (agent_activity._stale_after(agent_activity.SOURCE_MEETING)
            == agent_activity._stale_after(agent_activity.SOURCE_CHANNEL))


# --- who counts as being in one --------------------------------------------
# Reported live 2026-10-08, with a screenshot of the office: chatting with
# the whole team left everybody at their desks, and the live feed said every
# run was "from channel". The trace was being written for one phrasing only.

import routes_agent_chat
import agent_routing

TEAM = [{"id": "agent-ada", "name": "Ada"}, {"id": "agent-kai", "name": "Kai"},
        {"id": "agent-iris", "name": "Iris"}, {"id": "agent-rex", "name": "Rex"}]


def _route(text, **kw):
    return agent_routing.choose_speakers(text, TEAM, **kw)


def test_a_plain_message_to_the_room_is_a_meeting():
    """The bug itself. "hey" reaches everybody, so everybody convenes, even
    though the ladder calls it ROOM rather than MEETING."""
    speakers, _may_pass, why = _route("hey")
    assert why == agent_routing.ROUTE_ROOM
    assert len(speakers) > 1
    assert routes_agent_chat._is_a_meeting(speakers) is True


def test_calling_one_explicitly_is_still_a_meeting():
    speakers, _may_pass, why = _route("everyone answer: what is left today")
    assert why == agent_routing.ROUTE_MEETING
    assert routes_agent_chat._is_a_meeting(speakers) is True


def test_naming_two_of_them_is_a_meeting_of_two():
    """Two agents answering together is a meeting of two, and the floor says
    so: the room's caption counts whoever is in it.

    Note the rung is NAMED, not COLLECTIVE. That is the point of keying on
    how many ANSWER rather than on the label: naming two people is still
    convening two people, and a rule written against route names would have
    missed this one the same way it missed a plain "hey"."""
    speakers, _may_pass, why = _route("Ada and Kai, can you both look")
    assert why == agent_routing.ROUTE_NAMED
    assert len(speakers) == 2
    assert routes_agent_chat._is_a_meeting(speakers) is True


def test_asking_one_agent_is_not_a_meeting():
    """The guard. One agent answering is a conversation, and dragging it into
    the meeting room would make the room meaningless."""
    speakers, _may_pass, why = _route("Iris, find the invoice")
    assert why == agent_routing.ROUTE_NAMED
    assert speakers and len(speakers) == 1
    assert routes_agent_chat._is_a_meeting(speakers) is False


def test_a_follow_on_to_one_agent_is_not_a_meeting():
    speakers, _may_pass, why = _route("go ahead", last_speaker=TEAM[0])
    assert why == agent_routing.ROUTE_CONTINUATION
    assert routes_agent_chat._is_a_meeting(speakers) is False


def test_answering_a_held_question_is_not_a_meeting():
    """"Yes" belongs to whoever asked. Putting it to the room is the bug the
    approval rung exists to stop, and it must not become a meeting either."""
    speakers, _may_pass, why = _route("yes", last_speaker=TEAM[2],
                                      has_pending=True)
    assert why == agent_routing.ROUTE_APPROVAL
    assert routes_agent_chat._is_a_meeting(speakers) is False


def test_nobody_answering_is_not_a_meeting():
    assert routes_agent_chat._is_a_meeting([]) is False
    assert routes_agent_chat._is_a_meeting(None) is False
