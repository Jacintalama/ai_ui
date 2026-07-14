"""Tests for pre-build clarifying question OPTION BUTTONS on web, Discord, and
Slack (Task 5). Consumes Task 4's structured `questions`/`answers` shapes on
BuildStatusResponse and TasksClient.answer_build.

Discord: mirrors test_video_runners.py / test_build_answer_resume_discord.py's
CommandRouter fixture helpers.
Slack: mirrors test_slack_video_interactions.py / test_app_versions_surfaces.py's
SlackInteractionsHandler fixture helpers.

Hermetic: no real network, no real Discord/Slack calls, no real sleeping.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from handlers.commands import CommandRouter, CommandContext
from handlers.app_builder_panel import (
    QOPT_PREFIX,
    QSKIP_PREFIX,
    build_question_option_components,
    build_question_skip_components,
    is_qopt_button,
    parse_qopt_button,
    is_qskip_button,
    task_id_from_qskip_button,
)
from handlers.slack_app_builder_panel import (
    build_question_option_blocks,
    build_question_skip_blocks,
)
from handlers.slack_interactions import SlackInteractionsHandler


_QUESTIONS = [
    {"q": "Which color theme?", "options": ["Dark", "Light", "Auto"]},
    {"q": "Include a contact form?", "options": ["Yes", "No"]},
]


# ---------------------------------------------------------------------------
# Pure builders (Discord)
# ---------------------------------------------------------------------------

def _flat_buttons(rows):
    return [c for row in rows for c in row["components"]]


def test_discord_question_option_components_shape():
    rows = build_question_option_components("t1", 0, ["Dark", "Light", "Auto"])
    assert len(rows) == 1
    btns = rows[0]["components"]
    ids = [b["custom_id"] for b in btns]
    assert ids == [f"{QOPT_PREFIX}t1:0:0", f"{QOPT_PREFIX}t1:0:1", f"{QOPT_PREFIX}t1:0:2"]
    labels = [b["label"] for b in btns]
    assert labels == ["Dark", "Light", "Auto"]


def test_discord_question_skip_components_shape():
    rows = build_question_skip_components("t1")
    btns = _flat_buttons(rows)
    assert len(btns) == 1
    assert btns[0]["custom_id"] == f"{QSKIP_PREFIX}t1"


def test_discord_qopt_predicates_roundtrip():
    cid = f"{QOPT_PREFIX}t1:1:2"
    assert is_qopt_button(cid)
    assert parse_qopt_button(cid) == ("t1", 1, 2)
    assert not is_qopt_button(f"{QSKIP_PREFIX}t1")


def test_discord_qopt_malformed_raises():
    with pytest.raises(ValueError):
        parse_qopt_button(f"{QOPT_PREFIX}t1:x:2")
    with pytest.raises(ValueError):
        parse_qopt_button(f"{QOPT_PREFIX}t1:1")
    with pytest.raises(ValueError):
        parse_qopt_button(f"{QOPT_PREFIX}:0:0")


def test_discord_qskip_predicates_roundtrip():
    cid = f"{QSKIP_PREFIX}t1"
    assert is_qskip_button(cid)
    assert task_id_from_qskip_button(cid) == "t1"
    assert not is_qskip_button(f"{QOPT_PREFIX}t1:0:0")


# ---------------------------------------------------------------------------
# Pure builders (Slack)
# ---------------------------------------------------------------------------

def _slack_action_ids(blocks):
    return [e.get("action_id") for b in blocks if b.get("type") == "actions"
            for e in b.get("elements", []) if e.get("action_id")]


def test_slack_question_option_blocks_shape():
    blocks = build_question_option_blocks("t1", 0, ["Dark", "Light"])
    ids = _slack_action_ids(blocks)
    assert ids == [f"{QOPT_PREFIX}t1:0:0", f"{QOPT_PREFIX}t1:0:1"]


def test_slack_question_skip_blocks_shape():
    blocks = build_question_skip_blocks("t1")
    ids = _slack_action_ids(blocks)
    assert ids == [f"{QSKIP_PREFIX}t1"]


# ---------------------------------------------------------------------------
# CommandRouter: _watch_build renders structured questions (shared code path
# for both Discord and Slack — platform only changes components vs. blocks)
# ---------------------------------------------------------------------------

def _router(mapping, tasks_client):
    if not isinstance(getattr(tasks_client, "resolve_link", None), AsyncMock):
        tasks_client.resolve_link = AsyncMock(return_value=None)
    return CommandRouter(
        openwebui_client=MagicMock(),
        n8n_client=MagicMock(api_key=""),
        discord_user_email_map=mapping,
        tasks_client=tasks_client,
    )


def _thread_ctx(uid, *, notify_channel_msg=None, platform="discord"):
    captured = []

    async def respond(msg):
        captured.append(msg)

    ctx = CommandContext(
        user_id=uid, user_name="tester", channel_id="thread1",
        raw_text="app chat", subcommand="aiuibuilder", arguments="",
        platform=platform, respond=respond, metadata={}, notify_channel=respond,
        notify_channel_msg=notify_channel_msg,
    )
    return ctx, captured


@pytest.mark.asyncio
async def test_watch_build_structured_questions_posts_one_message_per_question_plus_skip():
    tc = MagicMock()
    tc.get_build_status = AsyncMock(return_value={
        "status": "needs_input", "slug": "s1", "questions": _QUESTIONS,
    })
    router = _router({"u1": "a@x.com"}, tc)
    posted = []

    async def notify_channel_msg(msg):
        posted.append(msg)

    ctx, _ = _thread_ctx("u1", notify_channel_msg=notify_channel_msg)
    await router._watch_build(
        ctx, "a@x.com", "t1", "s1", display_name="S1", poll_seconds=0, max_polls=1,
    )
    # one message per question + one skip message
    assert len(posted) == len(_QUESTIONS) + 1
    assert "Which color theme?" in posted[0]["content"]
    assert "components" in posted[0]  # discord shape
    skip_msg = posted[-1]
    skip_ids = [b["custom_id"] for row in skip_msg["components"] for b in row["components"]]
    assert skip_ids == [f"{QSKIP_PREFIX}t1"]
    # armed for qopt clicks, keyed by task_id
    assert "t1" in router._pending_build_questions
    assert router._pending_build_questions["t1"]["questions"] == _QUESTIONS
    # the free-text flow was NOT armed
    assert "u1" not in router._pending_build_answer


@pytest.mark.asyncio
async def test_watch_build_structured_questions_slack_uses_blocks_not_components():
    tc = MagicMock()
    tc.get_build_status = AsyncMock(return_value={
        "status": "needs_input", "slug": "s1", "questions": _QUESTIONS,
    })
    router = _router({"u1": "a@x.com"}, tc)
    posted = []

    async def notify_channel_msg(msg):
        posted.append(msg)

    ctx, _ = _thread_ctx("u1", notify_channel_msg=notify_channel_msg, platform="slack")
    await router._watch_build(
        ctx, "a@x.com", "t1", "s1", display_name="S1", poll_seconds=0, max_polls=1,
    )
    assert len(posted) == len(_QUESTIONS) + 1
    assert "blocks" in posted[0]
    assert "components" not in posted[0]


@pytest.mark.asyncio
async def test_watch_build_structured_questions_without_notify_channel_msg_falls_back():
    """No surface for posting buttons wired -> degrade to the Jul-13 free-text
    armed-answer flow rather than stranding the user."""
    tc = MagicMock()
    tc.get_build_status = AsyncMock(return_value={
        "status": "needs_input", "slug": "s1", "questions": _QUESTIONS,
        "question": None, "error": None,
    })
    router = _router({"u1": "a@x.com"}, tc)
    ctx, captured = _thread_ctx("u1", notify_channel_msg=None)
    await router._watch_build(
        ctx, "a@x.com", "t1", "s1", display_name="S1", poll_seconds=0, max_polls=1,
    )
    assert "t1" not in router._pending_build_questions
    assert router._pending_build_answer.get("u1", {}).get("task_id") == "t1"
    assert any("Reply here" in m for m in captured)


@pytest.mark.asyncio
async def test_watch_build_free_text_only_question_unaffected_by_questions_support():
    """Jul-13 path: questions=None, question=str -> unchanged, no option
    buttons, even when notify_channel_msg IS available."""
    tc = MagicMock()
    tc.get_build_status = AsyncMock(return_value={
        "status": "needs_input", "slug": "s1",
        "question": "Which colour theme?", "error": "Which colour theme?",
        "questions": None,
    })
    router = _router({"u1": "a@x.com"}, tc)
    posted = []

    async def notify_channel_msg(msg):
        posted.append(msg)

    ctx, captured = _thread_ctx("u1", notify_channel_msg=notify_channel_msg)
    await router._watch_build(
        ctx, "a@x.com", "t1", "s1", display_name="S1", poll_seconds=0, max_polls=1,
    )
    assert posted == []  # no button messages posted
    assert "t1" not in router._pending_build_questions
    assert router._pending_build_answer.get("u1", {}).get("task_id") == "t1"
    assert any("Which colour theme?" in m for m in captured)


# ---------------------------------------------------------------------------
# CommandRouter: qopt/qskip answer handling
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_build_question_option_partial_answer_does_not_submit():
    tc = MagicMock()
    tc.answer_build = AsyncMock()
    router = _router({"u1": "a@x.com"}, tc)
    router._pending_build_questions["t1"] = {
        "questions": _QUESTIONS, "answers": {}, "uid": "u1", "slug": "s1", "display": "S1",
    }
    ctx, captured = _thread_ctx("u1")
    await router.run_build_question_option(ctx, "t1", 0, 1)  # "Light"
    tc.answer_build.assert_not_awaited()
    assert router._pending_build_questions["t1"]["answers"]["0"] == "Light"
    assert any("Light" in m for m in captured)


@pytest.mark.asyncio
async def test_run_build_question_option_last_answer_submits_once_in_order():
    tc = MagicMock()
    tc.answer_build = AsyncMock(return_value={"status": "running", "slug": "s1"})
    router = _router({"u1": "a@x.com"}, tc)
    router._pending_build_questions["t1"] = {
        "questions": _QUESTIONS, "answers": {}, "uid": "u1", "slug": "s1", "display": "S1",
    }

    respawned = {}

    async def fake_watch(self, ctx, email, task_id, slug, **kw):
        respawned["args"] = (email, task_id, slug)

    with patch.object(CommandRouter, "_watch_build", fake_watch):
        ctx, captured = _thread_ctx("u1")
        await router.run_build_question_option(ctx, "t1", 0, 0)  # "Dark"
        await router.run_build_question_option(ctx, "t1", 1, 1)  # "No"
        await asyncio.sleep(0)  # let the re-spawned watcher task start

    tc.answer_build.assert_awaited_once()
    args, kwargs = tc.answer_build.call_args
    assert args[0] == "a@x.com"
    assert args[1] == "t1"
    assert kwargs.get("answers") == ["Dark", "No"]  # ordered by question index
    # cleared so a stray extra click can't re-submit
    assert "t1" not in router._pending_build_questions
    assert respawned.get("args") == ("a@x.com", "t1", "s1")
    assert any("continuing" in m.lower() or "building" in m.lower() for m in captured)


@pytest.mark.asyncio
async def test_run_build_question_option_answering_out_of_order_still_orders_by_question_index():
    tc = MagicMock()
    tc.answer_build = AsyncMock(return_value={"status": "running", "slug": "s1"})
    router = _router({"u1": "a@x.com"}, tc)
    router._pending_build_questions["t1"] = {
        "questions": _QUESTIONS, "answers": {}, "uid": "u1", "slug": "s1", "display": "S1",
    }

    async def fake_watch(self, ctx, email, task_id, slug, **kw):
        return None

    with patch.object(CommandRouter, "_watch_build", fake_watch):
        ctx, _ = _thread_ctx("u1")
        # answer question 1 (index 1) before question 0
        await router.run_build_question_option(ctx, "t1", 1, 0)  # "Yes"
        await router.run_build_question_option(ctx, "t1", 0, 2)  # "Auto"
        await asyncio.sleep(0)

    tc.answer_build.assert_awaited_once()
    _, kwargs = tc.answer_build.call_args
    assert kwargs.get("answers") == ["Auto", "Yes"]


@pytest.mark.asyncio
async def test_run_build_question_option_expired_entry_is_graceful():
    tc = MagicMock()
    router = _router({"u1": "a@x.com"}, tc)
    ctx, captured = _thread_ctx("u1")
    await router.run_build_question_option(ctx, "gone", 0, 0)
    assert any("expired" in m.lower() for m in captured)


@pytest.mark.asyncio
async def test_run_build_question_skip_calls_answer_build_with_skip_sentinel():
    tc = MagicMock()
    tc.answer_build = AsyncMock(return_value={"status": "running", "slug": "s1"})
    router = _router({"u1": "a@x.com"}, tc)
    router._pending_build_questions["t1"] = {
        "questions": _QUESTIONS, "answers": {"0": "Dark"},
        "uid": "u1", "slug": "s1", "display": "S1",
    }
    respawned = {}

    async def fake_watch(self, ctx, email, task_id, slug, **kw):
        respawned["args"] = (email, task_id, slug)

    with patch.object(CommandRouter, "_watch_build", fake_watch):
        ctx, captured = _thread_ctx("u1")
        await router.run_build_question_skip(ctx, "t1")
        await asyncio.sleep(0)

    tc.answer_build.assert_awaited_once_with("a@x.com", "t1", answer="__skip__")
    assert "t1" not in router._pending_build_questions
    assert respawned.get("args") == ("a@x.com", "t1", "s1")


@pytest.mark.asyncio
async def test_run_build_question_skip_unlinked_user_is_told_to_link():
    tc = MagicMock()
    tc.answer_build = AsyncMock()
    router = _router({}, tc)  # "u1" not in the map -> not linked
    router._pending_build_questions["t1"] = {
        "questions": _QUESTIONS, "answers": {}, "uid": "u1", "slug": "s1", "display": "S1",
    }
    ctx, captured = _thread_ctx("u1")
    await router.run_build_question_skip(ctx, "t1")
    tc.answer_build.assert_not_awaited()


# ---------------------------------------------------------------------------
# Slack SlackInteractionsHandler dispatch: qopt/qskip route to the router
# ---------------------------------------------------------------------------

def _slack_router():
    router = MagicMock()
    router._background_tasks = set()
    router.run_build_question_option = AsyncMock()
    router.run_build_question_skip = AsyncMock()
    return router


def _slack_handler(router, slack=None):
    slack = slack or MagicMock()
    slack.open_modal = AsyncMock(return_value=True)
    slack.post_message = AsyncMock(return_value="ts")
    slack.post_ephemeral = AsyncMock(return_value=True)
    slack.open_dm = AsyncMock(return_value="D9")
    return SlackInteractionsHandler(slack_client=slack, command_router=router), slack


def _block_actions_payload(action_id: str, user_id: str = "U1",
                            channel: str = "D9") -> dict:
    return {
        "type": "block_actions",
        "trigger_id": "trig-1",
        "user": {"id": user_id, "username": "tester"},
        "channel": {"id": channel},
        "team": {"id": "T1"},
        "actions": [{"action_id": action_id}],
    }


async def _run_spawned(router, payload):
    handler, slack = _slack_handler(router)
    resp = await handler.handle_interaction(payload)
    assert resp == {}
    pending = list(router._background_tasks)
    if pending:
        await asyncio.gather(*pending)
    return handler, slack


@pytest.mark.asyncio
async def test_slack_qopt_button_dispatches_to_router_with_parsed_indices():
    router = _slack_router()
    await _run_spawned(router, _block_actions_payload(f"{QOPT_PREFIX}t1:0:1"))
    router.run_build_question_option.assert_awaited_once()
    args = router.run_build_question_option.await_args.args
    assert args[1:] == ("t1", 0, 1)


@pytest.mark.asyncio
async def test_slack_qskip_button_dispatches_to_router_with_task_id():
    router = _slack_router()
    await _run_spawned(router, _block_actions_payload(f"{QSKIP_PREFIX}t1"))
    router.run_build_question_skip.assert_awaited_once()
    args = router.run_build_question_skip.await_args.args
    assert args[1:] == ("t1",)


@pytest.mark.asyncio
async def test_slack_qopt_malformed_action_id_is_ignored_not_500():
    router = _slack_router()
    handler, slack = _slack_handler(router)
    resp = await handler.handle_interaction(
        _block_actions_payload(f"{QOPT_PREFIX}t1:notanint:0"))
    assert resp == {}
    router.run_build_question_option.assert_not_awaited()
