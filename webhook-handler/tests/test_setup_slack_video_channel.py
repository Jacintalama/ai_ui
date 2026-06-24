"""Tests for scripts/setup_slack_video_channel.py (helpers/client patched)."""
import asyncio
import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

# Make the scripts/ directory importable (same pattern as test_setup_video_channel.py).
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import setup_slack_video_channel as s  # noqa: E402


def _clear_env(monkeypatch):
    for k in ("SLACK_BOT_TOKEN", "SLACK_VIDEO_CHANNEL_ID"):
        monkeypatch.delenv(k, raising=False)


def test_default_channel_id_constant():
    """DEFAULT_CHANNEL_ID should be the #video-generation channel."""
    assert s.DEFAULT_CHANNEL_ID == "C0BCRE20JNR"


def test_missing_token_returns_1(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["setup_slack_video_channel.py"])
    assert asyncio.run(s.main()) == 1


def test_default_channel_posts_video_panel(monkeypatch):
    """With no argv or env override, posts to DEFAULT_CHANNEL_ID."""
    from handlers.slack_video_panel import build_video_panel

    _clear_env(monkeypatch)
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setattr(sys, "argv", ["setup_slack_video_channel.py"])

    with patch("setup_slack_video_channel.SlackClient") as MockSlack:
        inst = MockSlack.return_value
        inst.post_message = AsyncMock(return_value="1234.5678")

        rc = asyncio.run(s.main())

        MockSlack.assert_called_once_with(bot_token="xoxb-test")
        inst.post_message.assert_called_once_with(
            s.DEFAULT_CHANNEL_ID,
            text="AIUI Video Studio",
            blocks=build_video_panel()["blocks"],
        )

    assert rc == 0


def test_argv_overrides_channel(monkeypatch):
    """A channel id passed as argv[1] takes priority over env and default."""
    _clear_env(monkeypatch)
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setattr(sys, "argv", ["setup_slack_video_channel.py", "CARGV999"])

    with patch("setup_slack_video_channel.SlackClient") as MockSlack:
        inst = MockSlack.return_value
        inst.post_message = AsyncMock(return_value="ts-argv")

        rc = asyncio.run(s.main())

        inst.post_message.assert_called_once()
        channel_used = inst.post_message.call_args.args[0]
        assert channel_used == "CARGV999"

    assert rc == 0


def test_env_overrides_default_channel(monkeypatch):
    """SLACK_VIDEO_CHANNEL_ID env var is used when no argv is given."""
    _clear_env(monkeypatch)
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_VIDEO_CHANNEL_ID", "CENV456")
    monkeypatch.setattr(sys, "argv", ["setup_slack_video_channel.py"])

    with patch("setup_slack_video_channel.SlackClient") as MockSlack:
        inst = MockSlack.return_value
        inst.post_message = AsyncMock(return_value="ts-env")

        rc = asyncio.run(s.main())

        channel_used = inst.post_message.call_args.args[0]
        assert channel_used == "CENV456"

    assert rc == 0


def test_post_failure_returns_3(monkeypatch):
    """When post_message returns None (Slack error), main() returns 3."""
    _clear_env(monkeypatch)
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setattr(sys, "argv", ["setup_slack_video_channel.py"])

    with patch("setup_slack_video_channel.SlackClient") as MockSlack:
        inst = MockSlack.return_value
        inst.post_message = AsyncMock(return_value=None)

        rc = asyncio.run(s.main())

    assert rc == 3
