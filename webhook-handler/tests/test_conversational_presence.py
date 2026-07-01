"""Conversational AI presence: the bot answers general chat, the private app
thread is a conversation (answer + refine), and a vague build asks 'what kind'."""
from unittest.mock import AsyncMock, MagicMock

from handlers import commands as cmd
from handlers import intent_router as ir
from handlers import video_intake as vi
from handlers.commands import CommandRouter, CommandContext, is_vague_build


def _router(tc=None):
    tc = tc or MagicMock()
    if not isinstance(getattr(tc, "resolve_link", None), AsyncMock):
        tc.resolve_link = AsyncMock(return_value=None)
    return CommandRouter(
        openwebui_client=MagicMock(), n8n_client=MagicMock(api_key=""),
        discord_user_email_map={"100": "a@x.com"}, tasks_client=tc)


def _ctx(text="hi there friend", platform="discord", user_id="100"):
    return CommandContext(
        user_id=user_id, user_name="t", channel_id="c", raw_text=text,
        subcommand="x", arguments=text, platform=platform,
        respond=AsyncMock(), metadata={}, respond_components=AsyncMock())


# --- is_vague_build ---

def test_is_vague_build():
    assert is_vague_build("a website") is True
    assert is_vague_build("build me a website") is True
    assert is_vague_build("an app") is True
    assert is_vague_build("a portfolio") is False
    assert is_vague_build("a flower shop site") is False
    assert is_vague_build("a todo list with dark mode") is False


# --- channels answer general chat ---

async def test_handle_chat_message_answers_non_actionable(monkeypatch):
    monkeypatch.setattr(cmd.settings, "intent_router_enabled", True)
    monkeypatch.setattr(ir, "classify",
                        AsyncMock(return_value=ir.IntentResult("question", 0.9, "hi")))
    r = _router()
    r._handle_ask = AsyncMock()
    assert await r.handle_chat_message(_ctx("are you there friend")) is True
    r._handle_ask.assert_awaited_once()


# --- builder-thread conversation ---

async def test_builder_thread_pending_statement_builds(monkeypatch):
    monkeypatch.setattr(ir, "classify",
                        AsyncMock(return_value=ir.IntentResult("build_app", 0.9, "x")))
    r = _router()
    r.run_panel_build = AsyncMock()
    r._pending_clarify["100"] = {"intent": "build_app", "text": "a website"}
    await r.handle_builder_thread_message(_ctx(), "a portfolio for a photographer")
    r.run_panel_build.assert_awaited_once()
    assert "100" not in r._pending_clarify


async def test_builder_thread_pending_question_keeps_pending(monkeypatch):
    monkeypatch.setattr(ir, "classify",
                        AsyncMock(return_value=ir.IntentResult("question", 0.9, "x")))
    r = _router()
    r.run_panel_build = AsyncMock()
    r._handle_ask = AsyncMock()
    r._pending_clarify["100"] = {"intent": "build_app", "text": "a website"}
    await r.handle_builder_thread_message(_ctx(), "are you there?")
    r._handle_ask.assert_awaited_once()
    r.run_panel_build.assert_not_awaited()
    assert "100" in r._pending_clarify


async def test_builder_thread_app_statement_enhances(monkeypatch):
    monkeypatch.setattr(ir, "classify",
                        AsyncMock(return_value=ir.IntentResult("build_app", 0.9, "x")))
    r = _router()
    r.run_panel_enhance = AsyncMock()
    r._user_app_slug["100"] = "port-1"
    await r.handle_builder_thread_message(_ctx(), "add a contact form")
    r.run_panel_enhance.assert_awaited_once()
    assert r.run_panel_enhance.call_args.args[1] == "port-1"
    assert r.run_panel_enhance.call_args.args[2] == "add a contact form"


