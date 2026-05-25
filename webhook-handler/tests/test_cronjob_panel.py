import pytest
from handlers import cronjob_panel as cp


def test_cron_from_choice_daily():
    assert cp.cron_from_choice("daily", hour=9) == "0 9 * * *"

def test_cron_from_choice_weekdays():
    assert cp.cron_from_choice("weekdays", hour=8) == "0 8 * * 1-5"

def test_cron_from_choice_weekly():
    assert cp.cron_from_choice("weekly", hour=18, dow="1") == "0 18 * * 1"

def test_cron_from_choice_hourly_ignores_hour():
    assert cp.cron_from_choice("hourly") == "0 * * * *"

def test_cron_from_choice_weekly_requires_dow():
    with pytest.raises(ValueError):
        cp.cron_from_choice("weekly", hour=9)

def test_cron_from_choice_daily_requires_hour():
    with pytest.raises(ValueError):
        cp.cron_from_choice("daily")

def test_describe_cron_daily():
    assert cp.describe_cron("0 9 * * *") == "daily at 09:00"

def test_describe_cron_weekdays():
    assert cp.describe_cron("0 8 * * 1-5") == "weekdays at 08:00"

def test_describe_cron_weekly():
    assert cp.describe_cron("0 18 * * 1") == "Mondays at 18:00"

def test_describe_cron_hourly():
    assert cp.describe_cron("0 * * * *") == "every hour"

def test_describe_cron_unknown_falls_back_to_raw():
    assert cp.describe_cron("*/7 13 5 * *") == "*/7 13 5 * *"
