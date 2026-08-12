"""Slash commands, which are the only way continuity crosses a surface.

/resume repoints this conversation at another chat. It never merges anything
and never moves context on its own.
"""
from unittest.mock import AsyncMock

import pytest

from gateway import commands
from gateway.events import SessionSource

SOURCE = SessionSource(platform="telegram", chat_id="42", user_id="111")


@pytest.fixture
def tasks():
    client = AsyncMock()
    client.gateway_recent_sessions.return_value = [
        {"platform": "telegram", "chat_id": "42", "owui_chat_id": "chat-a",
         "updated_at": "2026-08-10T10:00:00+00:00"},
        {"platform": "cli", "chat_id": "dev-box", "owui_chat_id": "chat-b",
         "updated_at": "2026-08-09T09:00:00+00:00"},
    ]
    return client


@pytest.mark.parametrize("text,expected", [
    ("/resume", True), ("/RESUME", True), ("  /resume 2 ", True),
    ("/help", True), ("/start", True),
    ("resume", False), ("what is /resume", False), ("", False),
])
def test_command_detection(text, expected):
    assert commands.is_command(text) is expected


async def test_resume_with_no_argument_lists_the_options(tasks):
    out = await commands.handle("/resume", tasks, SOURCE, "u1")

    assert "1" in out and "2" in out
    assert "cli" in out.lower()
    tasks.gateway_put_session.assert_not_called()


async def test_resume_with_a_number_repoints_the_session(tasks):
    out = await commands.handle("/resume 2", tasks, SOURCE, "u1")

    tasks.gateway_put_session.assert_awaited_once_with(
        "telegram", "42", "chat-b", "u1")
    assert "picked up" in out.lower() or "resumed" in out.lower()


async def test_an_out_of_range_pick_is_refused_without_a_write(tasks):
    out = await commands.handle("/resume 9", tasks, SOURCE, "u1")

    tasks.gateway_put_session.assert_not_called()
    assert "1" in out and "2" in out


async def test_a_non_numeric_argument_is_refused_without_a_write(tasks):
    out = await commands.handle("/resume banana", tasks, SOURCE, "u1")
    tasks.gateway_put_session.assert_not_called()
    assert out


async def test_resume_with_no_history_says_so(tasks):
    tasks.gateway_recent_sessions.return_value = []
    out = await commands.handle("/resume", tasks, SOURCE, "u1")
    assert "nothing" in out.lower() or "no " in out.lower()
    tasks.gateway_put_session.assert_not_called()


async def test_help_lists_what_exists(tasks):
    out = await commands.handle("/help", tasks, SOURCE, "u1")
    assert "/resume" in out


async def test_start_is_a_welcome_not_an_error(tasks):
    out = await commands.handle("/start", tasks, SOURCE, "u1")
    assert out and "/resume" in out


async def test_an_unknown_command_points_at_help(tasks):
    out = await commands.handle("/nonsense", tasks, SOURCE, "u1")
    assert "/help" in out


async def test_plain_text_is_not_a_command(tasks):
    assert await commands.handle("hello there", tasks, SOURCE, "u1") is None


async def test_no_command_reply_uses_a_dash_character(tasks):
    for text in ("/help", "/start", "/resume", "/resume 9", "/nonsense"):
        out = await commands.handle(text, tasks, SOURCE, "u1")
        assert "—" not in out and "–" not in out, text
