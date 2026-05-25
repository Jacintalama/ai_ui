"""Redesigned Schedules builders: entry panel (Open+Link), dashboard, dropdown, card."""
from handlers import app_builder_panel as p


def test_panel_has_open_and_link_not_new_or_list():
    ids = {b["custom_id"] for row in p.build_schedules_panel()["components"]
           for b in row["components"]}
    assert p.SCHED_OPEN_ID in ids
    assert p.LINK_START_ID in ids
    assert p.SCHED_NEW_ID not in ids   # New moved into the thread dashboard
    assert p.SCHED_LIST_ID not in ids  # replaced by the dropdown


def test_dashboard_empty_has_new_no_dropdown():
    out = p.build_schedules_dashboard([])
    ids = {b.get("custom_id") for row in out["components"] for b in row.get("components", [])}
    assert p.SCHED_NEW_ID in ids
    assert p.SCHED_SELECT_ID not in ids
    assert "no schedules" in out["content"].lower()


def test_dashboard_with_schedules_has_new_and_dropdown():
    scheds = [{"id": "s1", "cron_expr": "*/5 * * * *", "prompt": "summarize emails",
               "enabled": True, "last_run_status": None}]
    out = p.build_schedules_dashboard(scheds)
    ids = {b.get("custom_id") for row in out["components"] for b in row.get("components", [])}
    assert p.SCHED_NEW_ID in ids
    assert p.SCHED_SELECT_ID in ids


def test_schedule_select_options_are_human_readable():
    scheds = [
        {"id": "s1", "cron_expr": "*/5 * * * *", "prompt": "summarize emails",
         "enabled": True, "last_run_status": None},
        {"id": "s2", "cron_expr": "0 9 * * 1", "prompt": "weekly report",
         "enabled": False, "last_run_status": "completed"},
    ]
    sel = p.build_schedule_select(scheds)[0]["components"][0]
    assert sel["custom_id"] == p.SCHED_SELECT_ID
    assert sel["type"] == p.SELECT_MENU
    opts = {o["value"]: o for o in sel["options"]}
    assert opts["s1"]["label"] == "every 5 minutes — summarize emails"
    assert "active" in opts["s1"]["description"].lower()
    assert "paused" in opts["s2"]["description"].lower()


def test_schedule_card_clean_text_and_actions():
    s = {"id": "s1", "cron_expr": "*/5 * * * *", "prompt": "summarize emails",
         "enabled": True, "last_run_status": "completed"}
    out = p.build_schedule_card(s)
    embed = out["embeds"][0]
    assert "summarize emails" in embed["title"]
    assert any("every 5 minutes" in f["value"] for f in embed["fields"])
    assert "*/5" not in str(embed)  # no raw cron leaking through
    assert isinstance(embed["color"], int)
    ids = {b["custom_id"] for row in out["components"] for b in row["components"]}
    assert ids.issuperset({"aiuisched:run:s1", "aiuisched:edit:s1", "aiuisched:del:s1"})
    assert "aiuisched:pause:s1" in ids


def test_schedule_card_paused_shows_resume():
    s = {"id": "s2", "cron_expr": "0 9 * * 1", "prompt": "x",
         "enabled": False, "last_run_status": None}
    ids = {b["custom_id"] for row in p.build_schedule_card(s)["components"]
           for b in row["components"]}
    assert "aiuisched:resume:s2" in ids
    assert "aiuisched:pause:s2" not in ids


def test_build_deleted_card():
    out = p.build_deleted_card()
    assert "delet" in out["content"].lower()
    assert out["components"] == []


def test_open_select_predicates():
    assert p.is_sched_open(p.SCHED_OPEN_ID)
    assert p.is_sched_select(p.SCHED_SELECT_ID)
    assert not p.is_sched_open(p.SCHED_SELECT_ID)
