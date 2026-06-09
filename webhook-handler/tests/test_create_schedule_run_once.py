import pytest
from unittest.mock import AsyncMock, MagicMock
from clients.tasks import TasksClient
from handlers.commands import CommandRouter, CommandContext


def _client(resp_json):
    tc = TasksClient.__new__(TasksClient)  # bypass __init__ network setup
    resp = MagicMock()
    resp.json.return_value = resp_json
    tc._request = AsyncMock(return_value=resp)
    return tc


@pytest.mark.asyncio
async def test_create_schedule_includes_run_once_when_true():
    tc = _client({"id": "s1"})
    await tc.create_schedule("u@x.com", name="n", cron="0 9 * * *", prompt="p", run_once=True)
    body = tc._request.call_args.kwargs["json"]
    assert body["run_once"] is True


@pytest.mark.asyncio
async def test_create_schedule_omits_run_once_by_default():
    tc = _client({"id": "s1"})
    await tc.create_schedule("u@x.com", name="n", cron="0 9 * * *", prompt="p")
    body = tc._request.call_args.kwargs["json"]
    assert "run_once" not in body  # keeps existing create payloads stable


@pytest.mark.asyncio
async def test_run_schedule_create_forwards_run_once():
    r = CommandRouter.__new__(CommandRouter)
    tc = MagicMock()
    tc.create_schedule = AsyncMock(return_value={"id": "s1"})
    r._tasks_client = tc
    r._resolve_email_for_ctx = AsyncMock(return_value="u@x.com")
    ctx = CommandContext(
        user_id="1", user_name="a", channel_id="c", raw_text="", subcommand="",
        arguments="", platform="discord", respond=AsyncMock(), respond_components=AsyncMock())
    await r.run_schedule_create(ctx, name="n", cron="0 9 * * *", prompt="p", run_once=True)
    assert tc.create_schedule.call_args.kwargs.get("run_once") is True
