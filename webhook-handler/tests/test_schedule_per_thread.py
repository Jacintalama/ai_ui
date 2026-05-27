import os
import asyncio
from unittest.mock import AsyncMock

os.environ.setdefault("OAUTH_STATE_SECRET", "test-secret-123")

from handlers.discord_commands import DiscordCommandHandler

SCHED_NAME = "every day at 9:36 PM: send an email and say hello"


def _make_handler():
    discord = AsyncMock()
    router = AsyncMock()
    return DiscordCommandHandler(discord, router), discord, router


def _payload():
    return {
        "member": {"user": {"id": "U1", "username": "ralphz"}},
        "channel_id": "PARENT_CHAN",
        "id": "INT1",
        "guild_id": "G1",
    }


def test_each_schedule_gets_its_own_thread_named_after_it():
    h, discord, router = _make_handler()
    discord.create_private_thread.return_value = "THREAD_NEW"
    token = "tok1"
    h._pending_schedules[token] = {
        "name": SCHED_NAME, "cron": "36 21 * * *",
        "prompt": "send an email and say hello",
    }

    asyncio.run(h._create_pending_schedule(_payload(), token, "itok"))

    # A NEW private thread named after THIS schedule, under the parent channel.
    discord.create_private_thread.assert_awaited_once()
    parent, name = discord.create_private_thread.call_args.args[:2]
    assert parent == "PARENT_CHAN"
    assert name == SCHED_NAME[:90]
    assert "schedules-ralphz" not in name  # not the old per-user thread name

    # The per-user shared-thread cache must NOT decide the delivery target.
    router.get_user_thread.assert_not_called()

    # Schedule is created delivering to the dedicated thread.
    router.run_schedule_create.assert_awaited_once()
    assert router.run_schedule_create.call_args.kwargs["delivery_channel_id"] == "THREAD_NEW"


def test_falls_back_to_channel_when_thread_creation_fails():
    h, discord, router = _make_handler()
    discord.create_private_thread.return_value = None  # creation failed
    token = "tok2"
    h._pending_schedules[token] = {
        "name": SCHED_NAME, "cron": "36 21 * * *", "prompt": "x",
    }

    asyncio.run(h._create_pending_schedule(_payload(), token, "itok"))

    router.run_schedule_create.assert_awaited_once()
    assert router.run_schedule_create.call_args.kwargs["delivery_channel_id"] == "PARENT_CHAN"
