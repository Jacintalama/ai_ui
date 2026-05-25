"""Human-readable formatting for schedules: cron→English, status, dropdown label."""
import pytest

from handlers.schedule_format import cron_to_human, schedule_status_label, schedule_label


@pytest.mark.parametrize("cron,human", [
    ("*/5 * * * *", "every 5 minutes"),
    ("*/30 * * * *", "every 30 minutes"),
    ("* * * * *", "every minute"),
    ("0 */2 * * *", "every 2 hours"),
    ("0 * * * *", "every hour"),
    ("0 8 * * *", "every day at 8:00 AM"),
    ("30 6 * * *", "every day at 6:30 AM"),
    ("0 20 * * *", "every day at 8:00 PM"),
    ("0 9 * * 1", "every Monday at 9:00 AM"),
    ("30 17 * * 5", "every Friday at 5:30 PM"),
    ("0 0 * * 0", "every Sunday at 12:00 AM"),
])
def test_cron_to_human(cron, human):
    assert cron_to_human(cron) == human


def test_cron_to_human_exotic_falls_back_to_raw():
    assert cron_to_human("15 3 1 * *") == "15 3 1 * *"
    assert cron_to_human("not a cron") == "not a cron"


@pytest.mark.parametrize("sched,expected", [
    ({"enabled": False, "last_run_status": "running"}, "⏸ paused"),
    ({"enabled": True, "last_run_status": None}, "🟢 active"),
    ({"enabled": True, "last_run_status": "running"}, "⏳ running now"),
    ({"enabled": True, "last_run_status": "completed"}, "✅ active · last run ok"),
    ({"enabled": True, "last_run_status": "failed"}, "⚠️ active · last run failed"),
])
def test_schedule_status_label(sched, expected):
    assert schedule_status_label(sched) == expected


def test_schedule_label_combines_time_and_task():
    s = {"cron_expr": "*/5 * * * *", "prompt": "summarize my unread emails"}
    assert schedule_label(s) == "every 5 minutes — summarize my unread emails"


def test_schedule_label_truncates_long_prompt_to_first_line():
    s = {"cron_expr": "0 8 * * *", "prompt": "do a big thing\nwith details\nand more"}
    label = schedule_label(s)
    assert label.startswith("every day at 8:00 AM — do a big thing")
    assert "\n" not in label
    assert len(label) <= 100  # Discord select-option label cap
