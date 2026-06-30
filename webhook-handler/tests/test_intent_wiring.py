"""Wiring tests for the intent router: the Discord/Slack-slash _handle_natural
seam and the router's pending-intent run/cancel logic. The brain itself is
tested in test_intent_router.py; here we check the routing + flag behavior."""
from unittest.mock import AsyncMock, MagicMock

from handlers import commands as cmd
from handlers import intent_router as ir
from handlers.commands import CommandRouter, CommandContext


def _router():
    return CommandRouter(
        openwebui_client=MagicMock(),
        n8n_client=MagicMock(api_key=""),
        discord_user_email_map={},
        tasks_client=MagicMock(),
    )


def _ctx(text="build me a form", with_components=True):
    return CommandContext(
        user_id="100", user_name="t", channel_id="c", raw_text=text,
        subcommand=cmd.NATURAL, arguments=text, platform="discord",
        respond=AsyncMock(), metadata={},
        respond_components=AsyncMock() if with_components else None,
    )


async def test_flag_off_falls_back_to_ask(monkeypatch):
    monkeypatch.setattr(cmd.settings, "intent_router_enabled", False)
    r = _router()
    r._handle_ask = AsyncMock()
    await r._handle_natural(_ctx())
    r._handle_ask.assert_awaited_once()


async def test_flag_on_build_shows_confirm_card(monkeypatch):
    monkeypatch.setattr(cmd.settings, "intent_router_enabled", True)
    monkeypatch.setattr(
        ir, "classify",
        AsyncMock(return_value=ir.IntentResult("build_app", 0.9, "a form")))
    r = _router()
    ctx = _ctx()
    await r._handle_natural(ctx)
    ctx.respond_components.assert_awaited_once()
    assert len(r._pending_intents) == 1


async def test_flag_on_question_answers(monkeypatch):
    monkeypatch.setattr(cmd.settings, "intent_router_enabled", True)
    monkeypatch.setattr(
        ir, "classify",
        AsyncMock(return_value=ir.IntentResult("question", 0.9, "hi")))
    r = _router()
    r._handle_ask = AsyncMock()
    await r._handle_natural(_ctx(text="how are you"))
    r._handle_ask.assert_awaited_once()


async def test_flag_on_video_suggests(monkeypatch):
    monkeypatch.setattr(cmd.settings, "intent_router_enabled", True)
    monkeypatch.setattr(
        ir, "classify",
        AsyncMock(return_value=ir.IntentResult("make_video", 0.9, "x")))
    r = _router()
    ctx = _ctx()
    await r._handle_natural(ctx)
    ctx.respond.assert_awaited_once()
    assert len(r._pending_intents) == 0  # suggest parks nothing


async def test_run_confirmed_build_calls_run_panel_build():
    r = _router()
    r.run_panel_build = AsyncMock()
    tok = r.park_intent("build_app", "a form")
    await r.run_confirmed_intent(_ctx(), tok)
    r.run_panel_build.assert_awaited_once()
    assert tok not in r._pending_intents


async def test_run_confirmed_expired_token_is_graceful():
    r = _router()
    ctx = _ctx()
    await r.run_confirmed_intent(ctx, "nope")
    ctx.respond.assert_awaited_once()


async def test_answer_intent_uses_parked_detail():
    r = _router()
    r._handle_ask = AsyncMock()
    tok = r.park_intent("build_app", "a portfolio site")
    ctx = _ctx(text="orig")
    await r.answer_intent(ctx, tok)
    r._handle_ask.assert_awaited_once()
    assert ctx.arguments == "a portfolio site"
    assert tok not in r._pending_intents
