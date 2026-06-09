"""DiscordCommandHandler routing for the date/time picker (aiuisched:pick:*)."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from handlers.discord_commands import DiscordCommandHandler
from handlers.app_builder_panel import SCHED_NEW_ID, SCHED_MODAL_ID
from handlers import schedule_picker as sp


def _handler(router=None):
    d = MagicMock()
    d.edit_original = AsyncMock(return_value=True)
    return DiscordCommandHandler(discord_client=d, command_router=router or MagicMock())


def _btn(cid, user="100"):
    return {"type": 3, "id": "i", "token": "t", "data": {"custom_id": cid},
            "member": {"user": {"id": user, "username": "a"}}, "channel_id": "c"}


def _select(cid, value, user="100"):
    return {"type": 3, "id": "i", "token": "t",
            "data": {"custom_id": cid, "values": [value]},
            "member": {"user": {"id": user, "username": "a"}}, "channel_id": "c"}


def _task_submit(cid, what, user="100"):
    return {"type": 5, "id": "i", "token": "t", "channel_id": "c",
            "member": {"user": {"id": user, "username": "a"}},
            "data": {"custom_id": cid, "components": [
                {"type": 1, "components": [
                    {"type": 4, "custom_id": sp.TASK_INPUT_ID, "value": what}]}]}}


@pytest.mark.asyncio
async def test_new_opens_kind_card_and_parks_token():
    h = _handler()
    resp = await h.handle_interaction(_btn(SCHED_NEW_ID))
    assert resp["type"] == 4  # ephemeral message
    ids = [c["custom_id"] for row in resp["data"]["components"] for c in row["components"]]
    assert any("kindrep" in i for i in ids) and any("kindonce" in i for i in ids)
    assert h._pending_picks  # a token was created


@pytest.mark.asyncio
async def test_kind_then_freq_accumulates_and_rerenders():
    h = _handler()
    h._pending_picks["tk"] = {}
    r1 = await h.handle_interaction(_btn(sp.pick_cid("kindrep", "tk")))
    assert r1["type"] == 7  # UPDATE_MESSAGE
    assert h._pending_picks["tk"] == {"kind": "rep"}
    r2 = await h.handle_interaction(_select(sp.pick_cid("freq", "tk"), "daily"))
    assert r2["type"] == 7
    assert h._pending_picks["tk"]["freq"] == "daily"


@pytest.mark.asyncio
async def test_changing_freq_drops_stale_weekday():
    h = _handler()
    h._pending_picks["tk"] = {"kind": "rep", "freq": "weekly", "hour": "9", "weekday": "monday"}
    await h.handle_interaction(_select(sp.pick_cid("freq", "tk"), "daily"))
    assert "weekday" not in h._pending_picks["tk"]
    assert h._pending_picks["tk"]["hour"] == "9"  # hour stays (daily uses it)


@pytest.mark.asyncio
async def test_settask_opens_task_modal():
    h = _handler()
    h._pending_picks["tk"] = {"kind": "rep", "freq": "daily", "hour": "9"}
    resp = await h.handle_interaction(_btn(sp.pick_cid("settask", "tk")))
    assert resp["type"] == 9
    assert resp["data"]["custom_id"] == f"{sp.TASK_MODAL_PREFIX}tk"


@pytest.mark.asyncio
async def test_task_submit_parks_picker_cron_and_run_once():
    h = _handler()
    h._pending_picks["tk"] = {"kind": "rep", "freq": "daily", "hour": "9"}
    resp = await h.handle_interaction(_task_submit(f"{sp.TASK_MODAL_PREFIX}tk", "say hi"))
    assert resp["type"] == 4  # confirm card (no Gmail/Drive intent in "say hi")
    pend = list(h._pending_schedules.values())[-1]
    assert pend["cron"] == "0 9 * * *" and pend["run_once"] is False
    assert h._pending_picks.get("tk") is None  # consumed


@pytest.mark.asyncio
async def test_one_time_past_is_rejected():
    h = _handler()
    h._pending_picks["tk"] = {"kind": "once", "date": "2000-01-01", "hour": "9"}
    resp = await h.handle_interaction(_task_submit(f"{sp.TASK_MODAL_PREFIX}tk", "do it"))
    assert resp["type"] == 4
    assert "past" in resp["data"]["content"].lower()
    assert not h._pending_schedules  # nothing parked


@pytest.mark.asyncio
async def test_expired_token_is_friendly():
    h = _handler()
    resp = await h.handle_interaction(_btn(sp.pick_cid("freq", "missing")))
    assert resp["type"] == 7  # UPDATE_MESSAGE with a restart hint
    assert "start over" in resp["data"]["content"].lower()


@pytest.mark.asyncio
async def test_kindonce_renders_onetime_card():
    h = _handler()
    h._pending_picks["tk"] = {}
    resp = await h.handle_interaction(_btn(sp.pick_cid("kindonce", "tk")))
    assert resp["type"] == 7
    assert h._pending_picks["tk"] == {"kind": "once"}
    ids = [c["custom_id"] for row in resp["data"]["components"] for c in row["components"]]
    assert any("qtoday" in i for i in ids)
    assert sp.pick_cid("date", "tk") in ids


@pytest.mark.asyncio
async def test_quick_date_button_sets_date():
    h = _handler()
    h._pending_picks["tk"] = {"kind": "once"}
    await h.handle_interaction(_btn(sp.pick_cid("qtomorrow", "tk")))
    assert h._pending_picks["tk"].get("date")  # a YYYY-MM-DD was set


@pytest.mark.asyncio
async def test_one_time_future_parks_run_once_true():
    h = _handler()
    h._pending_picks["tk"] = {"kind": "once", "date": "2099-12-31", "hour": "9"}
    resp = await h.handle_interaction(_task_submit(f"{sp.TASK_MODAL_PREFIX}tk", "ping me"))
    assert resp["type"] == 4
    pend = list(h._pending_schedules.values())[-1]
    assert pend["run_once"] is True and pend["cron"] == "0 9 31 12 *"
