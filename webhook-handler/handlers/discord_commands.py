"""Discord interaction handler for /aiui slash commands."""
import asyncio
import logging
from typing import Any, Awaitable, Callable

from clients.discord import DiscordClient
from handlers.commands import CommandRouter, CommandContext
from handlers.app_builder_panel import (
    build_modal_payload,
    is_panel_button,
    is_panel_modal,
    template_key_from_button,
    template_key_from_modal,
    DESCRIPTION_INPUT_ID,
    is_publish_button,
    slug_from_publish_button,
    build_ready_components,
)

logger = logging.getLogger(__name__)

# Discord interaction types (payload["type"])
PING = 1
APPLICATION_COMMAND = 2
MESSAGE_COMPONENT = 3
MODAL_SUBMIT = 5  # NOTE: same number as DEFERRED_CHANNEL_MESSAGE below, but a
                  # different field (interaction type vs. callback type).

# Discord interaction callback (response) types
PONG = 1
DEFERRED_CHANNEL_MESSAGE = 5
DEFERRED_UPDATE_MESSAGE = 6
MODAL = 9


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
        - MESSAGE_COMPONENT -> MODAL (type 9) for template buttons; DEFERRED (type 5) for the Publish button
        - MODAL_SUBMIT -> DEFERRED (type 5), routes the build to background
        """
        interaction_type = payload.get("type")

        # PING — required for endpoint validation
        if interaction_type == PING:
            logger.info("Discord PING received, responding with PONG")
            return {"type": PONG}

        # APPLICATION_COMMAND — slash command invocation
        if interaction_type == APPLICATION_COMMAND:
            return await self._handle_application_command(payload)

        # MESSAGE_COMPONENT — a button click (e.g. an App Builder template button)
        if interaction_type == MESSAGE_COMPONENT:
            return await self._handle_message_component(payload)

        # MODAL_SUBMIT — the "Describe your app" form was submitted
        if interaction_type == MODAL_SUBMIT:
            return await self._handle_modal_submit(payload)

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

        notify_channel, notify_channel_rich = self._channel_notifiers(channel_id)

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
            notify_channel_rich=notify_channel_rich if channel_id else None,
        )

        # Fire-and-forget: process in background, edit deferred response
        asyncio.create_task(self.router.execute(ctx))

        # Immediate ACK — tells Discord we'll follow up (type 5 = DEFERRED)
        return {"type": DEFERRED_CHANNEL_MESSAGE}

    def _channel_notifiers(
        self, channel_id: str
    ) -> tuple[Callable[[str], Awaitable[None]], Callable[[str, str, str], Awaitable[None]]]:
        """Build the plain + rich channel notifiers for a ctx. The rich one
        posts a build-ready message with a Publish button."""
        async def notify_channel(msg: str) -> None:
            await self.discord.post_channel_message(channel_id, msg)

        async def notify_channel_rich(msg: str, slug: str, preview_url: str) -> None:
            await self.discord.post_channel_message(
                channel_id, msg, components=build_ready_components(slug, preview_url),
            )
        return notify_channel, notify_channel_rich

    async def _handle_message_component(self, payload: dict[str, Any]) -> dict[str, Any]:
        """A button click. App Builder template buttons open a modal; any other
        component is a harmless no-op (never a 500)."""
        data = payload.get("data", {})
        custom_id = data.get("custom_id", "")
        if is_publish_button(custom_id):
            return await self._handle_publish_component(payload, custom_id)
        if not is_panel_button(custom_id):
            logger.info(f"Ignoring unknown component custom_id: {custom_id}")
            return {"type": DEFERRED_UPDATE_MESSAGE}
        template_key = template_key_from_button(custom_id)
        logger.info(f"App Builder button clicked: template={template_key}")
        return {"type": MODAL, "data": build_modal_payload(template_key)}

    async def _handle_publish_component(self, payload: dict[str, Any], custom_id: str) -> dict[str, Any]:
        """A Publish button click. Route to run_panel_publish in the background,
        ACK deferred — mirrors the modal-submit pattern."""
        slug = slug_from_publish_button(custom_id)
        interaction_token = payload.get("token", "")
        member = payload.get("member", {})
        user = member.get("user", payload.get("user", {}))
        user_id = user.get("id", "")
        user_name = user.get("username", "unknown")
        channel_id = payload.get("channel_id", "")

        async def respond(msg: str) -> None:
            await self.discord.edit_original(
                interaction_token=interaction_token, content=msg,
            )

        ctx = CommandContext(
            user_id=user_id,
            user_name=user_name,
            channel_id=channel_id,
            raw_text=f"aiuibuilder publish {slug}",
            subcommand="aiuibuilder",
            arguments="",
            platform="discord",
            respond=respond,
            metadata={
                "interaction_id": payload.get("id", ""),
                "interaction_token": interaction_token,
                "guild_id": payload.get("guild_id", ""),
            },
        )
        asyncio.create_task(self.router.run_panel_publish(ctx, slug))
        return {"type": DEFERRED_CHANNEL_MESSAGE}

    async def _handle_modal_submit(self, payload: dict[str, Any]) -> dict[str, Any]:
        """An App Builder modal submission. Extract the description, route to the
        build in the background, and ACK deferred — mirrors the slash-command
        deferred pattern (the watcher posts the link via the bot token later)."""
        data = payload.get("data", {})
        custom_id = data.get("custom_id", "")
        if not is_panel_modal(custom_id):
            logger.info(f"Ignoring unknown modal custom_id: {custom_id}")
            return {"type": DEFERRED_UPDATE_MESSAGE}

        interaction_token = payload.get("token", "")
        member = payload.get("member", {})
        user = member.get("user", payload.get("user", {}))
        user_id = user.get("id", "")
        user_name = user.get("username", "unknown")
        channel_id = payload.get("channel_id", "")

        template_key = template_key_from_modal(custom_id)
        description = self._extract_modal_value(data, DESCRIPTION_INPUT_ID)

        async def respond(msg: str) -> None:
            await self.discord.edit_original(
                interaction_token=interaction_token, content=msg,
            )

        notify_channel, notify_channel_rich = self._channel_notifiers(channel_id)

        ctx = CommandContext(
            user_id=user_id,
            user_name=user_name,
            channel_id=channel_id,
            # Synthetic, for logging only — the authoritative inputs are
            # template_key + description (run_panel_build uses those, not raw_text).
            raw_text=f"aiuibuilder build {template_key or ''} {description}".strip(),
            subcommand="aiuibuilder",
            arguments="",
            platform="discord",
            respond=respond,
            metadata={
                "interaction_id": payload.get("id", ""),
                "interaction_token": interaction_token,
                "guild_id": payload.get("guild_id", ""),
            },
            notify_channel=notify_channel if channel_id else None,
            notify_channel_rich=notify_channel_rich if channel_id else None,
        )

        # Fire-and-forget, mirroring _handle_application_command. run_panel_build
        # itself is short-lived; its long-running build watcher is tracked with a
        # strong ref inside CommandRouter (_background_tasks), so it won't be GC'd.
        asyncio.create_task(self.router.run_panel_build(ctx, template_key, description))
        return {"type": DEFERRED_CHANNEL_MESSAGE}

    @staticmethod
    def _extract_modal_value(data: dict[str, Any], input_custom_id: str) -> str:
        """Pull a text-input value out of a modal-submit payload.
        data.components[*].components[*] -> {custom_id, value}."""
        for row in data.get("components", []):
            for comp in row.get("components", []):
                if comp.get("custom_id") == input_custom_id:
                    return (comp.get("value") or "").strip()
        return ""

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
