"""Button clicks on the #channels and #graph panels reach the shared handlers.

Discord: a component click is ACKed ephemeral-deferred and the handler runs in
the background; "Ask the graph" opens a modal whose submit carries the topic.
Slack: a block action returns immediately and the handler runs in the
background, replying ephemerally in the channel the click came from; the
modal stashes that channel in private_metadata so the submit can find it.

The handlers themselves (_handle_channels, _handle_graph) are the ones behind
`/aiui channels` and `/aiui graph`, tested in test_channels_graph_commands.py.
Here they are mocks: what is under test is the wiring.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from handlers import channels_panel as chan
from handlers import graph_panel as gp
from handlers import slack_channels_panel as schan
from handlers import slack_graph_panel as sgp
from handlers.discord_commands import DiscordCommandHandler
from handlers.slack_interactions import SlackInteractionsHandler


# ---------------------------------------------------------------- Discord

def _discord_handler(router):
    discord = MagicMock()
    discord.edit_original = AsyncMock(return_value=True)
    discord.post_channel_message = AsyncMock(return_value=True)
    return DiscordCommandHandler(discord_client=discord, command_router=router), discord


def _discord_router():
    router = MagicMock()
    router._handle_channels = AsyncMock()
    router._handle_graph = AsyncMock()
    return router


def _component(custom_id, user_id="100"):
    return {"type": 3, "id": "i", "token": "tok", "channel_id": "c",
            "data": {"custom_id": custom_id},
            "member": {"user": {"id": user_id, "username": "t"}}}


async def _drain(handler):
    await asyncio.gather(*list(handler._bg_tasks))


@pytest.mark.asyncio
async def test_discord_my_channels_acks_ephemeral_and_runs_the_handler():
    router = _discord_router()
    handler, discord = _discord_handler(router)
    resp = await handler.handle_interaction(_component(chan.MY))
    assert resp == {"type": 5, "data": {"flags": 64}}
    await _drain(handler)
    router._handle_channels.assert_awaited_once()
    ctx = router._handle_channels.await_args.args[0]
    assert ctx.platform == "discord" and ctx.user_id == "100"
    await ctx.respond("hello")
    discord.edit_original.assert_awaited_with(interaction_token="tok", content="hello")


@pytest.mark.asyncio
async def test_discord_my_graph_runs_the_handler_with_no_topic():
    router = _discord_router()
    handler, _ = _discord_handler(router)
    resp = await handler.handle_interaction(_component(gp.MY))
    assert resp == {"type": 5, "data": {"flags": 64}}
    await _drain(handler)
    ctx = router._handle_graph.await_args.args[0]
    assert ctx.arguments == ""


@pytest.mark.asyncio
async def test_discord_ask_opens_the_modal():
    router = _discord_router()
    handler, _ = _discord_handler(router)
    resp = await handler.handle_interaction(_component(gp.ASK))
    assert resp["type"] == 9
    assert resp["data"]["custom_id"] == gp.ASK_MODAL
    router._handle_graph.assert_not_called()


@pytest.mark.asyncio
async def test_discord_ask_submit_runs_the_handler_with_the_topic():
    router = _discord_router()
    handler, discord = _discord_handler(router)
    payload = {"type": 5, "id": "i", "token": "tok", "channel_id": "c",
               "data": {"custom_id": gp.ASK_MODAL, "components": [
                   {"type": 1, "components": [{"custom_id": gp.TOPIC_INPUT, "value": " portfolio "}]}]},
               "member": {"user": {"id": "100", "username": "t"}}}
    resp = await handler.handle_interaction(payload)
    assert resp == {"type": 5, "data": {"flags": 64}}
    await _drain(handler)
    ctx = router._handle_graph.await_args.args[0]
    assert ctx.arguments == "portfolio"
    await ctx.respond("ctx")
    discord.edit_original.assert_awaited_with(interaction_token="tok", content="ctx")


@pytest.mark.asyncio
async def test_discord_unknown_ids_under_the_prefixes_do_not_crash():
    router = _discord_router()
    handler, _ = _discord_handler(router)
    for cid in ("chan:bogus", "graph:bogus"):
        resp = await handler.handle_interaction(_component(cid))
        assert resp == {"type": 6}
    router._handle_channels.assert_not_called()
    router._handle_graph.assert_not_called()


# ------------------------------------------------------------------ Slack

def _slack_handler(router):
    slack = MagicMock()
    slack.open_modal = AsyncMock(return_value=True)
    slack.post_message = AsyncMock(return_value="ts")
    slack.post_ephemeral = AsyncMock(return_value=True)
    slack.open_dm = AsyncMock(return_value="D9")
    return SlackInteractionsHandler(slack_client=slack, command_router=router), slack


def _slack_router():
    router = MagicMock()
    router._background_tasks = set()
    router._handle_channels = AsyncMock()
    router._handle_graph = AsyncMock()
    return router


def _block_action(action_id, channel="C1"):
    return {"type": "block_actions", "trigger_id": "tr",
            "actions": [{"action_id": action_id}],
            "user": {"id": "U1", "name": "t"}, "channel": {"id": channel}}


async def _drain_slack(router):
    await asyncio.gather(*list(router._background_tasks))


@pytest.mark.asyncio
async def test_slack_my_channels_runs_the_handler_and_replies_ephemerally():
    router = _slack_router()
    handler, slack = _slack_handler(router)
    resp = await handler.handle_interaction(_block_action(schan.MY_ACTION_ID))
    assert resp == {}
    await _drain_slack(router)
    ctx = router._handle_channels.await_args.args[0]
    assert ctx.platform == "slack" and ctx.user_id == "U1"
    await ctx.respond("hello")
    slack.post_ephemeral.assert_awaited_with("C1", "U1", "hello")


@pytest.mark.asyncio
async def test_slack_my_graph_runs_the_handler_with_no_topic():
    router = _slack_router()
    handler, _ = _slack_handler(router)
    await handler.handle_interaction(_block_action(sgp.MY_ACTION_ID))
    await _drain_slack(router)
    assert router._handle_graph.await_args.args[0].arguments == ""


@pytest.mark.asyncio
async def test_slack_ask_opens_the_modal_with_the_origin_channel():
    router = _slack_router()
    handler, slack = _slack_handler(router)
    await handler.handle_interaction(_block_action(sgp.ASK_ACTION_ID, channel="C7"))
    slack.open_modal.assert_awaited_once()
    trigger_id, view = slack.open_modal.await_args.args
    assert trigger_id == "tr"
    assert view["callback_id"] == sgp.ASK_MODAL_ID
    assert view["private_metadata"] == "C7"
    router._handle_graph.assert_not_called()


@pytest.mark.asyncio
async def test_slack_ask_submit_runs_the_handler_with_the_topic_in_the_origin_channel():
    router = _slack_router()
    handler, slack = _slack_handler(router)
    payload = {"type": "view_submission", "user": {"id": "U1", "name": "t"},
               "view": {"callback_id": sgp.ASK_MODAL_ID, "private_metadata": "C7",
                        "state": {"values": {sgp.TOPIC_BLOCK_ID: {sgp.TOPIC_INPUT_ID: {"value": "portfolio"}}}}}}
    resp = await handler.handle_interaction(payload)
    assert resp == {}
    await _drain_slack(router)
    ctx = router._handle_graph.await_args.args[0]
    assert ctx.arguments == "portfolio"
    await ctx.respond("ctx")
    slack.post_ephemeral.assert_awaited_with("C7", "U1", "ctx")


@pytest.mark.asyncio
async def test_slack_link_buttons_no_op():
    router = _slack_router()
    handler, slack = _slack_handler(router)
    for aid in (schan.LINK_ACTION_ID, sgp.OPEN_ACTION_ID):
        resp = await handler.handle_interaction(_block_action(aid))
        assert resp == {}
    await _drain_slack(router)
    router._handle_channels.assert_not_called()
    router._handle_graph.assert_not_called()
    slack.open_modal.assert_not_called()
