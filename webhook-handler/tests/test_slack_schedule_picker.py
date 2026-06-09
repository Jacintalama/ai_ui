"""Slack create modal native date/time pickers (Task 6)."""
from datetime import datetime
from handlers import slack_schedule_panel as ssp
from handlers import schedule_picker as sp

NOW = datetime(2026, 6, 9, 10, 0)


def test_modal_has_picker_blocks_and_no_when_text():
    view = ssp.build_schedule_modal()
    ids = [b["block_id"] for b in view["blocks"] if b.get("type") == "input"]
    assert ssp.SCHED_REPEAT_BLOCK_ID in ids
    assert ssp.SCHED_TIME_BLOCK_ID in ids
    assert ssp.SCHED_WEEKDAY_BLOCK_ID in ids
    assert ssp.SCHED_DATE_BLOCK_ID in ids
    # the old free-text "When?" input is gone (Slack create modal is picker-only)
    assert ssp.SCHED_WHEN_BLOCK_ID not in ids


def test_picks_from_view_weekly_round_trips():
    view = {"state": {"values": ssp.sample_view_state("weekly", time="09:00", weekday="monday")}}
    picks = ssp.slack_picks_from_view(view)
    assert picks == {"kind": "rep", "freq": "weekly", "weekday": "monday", "hour": "9"}
    cron, run_once, _ = sp.picks_to_cron(picks, now=NOW)
    assert cron == "0 9 * * 1" and run_once is False


def test_picks_from_view_one_time_round_trips():
    view = {"state": {"values": ssp.sample_view_state("one_time", time="14:00", date="2026-06-15")}}
    picks = ssp.slack_picks_from_view(view)
    assert picks == {"kind": "once", "date": "2026-06-15", "hour": "14"}
    cron, run_once, _ = sp.picks_to_cron(picks, now=NOW)
    assert cron == "0 14 15 6 *" and run_once is True


def test_picks_from_view_hourly_ignores_time():
    view = {"state": {"values": ssp.sample_view_state("hourly", time="09:00")}}
    picks = ssp.slack_picks_from_view(view)
    cron, run_once, _ = sp.picks_to_cron(picks, now=NOW)
    assert cron == "0 * * * *" and run_once is False
