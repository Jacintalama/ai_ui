"""Discord answer-and-resume for a paused (needs_input) build.

The watcher arms a per-user pending-answer flag and posts the question into the
thread; the user's next thread reply resumes the build via /answer.
"""
import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock

from handlers.commands import CommandRouter, CommandContext


def _router(mapping, tasks_client):
    if not isinstance(getattr(tasks_client, "resolve_link", None), AsyncMock):
        tasks_client.resolve_link = AsyncMock(return_value=None)
    return CommandRouter(
        openwebui_client=MagicMock(),
        n8n_client=MagicMock(api_key=""),
        discord_user_email_map=mapping,
        tasks_client=tasks_client,
    )


def _thread_ctx(uid, captured):
    async def respond(msg):
        captured.append(msg)
    return CommandContext(
        user_id=uid, user_name="tester", channel_id="thread1",
        raw_text="app chat", subcommand="aiuibuilder", arguments="",
        platform="discord", respond=respond, metadata={}, notify_channel=respond,
    )


@pytest.mark.asyncio
async def test_watch_build_needs_input_arms_answer_and_posts_question():
    captured = []
    tc = MagicMock()
    tc.get_build_status = AsyncMock(return_value={
        "status": "needs_input", "slug": "s1",
        "question": "Which colour theme?", "error": "Which colour theme?",
    })
    router = _router({"u1": "a@x.com"}, tc)
    ctx = _thread_ctx("u1", captured)
    await router._watch_build(
        ctx, "a@x.com", "t1", "s1", display_name="S1", poll_seconds=0, max_polls=1,
    )
    # armed for the next thread reply
    assert router._pending_build_answer.get("u1", {}).get("task_id") == "t1"
    # the question is surfaced with a reply prompt (no more dead-end copy)
    assert any("Which colour theme?" in m for m in captured)
    assert any("Reply here" in m for m in captured)
    assert not any("Continue it in the App Builder" in m for m in captured)


@pytest.mark.asyncio
async def test_thread_reply_answers_paused_build_and_respawns_watcher(monkeypatch):
    captured = []
    tc = MagicMock()
    tc.answer_build = AsyncMock(return_value={"status": "running", "slug": "s1"})
    router = _router({"u1": "a@x.com"}, tc)
    router._pending_build_answer["u1"] = {"task_id": "t1", "slug": "s1", "display": "S1"}

    respawned = {}
    async def fake_watch(self, ctx, email, task_id, slug, **kw):
        respawned["args"] = (email, task_id, slug)
    monkeypatch.setattr(CommandRouter, "_watch_build", fake_watch)

    ctx = _thread_ctx("u1", captured)
    await router.handle_builder_thread_message(ctx, "use a dark teal theme")
    await asyncio.sleep(0)  # let the re-spawned watcher task start

    tc.answer_build.assert_awaited_once()
    args = tc.answer_build.call_args.args
    assert args[0] == "a@x.com"
    assert args[1] == "t1"
    assert args[2] == "use a dark teal theme"
    # flag cleared so a later message doesn't re-answer
    assert "u1" not in router._pending_build_answer
    assert any("continuing" in m.lower() for m in captured)
    # watcher re-armed so completion still lands in-thread
    assert respawned.get("args") == ("a@x.com", "t1", "s1")


@pytest.mark.asyncio
async def test_thread_reply_without_pending_answer_is_not_treated_as_answer(monkeypatch):
    # A normal thread message (no paused build) must NOT hit answer_build.
    captured = []
    tc = MagicMock()
    tc.answer_build = AsyncMock()
    router = _router({"u1": "a@x.com"}, tc)
    # no current app either -> falls through to _handle_ask
    monkeypatch.setattr(CommandRouter, "_handle_ask", AsyncMock())
    ctx = _thread_ctx("u1", captured)
    await router.handle_builder_thread_message(ctx, "hello there")
    tc.answer_build.assert_not_awaited()
