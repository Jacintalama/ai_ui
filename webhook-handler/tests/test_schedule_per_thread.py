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


def _payload(channel_id="PARENT_CHAN"):
    return {
        "member": {"user": {"id": "U1", "username": "ralphz"}},
        "channel_id": channel_id,
        "id": "INT1",
        "guild_id": "G1",
    }


def _pending(h, token="tok"):
    h._pending_schedules[token] = {
        "name": SCHED_NAME, "cron": "36 21 * * *",
        "prompt": "send an email and say hello",
    }
    return token


def test_thread_named_after_schedule_on_resolved_parent():
    h, discord, router = _make_handler()
    discord.resolve_thread_parent.return_value = "PARENT_CHAN"  # already a text channel
    discord.create_private_thread.return_value = "THREAD_NEW"
    token = _pending(h)

    asyncio.run(h._create_pending_schedule(_payload("PARENT_CHAN"), token, "itok"))

    discord.resolve_thread_parent.assert_awaited_once_with("PARENT_CHAN")
    parent, name = discord.create_private_thread.call_args.args[:2]
    assert parent == "PARENT_CHAN"
    assert name == SCHED_NAME[:90]
    assert "schedules-ralphz" not in name  # not the old per-user thread name
    router.get_user_thread.assert_not_called()
    router.run_schedule_create.assert_awaited_once()
    assert router.run_schedule_create.call_args.kwargs["delivery_channel_id"] == "THREAD_NEW"


def test_created_from_within_a_thread_uses_parent_channel():
    """Regression: creating a schedule from inside the dashboard thread must
    create the per-schedule thread on the thread's PARENT (Discord can't nest
    threads), not on the thread itself (which 400s with code 50024)."""
    h, discord, router = _make_handler()
    discord.resolve_thread_parent.return_value = "REAL_PARENT"  # channel_id was a thread
    discord.create_private_thread.return_value = "THREAD_NEW"
    token = _pending(h)

    asyncio.run(h._create_pending_schedule(_payload("DASH_THREAD"), token, "itok"))

    discord.resolve_thread_parent.assert_awaited_once_with("DASH_THREAD")
    parent = discord.create_private_thread.call_args.args[0]
    assert parent == "REAL_PARENT"  # NOT "DASH_THREAD"
    assert router.run_schedule_create.call_args.kwargs["delivery_channel_id"] == "THREAD_NEW"


def test_falls_back_to_channel_when_thread_creation_fails():
    h, discord, router = _make_handler()
    discord.resolve_thread_parent.return_value = "PARENT_CHAN"
    discord.create_private_thread.return_value = None  # creation failed
    token = _pending(h)

    asyncio.run(h._create_pending_schedule(_payload("PARENT_CHAN"), token, "itok"))

    router.run_schedule_create.assert_awaited_once()
    assert router.run_schedule_create.call_args.kwargs["delivery_channel_id"] == "PARENT_CHAN"
