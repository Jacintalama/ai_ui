"""What may this agent do, here, right now.

The whole point of this module is that there is ONE answer to that, in one
function. This codebase has twice had access logic living in two places where
fixing one left the other open, so the table below is exhaustive on purpose.
"""
import pytest

import agent_access as aa


# --- reading the level off the agent row ----------------------------------

@pytest.mark.parametrize("meta,expected", [
    ({"access": "read"}, "read"),
    ({"access": "ask"}, "ask"),
    ({"access": "all"}, "all"),
    ({"access": "ALL"}, "all"),
    ({"access": "  ask  "}, "ask"),
])
def test_a_level_is_read_off_the_agent_row(meta, expected):
    assert aa.level_of(meta) == expected


@pytest.mark.parametrize("meta", [
    None, {}, {"access": None}, {"access": 3}, {"access": ""},
    {"access": "banana"}, {"access": ["all"]}, "not a dict",
])
def test_anything_unrecognised_is_no_opinion_not_a_default(meta):
    """Absent means "behave exactly as today". Reading a junk value as a
    level would hand an agent a permission nobody chose."""
    assert aa.level_of(meta) is None


# --- the ceiling ----------------------------------------------------------

@pytest.mark.parametrize("level,tool_mode,expected", [
    # The agent's level is a ceiling. A schedule may narrow it, never widen it.
    ("read", "full", aa.MODE_READ_ONLY),
    ("all", "read_only", aa.MODE_READ_ONLY),
    ("all", "full", aa.MODE_FULL),
    ("ask", "full", aa.MODE_READ_ONLY),
    ("ask", "read_only", aa.MODE_READ_ONLY),
    ("read", "read_only", aa.MODE_READ_ONLY),
    # No opinion reproduces today's behaviour exactly.
    (None, "full", aa.MODE_FULL),
    (None, "read_only", aa.MODE_READ_ONLY),
    (None, None, aa.MODE_READ_ONLY),
])
def test_the_schedule_ceiling(level, tool_mode, expected):
    assert aa.effective_mode(level, tool_mode, aa.SURFACE_SCHEDULE) == expected


@pytest.mark.parametrize("level,expected", [
    ("read", aa.MODE_READ_ONLY),
    ("ask", aa.MODE_ASK),
    ("all", aa.MODE_FULL),
    # Today a channel refuses every tool, so read-only cannot regress anything.
    (None, aa.MODE_READ_ONLY),
])
def test_a_channel_follows_the_agent_alone(level, expected):
    assert aa.effective_mode(level, None, aa.SURFACE_CHANNEL) == expected


def test_a_schedule_never_asks():
    """A schedule fires whether or not anybody is online. Asking would hang
    the run at 3am waiting for an answer nobody is there to give."""
    assert aa.effective_mode("ask", "full", aa.SURFACE_SCHEDULE) != aa.MODE_ASK


def test_a_channel_tool_mode_is_ignored_entirely():
    """There is no schedule behind a Discord message, so nothing may sneak a
    tool_mode in and widen a read-only agent."""
    assert aa.effective_mode("read", "full", aa.SURFACE_CHANNEL) == aa.MODE_READ_ONLY


# --- what the person is told ----------------------------------------------

def test_a_schedule_keeps_the_sentence_it_has_today():
    assert (aa.refusal_reason(None, "read_only", aa.SURFACE_SCHEDULE)
            == "this schedule is set to read only")


def test_an_asking_agent_on_a_schedule_says_why_it_could_not_ask():
    reason = aa.refusal_reason("ask", "full", aa.SURFACE_SCHEDULE)
    assert reason == "a scheduled run has nobody to ask"


def test_a_channel_never_talks_about_schedules():
    """The sentence "this schedule is set to read only" is simply false in a
    Discord DM, and it is what the loop says today."""
    reason = aa.refusal_reason("read", None, aa.SURFACE_CHANNEL)
    assert "schedule" not in reason
    assert reason == "this agent is set to read only"


def test_a_read_only_agent_on_a_schedule_blames_the_agent_not_the_schedule():
    """These are different causes with different fixes. Telling somebody the
    schedule is read only when the agent is sends them to change the wrong
    setting."""
    assert (aa.refusal_reason("read", "full", aa.SURFACE_SCHEDULE)
            == "this agent is set to read only")
    assert (aa.refusal_reason(None, "read_only", aa.SURFACE_SCHEDULE)
            == "this schedule is set to read only")


@pytest.mark.parametrize("surface", [aa.SURFACE_CHANNEL, aa.SURFACE_SCHEDULE])
@pytest.mark.parametrize("level", [None, "read", "ask", "all"])
def test_every_reason_reads_as_a_clause(surface, level):
    """These get interpolated into two sentences, so a trailing full stop or
    a leading capital would produce garbage in one of them."""
    reason = aa.refusal_reason(level, "full", surface)
    assert reason and not reason.endswith(".") and reason[0].islower()
    assert "\u2014" not in reason and "\u2013" not in reason


# --- the approval signal --------------------------------------------------

def test_approval_required_carries_what_is_needed_to_resume():
    convo = [{"role": "user", "content": "send it"}]
    calls = [{"id": "call_1", "function": {"name": "send_email"}}]
    err = aa.ApprovalRequired(convo, calls)
    assert err.conversation == convo
    assert err.calls == calls
