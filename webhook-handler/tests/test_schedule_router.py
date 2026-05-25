"""CommandRouter schedule methods: run_schedule_list / _create / _action.
Mirrors the run_panel_* pattern — email lookup + TasksClient + friendly errors."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from handlers.commands import CommandRouter, CommandContext
from clients.tasks import TasksAPIError


def _ctx(user_id):
    cap = {"text": [], "components": []}

    async def respond(msg):
        cap["text"].append(msg)

    async def respond_components(msg, components):
        cap["components"].append((msg, components))

    ctx = CommandContext(
        user_id=user_id, user_name="tester", channel_id="c",
        raw_text="", subcommand="aiuibuilder", arguments="",
        platform="discord", respond=respond,
        respond_components=respond_components, metadata={},
    )
    return ctx, cap


def _router(mapping, tc):
    if not isinstance(getattr(tc, "resolve_link", None), AsyncMock):
        tc.resolve_link = AsyncMock(return_value=None)
    return CommandRouter(
        openwebui_client=MagicMock(), n8n_client=MagicMock(api_key=""),
        discord_user_email_map=mapping, tasks_client=tc,
    )


@pytest.mark.asyncio
async def test_run_schedule_list_empty_uses_text():
    tc = MagicMock()
    tc.list_schedules = AsyncMock(return_value=[])
    ctx, cap = _ctx("100")
    await _router({"100": "a@x.com"}, tc).run_schedule_list(ctx)
    tc.list_schedules.assert_awaited_once_with("a@x.com")
    assert cap["text"] and "no schedules" in cap["text"][0].lower()
    assert cap["components"] == []


@pytest.mark.asyncio
async def test_run_schedule_list_with_items_uses_components():
    tc = MagicMock()
    tc.list_schedules = AsyncMock(return_value=[
        {"id": "11111111-1111-1111-1111-111111111111", "name": "morning digest",
         "enabled": True, "last_run_status": "completed"}])
    ctx, cap = _ctx("100")
    await _router({"100": "a@x.com"}, tc).run_schedule_list(ctx)
    assert cap["components"], "should render schedule buttons"
    content, components = cap["components"][0]
    assert "morning digest" in content
    assert len(components) == 1


@pytest.mark.asyncio
async def test_run_schedule_list_unmapped_user():
    ctx, cap = _ctx("999")
    await _router({}, MagicMock()).run_schedule_list(ctx)
    assert any("isn't linked" in m for m in cap["text"])


@pytest.mark.asyncio
async def test_run_schedule_create_passes_delivery_channel():
    tc = MagicMock()
    tc.create_schedule = AsyncMock(return_value={"id": "s1"})
    ctx, cap = _ctx("100")
    await _router({"100": "a@x.com"}, tc).run_schedule_create(
        ctx, name="every day at 8:00 AM: digest", cron="0 8 * * *",
        prompt="summarize emails", delivery_channel_id="thread-1")
    tc.create_schedule.assert_awaited_once()
    assert tc.create_schedule.await_args.args[0] == "a@x.com"
    kw = tc.create_schedule.await_args.kwargs
    assert kw["cron"] == "0 8 * * *"
    assert kw["prompt"] == "summarize emails"
    assert kw["delivery_channel_id"] == "thread-1"
    assert any("scheduled" in m.lower() for m in cap["text"])


@pytest.mark.asyncio
async def test_run_schedule_create_unmapped_user():
    tc = MagicMock()
    tc.create_schedule = AsyncMock()
    ctx, cap = _ctx("999")
    await _router({}, tc).run_schedule_create(ctx, name="n", cron="0 8 * * *", prompt="p")
    tc.create_schedule.assert_not_called()
    assert any("isn't linked" in m for m in cap["text"])


@pytest.mark.asyncio
@pytest.mark.parametrize("action,method,reply", [
    ("run", "run_schedule_now", "running"),
    ("pause", "pause_schedule", "paused"),
    ("resume", "resume_schedule", "resumed"),
    ("del", "delete_schedule", "deleted"),
])
async def test_run_schedule_action_dispatches(action, method, reply):
    tc = MagicMock()
    setattr(tc, method, AsyncMock(return_value=True))
    ctx, cap = _ctx("100")
    await _router({"100": "a@x.com"}, tc).run_schedule_action(ctx, action, "sid-1")
    getattr(tc, method).assert_awaited_once_with("a@x.com", "sid-1")
    assert any(reply in m.lower() for m in cap["text"])


@pytest.mark.asyncio
async def test_run_schedule_action_tasks_error_is_friendly():
    tc = MagicMock()
    tc.delete_schedule = AsyncMock(side_effect=TasksAPIError(0, "down"))
    ctx, cap = _ctx("100")
    await _router({"100": "a@x.com"}, tc).run_schedule_action(ctx, "del", "sid-1")
    assert cap["text"]
