import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from handlers.discord_commands import DiscordCommandHandler
from handlers.app_builder_panel import (
    PANEL_NEW_ID, PANEL_MYAPPS_ID, TEMPLATE_SELECT_ID, APP_SELECT_ID,
    LINK_START_ID,
)


def _payload(custom_id, user_id="U1"):
    return {"type": 3, "data": {"custom_id": custom_id},
            "member": {"user": {"id": user_id, "username": "maya"}},
            "channel_id": "C1", "token": "tok"}


@pytest.mark.asyncio
async def test_build_new_posts_template_picker_to_thread():
    discord = MagicMock()
    discord.create_private_thread = AsyncMock(return_value="THREAD1")
    discord.add_thread_member = AsyncMock()
    discord.post_channel_message = AsyncMock()
    discord.edit_original = AsyncMock()
    router = MagicMock()
    router.get_user_builder_thread = AsyncMock(return_value=None)
    router.set_user_builder_thread = AsyncMock()
    router._resolve_email_auto = AsyncMock(return_value="maya@x.com")
    router._tasks_client = MagicMock()
    router._tasks_client.list_templates = AsyncMock(
        return_value=[{"key": "portfolio", "label": "Portfolio"}])
    h = DiscordCommandHandler(discord, router)
    resp = await h.handle_interaction(_payload(PANEL_NEW_ID))
    await asyncio.sleep(0)
    args = discord.post_channel_message.await_args
    assert args.args[0] == "THREAD1"
    comps = args.kwargs.get("components") or (args.args[2] if len(args.args) > 2 else [])
    flat = [c for row in comps for c in row["components"]]
    assert any(c.get("custom_id") == TEMPLATE_SELECT_ID for c in flat)


@pytest.mark.asyncio
async def test_build_new_returns_deferred_ephemeral():
    discord = MagicMock()
    discord.create_private_thread = AsyncMock(return_value="THREAD1")
    discord.add_thread_member = AsyncMock()
    discord.post_channel_message = AsyncMock()
    discord.edit_original = AsyncMock()
    router = MagicMock()
    router.get_user_thread = AsyncMock(return_value=None)
    router.set_user_thread = AsyncMock()
    router._resolve_email_auto = AsyncMock(return_value="maya@x.com")
    router._tasks_client = MagicMock()
    router._tasks_client.list_templates = AsyncMock(return_value=[])
    h = DiscordCommandHandler(discord, router)
    resp = await h.handle_interaction(_payload(PANEL_NEW_ID))
    assert resp["type"] == 5
    assert resp["data"]["flags"] == 64


@pytest.mark.asyncio
async def test_my_apps_posts_apps_dropdown_to_thread():
    discord = MagicMock(); discord.create_private_thread = AsyncMock(return_value="T1")
    discord.add_thread_member = AsyncMock(); discord.post_channel_message = AsyncMock()
    discord.edit_original = AsyncMock()
    router = MagicMock()
    router.get_user_builder_thread = AsyncMock(return_value="T1"); router.set_user_builder_thread = AsyncMock()
    router._resolve_email = AsyncMock(return_value="maya@x.com")
    router._tasks_client = MagicMock()
    router._tasks_client.list_projects = AsyncMock(return_value=[{"slug": "shop-1", "name": "Shop"}])
    h = DiscordCommandHandler(discord, router)
    await h.handle_interaction(_payload(PANEL_MYAPPS_ID)); await asyncio.sleep(0)
    assert discord.post_channel_message.await_args.args[0] == "T1"
    args = discord.post_channel_message.await_args
    comps = args.kwargs.get("components") or (args.args[2] if len(args.args) > 2 else [])
    flat = [c for row in comps for c in row["components"]]
    assert any(c.get("custom_id") == APP_SELECT_ID for c in flat)


@pytest.mark.asyncio
async def test_my_apps_empty_state():
    discord = MagicMock(); discord.create_private_thread = AsyncMock(return_value="T1")
    discord.add_thread_member = AsyncMock(); discord.post_channel_message = AsyncMock()
    discord.edit_original = AsyncMock()
    router = MagicMock()
    router.get_user_builder_thread = AsyncMock(return_value="T1"); router.set_user_builder_thread = AsyncMock()
    router._resolve_email = AsyncMock(return_value="maya@x.com")
    router._tasks_client = MagicMock(); router._tasks_client.list_projects = AsyncMock(return_value=[])
    h = DiscordCommandHandler(discord, router)
    await h.handle_interaction(_payload(PANEL_MYAPPS_ID)); await asyncio.sleep(0)
    posted = " ".join(str(c.args) for c in discord.post_channel_message.await_args_list)
    assert "No apps yet" in posted


