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
