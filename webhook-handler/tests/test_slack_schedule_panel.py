"""Tests for Slack Block Kit builders for the cron scheduler (Slack mirror of
the Discord schedule panel)."""
import json

from handlers.slack_schedule_panel import (
    build_schedules_panel,
    build_schedules_dashboard,
    build_schedule_card,
    build_schedule_modal,
    build_schedule_edit_modal,
    build_retry_blocks,
)
from handlers.app_builder_panel import (
    SCHED_OPEN_ID,
    SCHED_NEW_ID,
    SCHED_MODAL_ID,
    SCHED_EDITMODAL_PREFIX,
    SCHED_RUN_PREFIX,
    SCHED_PAUSE_PREFIX,
    SCHED_RESUME_PREFIX,
    SCHED_DEL_PREFIX,
    SCHED_EDIT_PREFIX,
)


def _action_ids(blocks: list[dict]) -> list[str]:
    """All action_ids across every actions block in a block list."""
    ids: list[str] = []
    for b in blocks:
        if b.get("type") == "actions":
            for el in b.get("elements", []):
                if "action_id" in el:
                    ids.append(el["action_id"])
    return ids


def _assert_actions_blocks_within_limit(blocks: list[dict]) -> None:
    for b in blocks:
        if b.get("type") == "actions":
            assert len(b.get("elements", [])) <= 5


_SCHED = {
    "id": "sched-123",
    "prompt": "summarize my unread emails",
    "cron_expr": "0 9 * * *",
    "enabled": True,
}


def test_panel_has_open_button():
    blocks = build_schedules_panel()
    assert isinstance(blocks, list)
    assert SCHED_OPEN_ID in _action_ids(blocks)
    _assert_actions_blocks_within_limit(blocks)


def test_dashboard_with_one_schedule():
    blocks = build_schedules_dashboard([_SCHED])
    ids = _action_ids(blocks)
    assert SCHED_NEW_ID in ids
    assert f"{SCHED_RUN_PREFIX}{_SCHED['id']}" in ids
    assert f"{SCHED_EDIT_PREFIX}{_SCHED['id']}" in ids
    assert f"{SCHED_DEL_PREFIX}{_SCHED['id']}" in ids
    _assert_actions_blocks_within_limit(blocks)


def _edit_button(blocks: list[dict]) -> dict:
    for b in blocks:
        if b.get("type") == "actions":
            for el in b.get("elements", []):
                if el.get("action_id") == f"{SCHED_EDIT_PREFIX}{_SCHED['id']}":
                    return el
    raise AssertionError("edit button not found")


def test_edit_button_carries_prefill_value():
    """Edit button must carry the prefill (id/prompt/cron) as JSON in `value`
    so the edit modal can open synchronously with no fetch at click time."""
    blocks = build_schedule_card(_SCHED)
    btn = _edit_button(blocks)
    assert "value" in btn
    data = json.loads(btn["value"])
    assert data["id"] == str(_SCHED["id"])
    assert data["prompt"] == _SCHED["prompt"]
    assert data["cron"] == _SCHED["cron_expr"]
    # action_id unchanged so routing stays the same
    assert btn["action_id"] == f"{SCHED_EDIT_PREFIX}{_SCHED['id']}"


def test_edit_button_value_truncates_long_prompt():
    """Slack button `value` max is 2000 chars; the prompt is truncated to stay
    safely under the limit."""
    long = "x" * 5000
    blocks = build_schedule_card({**_SCHED, "prompt": long})
    btn = _edit_button(blocks)
    assert len(btn["value"]) <= 2000
    data = json.loads(btn["value"])
    assert len(data["prompt"]) <= 1500


def test_dashboard_empty_has_no_schedules_text():
    blocks = build_schedules_dashboard([])
    text = " ".join(
        b.get("text", {}).get("text", "")
        for b in blocks
        if b.get("type") == "section"
    ).lower()
    assert "no schedules" in text
    _assert_actions_blocks_within_limit(blocks)


def test_card_enabled_has_pause_not_resume():
    blocks = build_schedule_card({**_SCHED, "enabled": True})
    ids = _action_ids(blocks)
    assert f"{SCHED_PAUSE_PREFIX}{_SCHED['id']}" in ids
    assert f"{SCHED_RESUME_PREFIX}{_SCHED['id']}" not in ids
    _assert_actions_blocks_within_limit(blocks)


def test_card_disabled_has_resume_not_pause():
    blocks = build_schedule_card({**_SCHED, "enabled": False})
    ids = _action_ids(blocks)
    assert f"{SCHED_RESUME_PREFIX}{_SCHED['id']}" in ids
    assert f"{SCHED_PAUSE_PREFIX}{_SCHED['id']}" not in ids
    _assert_actions_blocks_within_limit(blocks)


def _plain_text_input_blocks(view: dict) -> list[dict]:
    out = []
    for b in view.get("blocks", []):
        el = b.get("element", {})
        if el.get("type") == "plain_text_input":
            out.append(b)
    return out


def test_create_modal_shape():
    view = build_schedule_modal()
    assert view["callback_id"] == SCHED_MODAL_ID
    inputs = _plain_text_input_blocks(view)
    assert len(inputs) == 2
    # one multiline, one single-line
    multilines = [b["element"].get("multiline", False) for b in inputs]
    assert True in multilines
    assert False in multilines


def test_edit_modal_prefilled():
    view = build_schedule_edit_modal(_SCHED)
    assert view["callback_id"].startswith(SCHED_EDITMODAL_PREFIX)
    assert view["callback_id"] == f"{SCHED_EDITMODAL_PREFIX}{_SCHED['id']}"
    inputs = _plain_text_input_blocks(view)
    initials = {b["element"].get("initial_value") for b in inputs}
    assert _SCHED["prompt"] in initials
    assert _SCHED["cron_expr"] in initials


def test_retry_blocks():
    blocks = build_retry_blocks(_SCHED["id"])
    ids = _action_ids(blocks)
    assert f"{SCHED_RUN_PREFIX}{_SCHED['id']}" in ids
    _assert_actions_blocks_within_limit(blocks)
