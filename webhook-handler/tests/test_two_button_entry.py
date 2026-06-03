import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from handlers.discord_commands import DiscordCommandHandler
from handlers.app_builder_panel import (
    PANEL_NEW_ID, PANEL_MYAPPS_ID, TEMPLATE_SELECT_ID, APP_SELECT_ID,
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
    router.get_user_thread = AsyncMock(return_value=None)
    router.set_user_thread = AsyncMock()
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
    router.get_user_thread = AsyncMock(return_value="T1"); router.set_user_thread = AsyncMock()
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
    router.get_user_thread = AsyncMock(return_value="T1"); router.set_user_thread = AsyncMock()
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
    router._not_linked_msg = MagicMock(return_value="Your Discord account isn't linked yet.")
    router._tasks_client = MagicMock(); router._tasks_client.list_projects = AsyncMock(return_value=[])
    h = DiscordCommandHandler(discord, router)
    await h.handle_interaction(_payload(PANEL_MYAPPS_ID)); await asyncio.sleep(0)
    assert discord.post_channel_message.await_count == 0
    content = discord.edit_original.await_args.kwargs.get("content", "")
    assert "isn't linked" in content
    router._tasks_client.list_projects.assert_not_awaited()


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
