"""DiscordCommandHandler must track its background tasks and log failures.

~21 create_task(...) sites were fire-and-forget: no stored reference (an
unreferenced task can be GC'd mid-flight per CPython docs) and no exception
retrieval (a raise inside is silently swallowed). So a button/modal/slash
action — build, publish, delete, schedule, outreach — could just vanish.
_spawn() keeps a strong reference and logs the exception. (audit 2026-06-15.)
"""
import asyncio
import logging
from unittest.mock import MagicMock

from handlers.discord_commands import DiscordCommandHandler


def _handler():
    return DiscordCommandHandler(discord_client=MagicMock(), command_router=MagicMock())


async def test_spawn_holds_reference_then_clears():
    handler = _handler()
    ran = []

    async def ok():
        ran.append(1)

    task = handler._spawn(ok())
    assert task in handler._bg_tasks       # strong ref held while running
    await task
    await asyncio.sleep(0)                  # let the done-callback fire
    assert ran == [1]
    assert handler._bg_tasks == set()       # cleared after completion


async def test_spawn_logs_exception_instead_of_swallowing(caplog):
    handler = _handler()

    async def boom():
        raise ValueError("kaboom")

    with caplog.at_level(logging.ERROR):
        handler._spawn(boom())
        for _ in range(20):
            await asyncio.sleep(0)
            if not handler._bg_tasks:
                break

    assert "kaboom" in caplog.text          # failure surfaced, not silent
    assert handler._bg_tasks == set()
