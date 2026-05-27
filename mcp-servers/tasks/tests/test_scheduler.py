"""Scheduler — pure-function tests for cron matching + should_fire dedupe."""
import os
import sys

# Make the tasks/ dir importable when running tests directly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from scheduler import cron_matches_now, should_fire

PH = ZoneInfo("Asia/Manila")


def test_cron_matches_at_20_00_PHT_not_at_20_00_UTC():
    pht_8pm = datetime(2026, 5, 18, 20, 0, 0, tzinfo=PH)
    assert cron_matches_now("0 20 * * *", "Asia/Manila", pht_8pm.astimezone(timezone.utc)) is True

    utc_8pm = datetime(2026, 5, 18, 20, 0, 0, tzinfo=timezone.utc)
    # In Manila that's 04:00 next day — does NOT match 0 20 * * *
    assert cron_matches_now("0 20 * * *", "Asia/Manila", utc_8pm) is False


def test_dedupe_within_same_minute():
    now = datetime(2026, 5, 18, 12, 0, 30, tzinfo=timezone.utc)
    just_ran = datetime(2026, 5, 18, 12, 0, 5, tzinfo=timezone.utc)
    # last_run_at 25s ago, same minute → should NOT fire
    assert should_fire(cron_expr="* * * * *", tz="UTC",
                       last_run_at=just_ran, now=now, enabled=True) is False


def test_disabled_never_fires():
    now = datetime(2026, 5, 18, 12, 0, 30, tzinfo=timezone.utc)
    assert should_fire(cron_expr="* * * * *", tz="UTC",
                       last_run_at=None, now=now, enabled=False) is False


def test_enabled_first_run_fires_when_matched():
    now = datetime(2026, 5, 18, 12, 0, 30, tzinfo=timezone.utc)
    assert should_fire(cron_expr="* * * * *", tz="UTC",
                       last_run_at=None, now=now, enabled=True) is True


def test_enabled_last_run_old_enough_fires():
    now = datetime(2026, 5, 18, 12, 5, 30, tzinfo=timezone.utc)
    old = datetime(2026, 5, 18, 12, 4, 30, tzinfo=timezone.utc)  # 60s ago
    assert should_fire(cron_expr="* * * * *", tz="UTC",
                       last_run_at=old, now=now, enabled=True) is True
