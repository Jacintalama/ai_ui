"""Slack interactivity handler: App Builder panel buttons and modal submits.

Slack delivers interactive payloads (button clicks, modal submissions) to a
single Interactivity Request URL as `payload=<json>` form data. main.py parses
that and hands the decoded dict here. Mirrors handlers/discord_commands.py's
button -> modal -> build flow, adapted to Block Kit / views.
"""
import asyncio
import logging
from typing import Any, Awaitable, Callable, Optional

from clients.slack import SlackClient
from handlers.commands import CommandRouter, CommandContext
from handlers.slack_app_builder_panel import (
    TEMPLATE_SELECT_ACTION_ID,
    build_modal_view,
    build_ready_attachment,
    description_from_view,
    is_panel_button,
    is_panel_modal,
    template_key_from_button,
    template_key_from_modal,
)

logger = logging.getLogger(__name__)


class SlackInteractionsHandler:
    """Routes Slack `block_actions` (button click) and `view_submission`
    (modal submit) payloads for the App Builder panel."""

    def __init__(self, slack_client: SlackClient, command_router: CommandRouter):
        self.slack = slack_client
        self.router = command_router

    async def handle_interaction(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Returns the body Slack expects: empty dict (=> empty 200) both to
        ACK a button click and to close a submitted modal."""
        ptype = payload.get("type")
        if ptype == "block_actions":
            return await self._handle_block_actions(payload)
        if ptype == "view_submission":
            return await self._handle_view_submission(payload)
        logger.info(f"Ignoring Slack interaction type: {ptype}")
        return {}

    async def _handle_block_actions(self, payload: dict[str, Any]) -> dict[str, Any]:
        """A panel button click or dropdown selection opens the 'Describe your
        app' modal. The originating channel is stashed in the modal's
        private_metadata so the submit handler knows where to post the result.
        Unknown actions no-op."""
        actions = payload.get("actions", [])
        action_id = actions[0].get("action_id", "") if actions else ""
        trigger_id = payload.get("trigger_id", "")
        channel_id = (payload.get("channel") or {}).get("id", "")

        if action_id == TEMPLATE_SELECT_ACTION_ID:
            # C8: dropdown select — read the chosen option value
            selected_value = (actions[0].get("selected_option") or {}).get("value", "")
            template_key = template_key_from_button(selected_value) if selected_value else None
            logger.info(f"App Builder dropdown selected: template={template_key}")
            view = build_modal_view(template_key, None, channel_id)
            await self.slack.open_modal(trigger_id, view)
            return {}

        if is_panel_button(action_id):
            template_key = template_key_from_button(action_id)
            logger.info(f"App Builder button clicked: template={template_key}")
            view = build_modal_view(template_key, None, channel_id)
            await self.slack.open_modal(trigger_id, view)
            return {}

        logger.info(f"Ignoring unknown Slack action_id: {action_id}")
        return {}

    def _dm_context(
        self,
        payload: dict[str, Any],
        *,
        dm_id: Optional[str],
        origin_channel: str,
        user_id: str,
        user_name: str,
        subcommand: str,
        raw_text: str,
    ) -> CommandContext:
        """Build a DM-targeted CommandContext with shared closures.

        If dm_id is set, all messages go to the DM channel; otherwise they
        fall back to an ephemeral in the origin channel. Both notify_channel
        and notify_channel_rich are always set so the watcher never early-exits.
        """
        target = dm_id or origin_channel

        async def respond(msg: str) -> None:
            if dm_id:
                await self.slack.post_message(channel=dm_id, text=msg)
            elif origin_channel:
                await self.slack.post_ephemeral(origin_channel, user_id, msg)

        async def notify_channel(msg: str) -> None:
            await respond(msg)

        async def notify_channel_rich(msg: str, slug: str, url: str, owner: str) -> None:
            att = build_ready_attachment(slug, url)
            if dm_id:
                await self.slack.post_message(
                    channel=dm_id,
                    text=f"Build ready: {slug}",
                    attachments=[att],
                )
            elif origin_channel:
                await self.slack.post_ephemeral(
                    origin_channel,
                    user_id,
                    f"Build ready: {slug}",
                    blocks=att["blocks"],
                )

        return CommandContext(
            user_id=user_id,
            user_name=user_name,
            channel_id=target,
            raw_text=raw_text,
            subcommand=subcommand,
            arguments="",
            platform="slack",
            respond=respond,
            metadata={"team_id": payload.get("team", {}).get("id", "")},
            notify_channel=notify_channel,
            notify_channel_rich=notify_channel_rich,
        )

    async def _handle_view_submission(self, payload: dict[str, Any]) -> dict[str, Any]:
        """The 'Describe your app' modal was submitted. Open a DM with the user,
        post an ephemeral ack in the origin channel, then run the build in the
        DM. Returns empty dict immediately to close the modal."""
        view = payload.get("view", {})
        callback_id = view.get("callback_id", "")
        user = payload.get("user", {})
        user_id = user.get("id", "")
        user_name = user.get("username") or user.get("name", "unknown")

        if is_panel_modal(callback_id):
            template_key = template_key_from_modal(callback_id)
            origin_channel = view.get("private_metadata", "") or ""
            description = description_from_view(view)

            async def _start() -> None:
                dm_id = await self.slack.open_dm(user_id)
                if dm_id:
                    if origin_channel:
                        await self.slack.post_ephemeral(
                            origin_channel,
                            user_id,
                            "Starting your build - I've sent it to your DMs.",
                        )
                    await self.slack.post_message(
                        channel=dm_id,
                        text=f"Building `{template_key or 'app'}`...",
                    )
                ctx = self._dm_context(
                    payload,
                    dm_id=dm_id,
                    origin_channel=origin_channel,
                    user_id=user_id,
                    user_name=user_name,
                    subcommand="aiuibuilder",
                    raw_text=f"aiuibuilder build {template_key or ''} {description}".strip(),
                )
                await self.router.run_panel_build(ctx, template_key, description)

            asyncio.create_task(_start())
            return {}  # empty 200 closes the modal

        logger.info(f"Ignoring unknown Slack callback_id: {callback_id}")
        return {}
