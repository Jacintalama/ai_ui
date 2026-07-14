"""Tests for App Builder version-history + rollback surfaces on Discord and
Slack (Task 2). Builds on Task 1's TasksClient.list_app_versions /
rollback_app.

Discord: mirrors test_video_runners.py's CommandRouter fixture helpers.
Slack: mirrors test_slack_video_interactions.py / test_slack_app_walkthrough_video.py's
SlackInteractionsHandler fixture helpers.

Hermetic: no real network, no real Discord/Slack calls, no real sleeping.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from clients.tasks import TasksAPIError
from handlers.commands import CommandRouter, CommandContext
from handlers.app_builder_panel import (
    VERSIONS_PREFIX,
    VERPICK_PREFIX,
    ROLLBACK_OK_PREFIX,
    ROLLBACK_NO_PREFIX,
    STYLE_DANGER,
    build_project_menu_components,
    build_versions_select_components,
    build_rollback_confirm_components,
    is_versions_button, slug_from_versions_button,
    is_verpick_select, slug_from_verpick_select,
    is_rollback_ok, slug_sha_from_rollback_ok,
    is_rollback_no, slug_sha_from_rollback_no,
)
from handlers.slack_app_builder_panel import (
    VERSIONS_PREFIX as SLACK_VERSIONS_PREFIX,
    ROLLBACK_PREFIX,
    build_apps_list_blocks,
    build_versions_list_blocks,
    slug_sha_from_rollback_action,
)
from handlers.slack_interactions import SlackInteractionsHandler


_VERSIONS = [
    {"sha": "aaa1111111111111111111111111111111111", "short_sha": "aaa1111",
     "date": "2026-07-14T10:00:00Z", "author": "alice", "message": "Add pricing section",
     "is_current": True, "status": "ok"},
    {"sha": "bbb2222222222222222222222222222222222", "short_sha": "bbb2222",
     "date": "2026-07-13T09:00:00Z", "author": "alice", "message": "Initial build",
     "is_current": False, "status": "ok"},
    {"sha": "ccc3333333333333333333333333333333333", "short_sha": "ccc3333",
     "date": "2026-07-12T08:00:00Z", "author": "alice", "message": "Enhance: add footer",
     "is_current": False, "status": "error"},
]


# ---------------------------------------------------------------------------
# Pure builders (both platforms)
# ---------------------------------------------------------------------------

def _flat_buttons(rows):
    return [c for row in rows for c in row["components"]]


def test_discord_project_menu_has_versions_button():
    rows = build_project_menu_components(
        "shop", published=False, preview_url="https://x/tasks/preview-app/shop/")
    ids = [b.get("custom_id") for b in _flat_buttons(rows)]
    assert f"{VERSIONS_PREFIX}shop" in ids
    for row in rows:
        assert len(row["components"]) <= 5


def test_discord_versions_select_excludes_current_and_orders_newest_first():
    rows = build_versions_select_components("shop", _VERSIONS)
    assert len(rows) == 1
    options = rows[0]["components"][0]["options"]
    values = [o["value"] for o in options]
    assert "aaa1111" not in values  # current version omitted
    assert values == ["bbb2222", "ccc3333"]  # order preserved (newest first)


def test_discord_versions_select_empty_when_only_current():
    rows = build_versions_select_components("shop", [_VERSIONS[0]])
    assert rows == []


def test_discord_rollback_confirm_components_shape():
    rows = build_rollback_confirm_components("shop", "bbb2222")
    btns = _flat_buttons(rows)
    ids = [b["custom_id"] for b in btns]
    assert f"{ROLLBACK_OK_PREFIX}shop:bbb2222" in ids
    assert f"{ROLLBACK_NO_PREFIX}shop:bbb2222" in ids
    confirm = next(b for b in btns if b["custom_id"] == f"{ROLLBACK_OK_PREFIX}shop:bbb2222")
    assert confirm["style"] == STYLE_DANGER


def test_discord_versions_id_predicates_roundtrip():
    assert is_versions_button(f"{VERSIONS_PREFIX}shop")
    assert slug_from_versions_button(f"{VERSIONS_PREFIX}shop") == "shop"
    assert is_verpick_select(f"{VERPICK_PREFIX}shop")
    assert slug_from_verpick_select(f"{VERPICK_PREFIX}shop") == "shop"
    assert is_rollback_ok(f"{ROLLBACK_OK_PREFIX}shop:bbb2222")
    assert slug_sha_from_rollback_ok(f"{ROLLBACK_OK_PREFIX}shop:bbb2222") == ("shop", "bbb2222")
    assert is_rollback_no(f"{ROLLBACK_NO_PREFIX}shop:bbb2222")
    assert slug_sha_from_rollback_no(f"{ROLLBACK_NO_PREFIX}shop:bbb2222") == ("shop", "bbb2222")


def _slack_action_ids(blocks):
    return [e.get("action_id") for b in blocks if b.get("type") == "actions"
            for e in b.get("elements", []) if e.get("action_id")]


def test_slack_apps_list_row_has_versions_button():
    blocks = build_apps_list_blocks(
        [{"slug": "myapp", "name": "My App", "published": False}], owner="o@x.com")
    assert f"{SLACK_VERSIONS_PREFIX}myapp" in _slack_action_ids(blocks)


def test_slack_versions_list_current_has_no_rollback_control():
    blocks = build_versions_list_blocks("myapp", _VERSIONS)
    action_ids = _slack_action_ids(blocks)
    assert f"{ROLLBACK_PREFIX}myapp:aaa1111111111111111111111111111111111" not in action_ids
    assert f"{ROLLBACK_PREFIX}myapp:bbb2222222222222222222222222222222222" in action_ids
    assert f"{ROLLBACK_PREFIX}myapp:ccc3333333333333333333333333333333333" in action_ids
    # Rollback buttons carry a native confirm dialog.
    rollback_btn = next(
        e for b in blocks if b.get("type") == "actions" for e in b["elements"]
        if e.get("action_id", "").startswith(ROLLBACK_PREFIX)
    )
    assert "confirm" in rollback_btn


def test_slack_versions_list_empty():
    blocks = build_versions_list_blocks("myapp", [])
    assert len(blocks) == 1
    assert "myapp" in blocks[0]["text"]["text"]


def test_slack_rollback_action_id_parses_slug_and_sha():
    action_id = f"{ROLLBACK_PREFIX}myapp:bbb2222"
    assert slug_sha_from_rollback_action(action_id) == ("myapp", "bbb2222")


# ---------------------------------------------------------------------------
# Discord CommandRouter runners
# ---------------------------------------------------------------------------

def _ctx(*, respond_components=None, platform="discord"):
    return CommandContext(
        user_id="100", user_name="alice", channel_id="c", raw_text="",
        subcommand="", arguments="", platform=platform, respond=AsyncMock(),
        respond_components=respond_components,
    )


def _router(tasks_client, *, email="u@x.com"):
    r = CommandRouter.__new__(CommandRouter)
    r._tasks_client = tasks_client
    r._discord = None
    r._background_tasks = set()
    r._resolve_email_for_ctx = AsyncMock(return_value=email)
    r._respond_not_linked = AsyncMock()
    return r


@pytest.mark.asyncio
async def test_run_app_versions_posts_select_excluding_current():
    tc = MagicMock()
    tc.list_app_versions = AsyncMock(return_value=_VERSIONS)
    r = _router(tc)
    rc = AsyncMock()
    ctx = _ctx(respond_components=rc)
    await r.run_app_versions(ctx, "shop")
    tc.list_app_versions.assert_awaited_once_with("u@x.com", "shop")
    rc.assert_awaited_once()
    header, components = rc.await_args.args
    assert "aaa1111" in header  # current shown in the header
    options = components[0]["components"][0]["options"]
    values = [o["value"] for o in options]
    assert values == ["bbb2222", "ccc3333"]


@pytest.mark.asyncio
async def test_run_app_versions_no_history():
    tc = MagicMock()
    tc.list_app_versions = AsyncMock(return_value=[])
    r = _router(tc)
    ctx = _ctx(respond_components=AsyncMock())
    await r.run_app_versions(ctx, "shop")
    ctx.respond.assert_awaited_once()
    assert "No version history" in ctx.respond.await_args.args[0]


@pytest.mark.asyncio
async def test_run_app_versions_only_current_says_nothing_to_restore():
    tc = MagicMock()
    tc.list_app_versions = AsyncMock(return_value=[_VERSIONS[0]])
    r = _router(tc)
    ctx = _ctx(respond_components=AsyncMock())
    await r.run_app_versions(ctx, "shop")
    ctx.respond.assert_awaited_once()
    assert "No earlier versions" in ctx.respond.await_args.args[0]


@pytest.mark.asyncio
async def test_run_app_versions_unlinked():
    r = _router(MagicMock())
    r._resolve_email_for_ctx = AsyncMock(return_value=None)
    ctx = _ctx()
    await r.run_app_versions(ctx, "shop")
    r._respond_not_linked.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_app_versions_api_error():
    tc = MagicMock()
    tc.list_app_versions = AsyncMock(side_effect=TasksAPIError(404, "not found"))
    r = _router(tc)
    ctx = _ctx()
    await r.run_app_versions(ctx, "shop")
    ctx.respond.assert_awaited_once()
    assert "not yours" in ctx.respond.await_args.args[0]


@pytest.mark.asyncio
async def test_run_app_rollback_calls_client_with_email_slug_sha():
    tc = MagicMock()
    tc.rollback_app = AsyncMock(return_value={"ok": True, "noop": False})
    r = _router(tc)
    ctx = _ctx()
    await r.run_app_rollback(ctx, "shop", "bbb2222")
    tc.rollback_app.assert_awaited_once_with("u@x.com", "shop", "bbb2222")
    ctx.respond.assert_awaited_once()
    assert "bbb2222" in ctx.respond.await_args.args[0]


@pytest.mark.asyncio
async def test_run_app_rollback_noop():
    tc = MagicMock()
    tc.rollback_app = AsyncMock(return_value={"ok": True, "noop": True})
    r = _router(tc)
    ctx = _ctx()
    await r.run_app_rollback(ctx, "shop", "bbb2222")
    assert "nothing to change" in ctx.respond.await_args.args[0]


@pytest.mark.asyncio
async def test_run_app_rollback_409_is_clean():
    tc = MagicMock()
    tc.rollback_app = AsyncMock(side_effect=TasksAPIError(409, "An enhancement is already in progress"))
    r = _router(tc)
    ctx = _ctx()
    await r.run_app_rollback(ctx, "shop", "bbb2222")
    msg = ctx.respond.await_args.args[0]
    assert "still running" in msg
    assert "Traceback" not in msg


@pytest.mark.asyncio
async def test_run_app_rollback_unlinked():
    r = _router(MagicMock())
    r._resolve_email_for_ctx = AsyncMock(return_value=None)
    ctx = _ctx()
    await r.run_app_rollback(ctx, "shop", "bbb2222")
    r._respond_not_linked.assert_awaited_once()


# ---------------------------------------------------------------------------
# Slack SlackInteractionsHandler runners
# ---------------------------------------------------------------------------

def _slack_handler(router, slack=None):
    slack = slack or MagicMock()
    slack.open_modal = AsyncMock(return_value=True)
    slack.post_message = AsyncMock(return_value="ts")
    slack.post_ephemeral = AsyncMock(return_value=True)
    slack.open_dm = AsyncMock(return_value="D9")
    return SlackInteractionsHandler(slack_client=slack, command_router=router), slack


def _slack_router():
    router = MagicMock()
    router._background_tasks = set()
    router._resolve_email_for_ctx = AsyncMock(return_value="u@x.com")
    router._not_linked_text = MagicMock(return_value="not-linked msg")
    tc = MagicMock()
    tc.list_app_versions = AsyncMock(return_value=_VERSIONS)
    tc.rollback_app = AsyncMock(return_value={"ok": True, "noop": False})
    router._tasks_client = tc
    return router


def _block_actions_payload(action_id: str, user_id: str = "U1",
                           channel: str = "C-apps") -> dict:
    return {
        "type": "block_actions",
        "trigger_id": "trig-1",
        "user": {"id": user_id, "username": "tester"},
        "channel": {"id": channel},
        "team": {"id": "T1"},
        "actions": [{"action_id": action_id}],
    }


async def _run_spawned(router, payload):
    import asyncio
    handler, slack = _slack_handler(router)
    resp = await handler.handle_interaction(payload)
    assert resp == {}
    pending = list(router._background_tasks)
    if pending:
        await asyncio.gather(*pending)
    return handler, slack


@pytest.mark.asyncio
async def test_slack_versions_button_dms_list():
    router = _slack_router()
    handler, slack = await _run_spawned(
        router, _block_actions_payload(f"{SLACK_VERSIONS_PREFIX}myapp"))
    router._tasks_client.list_app_versions.assert_awaited_once_with("u@x.com", "myapp")
    slack.open_dm.assert_awaited_once_with("U1")
    post_call = slack.post_message.await_args
    assert post_call.kwargs.get("channel") == "D9"
    assert "blocks" in post_call.kwargs


@pytest.mark.asyncio
async def test_slack_rollback_button_calls_client_with_email_slug_sha():
    router = _slack_router()
    handler, slack = await _run_spawned(
        router, _block_actions_payload(f"{ROLLBACK_PREFIX}myapp:bbb2222"))
    router._tasks_client.rollback_app.assert_awaited_once_with("u@x.com", "myapp", "bbb2222")
    dm_texts = " ".join(
        c.kwargs.get("text", "") or ""
        for c in slack.post_message.call_args_list
        if c.kwargs.get("channel") == "D9"
    )
    assert "bbb2222" in dm_texts


@pytest.mark.asyncio
async def test_slack_rollback_409_is_clean():
    router = _slack_router()
    router._tasks_client.rollback_app = AsyncMock(
        side_effect=TasksAPIError(409, "An enhancement is already in progress"))
    handler, slack = await _run_spawned(
        router, _block_actions_payload(f"{ROLLBACK_PREFIX}myapp:bbb2222"))
    dm_texts = " ".join(
        c.kwargs.get("text", "") or ""
        for c in slack.post_message.call_args_list
        if c.kwargs.get("channel") == "D9"
    )
    assert "still running" in dm_texts
    assert "Traceback" not in dm_texts


@pytest.mark.asyncio
async def test_slack_versions_error_posts_clean_dm():
    router = _slack_router()
    router._tasks_client.list_app_versions = AsyncMock(side_effect=RuntimeError("boom"))
    handler, slack = await _run_spawned(
        router, _block_actions_payload(f"{SLACK_VERSIONS_PREFIX}myapp"))
    dm_texts = " ".join(
        c.kwargs.get("text", "") or ""
        for c in slack.post_message.call_args_list
        if c.kwargs.get("channel") == "D9"
    )
    assert "Traceback" not in dm_texts
    assert dm_texts.strip() != ""
