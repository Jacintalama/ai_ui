"""Discord plain-text (no slash) path: the bot reads ordinary messages in any
channel and acts only on real requests. Covers the pure extractors, the intake
hand-off, and the router's gateway handler."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from handlers import intent_router as ir
from handlers import video_intake as vi
from handlers import commands as cmd
from handlers.commands import CommandRouter, CommandContext


# --- pure helpers ---

def test_looks_like_chat_request():
    assert vi.looks_like_chat_request("build me a feedback form") is True
    assert vi.looks_like_chat_request("ok") is False
    assert vi.looks_like_chat_request("lol thanks") is False        # 2 words
    assert vi.looks_like_chat_request("!voice diag") is False
    assert vi.looks_like_chat_request("/aiui help") is False
    assert vi.looks_like_chat_request("https://example.com/page") is False


class _Author:
    def __init__(self):
        self.id = 100
        self.display_name = "Maria"
        self.name = "maria"


class _Chan:
    def __init__(self, parent_id=None):
        self.id = 5
        self.parent_id = parent_id
        self.parent = None
        self.name = "general"


class _Msg:
    def __init__(self, content, attachments=None, parent_id=None):
        self.content = content
        self.attachments = attachments or []
        self.author = _Author()
        self.channel = _Chan(parent_id)


def test_extract_chat_message_plain_text():
    info = vi.extract_chat_message(_Msg("build me a feedback form"))
    assert info["text"] == "build me a feedback form"
    assert info["channel_id"] == "5"
    assert info["is_thread"] is False
    assert info["author_name"] == "Maria"


def test_extract_chat_message_skips_url_attachment_short():
    assert vi.extract_chat_message(_Msg("https://x.com/abc")) is None
    assert vi.extract_chat_message(_Msg("hello")) is None
    assert vi.extract_chat_message(_Msg("a pic", attachments=[object()])) is None


def test_extract_chat_message_flags_thread():
    info = vi.extract_chat_message(_Msg("build me a feedback form", parent_id=9))
    assert info["is_thread"] is True


# --- intake hand-off ---

def _intake(router):
    discord = MagicMock()
    discord.post_channel_message = AsyncMock()
    return vi.VideoThreadIntake(router, discord)


async def test_handle_chat_non_thread_calls_router():
    router = MagicMock()
    router.handle_chat_message = AsyncMock()
    await _intake(router).handle_chat(
        author_id="1", author_name="m", channel_id="5", is_thread=False,
        text="build me a site")
    router.handle_chat_message.assert_awaited_once()


async def test_handle_chat_thread_skipped():
    router = MagicMock()
    router.handle_chat_message = AsyncMock()
    await _intake(router).handle_chat(
        author_id="1", author_name="m", channel_id="5", is_thread=True,
        text="build me a site")
    router.handle_chat_message.assert_not_awaited()


# --- router gateway handler ---

def _ctx(text):
    return CommandContext(
        user_id="1", user_name="m", channel_id="5", raw_text=text,
        subcommand=cmd.NATURAL, arguments=text, platform="discord",
        respond=AsyncMock(), metadata={}, respond_components=AsyncMock())


def _router():
    return CommandRouter(
        openwebui_client=MagicMock(), n8n_client=MagicMock(api_key=""),
        discord_user_email_map={}, tasks_client=MagicMock())


async def test_chat_message_flag_off(monkeypatch):
    monkeypatch.setattr(cmd.settings, "intent_router_enabled", False)
    r = _router()
    ctx = _ctx("build me a site")
    assert await r.handle_chat_message(ctx) is False
    ctx.respond_components.assert_not_awaited()


async def test_chat_message_build_posts_card(monkeypatch):
    monkeypatch.setattr(cmd.settings, "intent_router_enabled", True)
    monkeypatch.setattr(ir, "classify",
                        AsyncMock(return_value=ir.IntentResult("build_app", 0.9, "a site")))
    r = _router()
    ctx = _ctx("build me a site")
    assert await r.handle_chat_message(ctx) is True
    ctx.respond_components.assert_awaited_once()
    assert len(r._pending_intents) == 1


async def test_chat_message_question_is_silent(monkeypatch):
    monkeypatch.setattr(cmd.settings, "intent_router_enabled", True)
    monkeypatch.setattr(ir, "classify",
                        AsyncMock(return_value=ir.IntentResult("question", 0.9, "hi")))
    r = _router()
    ctx = _ctx("how is everyone doing today")
    assert await r.handle_chat_message(ctx) is False
    ctx.respond.assert_not_awaited()
    ctx.respond_components.assert_not_awaited()


async def test_chat_message_below_higher_bar_is_silent(monkeypatch):
    # 0.6 would pass the slash/Slack default but not the gateway's 0.75 bar.
    monkeypatch.setattr(cmd.settings, "intent_router_enabled", True)
    monkeypatch.setattr(ir, "classify",
                        AsyncMock(return_value=ir.IntentResult("build_app", 0.6, "x")))
    r = _router()
    ctx = _ctx("maybe build something idk")
    assert await r.handle_chat_message(ctx) is False
