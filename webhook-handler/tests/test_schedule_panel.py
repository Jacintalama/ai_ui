"""Tests for the pure Schedules panel/modal/card/list builders in
handlers/app_builder_panel.py (the `aiuisched:` custom_id family)."""
import pytest

from handlers import app_builder_panel as p


def test_build_schedules_panel_has_new_and_list_buttons():
    payload = p.build_schedules_panel()
    assert isinstance(payload["content"], str) and payload["content"]
    buttons = [b for row in payload["components"] for b in row["components"]]
    ids = {b["custom_id"] for b in buttons}
    assert p.SCHED_NEW_ID in ids
    assert p.SCHED_LIST_ID in ids


def test_build_schedule_modal_has_what_and_when_inputs():
    modal = p.build_schedule_modal()
    assert modal["custom_id"] == p.SCHED_MODAL_ID
    inputs = [c for row in modal["components"] for c in row["components"]]
    by_id = {i["custom_id"]: i for i in inputs}
    assert set(by_id) == {p.SCHED_WHAT_INPUT, p.SCHED_WHEN_INPUT}
    assert by_id[p.SCHED_WHAT_INPUT]["style"] == p.TEXT_PARAGRAPH
    assert by_id[p.SCHED_WHEN_INPUT]["style"] == p.TEXT_SHORT
    assert by_id[p.SCHED_WHAT_INPUT]["required"]
    assert by_id[p.SCHED_WHEN_INPUT]["required"]


def test_build_confirm_components_carries_token():
    buttons = [b for row in p.build_confirm_components("tok123") for b in row["components"]]
    ids = {b["custom_id"] for b in buttons}
    assert "aiuisched:confirm:tok123" in ids
    assert "aiuisched:cancel:tok123" in ids


def test_confirm_cancel_predicates_and_token_extraction():
    assert p.is_sched_confirm("aiuisched:confirm:abc")
    assert p.token_from_confirm("aiuisched:confirm:abc") == "abc"
    assert p.is_sched_cancel("aiuisched:cancel:abc")
    assert p.token_from_cancel("aiuisched:cancel:abc") == "abc"
    assert not p.is_sched_confirm("aiuisched:cancel:abc")


def test_token_extraction_rejects_empty():
    with pytest.raises(ValueError):
        p.token_from_confirm("aiuisched:confirm:")


def test_build_schedule_list_empty():
    out = p.build_schedule_list([])
    assert "no schedules" in out["content"].lower()
    assert out["components"] == []


def test_build_schedule_list_renders_rows_state_aware():
    scheds = [
        {"id": "11111111-1111-1111-1111-111111111111",
         "name": "every day at 8:00 AM: summarize emails",
         "enabled": True, "last_run_status": "completed"},
        {"id": "22222222-2222-2222-2222-222222222222",
         "name": "every Monday at 9:00 AM: weekly report",
         "enabled": False, "last_run_status": None},
    ]
    out = p.build_schedule_list(scheds)
    assert "summarize emails" in out["content"]
    assert "weekly report" in out["content"]
    rows = out["components"]
    assert len(rows) == 2
    first = {b["custom_id"] for b in rows[0]["components"]}
    assert "aiuisched:run:11111111-1111-1111-1111-111111111111" in first
    assert "aiuisched:pause:11111111-1111-1111-1111-111111111111" in first
    assert "aiuisched:del:11111111-1111-1111-1111-111111111111" in first
    second = {b["custom_id"] for b in rows[1]["components"]}
    assert "aiuisched:resume:22222222-2222-2222-2222-222222222222" in second


def test_build_schedule_list_caps_at_5_rows():
    scheds = [
        {"id": str(i), "name": f"job {i}", "enabled": True, "last_run_status": None}
        for i in range(8)
    ]
    assert len(p.build_schedule_list(scheds)["components"]) <= 5


def test_sched_action_predicates_and_id_extraction():
    assert p.is_sched_run("aiuisched:run:abc") and p.id_from_run("aiuisched:run:abc") == "abc"
    assert p.is_sched_pause("aiuisched:pause:abc") and p.id_from_pause("aiuisched:pause:abc") == "abc"
    assert p.is_sched_resume("aiuisched:resume:abc") and p.id_from_resume("aiuisched:resume:abc") == "abc"
    assert p.is_sched_del("aiuisched:del:abc") and p.id_from_del("aiuisched:del:abc") == "abc"


def test_sched_entry_predicates():
    assert p.is_sched_new(p.SCHED_NEW_ID)
    assert p.is_sched_list(p.SCHED_LIST_ID)
    assert p.is_sched_modal(p.SCHED_MODAL_ID)
    assert not p.is_sched_new(p.SCHED_LIST_ID)
