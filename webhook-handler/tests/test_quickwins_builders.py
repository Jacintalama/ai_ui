"""Pure builders for the quick-wins: retry button, schedule-edit, and linking."""
import pytest

from handlers import app_builder_panel as p


# --- #3 Retry on failed runs ---
def test_build_retry_components_reuses_run_handler():
    btns = [b for row in p.build_retry_components("sid-1") for b in row["components"]]
    assert any(b["custom_id"] == "aiuisched:run:sid-1" for b in btns)
    assert any("retry" in b["label"].lower() for b in btns)


# --- #4 Edit a schedule ---
def test_schedule_list_row_has_edit_button():
    scheds = [{"id": "sid-1", "name": "every morning: digest",
               "enabled": True, "last_run_status": None}]
    out = p.build_schedule_list(scheds)
    ids = {b["custom_id"] for row in out["components"] for b in row["components"]}
    assert "aiuisched:edit:sid-1" in ids
    # still has the originals
    assert "aiuisched:run:sid-1" in ids and "aiuisched:del:sid-1" in ids


def test_edit_predicates_and_id_extraction():
    assert p.is_sched_edit("aiuisched:edit:abc") and p.id_from_edit("aiuisched:edit:abc") == "abc"
    assert p.is_sched_editmodal("aiuisched:editmodal:abc")
    assert p.id_from_editmodal("aiuisched:editmodal:abc") == "abc"
    assert not p.is_sched_edit("aiuisched:editmodal:abc")  # disjoint prefixes


def test_build_schedule_edit_modal_prefills_current_values():
    modal = p.build_schedule_edit_modal("sid-1", what="summarize emails", when="every morning")
    assert modal["custom_id"] == "aiuisched:editmodal:sid-1"
    inputs = {i["custom_id"]: i for row in modal["components"] for i in row["components"]}
    assert inputs[p.SCHED_WHAT_INPUT]["value"] == "summarize emails"
    assert inputs[p.SCHED_WHEN_INPUT]["value"] == "every morning"


# --- #1 Self-service linking ---
def test_schedules_panel_has_link_button():
    ids = {b["custom_id"] for row in p.build_schedules_panel()["components"]
           for b in row["components"]}
    assert p.LINK_START_ID in ids


def test_build_link_modal_has_email_field():
    modal = p.build_link_modal()
    assert modal["custom_id"] == p.LINK_MODAL_ID
    inputs = [i for row in modal["components"] for i in row["components"]]
    assert any(i["custom_id"] == p.LINK_EMAIL_INPUT for i in inputs)


def test_build_link_request_components_carries_discord_id():
    ids = {b["custom_id"] for row in p.build_link_request_components("123")
           for b in row["components"]}
    assert "aiuilink:approve:123" in ids
    assert "aiuilink:reject:123" in ids


def test_link_predicates_and_id_extraction():
    assert p.is_link_start(p.LINK_START_ID)
    assert p.is_link_modal(p.LINK_MODAL_ID)
    assert p.is_link_approve("aiuilink:approve:123")
    assert p.id_from_link_approve("aiuilink:approve:123") == "123"
    assert p.is_link_reject("aiuilink:reject:123")
    assert p.id_from_link_reject("aiuilink:reject:123") == "123"
    assert not p.is_link_approve("aiuilink:reject:123")