@pytest.mark.asyncio
async def test_my_apps_not_linked():
    discord = MagicMock(); discord.create_private_thread = AsyncMock(return_value="T1")
    discord.add_thread_member = AsyncMock(); discord.post_channel_message = AsyncMock()
    discord.edit_original = AsyncMock()
    router = MagicMock()
    router.get_user_thread = AsyncMock(return_value="T1"); router.set_user_thread = AsyncMock()
    router._resolve_email = AsyncMock(return_value=None)
    router._tasks_client = MagicMock(); router._tasks_client.list_projects = AsyncMock(return_value=[])
    h = DiscordCommandHandler(discord, router)
    await h.handle_interaction(_payload(PANEL_MYAPPS_ID)); await asyncio.sleep(0)
    assert discord.post_channel_message.await_count == 0
    # New unified not-linked card: friendly self-service text + Link button row,
    # no person's name, and we never reach the tasks API.
    kwargs = discord.edit_original.await_args.kwargs
    content = kwargs.get("content", "")
    assert "Link my account" in content
    assert "Lukas" not in content and "isn't linked" not in content
    components = kwargs.get("components") or []
    ids = [c.get("custom_id") for row in components for c in row["components"]]
    assert LINK_START_ID in ids
    router._tasks_client.list_projects.assert_not_awaited()


# ---------------------------------------------------------------------------
# Thread routing: App Builder uses the BUILDER thread; cron uses SCHEDULES
# ---------------------------------------------------------------------------
from handlers.app_builder_panel import SCHED_OPEN_ID


def _router_with_both_thread_slots():
    """Router mock wired with BOTH thread storage slots so a test can assert
    which one a handler reaches for."""
    router = MagicMock()
    router.get_user_thread = AsyncMock(return_value=None)
    router.set_user_thread = AsyncMock()
    router.get_user_builder_thread = AsyncMock(return_value=None)
    router.set_user_builder_thread = AsyncMock()
    router._tasks_client = MagicMock()
    return router


@pytest.mark.asyncio
async def test_build_new_uses_builder_thread_not_schedules():
    discord = MagicMock()
    discord.create_private_thread = AsyncMock(return_value="BT1")
    discord.add_thread_member = AsyncMock()
    discord.post_channel_message = AsyncMock()
    discord.edit_original = AsyncMock()
    router = _router_with_both_thread_slots()
    router._resolve_email_auto = AsyncMock(return_value="maya@x.com")
    router._tasks_client.list_templates = AsyncMock(
        return_value=[{"key": "portfolio", "label": "Portfolio"}])
    h = DiscordCommandHandler(discord, router)
    await h.handle_interaction(_payload(PANEL_NEW_ID))
    await asyncio.sleep(0)
    router.get_user_builder_thread.assert_awaited()
    router.set_user_builder_thread.assert_awaited()
    router.get_user_thread.assert_not_awaited()
    router.set_user_thread.assert_not_awaited()
    # New thread named for the app builder, not schedules.
    assert discord.create_private_thread.await_args.args[1].startswith("aiui-apps-")


@pytest.mark.asyncio
async def test_my_apps_uses_builder_thread_not_schedules():
    discord = MagicMock()
    discord.create_private_thread = AsyncMock(return_value="BT1")
    discord.add_thread_member = AsyncMock()
    discord.post_channel_message = AsyncMock()
    discord.edit_original = AsyncMock()
    router = _router_with_both_thread_slots()
    router._resolve_email = AsyncMock(return_value="maya@x.com")
    router._tasks_client.list_projects = AsyncMock(
        return_value=[{"slug": "shop-1", "name": "Shop"}])
    h = DiscordCommandHandler(discord, router)
    await h.handle_interaction(_payload(PANEL_MYAPPS_ID))
    await asyncio.sleep(0)
    router.get_user_builder_thread.assert_awaited()
    router.set_user_builder_thread.assert_awaited()
    router.get_user_thread.assert_not_awaited()
    router.set_user_thread.assert_not_awaited()
    assert discord.create_private_thread.await_args.args[1].startswith("aiui-apps-")


