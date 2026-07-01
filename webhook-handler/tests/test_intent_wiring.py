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


async def test_flag_on_build_asks_clarify(monkeypatch):
    monkeypatch.setattr(cmd.settings, "intent_router_enabled", True)
    monkeypatch.setattr(
        ir, "classify",
        AsyncMock(return_value=ir.IntentResult("build_app", 0.9, "a form")))
    monkeypatch.setattr(
        ir, "clarify_question",
        AsyncMock(return_value="What kind of form, and who fills it out?"))
    r = _router()
    ctx = _ctx()
    await r._handle_natural(ctx)
    ctx.respond.assert_awaited_once()               # clarify question
    ctx.respond_components.assert_not_awaited()      # no card yet
    assert "100" in r._pending_clarify


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


async def test_run_confirmed_daily_briefing_creates():
    r = _router()
    r.create_daily_briefing = AsyncMock()
    tok = r.park_intent("daily_briefing", "brief me every morning")
    await r.run_confirmed_intent(_ctx(), tok)
    r.create_daily_briefing.assert_awaited_once()
    assert tok not in r._pending_intents


async def test_peek_intent_does_not_pop():
    r = _router()
    tok = r.park_intent("build_app", "a site")
    assert r.peek_intent(tok)["intent"] == "build_app"
    assert tok in r._pending_intents


async def test_run_confirmed_schedule_routes():
    r = _router()
    r.run_scheduled_from_chat = AsyncMock()
    tok = r.park_intent("schedule_task", "d", when="0 8 * * *", task="summarize")
    await r.run_confirmed_intent(_ctx(), tok)
    r.run_scheduled_from_chat.assert_awaited_once()


async def test_run_scheduled_from_chat_creates():
    r = _router()
    r.run_schedule_create = AsyncMock()
    await r.run_scheduled_from_chat(_ctx(), {
        "intent": "schedule_task", "detail": "d",
        "when": "0 8 * * *", "task": "summarize my emails"})
    r.run_schedule_create.assert_awaited_once()
    assert r.run_schedule_create.call_args.kwargs["prompt"] == "summarize my emails"


async def test_run_scheduled_from_chat_missing_when_asks():
    r = _router()
    r.run_schedule_create = AsyncMock()
    ctx = _ctx()
    await r.run_scheduled_from_chat(ctx, {
        "intent": "schedule_task", "detail": "d", "when": "", "task": "summarize"})
    r.run_schedule_create.assert_not_awaited()
    ctx.respond.assert_awaited_once()


# --- Slack message classify wiring (slack.py _try_intent) ---
from handlers import slack as slackmod


def _slack_handler():
    h = slackmod.SlackWebhookHandler(openwebui_client=MagicMock(),
                                     slack_client=MagicMock(), ai_model="m")
    h.slack.post_message = AsyncMock()
    h.router = MagicMock()
    return h


async def test_slack_try_intent_off_returns_false(monkeypatch):
    monkeypatch.setattr(slackmod.settings, "intent_router_enabled", False)
    h = _slack_handler()
    assert await h._try_intent("build me a form", "c", user_id="U1") is False


async def test_slack_try_intent_clarify_posts_question(monkeypatch):
    monkeypatch.setattr(slackmod.settings, "intent_router_enabled", True)
    h = _slack_handler()
    h.router.plan_chat_step = AsyncMock(return_value=cmd.ChatStep("clarify", "What kind?"))
    assert await h._try_intent("build me a form", "c", user_id="U1") is True
    h.slack.post_message.assert_awaited_once()


async def test_slack_try_intent_confirm_posts_blocks(monkeypatch):
    monkeypatch.setattr(slackmod.settings, "intent_router_enabled", True)
    h = _slack_handler()
    h.router.plan_chat_step = AsyncMock(
        return_value=cmd.ChatStep("confirm", "Here's what I've got: a form. Want me to go ahead?", "tok"))
    assert await h._try_intent("a feedback form", "c", user_id="U1") is True
    h.slack.post_message.assert_awaited_once()
    # posted with confirm blocks (not just text)
    assert h.slack.post_message.call_args.kwargs.get("blocks")


async def test_slack_try_intent_answer_returns_false(monkeypatch):
    monkeypatch.setattr(slackmod.settings, "intent_router_enabled", True)
    h = _slack_handler()
    h.router.plan_chat_step = AsyncMock(return_value=cmd.ChatStep("answer", ""))
    assert await h._try_intent("how are you", "c", user_id="U1") is False


async def test_run_schedule_create_passes_platform():
    r = _router()
    r._resolve_email_for_ctx = AsyncMock(return_value="a@x.com")
    r._tasks_client = MagicMock()
    r._tasks_client.create_schedule = AsyncMock()
    ctx = CommandContext(
        user_id="U1", user_name="t", channel_id="D1", raw_text="", subcommand="x",
        arguments="", platform="slack", respond=AsyncMock(), metadata={})
    await r.run_schedule_create(ctx, name="n", cron="0 8 * * *", prompt="p",
                                delivery_channel_id="D1")
    assert r._tasks_client.create_schedule.call_args.kwargs["delivery_platform"] == "slack"
