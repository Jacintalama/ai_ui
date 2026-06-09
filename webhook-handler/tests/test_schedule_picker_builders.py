from datetime import datetime
from handlers import schedule_picker as sp

NOW = datetime(2026, 6, 9, 10, 0)  # a Tuesday
TOKEN = "tok123"


def _custom_ids(card):
    out = []
    for row in card["components"]:
        for c in row["components"]:
            if "custom_id" in c:
                out.append(c["custom_id"])
    return out


def test_kind_card_has_two_kind_buttons():
    card = sp.build_kind_card(TOKEN)
    ids = _custom_ids(card)
    assert sp.pick_cid("kindrep", TOKEN) in ids
    assert sp.pick_cid("kindonce", TOKEN) in ids


def test_repeating_card_daily_needs_time_not_ready():
    card = sp.build_repeating_card(TOKEN, {"kind": "rep", "freq": "daily"})
    ids = _custom_ids(card)
    assert sp.pick_cid("freq", TOKEN) in ids
    assert sp.pick_cid("hour", TOKEN) in ids       # time select offered
    assert sp.pick_cid("settask", TOKEN) not in ids  # not ready (no hour yet)
    assert sp.pick_cid("typeit", TOKEN) in ids       # fallback always present


def test_repeating_card_daily_with_time_ready():
    card = sp.build_repeating_card(TOKEN, {"kind": "rep", "freq": "daily", "hour": "9"})
    assert sp.pick_cid("settask", TOKEN) in _custom_ids(card)


def test_repeating_hourly_ready_no_time_select():
    card = sp.build_repeating_card(TOKEN, {"kind": "rep", "freq": "hourly"})
    ids = _custom_ids(card)
    assert sp.pick_cid("hour", TOKEN) not in ids
    assert sp.pick_cid("settask", TOKEN) in ids


def test_weekly_needs_weekday():
    not_ready = sp.build_repeating_card(TOKEN, {"kind": "rep", "freq": "weekly", "hour": "9"})
    ids = _custom_ids(not_ready)
    assert sp.pick_cid("weekday", TOKEN) in ids
    assert sp.pick_cid("settask", TOKEN) not in ids
    ready = sp.build_repeating_card(
        TOKEN, {"kind": "rep", "freq": "weekly", "hour": "9", "weekday": "monday"})
    assert sp.pick_cid("settask", TOKEN) in _custom_ids(ready)


def test_onetime_card_quickpicks_and_selects():
    card = sp.build_onetime_card(TOKEN, {"kind": "once"}, NOW)
    ids = _custom_ids(card)
    for f in ("qtoday", "qtomorrow", "qnextmon", "date", "hour", "typeit"):
        assert sp.pick_cid(f, TOKEN) in ids
    assert sp.pick_cid("settask", TOKEN) not in ids  # no date/hour yet
    ready = sp.build_onetime_card(TOKEN, {"kind": "once", "date": "2026-06-15", "hour": "9"}, NOW)
    assert sp.pick_cid("settask", TOKEN) in _custom_ids(ready)


def test_task_modal_shape():
    modal = sp.build_task_modal(TOKEN)
    assert modal["custom_id"] == f"{sp.TASK_MODAL_PREFIX}{TOKEN}"
    inp = modal["components"][0]["components"][0]
    assert inp["custom_id"] == sp.TASK_INPUT_ID and inp["style"] == 2  # paragraph


def test_select_option_caps():
    # every select must be within Discord's 25-option limit
    for card in (
        sp.build_repeating_card(TOKEN, {"kind": "rep", "freq": "weekly", "hour": "9"}),
        sp.build_onetime_card(TOKEN, {"kind": "once"}, NOW),
    ):
        for row in card["components"]:
            for c in row["components"]:
                if c.get("type") == 3:  # SELECT_MENU
                    assert 1 <= len(c["options"]) <= 25


def test_next_14_day_options():
    opts = sp.next_14_day_options(NOW)
    assert len(opts) == 14
    assert opts[0]["value"] == "2026-06-09"
    assert opts[1]["value"] == "2026-06-10"


def test_quick_date_iso():
    assert sp.quick_date_iso("qtoday", NOW) == "2026-06-09"
    assert sp.quick_date_iso("qtomorrow", NOW) == "2026-06-10"
    # NOW is Tuesday 2026-06-09 → next Monday is 2026-06-15
    assert sp.quick_date_iso("qnextmon", NOW) == "2026-06-15"
