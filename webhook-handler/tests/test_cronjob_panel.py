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


def test_encode_decode_cron_roundtrip():
    for expr in ["0 9 * * *", "0 8 * * 1-5", "0 18 * * 1", "0 * * * *"]:
        assert cp.decode_cron(cp.encode_cron(expr)) == expr

def test_encode_cron_has_no_spaces():
    assert " " not in cp.encode_cron("0 9 * * *")

def test_is_cron_prefix():
    assert cp.is_cron("cron:new") is True
    assert cp.is_cron("aiuibuild:tpl:x") is False

def test_simple_predicates():
    assert cp.is_new("cron:new")
    assert cp.is_list("cron:list")
    assert cp.is_schedule_select("cron:select")
    assert not cp.is_new("cron:list")

def test_freq_from_button():
    assert cp.is_freq_button("cron:freq:daily")
    assert cp.freq_from_button("cron:freq:weekly") == "weekly"
    with pytest.raises(ValueError):
        cp.freq_from_button("cron:new")

def test_hour_context_from_select():
    assert cp.hour_context_from_select("cron:hour:daily") == ("daily", None)
    assert cp.hour_context_from_select("cron:hour:weekly:3") == ("weekly", "3")

def test_create_modal_cron_roundtrip():
    cid = cp.create_modal_id("0 9 * * 1")
    assert cid.startswith("cron:create:")
    assert cp.is_create_modal(cid)
    assert cp.cron_from_create_modal(cid) == "0 9 * * 1"

def test_action_id_extractors():
    assert cp.is_action("cron:runnow:abc", "runnow")
    assert cp.id_from_action("cron:runnow:abc-123", "runnow") == "abc-123"
    assert cp.id_from_action("cron:delete:xyz", "delete") == "xyz"
    with pytest.raises(ValueError):
        cp.id_from_action("cron:pause:1", "runnow")

def test_custom_id_length_under_discord_limit():
    uuid = "123e4567-e89b-12d3-a456-426614174000"
    assert len(f"cron:delconfirm:{uuid}") < 100
    assert len(cp.create_modal_id("*/5 0-23 * * 1-5")) < 100


def test_panel_payload_has_two_buttons():
    payload = cp.build_panel_payload()
    assert "content" in payload
    rows = payload["components"]
    buttons = [c for row in rows for c in row["components"]]
    ids = {b["custom_id"] for b in buttons}
    assert ids == {"cron:new", "cron:list"}

def test_frequency_components_five_buttons():
    rows = cp.build_frequency_components()
    buttons = [c for row in rows for c in row["components"]]
    ids = [b["custom_id"] for b in buttons]
    assert ids == [
        "cron:freq:daily", "cron:freq:weekdays", "cron:freq:weekly",
        "cron:freq:hourly", "cron:freq:custom",
    ]

def test_dow_select_has_seven_options():
    rows = cp.build_dow_select()
    sel = rows[0]["components"][0]
    assert sel["type"] == 3
    assert sel["custom_id"] == "cron:dow"
    assert [o["value"] for o in sel["options"]] == ["1", "2", "3", "4", "5", "6", "0"]

def test_hour_select_24_options_and_context_in_custom_id():
    rows = cp.build_hour_select("daily")
    sel = rows[0]["components"][0]
    assert sel["custom_id"] == "cron:hour:daily"
    assert len(sel["options"]) == 24
    assert sel["options"][9]["value"] == "9"
    assert sel["options"][9]["label"] == "09:00"

def test_hour_select_weekly_carries_dow():
    rows = cp.build_hour_select("weekly", dow="1")
    assert rows[0]["components"][0]["custom_id"] == "cron:hour:weekly:1"
