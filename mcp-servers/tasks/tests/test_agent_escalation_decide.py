"""Who is asking, whether this agent is mid job for them, and the once a day
cap note. The clock is handed in, never read."""
import pytest

import agent_escalation as esc


@pytest.fixture(autouse=True)
def _state(monkeypatch):
    monkeypatch.setattr(esc, "_windows", {})
    monkeypatch.setattr(esc, "_noted", set())
    monkeypatch.setattr(esc, "STICKY_SECONDS", 900)
    monkeypatch.setattr(esc, "DAILY_CAP", 40)
    monkeypatch.setattr(esc, "MESSAGE_CHARS", 2000)


def test_an_intent_is_carried_and_then_gone():
    assert esc.current_intent() is None
    with esc.asking(esc.Intent(person_text="build an app", may_pass=True)):
        assert esc.current_intent().person_text == "build an app"
    assert esc.current_intent() is None


def test_the_window_opens_per_person_per_agent_and_closes_after_15_minutes():
    esc.mark_paid("Ada@Example.com", "agent-1", now=1000.0)
    assert esc.in_window("ada@example.com", "agent-1", now=1000.0 + 899)
    assert not esc.in_window("ada@example.com", "agent-2", now=1001.0)
    assert not esc.in_window("bob@example.com", "agent-1", now=1001.0)
    assert not esc.in_window("ada@example.com", "agent-1", now=1000.0 + 900)


@pytest.mark.parametrize("text,window,follow_up,expected", [
    ("build me an app", False, False, esc.REASON_BUILD),
    ("what is on my calendar tomorrow?", False, False, None),
    ("make it blue", False, False, None),
    ("make it blue", True, False, esc.REASON_STICKY),
    ("yes", True, False, esc.REASON_STICKY),
    ("what is on my calendar tomorrow?", True, False, None),
    ("why did the build fail?", True, False, esc.REASON_STICKY),
    ("", True, True, esc.REASON_STICKY),
    ("", False, True, None),
])
def test_decide(text, window, follow_up, expected):
    intent = esc.Intent(person_text=text, follow_up=follow_up)
    assert esc.decide(intent, window) == expected


def test_the_cap_note_is_said_once_a_day_per_person():
    first = esc.take_cap_note("a@example.com", today="2026-09-17")
    assert first == ("Today's limit of 40 turns on the stronger model is used "
                     "up, so this answer comes from the free model.")
    assert esc.take_cap_note("A@example.com", today="2026-09-17") == ""
    assert esc.take_cap_note("b@example.com", today="2026-09-17") != ""
    assert esc.take_cap_note("a@example.com", today="2026-09-18") != ""
