from datetime import datetime
import pytest
from handlers import schedule_picker as sp


NOW = datetime(2026, 6, 9, 10, 0)  # naive local-Manila wall clock is fine for v1


@pytest.mark.parametrize("picks,expected_cron,expected_once", [
    ({"kind": "rep", "freq": "daily", "hour": "9"}, "0 9 * * *", False),
    ({"kind": "rep", "freq": "weekdays", "hour": "8"}, "0 8 * * 1-5", False),
    ({"kind": "rep", "freq": "weekly", "hour": "9", "weekday": "monday"}, "0 9 * * 1", False),
    ({"kind": "rep", "freq": "hourly"}, "0 * * * *", False),
    ({"kind": "rep", "freq": "every30"}, "*/30 * * * *", False),
    ({"kind": "once", "date": "2026-06-15", "hour": "9"}, "0 9 15 6 *", True),
])
def test_picks_to_cron_ok(picks, expected_cron, expected_once):
    cron, run_once, label = sp.picks_to_cron(picks, now=NOW)
    assert cron == expected_cron
    assert run_once is expected_once
    assert label  # non-empty human label


def test_one_time_past_rejected():
    with pytest.raises(sp.PastTimeError):
        sp.picks_to_cron({"kind": "once", "date": "2026-06-09", "hour": "9"}, now=NOW)


def test_one_time_future_today_ok():
    cron, once, _ = sp.picks_to_cron({"kind": "once", "date": "2026-06-09", "hour": "11"}, now=NOW)
    assert once is True and cron == "0 11 9 6 *"


def test_codec_round_trip():
    token = "abc123"
    cid = sp.pick_cid("freq", token)
    field, tok = sp.parse_pick_cid(cid)
    assert field == "freq" and tok == token
