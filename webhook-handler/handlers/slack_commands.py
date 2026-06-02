"""Slack slash command handler (/aiui)."""
import asyncio
import logging
from typing import Any

from clients.slack import SlackClient
from handlers.commands import CommandRouter, CommandContext

logger = logging.getLogger(__name__)


class SlackCommandHandler:
    """Handles Slack slash command payloads (form-encoded)."""

    def __init__(self, slack_client: SlackClient, command_router: CommandRouter):
        self.slack = slack_client
        self.router = command_router

    async def handle_command(self, form_data: dict[str, Any]) -> dict[str, Any]:
        """
        Process a Slack slash command.

        Slack sends application/x-www-form-urlencoded with fields:
            command, text, response_url, user_id, user_name,
            channel_id, team_id, etc.

        Returns an immediate ACK response (< 3s). The actual command
        processing happens in a background task via response_url.
        """
        command = form_data.get("command", "/aiui")
        text = form_data.get("text", "")
        response_url = form_data.get("response_url", "")
        user_id = form_data.get("user_id", "")
        user_name = form_data.get("user_name", "unknown")
        channel_id = form_data.get("channel_id", "")

        logger.info(f"Slack command from {user_name}: {command} {text}")

        subcommand, arguments = CommandRouter.parse_command(text)

        async def respond(msg: str) -> None:
            if response_url:
                await self.slack.post_to_response_url(
                    response_url=response_url,
                    text=msg,
                    response_type="ephemeral",
                )

        async def notify_channel(msg: str) -> None:
            # Bot-token channel post — outlives the response_url window so a
            # long App Builder build can deliver its link when it finishes.
            if channel_id:
                await self.slack.post_message(channel=channel_id, text=msg)

        ctx = CommandContext(
            user_id=user_id,
            user_name=user_name,
            channel_id=channel_id,
            raw_text=text,
            subcommand=subcommand,
            arguments=arguments,
            platform="slack",
            respond=respond,
            metadata={
                "command": command,
                "response_url": response_url,
                "team_id": form_data.get("team_id", ""),
            },
            notify_channel=notify_channel if channel_id else None,
        )

        # Fire-and-forget: process in background, respond via response_url
        asyncio.create_task(self.router.execute(ctx))

        # Immediate ACK (must return within 3 seconds)
        return {
            "response_type": "ephemeral",
            "text": f"Processing `{subcommand}`...",
        }
