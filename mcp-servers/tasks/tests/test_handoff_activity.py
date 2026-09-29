"""Recent handoffs, so the office can draw a collaboration that happened.

The office was built to refuse to fake this. Its own test file says so: there
is deliberately no "simulate collaboration", because agents could not address
each other and a button that pretended otherwise was the one thing that page
must not do.

They can now, and `tasks.agent_step` records it: one row per tool call, with
`target_agent_id` set when the tool was a handoff. So a robot walking across
the floor to another robot is a fact being drawn, not an animation being
invented. This is the read that makes that possible.

Only the in-memory half runs here. The SQL half needs a real Postgres and is
verified in the container.
"""
import agent_activity


def test_a_handoff_is_shaped_for_the_floor():
    row = {"agent_id": "agent-nora", "target_agent_id": "agent-iris",
           "status": "ok", "started_at": _when("2026-09-29T03:05:00+00:00")}
    assert agent_activity._shape_handoff(row) == {
        "from": "agent-nora", "to": "agent-iris", "status": "ok",
        "at": "2026-09-29T03:05:00+00:00"}


def test_a_refused_handoff_is_still_drawn():
    """A refusal is something that happened. Hiding it would leave the floor
    showing only the collaborations that went well, which is the flattering
    half of the truth."""
    row = {"agent_id": "agent-nora", "target_agent_id": "agent-iris",
           "status": "refused", "started_at": _when("2026-09-29T03:05:00+00:00")}
    assert agent_activity._shape_handoff(row)["status"] == "refused"


def test_a_handoff_with_no_target_is_not_drawn():
    """A handoff refused before the colleague was resolved records no
    target. There is no second robot to draw a line to."""
    assert agent_activity._shape_handoff(
        {"agent_id": "agent-nora", "target_agent_id": None,
         "status": "refused", "started_at": _when("2026-09-29T03:05:00+00:00")}
    ) is None


def test_a_handoff_to_itself_is_not_drawn():
    """Refused by agent_handoff anyway, but a self-loop on the floor would
    draw a line from a robot to itself."""
    assert agent_activity._shape_handoff(
        {"agent_id": "agent-nora", "target_agent_id": "agent-nora",
         "status": "refused", "started_at": _when("2026-09-29T03:05:00+00:00")}
    ) is None


def test_no_email_reads_nothing():
    """Same scoping as every other read here: one person's agents helping
    each other is not another person's."""
    import asyncio
    assert asyncio.run(agent_activity.handoffs_for("")) == []


def test_the_window_is_minutes_not_hours():
    """The floor draws what is happening, not a history. A handoff from this
    morning should not still have two robots standing together at teatime."""
    assert 1 <= agent_activity.HANDOFF_WINDOW_MINUTES <= 15


def _when(iso: str):
    from datetime import datetime
    return datetime.fromisoformat(iso)
