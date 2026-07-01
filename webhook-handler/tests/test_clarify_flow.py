"""The plan_chat_step state machine: fresh executable -> clarify (pending stored);
pending statement -> recap+confirm (token parked); pending question -> answer
(pending kept); fresh question -> answer; fresh suggest -> suggest; daily_briefing
-> confirm without a clarify."""
from unittest.mock import AsyncMock, MagicMock

from handlers import commands as cmd
from handlers import intent_router as ir
from handlers.commands import CommandRouter, ChatStep, CommandContext


def _router():
    return CommandRouter(
        openwebui_client=MagicMock(), n8n_client=MagicMock(api_key=""),
        discord_user_email_map={}, tasks_client=MagicMock())


async def test_fresh_build_asks_clarify(monkeypatch):
    monkeypatch.setattr(ir, "classify",
                        AsyncMock(return_value=ir.IntentResult("build_app", 0.9, "a website")))
    monkeypatch.setattr(ir, "clarify_question",
                        AsyncMock(return_value="What kind of site, and who's it for?"))
    r = _router()
    step = await r.plan_chat_step("u1", "build me a website", threshold=0.6)
    assert step.kind == "clarify"
    assert step.text == "What kind of site, and who's it for?"
    assert r._pending_clarify["u1"] == {"intent": "build_app", "text": "build me a website"}
    assert not r._pending_intents  # nothing parked until the recap


async def test_fresh_build_below_bar_answers(monkeypatch):
    monkeypatch.setattr(ir, "classify",
                        AsyncMock(return_value=ir.IntentResult("build_app", 0.6, "x")))
    r = _router()
    step = await r.plan_chat_step("u1", "maybe build idk", threshold=0.75)
    assert step.kind == "answer"
    assert "u1" not in r._pending_clarify


async def test_pending_statement_recaps_and_parks(monkeypatch):
    monkeypatch.setattr(ir, "classify",
                        AsyncMock(return_value=ir.IntentResult("build_app", 0.9, "a portfolio for a photographer")))
    r = _router()
    r._pending_clarify["u1"] = {"intent": "build_app", "text": "build me a website"}
    step = await r.plan_chat_step("u1", "a portfolio for a photographer", threshold=0.6)
    assert step.kind == "confirm"
    assert step.token
    assert "u1" not in r._pending_clarify
    assert r._pending_intents[step.token]["intent"] == "build_app"
    assert "photographer" in step.text  # recap shows the detail


async def test_pending_question_keeps_pending(monkeypatch):
    monkeypatch.setattr(ir, "classify",
                        AsyncMock(return_value=ir.IntentResult("question", 0.9, "huh")))
    r = _router()
    r._pending_clarify["u1"] = {"intent": "build_app", "text": "build me a website"}
    step = await r.plan_chat_step("u1", "wait, what can you even do?", threshold=0.6)
    assert step.kind == "answer"
    assert "u1" in r._pending_clarify  # still waiting for the description


async def test_pending_schedule_extracts_when_task(monkeypatch):
    calls = {"n": 0}

    async def fake_classify(text, ow, model):
        calls["n"] += 1
        if calls["n"] == 1:  # the reply, checked for "is it a question"
            return ir.IntentResult("schedule_task", 0.9, "at 8am")
        return ir.IntentResult("schedule_task", 0.9, "summarize my emails",
                               when="every weekday at 8am", task="summarize my emails")

    monkeypatch.setattr(ir, "classify", fake_classify)
    r = _router()
    r._pending_clarify["u1"] = {"intent": "schedule_task", "text": "remind me about email"}
    step = await r.plan_chat_step("u1", "every weekday at 8am", threshold=0.6)
    assert step.kind == "confirm"
    data = r._pending_intents[step.token]
    assert data["when"] == "every weekday at 8am"
    assert data["task"] == "summarize my emails"
    assert "every weekday at 8am" in step.text


async def test_fresh_question_answers(monkeypatch):
    monkeypatch.setattr(ir, "classify",
                        AsyncMock(return_value=ir.IntentResult("question", 0.9, "hi")))
    r = _router()
    step = await r.plan_chat_step("u1", "how is everyone doing today", threshold=0.6)
    assert step.kind == "answer"


async def test_fresh_suggest(monkeypatch):
    monkeypatch.setattr(ir, "classify",
                        AsyncMock(return_value=ir.IntentResult("find_jobs", 0.9, "find me a job")))
    r = _router()
    step = await r.plan_chat_step("u1", "help me find a job", threshold=0.6)
    assert step.kind == "suggest"
    assert not r._pending_clarify


async def test_daily_briefing_confirms_without_clarify(monkeypatch):
    monkeypatch.setattr(ir, "classify",
                        AsyncMock(return_value=ir.IntentResult("daily_briefing", 0.9, "brief me")))
    clarify = AsyncMock()
    monkeypatch.setattr(ir, "clarify_question", clarify)
    r = _router()
    step = await r.plan_chat_step("u1", "brief me every morning", threshold=0.6)
    assert step.kind == "confirm"
    assert step.token
    clarify.assert_not_awaited()
    assert "u1" not in r._pending_clarify


def test_ask_prompt_mentions_build_and_schedule():
    r = _router()
    prompt = r._build_ask_system_prompt()
    low = prompt.lower()
    assert "build" in low and "schedule" in low and "briefing" in low
