"""CommandRouter quick-wins: _resolve_email (env→DB), run_schedule_edit,
and the link request/approve/reject pass-throughs."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from handlers.commands import CommandRouter, CommandContext
from clients.tasks import TasksAPIError


def _ctx(user_id):
    cap = {"text": []}

    async def respond(msg):
        cap["text"].append(msg)

    ctx = CommandContext(
        user_id=user_id, user_name="t", channel_id="c", raw_text="",
        subcommand="aiuibuilder", arguments="", platform="discord",
        respond=respond, metadata={},
    )
    return ctx, cap


def _router(mapping, tc):
    return CommandRouter(
        openwebui_client=MagicMock(), n8n_client=MagicMock(api_key=""),
        discord_user_email_map=mapping, tasks_client=tc,
    )


@pytest.mark.asyncio
async def test_resolve_email_env_hit_skips_db():
    tc = MagicMock(); tc.resolve_link = AsyncMock(return_value=None)
    assert await _router({"100": "env@x.com"}, tc)._resolve_email("100") == "env@x.com"
    tc.resolve_link.assert_not_called()


@pytest.mark.asyncio
async def test_resolve_email_db_hit():
    tc = MagicMock(); tc.resolve_link = AsyncMock(return_value="db@x.com")
    assert await _router({}, tc)._resolve_email("200") == "db@x.com"
    tc.resolve_link.assert_awaited_once_with("200")


@pytest.mark.asyncio
async def test_resolve_email_none_when_unlinked():
    tc = MagicMock(); tc.resolve_link = AsyncMock(return_value=None)
    assert await _router({}, tc)._resolve_email("999") is None


@pytest.mark.asyncio
async def test_resolve_email_tasks_down_returns_none():
    tc = MagicMock(); tc.resolve_link = AsyncMock(side_effect=TasksAPIError(0, "down"))
    assert await _router({}, tc)._resolve_email("999") is None


@pytest.mark.asyncio
async def test_run_schedule_edit_updates():
    tc = MagicMock(); tc.resolve_link = AsyncMock(return_value=None)
    tc.update_schedule = AsyncMock(return_value={"id": "sid1"})
    ctx, cap = _ctx("100")
    await _router({"100": "a@x.com"}, tc).run_schedule_edit(
        ctx, "sid1", name="every morning: digest", cron="0 8 * * *", prompt="digest")
    tc.update_schedule.assert_awaited_once()
    assert tc.update_schedule.await_args.args[0] == "a@x.com"
    assert tc.update_schedule.await_args.args[1] == "sid1"
    kw = tc.update_schedule.await_args.kwargs
    assert kw["cron"] == "0 8 * * *" and kw["prompt"] == "digest"
    assert any("updated" in m.lower() for m in cap["text"])


@pytest.mark.asyncio
async def test_request_link_passthrough():
    tc = MagicMock(); tc.request_link = AsyncMock(return_value={"status": "pending"})
    out = await _router({}, tc).request_link("123", "alice", "alice@x.com")
    tc.request_link.assert_awaited_once_with("123", "alice", "alice@x.com")
    assert out["status"] == "pending"


@pytest.mark.asyncio
async def test_approve_link_passthrough():
    tc = MagicMock(); tc.approve_link = AsyncMock(return_value={"email": "alice@x.com"})
    out = await _router({}, tc).approve_link("123", decided_by="admin@x.com")
    tc.approve_link.assert_awaited_once_with("123", decided_by="admin@x.com")
    assert out["email"] == "alice@x.com"


@pytest.mark.asyncio
async def test_reject_link_passthrough():
    tc = MagicMock(); tc.reject_link = AsyncMock(return_value=True)
    assert await _router({}, tc).reject_link("123") is True
    tc.reject_link.assert_awaited_once_with("123")


@pytest.mark.asyncio
async def test_get_schedule_for_edit_splits_name():
    tc = MagicMock(); tc.resolve_link = AsyncMock(return_value=None)
    tc.list_schedules = AsyncMock(return_value=[
        {"id": "sid1", "name": "every morning: summarize emails"}])
    out = await _router({"100": "a@x.com"}, tc).get_schedule_for_edit("100", "sid1")
    assert out == {"what": "summarize emails", "when": "every morning"}


@pytest.mark.asyncio
async def test_get_schedule_for_edit_not_found_returns_none():
    tc = MagicMock(); tc.resolve_link = AsyncMock(return_value=None)
    tc.list_schedules = AsyncMock(return_value=[])
    assert await _router({"100": "a@x.com"}, tc).get_schedule_for_edit("100", "x") is None


@pytest.mark.asyncio
async def test_get_schedule_for_edit_unlinked_returns_none():
    tc = MagicMock(); tc.resolve_link = AsyncMock(return_value=None)
    assert await _router({}, tc).get_schedule_for_edit("999", "sid1") is None