@pytest.mark.asyncio
async def test_sched_open_uses_schedules_thread_not_builder():
    discord = MagicMock()
    discord.create_private_thread = AsyncMock(return_value="ST1")
    discord.add_thread_member = AsyncMock()
    discord.post_channel_message = AsyncMock()
    discord.edit_original = AsyncMock()
    router = _router_with_both_thread_slots()
    router.dashboard_payload = AsyncMock(
        return_value={"content": "Your schedules:", "components": []})
    h = DiscordCommandHandler(discord, router)
    await h.handle_interaction(_payload(SCHED_OPEN_ID))
    await asyncio.sleep(0)
    router.get_user_thread.assert_awaited()
    router.set_user_thread.assert_awaited()
    router.get_user_builder_thread.assert_not_awaited()
    router.set_user_builder_thread.assert_not_awaited()
    assert discord.create_private_thread.await_args.args[1].startswith("schedules-")


@pytest.mark.asyncio
async def test_build_modal_submit_delivers_to_builder_thread():
    discord = MagicMock()
    discord.create_private_thread = AsyncMock(return_value="BT1")
    discord.add_thread_member = AsyncMock()
    discord.post_channel_message = AsyncMock()
    discord.edit_original = AsyncMock()
    router = _router_with_both_thread_slots()
    router.run_panel_build = AsyncMock()
    h = DiscordCommandHandler(discord, router)
    payload = {
        "type": 5,
        "data": {"custom_id": "aiuibuild:build:portfolio",
                 "components": [{"components": [
                     {"custom_id": "description", "value": "a site"}]}]},
        "member": {"user": {"id": "U1", "username": "maya"}},
        "channel_id": "C1", "token": "tok",
    }
    await h.handle_interaction(payload)
    await asyncio.sleep(0)
    # Build delivery must reuse/store the BUILDER thread, never the cron one.
    router.set_user_thread.assert_not_awaited()
    assert (router.get_user_builder_thread.await_count
            + router.set_user_builder_thread.await_count) >= 1


# ---------------------------------------------------------------------------
# Slack — Build an app button -> template picker in DM
# ---------------------------------------------------------------------------
from handlers.slack_interactions import SlackInteractionsHandler
from handlers.slack_app_builder_panel import (
    PANEL_NEW_ID, PANEL_MYAPPS_ID, TEMPLATE_SELECT_ACTION_ID,
)


def _slack_action(action_id, user="U1", channel="C-app"):
    return {"type": "block_actions", "user": {"id": user, "username": "maya"},
            "trigger_id": "t", "channel": {"id": channel},
            "actions": [{"action_id": action_id}]}


@pytest.mark.asyncio
async def test_slack_build_new_posts_picker_to_dm():
    slack = MagicMock()
    slack.open_dm = AsyncMock(return_value="D1"); slack.post_message = AsyncMock()
    slack.post_ephemeral = AsyncMock()
    router = MagicMock()
    router._resolve_email_for_ctx = AsyncMock(return_value="maya@x.com")
    router._tasks_client = MagicMock()
    router._tasks_client.list_templates = AsyncMock(return_value=[{"key": "portfolio", "label": "P"}])
    router._background_tasks = set()
    h = SlackInteractionsHandler(slack_client=slack, command_router=router)
    await h.handle_interaction(_slack_action(PANEL_NEW_ID)); await asyncio.sleep(0)
    slack.open_dm.assert_awaited_once_with("U1")
    posted = slack.post_message.await_args
    assert posted.kwargs.get("channel") == "D1"
    slack.post_ephemeral.assert_awaited_once()
    assert slack.post_ephemeral.await_args.args[0] == "C-app"


