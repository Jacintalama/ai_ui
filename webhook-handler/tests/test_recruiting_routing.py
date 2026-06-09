import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from handlers.discord_commands import DiscordCommandHandler
from handlers import recruiting_panel as rp


def _handler(router):
    d = MagicMock()
    return DiscordCommandHandler(discord_client=d, command_router=router)


async def _drain():
    for _ in range(6):
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_find_button_opens_modal():
    handler = _handler(MagicMock())
    payload = {"type": 3, "id": "i", "token": "t",
               "data": {"custom_id": rp.OUT_FIND_ID},
               "member": {"user": {"id": "100", "username": "alice"}}, "channel_id": "c"}
    resp = await handler.handle_interaction(payload)
    assert resp["type"] == 9  # MODAL
    assert resp["data"]["custom_id"] == rp.OUT_MODAL_ID


@pytest.mark.asyncio
async def test_modal_submit_dispatches_outreach():
    calls = []
    router = MagicMock()
    async def fake(ctx, role, location, jobdesc, count):
        calls.append((role, location, jobdesc, count))
    router.run_panel_outreach = fake
    handler = _handler(router)
    payload = {
        "type": 5,  # MODAL_SUBMIT
        "id": "i", "token": "t", "channel_id": "c",
        "member": {"user": {"id": "100", "username": "alice"}},
        "data": {"custom_id": rp.OUT_MODAL_ID, "components": [
            {"type": 1, "components": [{"type": 4, "custom_id": rp.OUT_ROLE_INPUT, "value": "Python"}]},
            {"type": 1, "components": [{"type": 4, "custom_id": rp.OUT_LOCATION_INPUT, "value": "Berlin"}]},
            {"type": 1, "components": [{"type": 4, "custom_id": rp.OUT_JOBDESC_INPUT, "value": "Hiring a dev"}]},
            {"type": 1, "components": [{"type": 4, "custom_id": rp.OUT_COUNT_INPUT, "value": "8"}]},
        ]},
    }
    resp = await handler.handle_interaction(payload)
    assert resp["type"] == 5  # DEFERRED_CHANNEL_MESSAGE
    await _drain()
    assert calls == [("Python", "Berlin", "Hiring a dev", 8)]
