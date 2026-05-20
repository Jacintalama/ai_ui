"""Discord interaction handler for /aiui slash commands."""
import asyncio
import logging
from typing import Any

from clients.discord import DiscordClient
from handlers.commands import CommandRouter, CommandContext

logger = logging.getLogger(__name__)

# Discord interaction types
PING = 1
APPLICATION_COMMAND = 2

# Discord interaction callback types
PONG = 1
DEFERRED_CHANNEL_MESSAGE = 5


class DiscordCommandHandler:
    """Handles Discord interaction payloads."""

    def __init__(self, discord_client: DiscordClient, command_router: CommandRouter):
        self.discord = discord_client
        self.router = command_router

    async def handle_interaction(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Process a Discord interaction.

        Returns an immediate response:
        - PING -> PONG (type 1)
        - APPLICATION_COMMAND -> DEFERRED (type 5), then process in background
        """
        interaction_type = payload.get("type")

        # PING — required for endpoint validation
        if interaction_type == PING:
            logger.info("Discord PING received, responding with PONG")
            return {"type": PONG}

        # APPLICATION_COMMAND — slash command invocation
        if interaction_type == APPLICATION_COMMAND:
            return await self._handle_application_command(payload)

        logger.info(f"Ignoring Discord interaction type: {interaction_type}")
        return {"type": PONG}

    async def _handle_application_command(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Handle a slash command interaction."""
        data = payload.get("data", {})
        options = data.get("options", [])
        interaction_token = payload.get("token", "")

        # Extract user info
        member = payload.get("member", {})
        user = member.get("user", payload.get("user", {}))
        user_id = user.get("id", "")
        user_name = user.get("username", "unknown")
        channel_id = payload.get("channel_id", "")

        # Parse subcommand and arguments from Discord options
        # Discord sends options as: [{"name": "ask", "options": [{"name": "question", "value": "..."}]}]
        # or for simple text: [{"name": "ask", "value": "..."}]
        subcommand, arguments = self._parse_options(options)

        logger.info(f"Discord command from {user_name}: {subcommand} {arguments[:80]}")

        async def respond(msg: str) -> None:
            await self.discord.edit_original(
                interaction_token=interaction_token,
                content=msg,
            )

        async def notify_channel(msg: str) -> None:
            await self.discord.post_channel_message(channel_id, msg)

        ctx = CommandContext(
            user_id=user_id,
            user_name=user_name,
            channel_id=channel_id,
            raw_text=f"{subcommand} {arguments}".strip(),
            subcommand=subcommand,
            arguments=arguments,
            platform="discord",
            respond=respond,
            metadata={
                "interaction_id": payload.get("id", ""),
                "interaction_token": interaction_token,
                "guild_id": payload.get("guild_id", ""),
            },
            notify_channel=notify_channel if channel_id else None,
        )

        # Fire-and-forget: process in background, edit deferred response
        asyncio.create_task(self.router.execute(ctx))

        # Immediate ACK — tells Discord we'll follow up (type 5 = DEFERRED)
        return {"type": DEFERRED_CHANNEL_MESSAGE}

    @staticmethod
    def _parse_options(options: list[dict]) -> tuple[str, str]:
        """
        Parse Discord command options into (subcommand, arguments).

        Handles two common structures:
        1. Subcommand with nested options:
           [{"name": "ask", "type": 1, "options": [{"name": "question", "value": "..."}]}]
        2. Simple string option:
           [{"name": "query", "type": 3, "value": "..."}]
        """
        if not options:
            return ("status", "")

        first = options[0]

        # Subcommand (type 1) with nested options
        if first.get("type") == 1:
            subcommand = first.get("name", "status")
            sub_options = first.get("options", [])
            if sub_options:
                arguments = sub_options[0].get("value", "")
            else:
                arguments = ""
            return (subcommand, arguments)

        # Direct string option (type 3)
        if first.get("type") == 3:
            value = first.get("value", "")
            return CommandRouter.parse_command(value)

        # Fallback: treat name as subcommand
        return (first.get("name", "status"), first.get("value", ""))