@pytest.mark.asyncio
async def test_slack_build_new_falls_back_to_ephemeral_when_no_dm():
    slack = MagicMock()
    slack.open_dm = AsyncMock(return_value=None); slack.post_message = AsyncMock()
    slack.post_ephemeral = AsyncMock()
    router = MagicMock()
    router._resolve_email_for_ctx = AsyncMock(return_value="maya@x.com")
    router._tasks_client = MagicMock()
    router._tasks_client.list_templates = AsyncMock(return_value=[{"key": "portfolio", "label": "P"}])
    router._background_tasks = set()
    h = SlackInteractionsHandler(slack_client=slack, command_router=router)
    await h.handle_interaction(_slack_action(PANEL_NEW_ID)); await asyncio.sleep(0)
    slack.post_message.assert_not_awaited()
    eph = slack.post_ephemeral.await_args
    assert eph.args[0] == "C-app"
    assert eph.kwargs.get("blocks")


# ---------------------------------------------------------------------------
# Slack — My apps button -> apps list in DM
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_slack_my_apps_posts_list_to_dm():
    slack = MagicMock(); slack.open_dm = AsyncMock(return_value="D1")
    slack.post_message = AsyncMock(); slack.post_ephemeral = AsyncMock()
    router = MagicMock()
    router._resolve_email_for_ctx = AsyncMock(return_value="maya@x.com")
    router._tasks_client = MagicMock(); router._tasks_client.list_projects = AsyncMock(
        return_value=[{"slug": "shop", "name": "Shop"}])
    router._background_tasks = set()
    h = SlackInteractionsHandler(slack_client=slack, command_router=router)
    await h.handle_interaction(_slack_action("aiuibuild:myapps")); await asyncio.sleep(0)
    assert slack.post_message.await_args.kwargs.get("channel") == "D1"


@pytest.mark.asyncio
async def test_slack_my_apps_empty_state():
    slack = MagicMock(); slack.open_dm = AsyncMock(return_value="D1")
    slack.post_message = AsyncMock(); slack.post_ephemeral = AsyncMock()
    router = MagicMock()
    router._resolve_email_for_ctx = AsyncMock(return_value="maya@x.com")
    router._tasks_client = MagicMock(); router._tasks_client.list_projects = AsyncMock(return_value=[])
    router._background_tasks = set()
    h = SlackInteractionsHandler(slack_client=slack, command_router=router)
    await h.handle_interaction(_slack_action("aiuibuild:myapps")); await asyncio.sleep(0)
    txt = " ".join(str(c.kwargs) for c in slack.post_message.await_args_list)
    assert "No apps yet" in txt


# ---------------------------------------------------------------------------
# TASK 7 — Delete action routes to _tasks_client.delete_app + confirmation
# ---------------------------------------------------------------------------

from handlers.slack_app_builder_panel import DELETE_PREFIX  # noqa: E402


@pytest.mark.asyncio
async def test_slack_delete_action_calls_delete_app_and_dms():
    slack = MagicMock()
    slack.open_dm = AsyncMock(return_value="D1")
    slack.post_message = AsyncMock()
    slack.post_ephemeral = AsyncMock()
    router = MagicMock()
    router._resolve_email_for_ctx = AsyncMock(return_value="maya@x.com")
    router._not_linked_text = MagicMock(return_value="not linked")
    router._tasks_client = MagicMock()
    router._tasks_client.delete_app = AsyncMock(return_value=True)
    router._background_tasks = set()
    h = SlackInteractionsHandler(slack_client=slack, command_router=router)

    resp = await h.handle_interaction(_slack_action(f"{DELETE_PREFIX}shop"))
    assert resp == {}
    # Background-task tracked
    assert len(router._background_tasks) >= 1
    await asyncio.sleep(0)

    router._tasks_client.delete_app.assert_awaited_once_with("maya@x.com", "shop")
    slack.post_message.assert_awaited()


@pytest.mark.asyncio
async def test_slack_delete_action_email_none_skips_delete():
    slack = MagicMock()
    slack.open_dm = AsyncMock(return_value="D1")
    slack.post_message = AsyncMock()
    slack.post_ephemeral = AsyncMock()
    router = MagicMock()
    router._resolve_email_for_ctx = AsyncMock(return_value=None)
    router._not_linked_text = MagicMock(return_value="not linked")
    router._tasks_client = MagicMock()
    router._tasks_client.delete_app = AsyncMock(return_value=True)
    router._background_tasks = set()
    h = SlackInteractionsHandler(slack_client=slack, command_router=router)

    resp = await h.handle_interaction(_slack_action(f"{DELETE_PREFIX}shop"))
    assert resp == {}
    await asyncio.sleep(0)

    router._tasks_client.delete_app.assert_not_awaited()
