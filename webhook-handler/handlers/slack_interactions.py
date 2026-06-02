"""Slack interactivity handler: App Builder panel buttons and modal submits.

Slack delivers interactive payloads (button clicks, modal submissions) to a
single Interactivity Request URL as `payload=<json>` form data. main.py parses
that and hands the decoded dict here. Mirrors handlers/discord_commands.py's
button -> modal -> build flow, adapted to Block Kit / views.
"""
import asyncio
import logging
from typing import Any

from clients.slack import SlackClient
from handlers.commands import CommandRouter, CommandContext
from handlers.slack_app_builder_panel import (
    build_modal_view,
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
        """A panel button click opens the 'Describe your app' modal. The
        originating channel is stashed in the modal's private_metadata so the
        submit handler knows where to post the result. Unknown buttons no-op."""
        actions = payload.get("actions", [])
        action_id = actions[0].get("action_id", "") if actions else ""
        if not is_panel_button(action_id):
            logger.info(f"Ignoring unknown Slack action_id: {action_id}")
            return {}
        template_key = template_key_from_button(action_id)
        trigger_id = payload.get("trigger_id", "")
        channel_id = (payload.get("channel") or {}).get("id", "")
        logger.info(f"App Builder button clicked: template={template_key}")
        view = build_modal_view(template_key, None, channel_id)
        await self.slack.open_modal(trigger_id, view)
        return {}

    async def _handle_view_submission(self, payload: dict[str, Any]) -> dict[str, Any]:
        """The 'Describe your app' modal was submitted. Resolve inputs, route
        the build to the background (run_panel_build resolves the email and
        starts the watcher), and return empty 200 to close the modal. Both the
        ack and the final link post to the originating channel."""
        view = payload.get("view", {})
        callback_id = view.get("callback_id", "")
        if not is_panel_modal(callback_id):
            logger.info(f"Ignoring unknown Slack callback_id: {callback_id}")
            return {}

        template_key = template_key_from_modal(callback_id)
        channel_id = view.get("private_metadata", "") or ""
        description = description_from_view(view)
        user = payload.get("user", {})
        user_id = user.get("id", "")
        user_name = user.get("username") or user.get("name", "unknown")

        async def respond(msg: str) -> None:
            if channel_id:
                await self.slack.post_message(channel=channel_id, text=msg)

        async def notify_channel(msg: str) -> None:
            if channel_id:
                await self.slack.post_message(channel=channel_id, text=msg)

        ctx = CommandContext(
            user_id=user_id,
            user_name=user_name,
            channel_id=channel_id,
            # Synthetic, for logging only — run_panel_build uses the explicit
            # template_key + description, not raw_text.
            raw_text=f"aiuibuilder build {template_key or ''} {description}".strip(),
            subcommand="aiuibuilder",
            arguments="",
            platform="slack",
            respond=respond,
            metadata={"team_id": payload.get("team", {}).get("id", "")},
            notify_channel=notify_channel if channel_id else None,
        )

        # Fire-and-forget; the long-running watcher is tracked inside
        # CommandRouter._background_tasks so it won't be GC'd.
        asyncio.create_task(self.router.run_panel_build(ctx, template_key, description))
        return {}  # empty 200 closes the modal
