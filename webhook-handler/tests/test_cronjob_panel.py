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
