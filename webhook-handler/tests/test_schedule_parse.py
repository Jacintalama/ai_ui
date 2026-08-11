"""Tests for the natural-language → cron parser used by the Discord
Schedules UX. parse_when(text) returns (cron_expr, human_readable) or None.
"""
import pytest

from handlers.schedule_parse import (
    MIN_INTERVAL_MINUTES, parse_when, too_frequent_error,
)


@pytest.mark.parametrize(
    "text,cron,human",
    [
        ("every morning", "0 8 * * *", "every day at 8:00 AM"),
        ("every evening", "0 20 * * *", "every day at 8:00 PM"),
        ("every day at 8pm", "0 20 * * *", "every day at 8:00 PM"),
        ("daily at 6:30am", "30 6 * * *", "every day at 6:30 AM"),
        ("every monday at 9am", "0 9 * * 1", "every Monday at 9:00 AM"),
        ("every friday at 5:30pm", "30 17 * * 5", "every Friday at 5:30 PM"),
        ("every sunday at 12am", "0 0 * * 0", "every Sunday at 12:00 AM"),
        ("every 30 minutes", "*/30 * * * *", "every 30 minutes"),
        ("every 2 hours", "0 */2 * * *", "every 2 hours"),
        ("every hour", "0 * * * *", "every hour"),
        ("hourly", "0 * * * *", "every hour"),
        ("daily", "0 8 * * *", "every day at 8:00 AM"),
        ("weekly", "0 8 * * 1", "every Monday at 8:00 AM"),
        ("every 9:26pm", "26 21 * * *", "every day at 9:26 PM"),
        ("every 9pm", "0 21 * * *", "every day at 9:00 PM"),
        ("every 21:00", "0 21 * * *", "every day at 9:00 PM"),
        ("at 9am", "0 9 * * *", "every day at 9:00 AM"),
        ("9:30pm", "30 21 * * *", "every day at 9:30 PM"),
    ],
)
def test_parse_when_natural_language(text, cron, human):
    result = parse_when(text)
    assert result is not None, f"{text!r} should parse"
    assert result[0] == cron
    assert result[1] == human


def test_parse_when_passthrough_valid_cron():
    result = parse_when("15 14 * * *")
    assert result is not None
    assert result[0] == "15 14 * * *"
    assert "15 14 * * *" in result[1]


def test_parse_when_rejects_invalid_cron_lookalike():
    # 5 fields but out-of-range minute — not a usable cron, should be rejected
    assert parse_when("99 99 * * *") is None


@pytest.mark.parametrize("text", ["", "   ", "sometime next week maybe", "asap", "tomorrow", "every 9", "9"])
def test_parse_when_unparseable_returns_none(text):
    assert parse_when(text) is None


def test_parse_when_strips_and_is_case_insensitive():
    assert parse_when("  Every Morning  ") == ("0 8 * * *", "every day at 8:00 AM")


# --- The 15-minute floor, enforced where the input is collected -------------
#
# The tasks API rejects these too (routes_schedules._enforce_interval_floor),
# but only after a round trip and with an error the user has to interpret.
# Catching them here is what turns a rejection into guidance.


@pytest.mark.parametrize("text", [
    "every 1 minutes",
    "every 5 minutes",
    "every 14 minutes",
    "* * * * *",            # typed straight into the raw-cron passthrough
    "*/5 * * * *",
    "0,15,59 0,23 * * *",   # 23:59 -> 00:00 is one minute
])
def test_parse_when_refuses_anything_under_the_floor(text):
    assert parse_when(text) is None


@pytest.mark.parametrize("text,cron", [
    ("every 15 minutes", "*/15 * * * *"),   # exactly the boundary
    ("every 30 minutes", "*/30 * * * *"),
    ("*/15 * * * *", "*/15 * * * *"),
    ("0,59 0 * * *", "0,59 0 * * *"),       # twice a day, 59 apart — fine
])
def test_parse_when_still_allows_the_floor_and_above(text, cron):
    result = parse_when(text)
    assert result is not None, f"{text!r} should still parse"
    assert result[0] == cron


@pytest.mark.parametrize("text", ["every 5 minutes", "* * * * *", "every 1 minutes"])
def test_too_frequent_error_names_the_minimum(text):
    """parse_when returns None for "too often" and for "I don't understand"
    alike; without this the first is reported as the second."""
    msg = too_frequent_error(text)
    assert msg, f"{text!r} should get a reason, not silence"
    assert str(MIN_INTERVAL_MINUTES) in msg


@pytest.mark.parametrize(
    "text", ["", "   ", "sometime next week maybe", "asap", "99 99 * * *"])
def test_too_frequent_error_stays_silent_on_an_unreadable_phrase(text):
    """Not the frequency's fault — the caller keeps its own wording for this."""
    assert too_frequent_error(text) is None


@pytest.mark.parametrize("text", ["every morning", "every 30 minutes", "0,59 0 * * *"])
def test_too_frequent_error_stays_silent_on_an_acceptable_schedule(text):
    assert too_frequent_error(text) is None
