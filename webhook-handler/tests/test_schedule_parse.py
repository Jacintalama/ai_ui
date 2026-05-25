"""Tests for the natural-language → cron parser used by the Discord
Schedules UX. parse_when(text) returns (cron_expr, human_readable) or None.
"""
import pytest

from handlers.schedule_parse import parse_when


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


@pytest.mark.parametrize("text", ["", "   ", "sometime next week maybe", "asap", "tomorrow"])
def test_parse_when_unparseable_returns_none(text):
    assert parse_when(text) is None


def test_parse_when_strips_and_is_case_insensitive():
    assert parse_when("  Every Morning  ") == ("0 8 * * *", "every day at 8:00 AM")
