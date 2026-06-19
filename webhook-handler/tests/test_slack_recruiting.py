import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from handlers.slack_interactions import SlackInteractionsHandler
from handlers import slack_recruiting_panel as srp


def _handler(router):
    slack = MagicMock(); slack.open_modal = AsyncMock(return_value=True)
    slack.post_message = AsyncMock(return_value=True)
    slack.open_dm = AsyncMock(return_value="D1")
    return SlackInteractionsHandler(slack_client=slack, command_router=router)


@pytest.mark.asyncio
async def test_find_button_opens_modal():
    h = _handler(MagicMock())
    payload = {"type": "block_actions", "trigger_id": "tg",
               "channel": {"id": "c"}, "user": {"id": "u"},
               "actions": [{"action_id": srp.OUT_FIND_ACTION_ID}]}
    await h.handle_interaction(payload)
    h.slack.open_modal.assert_awaited_once()


@pytest.mark.asyncio
async def test_view_submission_dispatches():
    calls = []
    router = MagicMock()
    async def fake(ctx, role, location, jobdesc, count):
        calls.append((role, location, jobdesc, count, ctx.notify_channel))
    router.run_panel_outreach = fake
    h = _handler(router)
    view = {"callback_id": srp.OUT_MODAL_CALLBACK,
            "private_metadata": "c",
            "state": {"values": srp.sample_state("Python", "Berlin", "Hiring", "8")}}
    payload = {"type": "view_submission", "user": {"id": "u"}, "view": view}
    await h.handle_interaction(payload)
    for _ in range(6):
        await asyncio.sleep(0)
    assert calls, "run_panel_outreach was not dispatched"
    role, location, jobdesc, count, notify = calls[0]
    # full field ordering (regression guard) + count parsed to int
    assert (role, location, jobdesc, count) == ("Python", "Berlin", "Hiring", 8)
    # the result-delivery channel must be wired, or _watch_outreach can't post back
    assert notify is not None


# --- Phase 3.1: reverse entry (Find Jobs) panel builders ---

def test_find_jobs_button_present_plain_text():
    blocks = srp.build_recruiting_blocks()
    actions = [b for b in blocks if b["type"] == "actions"][0]
    labels = {e["text"]["text"]: e["action_id"] for e in actions["elements"]}
    # NEW button is plain text "Find Jobs" (no emoji); Find Engineers stays as-is.
    assert labels.get("Find Jobs") == srp.OUT_REV_ACTION_ID
    assert any(v == srp.OUT_FIND_ACTION_ID for v in labels.values())


def test_build_reverse_view_reuses_ids_and_callback():
    v = srp.build_reverse_view("C123")
    assert v["type"] == "modal"
    assert v["callback_id"] == srp.OUT_REV_CALLBACK
    assert v["private_metadata"] == "C123"
    assert v["title"]["text"] == "Find Jobs"
    # MUST reuse build_outreach_view's block ids so reverse_fields_from_view parses it.
    out = srp.build_outreach_view("C123")
    assert [b["block_id"] for b in v["blocks"]] == [b["block_id"] for b in out["blocks"]]


def test_reverse_fields_round_trip_and_clamp():
    view = {"state": {"values": srp.sample_state("Backend", "Remote", "Skills here", "30")}}
    # delegates to outreach_fields_from_view -> parse_outreach_modal (count clamps 30->25)
    assert srp.reverse_fields_from_view(view) == ("Backend", "Remote", "Skills here", 25)


# --- Phase 3.5: reverse entry routing ---

@pytest.mark.asyncio
async def test_reverse_button_opens_modal():
    h = _handler(MagicMock())
    payload = {"type": "block_actions", "trigger_id": "tg",
               "channel": {"id": "c"}, "user": {"id": "u"},
               "actions": [{"action_id": srp.OUT_REV_ACTION_ID}]}
    await h.handle_interaction(payload)
    h.slack.open_modal.assert_awaited_once()
    _, view = h.slack.open_modal.await_args.args
    assert view["callback_id"] == srp.OUT_REV_CALLBACK


@pytest.mark.asyncio
async def test_reverse_modal_dispatches_run_panel_reverse():
    calls = []
    router = MagicMock()
    async def fake(ctx, role, location, jobdesc, count):
        calls.append((role, location, jobdesc, count,
                      ctx.notify_channel, ctx.notify_channel_msg))
    router.run_panel_reverse = fake
    h = _handler(router)
    view = {"callback_id": srp.OUT_REV_CALLBACK, "private_metadata": "c",
            "state": {"values": srp.sample_state("Backend dev", "Remote", "10y Python", "5")}}
    payload = {"type": "view_submission", "user": {"id": "u"}, "view": view}
    await h.handle_interaction(payload)
    for _ in range(6):
        await asyncio.sleep(0)
    assert calls, "run_panel_reverse was not dispatched"
    role, location, jobdesc, count, notify, ncm = calls[0]
    assert (role, location, jobdesc, count) == ("Backend dev", "Remote", "10y Python", 5)
    assert notify is not None      # text fallbacks
    assert ncm is not None         # Block Kit review poster for the manual watcher


@pytest.mark.asyncio
async def test_hire_modal_ctx_has_review_poster():
    calls = []
    router = MagicMock()
    async def fake(ctx, role, location, jobdesc, count):
        calls.append(ctx.notify_channel_msg)
    router.run_panel_outreach = fake
    h = _handler(router)
    view = {"callback_id": srp.OUT_MODAL_CALLBACK, "private_metadata": "c",
            "state": {"values": srp.sample_state("Python", "Berlin", "Hiring", "8")}}
    payload = {"type": "view_submission", "user": {"id": "u"}, "view": view}
    await h.handle_interaction(payload)
    for _ in range(6):
        await asyncio.sleep(0)
    assert calls and calls[0] is not None  # manual review needs notify_channel_msg