async def test_builder_thread_app_question_answers(monkeypatch):
    monkeypatch.setattr(ir, "classify",
                        AsyncMock(return_value=ir.IntentResult("question", 0.9, "x")))
    r = _router()
    r.run_panel_enhance = AsyncMock()
    r._handle_ask = AsyncMock()
    r._user_app_slug["100"] = "port-1"
    await r.handle_builder_thread_message(_ctx(), "is it live yet")
    r._handle_ask.assert_awaited_once()
    r.run_panel_enhance.assert_not_awaited()


async def test_builder_thread_no_app_answers(monkeypatch):
    monkeypatch.setattr(ir, "classify",
                        AsyncMock(return_value=ir.IntentResult("question", 0.9, "x")))
    r = _router()
    r._handle_ask = AsyncMock()
    await r.handle_builder_thread_message(_ctx(), "hello there")
    r._handle_ask.assert_awaited_once()


# --- vague build asks first ---

async def test_run_confirmed_vague_build_asks():
    r = _router()
    r.run_panel_build = AsyncMock()
    tok = r.park_intent("build_app", "a website")
    ctx = _ctx()
    await r.run_confirmed_intent(ctx, tok)
    r.run_panel_build.assert_not_awaited()
    assert "100" in r._pending_clarify
    ctx.respond.assert_awaited_once()


async def test_run_confirmed_rich_build_builds():
    r = _router()
    r.run_panel_build = AsyncMock()
    tok = r.park_intent("build_app", "a portfolio for a photographer")
    await r.run_confirmed_intent(_ctx(), tok)
    r.run_panel_build.assert_awaited_once()


# --- _start_build remembers the slug ---

async def test_start_build_remembers_slug():
    tc = MagicMock()
    tc.list_templates = AsyncMock(return_value=[])
    tc.start_build = AsyncMock(return_value={"slug": "my-app-1", "task_id": "t1"})
    r = _router(tc)
    ctx = _ctx("a portfolio", user_id="100")
    await r._start_build(ctx, "a@x.com", None, "a portfolio")
    assert r._user_app_slug.get("100") == "my-app-1"


# --- extract_chat_message + handle_chat routing ---

class _Author:
    def __init__(self):
        self.id = 100
        self.display_name = "m"
        self.name = "m"


class _Chan:
    def __init__(self, name, parent_id=None):
        self.id = 5
        self.name = name
        self.parent_id = parent_id
        self.parent = None


class _Msg:
    def __init__(self, content, name="general", parent_id=None):
        self.content = content
        self.attachments = []
        self.author = _Author()
        self.channel = _Chan(name, parent_id)


def test_extract_carries_channel_name():
    info = vi.extract_chat_message(_Msg("build me a portfolio site", name="aiui-apps-m", parent_id=9))
    assert info["channel_name"] == "aiui-apps-m"
    assert info["is_thread"] is True


def _intake(router):
    discord = MagicMock()
    discord.post_channel_message = AsyncMock()
    return vi.VideoThreadIntake(router, discord)


async def test_handle_chat_routes_builder_thread():
    router = MagicMock()
    router.handle_builder_thread_message = AsyncMock()
    router.handle_chat_message = AsyncMock()
    await _intake(router).handle_chat(
        author_id="1", author_name="m", channel_id="5", is_thread=True,
        text="add a gallery", channel_name="aiui-apps-m")
    router.handle_builder_thread_message.assert_awaited_once()
    router.handle_chat_message.assert_not_awaited()


async def test_handle_chat_skips_schedules_thread():
    router = MagicMock()
    router.handle_builder_thread_message = AsyncMock()
    router.handle_chat_message = AsyncMock()
    await _intake(router).handle_chat(
        author_id="1", author_name="m", channel_id="5", is_thread=True,
        text="hi there friend", channel_name="schedules-m")
    router.handle_builder_thread_message.assert_not_awaited()
    router.handle_chat_message.assert_not_awaited()


async def test_handle_chat_channel_goes_to_router():
    router = MagicMock()
    router.handle_chat_message = AsyncMock()
    await _intake(router).handle_chat(
        author_id="1", author_name="m", channel_id="5", is_thread=False,
        text="are you there friend", channel_name="general")
    router.handle_chat_message.assert_awaited_once()
