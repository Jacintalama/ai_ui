"""Discord interaction handler for /aiui slash commands."""
import asyncio
import logging
import re
import uuid
from typing import Any, Awaitable, Callable

from clients.discord import DiscordClient
from clients import connectors
from config import settings
from handlers import connector_intent
from handlers.commands import CommandRouter, CommandContext
from handlers.schedule_parse import parse_when

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match((email or "").strip()))


def _needs_connect(needs: set[str], *, linked: set[str]) -> list[str]:
    """Connectors that must be linked before saving a schedule (web is never gated)."""
    return [c for c in ("gmail", "drive") if c in needs and c not in linked]
from handlers.app_builder_panel import (
    build_modal_payload,
    is_panel_button,
    is_panel_modal,
    template_key_from_button,
    template_key_from_modal,
    DESCRIPTION_INPUT_ID,
    is_publish_button,
    slug_from_publish_button,
    build_ready_components, build_ready_embed,
    build_published_embed,
    build_enhance_modal,
    build_published_components,
    is_enhance_button, slug_from_enhance_button,
    is_unpublish_button, slug_from_unpublish_button,
    is_enhance_modal, slug_from_enhance_modal,
    is_app_select,
    is_status_button, slug_from_status_button,
    build_schedule_modal, build_confirm_components, build_connect_components,
    is_connect_resume, token_from_connect_resume,
    SCHED_WHAT_INPUT, SCHED_WHEN_INPUT,
    is_sched_new, is_sched_list, is_sched_modal,
    is_sched_confirm, token_from_confirm,
    is_sched_cancel, token_from_cancel,
    is_sched_run, id_from_run,
    is_sched_pause, id_from_pause,
    is_sched_resume, id_from_resume,
    is_sched_del, id_from_del,
    build_link_modal, build_link_request_components, build_schedule_edit_modal,
    LINK_EMAIL_INPUT,
    is_link_start, is_link_modal,
    is_link_approve, id_from_link_approve,
    is_link_reject, id_from_link_reject,
    is_sched_edit, id_from_edit,
    is_sched_editmodal, id_from_editmodal,
    is_sched_open, is_sched_select,
    is_template_select,
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
CHANNEL_MESSAGE_WITH_SOURCE = 4  # immediate message (used for the confirm card)
DEFERRED_CHANNEL_MESSAGE = 5
DEFERRED_UPDATE_MESSAGE = 6
UPDATE_MESSAGE = 7  # edit the component message in place (used for Cancel)
MODAL = 9


class DiscordCommandHandler:
    """Handles Discord interaction payloads."""

    def __init__(self, discord_client: DiscordClient, command_router: CommandRouter):
        self.discord = discord_client
        self.router = command_router
        # token -> {name, cron, prompt}: parsed-but-unconfirmed schedules. Popped
        # on Confirm/Cancel. In-memory and per-process (matches the rest of the
        # Discord flow); abandoned entries are tiny and harmless.
        self._pending_schedules: dict[str, dict] = {}

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

        async def respond_components(msg: str, components: list, embeds: list | None = None) -> None:
            await self.discord.edit_original(
                interaction_token=interaction_token, content=msg, components=components, embeds=embeds,
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
            respond_components=respond_components,
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
                channel_id, "", embeds=[build_ready_embed(slug, preview_url, msg)],
                components=build_ready_components(slug, preview_url),
            )
        return notify_channel, notify_channel_rich

    async def _handle_message_component(self, payload: dict[str, Any]) -> dict[str, Any]:
        """A button click. App Builder template buttons open a modal; Enhance
        opens an enhance modal; Publish/Unpublish route to the background; any
        other component is a harmless no-op (never a 500)."""
        data = payload.get("data", {})
        custom_id = data.get("custom_id", "")
        # All aiuibuild:* component ids are routed by their distinct second
        # segment (enhance/unpublish/publish/appselect/status/tpl), so check
        # order doesn't matter — but any NEW prefix added here must stay disjoint.
        if is_enhance_button(custom_id):
            try:
                slug = slug_from_enhance_button(custom_id)
            except ValueError:
                logger.info(f"Ignoring malformed enhance custom_id: {custom_id}")
                return {"type": DEFERRED_UPDATE_MESSAGE}
            return {"type": MODAL, "data": build_enhance_modal(slug)}
        if is_unpublish_button(custom_id):
            return await self._handle_unpublish_component(payload, custom_id)
        if is_publish_button(custom_id):
            return await self._handle_publish_component(payload, custom_id)
        if is_app_select(custom_id):
            return await self._handle_app_select_component(payload)
        if is_status_button(custom_id):
            try:
                slug = slug_from_status_button(custom_id)
            except ValueError:
                logger.info(f"Ignoring malformed status custom_id: {custom_id}")
                return {"type": DEFERRED_UPDATE_MESSAGE}
            return await self._handle_panel_route(
                payload, lambda ctx: self.router.run_panel_status(ctx, slug),
                raw_text=f"aiuibuilder status {slug}")
        # --- Schedules (aiuisched:*) ---
        if is_sched_new(custom_id):
            return {"type": MODAL, "data": build_schedule_modal()}
        if is_sched_list(custom_id):
            return await self._handle_panel_route(
                payload, lambda ctx: self.router.run_schedule_list(ctx),
                raw_text="schedules list")
        if is_sched_open(custom_id):
            return await self._handle_sched_open(payload)
        if is_sched_select(custom_id):
            values = data.get("values") or []
            if not values:
                return {"type": DEFERRED_UPDATE_MESSAGE}
            sid = values[0]
            return await self._handle_panel_route(
                payload, lambda ctx: self.router.run_schedule_card(ctx, sid),
                raw_text=f"schedules card {sid}")
        if is_sched_confirm(custom_id):
            return await self._handle_schedule_confirm(payload, custom_id)
        if is_connect_resume(custom_id):
            return await self._handle_connect_resume(payload, custom_id)
        if is_sched_cancel(custom_id):
            try:
                self._pending_schedules.pop(token_from_cancel(custom_id), None)
            except ValueError:
                pass
            return {"type": UPDATE_MESSAGE,
                    "data": {"content": "Cancelled.", "components": []}}
        for pred, extract, action in (
            (is_sched_run, id_from_run, "run"),
            (is_sched_pause, id_from_pause, "pause"),
            (is_sched_resume, id_from_resume, "resume"),
            (is_sched_del, id_from_del, "del"),
        ):
            if pred(custom_id):
                try:
                    sid = extract(custom_id)
                except ValueError:
                    return {"type": DEFERRED_UPDATE_MESSAGE}
                return await self._handle_panel_route(
                    payload,
                    lambda ctx, a=action, s=sid: self.router.run_schedule_action(ctx, a, s),
                    raw_text=f"schedules {action} {sid}")

        # --- Linking (aiuilink:*) + schedule Edit ---
        if is_link_start(custom_id):
            return {"type": MODAL, "data": build_link_modal()}
        if is_link_approve(custom_id):
            return await self._handle_link_decision(payload, custom_id, approve=True)
        if is_link_reject(custom_id):
            return await self._handle_link_decision(payload, custom_id, approve=False)
        if is_sched_edit(custom_id):
            return await self._handle_sched_edit_open(payload, custom_id)

        if is_template_select(custom_id):
            values = data.get("values") or []
            if not values:
                return {"type": DEFERRED_UPDATE_MESSAGE}
            return {"type": MODAL, "data": build_modal_payload(values[0])}

        if not is_panel_button(custom_id):
            logger.info(f"Ignoring unknown component custom_id: {custom_id}")
            return {"type": DEFERRED_UPDATE_MESSAGE}
        template_key = template_key_from_button(custom_id)
        logger.info(f"App Builder button clicked: template={template_key}")
        return {"type": MODAL, "data": build_modal_payload(template_key)}

    async def _handle_publish_component(self, payload: dict[str, Any], custom_id: str) -> dict[str, Any]:
        """A Publish button click. Route to run_panel_publish in the background,
        ACK deferred — mirrors the modal-submit pattern."""
        try:
            slug = slug_from_publish_button(custom_id)
        except ValueError:
            logger.info(f"Ignoring malformed publish custom_id: {custom_id}")
            return {"type": DEFERRED_UPDATE_MESSAGE}
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

        async def on_published(public_url: str) -> None:
            await self.discord.edit_original(
                interaction_token=interaction_token, content="",
                embeds=[build_published_embed(slug, public_url)],
                components=build_published_components(slug, public_url),
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
            on_published=on_published,
        )
        asyncio.create_task(self.router.run_panel_publish(ctx, slug))
        return {"type": DEFERRED_CHANNEL_MESSAGE}

    async def _handle_unpublish_component(self, payload: dict[str, Any], custom_id: str) -> dict[str, Any]:
        """An Unpublish button click → run_panel_unpublish in the background, ACK deferred."""
        try:
            slug = slug_from_unpublish_button(custom_id)
        except ValueError:
            logger.info(f"Ignoring malformed unpublish custom_id: {custom_id}")
            return {"type": DEFERRED_UPDATE_MESSAGE}
        interaction_token = payload.get("token", "")
        member = payload.get("member", {})
        user = member.get("user", payload.get("user", {}))

        async def respond(msg: str) -> None:
            await self.discord.edit_original(
                interaction_token=interaction_token, content=msg,
            )

        ctx = CommandContext(
            user_id=user.get("id", ""),
            user_name=user.get("username", "unknown"),
            channel_id=payload.get("channel_id", ""),
            raw_text=f"aiuibuilder unpublish {slug}",
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
        asyncio.create_task(self.router.run_panel_unpublish(ctx, slug))
        return {"type": DEFERRED_CHANNEL_MESSAGE}

    async def _handle_app_select_component(self, payload: dict[str, Any]) -> dict[str, Any]:
        """A dropdown selection from the 'Your apps' list → ephemeral per-project
        menu. Routes run_panel_menu in the background, ACK ephemeral-deferred."""
        data = payload.get("data", {})
        values = data.get("values") or []
        if not values:
            logger.info("Ignoring app-select with no values")
            return {"type": DEFERRED_UPDATE_MESSAGE}
        slug = values[0]
        return await self._handle_panel_route(
            payload, lambda ctx: self.router.run_panel_menu(ctx, slug),
            raw_text=f"aiuibuilder menu {slug}")

    async def _run_guarded(
        self,
        run: Callable[[CommandContext], Awaitable[None]],
        ctx: CommandContext,
        interaction_token: str,
    ) -> None:
        """Run a deferred background task, guaranteeing a terminal follow-up.

        A deferred ACK leaves the interaction "thinking" until something edits
        the original message. If ``run`` raises an unexpected error (anything a
        handler didn't already turn into a user-facing message), edit the
        message with a friendly error so the button never silently hangs."""
        try:
            await run(ctx)
        except Exception:  # noqa: BLE001 — last line of defense for a deferred ACK
            logger.exception("deferred interaction task failed")
            try:
                await self.discord.edit_original(
                    interaction_token=interaction_token,
                    content="⚠️ Something went wrong — please try again.",
                )
            except Exception:  # noqa: BLE001
                logger.exception("failed to deliver error follow-up")

    async def _handle_panel_route(
        self, payload: dict[str, Any], run: Callable[[CommandContext], Awaitable[None]],
        *, raw_text: str = "aiuibuilder menu",
    ) -> dict[str, Any]:
        """Build an ephemeral CommandContext from a component interaction, schedule
        `run(ctx)` in the background, and ACK ephemeral-deferred (flags=64)."""
        interaction_token = payload.get("token", "")
        member = payload.get("member", {})
        user = member.get("user", payload.get("user", {}))
        channel_id = payload.get("channel_id", "")

        async def respond(msg: str) -> None:
            await self.discord.edit_original(
                interaction_token=interaction_token, content=msg,
            )

        async def respond_components(msg: str, components: list, embeds: list | None = None) -> None:
            await self.discord.edit_original(
                interaction_token=interaction_token, content=msg, components=components, embeds=embeds,
            )

        ctx = CommandContext(
            user_id=user.get("id", ""),
            user_name=user.get("username", "unknown"),
            channel_id=channel_id,
            raw_text=raw_text,
            subcommand="aiuibuilder",
            arguments="",
            platform="discord",
            respond=respond,
            respond_components=respond_components,
            metadata={
                "interaction_id": payload.get("id", ""),
                "interaction_token": interaction_token,
                "guild_id": payload.get("guild_id", ""),
            },
        )
        asyncio.create_task(self._run_guarded(run, ctx, interaction_token))
        return {"type": DEFERRED_CHANNEL_MESSAGE, "data": {"flags": 64}}

    async def _handle_modal_submit(self, payload: dict[str, Any]) -> dict[str, Any]:
        """An App Builder modal submission. Extract the description, route to the
        build in the background, and ACK deferred — mirrors the slash-command
        deferred pattern (the watcher posts the link via the bot token later)."""
        data = payload.get("data", {})
        custom_id = data.get("custom_id", "")
        if is_enhance_modal(custom_id):
            try:
                slug = slug_from_enhance_modal(custom_id)
            except ValueError:
                logger.info(f"Ignoring malformed enhance modal custom_id: {custom_id}")
                return {"type": DEFERRED_UPDATE_MESSAGE}
            change = self._extract_modal_value(data, "change")
            interaction_token = payload.get("token", "")
            member = payload.get("member", {})
            user = member.get("user", payload.get("user", {}))
            channel_id = payload.get("channel_id", "")
            notify_channel, notify_channel_rich = self._channel_notifiers(channel_id)

            async def respond(msg: str) -> None:
                await self.discord.edit_original(
                    interaction_token=interaction_token, content=msg,
                )

            ctx = CommandContext(
                user_id=user.get("id", ""),
                user_name=user.get("username", "unknown"),
                channel_id=channel_id,
                raw_text=f"aiuibuilder enhance {slug}",
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
            asyncio.create_task(self.router.run_panel_enhance(ctx, slug, change))
            return {"type": DEFERRED_CHANNEL_MESSAGE}
        if is_sched_modal(custom_id):
            return await self._handle_schedule_modal_submit(payload)
        if is_sched_editmodal(custom_id):
            return self._handle_sched_edit_submit(payload, custom_id)
        if is_link_modal(custom_id):
            return self._handle_link_modal_submit(payload)
        if not is_panel_modal(custom_id):
            logger.info(f"Ignoring unknown modal custom_id: {custom_id}")
            return {"type": DEFERRED_UPDATE_MESSAGE}
        return await self._handle_build_modal_submit(payload, custom_id)

    async def _handle_build_modal_submit(self, payload: dict[str, Any], custom_id: str) -> dict[str, Any]:
        """Build-template modal submit. Open a PRIVATE THREAD for the user, post
        the build there, and ACK ephemerally with a pointer. Falls back to the
        main channel if thread creation fails. Returns an ephemeral deferred
        response within Discord's 3s window; the thread work runs in the
        background (mirrors the fire-and-forget build pattern)."""
        data = payload.get("data", {})
        template_key = template_key_from_modal(custom_id)
        description = self._extract_modal_value(data, DESCRIPTION_INPUT_ID)
        interaction_token = payload.get("token", "")
        member = payload.get("member", {})
        user = member.get("user", payload.get("user", {}))
        user_id = user.get("id", "")
        user_name = user.get("username", "unknown")
        channel_id = payload.get("channel_id", "")

        async def _open_and_build() -> None:
            # Detached task — guard everything so an unexpected error is logged,
            # not silently swallowed (it does two API calls before the build).
            try:
                target = channel_id
                thread_id = await self.discord.create_private_thread(
                    channel_id, f"{template_key or 'app'}-{user_name}"[:90]
                )
                if thread_id:
                    await self.discord.add_thread_member(thread_id, user_id)
                    await self.discord.edit_original(
                        interaction_token=interaction_token,
                        content=f"✅ Opening your private build space → <#{thread_id}>",
                    )
                    target = thread_id

                    async def respond(msg: str) -> None:
                        await self.discord.post_channel_message(target, msg)
                else:
                    async def respond(msg: str) -> None:
                        await self.discord.edit_original(
                            interaction_token=interaction_token, content=msg,
                        )

                notify_channel, notify_channel_rich = self._channel_notifiers(target)
                ctx = CommandContext(
                    user_id=user_id,
                    user_name=user_name,
                    channel_id=target,
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
                    notify_channel=notify_channel,
                    notify_channel_rich=notify_channel_rich,
                )
                await self.router.run_panel_build(ctx, template_key, description)
            except Exception as exc:  # noqa: BLE001
                logger.error("_open_and_build failed user=%s: %s", user_id, exc)

        asyncio.create_task(_open_and_build())
        # Ephemeral deferred ACK (flags=64) — only the clicking user sees it.
        return {"type": DEFERRED_CHANNEL_MESSAGE, "data": {"flags": 64}}

    async def _handle_schedule_modal_submit(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Schedule create modal submit: parse the plain-English 'when', and if
        it's understood, show an ephemeral confirmation card carrying a token.
        No I/O — the schedule is only created once the user clicks Confirm."""
        data = payload.get("data", {})
        what = self._extract_modal_value(data, SCHED_WHAT_INPUT)
        when = self._extract_modal_value(data, SCHED_WHEN_INPUT)
        parsed = parse_when(when)
        if not what or parsed is None:
            return {"type": CHANNEL_MESSAGE_WITH_SOURCE, "data": {
                "content": (
                    "I couldn't read the timing. Try a casual phrase like "
                    "*every 8pm*, *9am everyday*, *every morning*, *every Monday 9am*, "
                    "*every weekday at 8am*, or *every 30 minutes* — all times are Manila (GMT+8)."
                ),
                "flags": 64,
            }}
        cron, human = parsed
        name = f"{human}: {what[:60]}"
        token = uuid.uuid4().hex[:16]
        self._pending_schedules[token] = {"name": name, "cron": cron, "prompt": what}
        # Gate on connector intent: if the task needs Gmail/Drive and the owner
        # hasn't connected it, show Connect buttons instead of the confirm card.
        # The schedule is parked under `token` until they connect + resume.
        member = payload.get("member", {})
        user = member.get("user", payload.get("user", {}))
        owner = await self.router._resolve_email_auto(user.get("id", ""))
        needs = connector_intent.detect(what)
        linked: set[str] = set()
        if "gmail" in needs and await connectors.is_connected("gmail", owner, base_url=settings.gmail_url):
            linked.add("gmail")
        if "drive" in needs and await connectors.is_connected("drive", owner, base_url=settings.gdrive_url):
            linked.add("drive")
        missing = _needs_connect(needs, linked=linked)
        if missing:
            links: list[tuple[str, str]] = []
            if "gmail" in missing:
                links.append(("Gmail", connectors.connect_url(
                    "gmail", owner, public_base=settings.gmail_public_url)))
            if "drive" in missing:
                links.append(("Drive", connectors.connect_url(
                    "drive", owner, public_base=settings.gdrive_public_url)))
            return {"type": CHANNEL_MESSAGE_WITH_SOURCE, "data": {
                "content": (
                    f"📅 **{human}** — {what[:150]}\n"
                    "This task needs access to your account. Connect below (link is valid "
                    "10 min), then hit **✅ I've connected — create it**."
                ),
                "components": build_connect_components(token=token, links=links),
                "flags": 64,
            }}
        return {"type": CHANNEL_MESSAGE_WITH_SOURCE, "data": {
            "content": f"📅 **{human}** — {what[:200]}\nLook right?",
            "components": build_confirm_components(token),
            "flags": 64,
        }}

    async def _create_pending_schedule(
        self, payload: dict[str, Any], token: str, interaction_token: str,
    ) -> None:
        """Shared create path for Confirm + 'I've connected' resume: pop the parked
        schedule, resolve the user's private thread, create the schedule, and edit
        the card. Guarantees a terminal follow-up even on failure."""
        pending = self._pending_schedules.pop(token, None)
        member = payload.get("member", {})
        user = member.get("user", payload.get("user", {}))
        user_id = user.get("id", "")
        user_name = user.get("username", "unknown")
        channel_id = payload.get("channel_id", "")
        try:
            if not pending:
                await self.discord.edit_original(
                    interaction_token=interaction_token,
                    content="That schedule request expired — please set it up again.",
                    components=[],
                )
                return
            # Results land in a private thread (created/reused) so they stay
            # visible only to this user. Fall back to the channel if thread
            # creation fails.
            target = channel_id
            thread_id = await self.router.get_user_thread(user_id)
            if not thread_id:
                thread_id = await self.discord.create_private_thread(
                    channel_id, f"schedules-{user_name}"[:90]
                )
                if thread_id:
                    await self.router.set_user_thread(user_id, thread_id)
            if thread_id:
                await self.discord.add_thread_member(thread_id, user_id)
                target = thread_id

            async def respond(msg: str) -> None:
                await self.discord.edit_original(
                    interaction_token=interaction_token, content=msg,
                    components=[],  # drop the buttons
                )

            ctx = CommandContext(
                user_id=user_id, user_name=user_name, channel_id=channel_id,
                raw_text="schedules create", subcommand="aiuibuilder",
                arguments="", platform="discord", respond=respond,
                metadata={
                    "interaction_id": payload.get("id", ""),
                    "interaction_token": interaction_token,
                    "guild_id": payload.get("guild_id", ""),
                },
            )
            await self.router.run_schedule_create(
                ctx, name=pending["name"], cron=pending["cron"],
                prompt=pending["prompt"], delivery_channel_id=target,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("_create_pending_schedule failed user=%s: %s", user_id, exc)
            try:
                await self.discord.edit_original(
                    interaction_token=interaction_token,
                    content="⚠️ Couldn't save that schedule — please try again.",
                    components=[],
                )
            except Exception:  # noqa: BLE001
                logger.exception("failed to deliver schedule-create error follow-up")

    async def _handle_schedule_confirm(self, payload: dict[str, Any], custom_id: str) -> dict[str, Any]:
        """Confirm button: create the parked schedule in the background. ACK
        ephemeral-deferred (type 6) so the follow-up edits the card in place and
        clears its buttons — preventing a second Confirm on a stale card."""
        try:
            token = token_from_confirm(custom_id)
        except ValueError:
            token = ""
        interaction_token = payload.get("token", "")
        asyncio.create_task(self._create_pending_schedule(payload, token, interaction_token))
        return {"type": DEFERRED_UPDATE_MESSAGE}

    async def _handle_connect_resume(self, payload: dict[str, Any], custom_id: str) -> dict[str, Any]:
        """'I've connected — create it' → re-check connection; if satisfied, create
        the parked schedule. Otherwise tell the user what's still missing."""
        try:
            token = token_from_connect_resume(custom_id)
        except ValueError:
            token = ""
        interaction_token = payload.get("token", "")
        member = payload.get("member", {})
        user = member.get("user", payload.get("user", {}))
        user_id = user.get("id", "")

        async def _do() -> None:
            try:
                pending = self._pending_schedules.get(token)
                if not pending:
                    await self.discord.edit_original(
                        interaction_token=interaction_token,
                        content="That request expired — please set it up again.",
                        components=[],
                    )
                    return
                owner = await self.router._resolve_email_auto(user_id)
                needs = connector_intent.detect(pending["prompt"])
                linked: set[str] = set()
                if "gmail" in needs and await connectors.is_connected("gmail", owner, base_url=settings.gmail_url):
                    linked.add("gmail")
                if "drive" in needs and await connectors.is_connected("drive", owner, base_url=settings.gdrive_url):
                    linked.add("drive")
                missing = _needs_connect(needs, linked=linked)
                if missing:
                    await self.discord.edit_original(
                        interaction_token=interaction_token,
                        content=(f"Still not connected: {', '.join(missing)}. "
                                 "Connect, then tap **✅ I've connected — create it** again."),
                    )
                    return
                await self._create_pending_schedule(payload, token, interaction_token)
            except Exception as exc:  # noqa: BLE001
                logger.error("_handle_connect_resume failed user=%s: %s", user_id, exc)
                try:
                    await self.discord.edit_original(
                        interaction_token=interaction_token,
                        content="⚠️ Something went wrong — please try again.",
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("failed to deliver connect-resume error follow-up")

        asyncio.create_task(_do())
        return {"type": DEFERRED_UPDATE_MESSAGE}

    async def _handle_sched_open(self, payload: dict[str, Any]) -> dict[str, Any]:
        """'Open my schedules' (in #app-builder) → post the dashboard into the
        user's private thread (create/reuse), and point the ephemeral ACK at it."""
        interaction_token = payload.get("token", "")
        member = payload.get("member", {})
        user = member.get("user", payload.get("user", {}))
        user_id = user.get("id", "")
        user_name = user.get("username", "unknown")
        channel_id = payload.get("channel_id", "")

        async def _do() -> None:
            try:
                dash = await self.router.dashboard_payload(user_id)
                if dash is None:
                    await self.discord.edit_original(
                        interaction_token=interaction_token,
                        content="Your Discord account isn't linked yet. Hit **🔗 Link my account** first.",
                    )
                    return
                thread_id = await self.router.get_user_thread(user_id)
                if not thread_id:
                    thread_id = await self.discord.create_private_thread(
                        channel_id, f"schedules-{user_name}"[:90]
                    )
                    if thread_id:
                        await self.router.set_user_thread(user_id, thread_id)
                if thread_id:
                    await self.discord.add_thread_member(thread_id, user_id)
                    await self.discord.post_channel_message(
                        thread_id, dash["content"], components=dash["components"])
                    await self.discord.edit_original(
                        interaction_token=interaction_token,
                        content=f"📅 Your schedules are in <#{thread_id}>",
                    )
                else:
                    # Couldn't open a thread — fall back to an ephemeral dashboard.
                    await self.discord.edit_original(
                        interaction_token=interaction_token,
                        content=dash["content"], components=dash.get("components"),
                    )
            except Exception as exc:  # noqa: BLE001
                logger.error("_handle_sched_open failed user=%s: %s", user_id, exc)
                await self.discord.edit_original(
                    interaction_token=interaction_token,
                    content="Couldn't open your schedules — please try again.",
                )

        asyncio.create_task(_do())
        return {"type": DEFERRED_CHANNEL_MESSAGE, "data": {"flags": 64}}

    def _handle_link_modal_submit(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Link modal submit: validate email, then (background) record the request
        and post an Approve/Reject card to the admin channel."""
        data = payload.get("data", {})
        email = self._extract_modal_value(data, LINK_EMAIL_INPUT)
        member = payload.get("member", {})
        user = member.get("user", payload.get("user", {}))
        user_id = user.get("id", "")
        user_name = user.get("username", "unknown")
        interaction_token = payload.get("token", "")
        if not _valid_email(email):
            return {"type": CHANNEL_MESSAGE_WITH_SOURCE, "data": {
                "content": "That doesn't look like a valid email — try again.",
                "flags": 64,
            }}

        async def _do() -> None:
            try:
                await self.router.request_link(user_id, user_name, email)
                admin_channel = settings.discord_alert_channel_id
                if admin_channel:
                    await self.discord.post_channel_message(
                        admin_channel,
                        f"🔗 **Link request** — <@{user_id}> ({user_name}) → `{email}`",
                        components=build_link_request_components(user_id),
                    )
                await self.discord.edit_original(
                    interaction_token=interaction_token,
                    content="✅ Request sent — an admin will review it shortly.",
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("link request failed user=%s: %s", user_id, exc)
                await self.discord.edit_original(
                    interaction_token=interaction_token,
                    content="Couldn't send your request — please try again.",
                )

        asyncio.create_task(_do())
        return {"type": DEFERRED_CHANNEL_MESSAGE, "data": {"flags": 64}}

    async def _handle_link_decision(
        self, payload: dict[str, Any], custom_id: str, *, approve: bool,
    ) -> dict[str, Any]:
        """Admin Approve/Reject button on a link request → update DB + the message."""
        try:
            discord_id = (id_from_link_approve(custom_id) if approve
                          else id_from_link_reject(custom_id))
        except ValueError:
            return {"type": DEFERRED_UPDATE_MESSAGE}
        interaction_token = payload.get("token", "")
        member = payload.get("member", {})
        admin = member.get("user", payload.get("user", {}))

        async def _do() -> None:
            try:
                if approve:
                    await self.router.approve_link(discord_id, decided_by=admin.get("username", ""))
                    text = f"✅ Approved <@{discord_id}>"
                else:
                    await self.router.reject_link(discord_id)
                    text = f"✖ Rejected <@{discord_id}>"
                await self.discord.edit_original(
                    interaction_token=interaction_token, content=text, components=[],
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("link decision failed id=%s: %s", discord_id, exc)

        asyncio.create_task(_do())
        return {"type": DEFERRED_UPDATE_MESSAGE}

    async def _handle_sched_edit_open(self, payload: dict[str, Any], custom_id: str) -> dict[str, Any]:
        """Edit button → fetch the schedule, open a pre-filled modal. Must respond
        with the modal synchronously (Discord can't defer-then-modal)."""
        try:
            schedule_id = id_from_edit(custom_id)
        except ValueError:
            return {"type": DEFERRED_UPDATE_MESSAGE}
        member = payload.get("member", {})
        user = member.get("user", payload.get("user", {}))
        data = await self.router.get_schedule_for_edit(user.get("id", ""), schedule_id)
        if data is None:
            return {"type": CHANNEL_MESSAGE_WITH_SOURCE, "data": {
                "content": "Couldn't load that schedule (are you linked?).",
                "flags": 64,
            }}
        return {"type": MODAL, "data": build_schedule_edit_modal(
            schedule_id, what=data["what"], when=data["when"])}

    def _handle_sched_edit_submit(self, payload: dict[str, Any], custom_id: str) -> dict[str, Any]:
        """Edit modal submit: re-parse the when, then update the schedule."""
        try:
            schedule_id = id_from_editmodal(custom_id)
        except ValueError:
            return {"type": DEFERRED_UPDATE_MESSAGE}
        data = payload.get("data", {})
        what = self._extract_modal_value(data, SCHED_WHAT_INPUT)
        when = self._extract_modal_value(data, SCHED_WHEN_INPUT)
        parsed = parse_when(when)
        if not what or parsed is None:
            return {"type": CHANNEL_MESSAGE_WITH_SOURCE, "data": {
                "content": ("I couldn't read that time. Try 'every morning', "
                            "'every Monday 9am', or 'every 30 minutes'."),
                "flags": 64,
            }}
        cron, human = parsed
        name = f"{human}: {what[:60]}"
        member = payload.get("member", {})
        user = member.get("user", payload.get("user", {}))
        interaction_token = payload.get("token", "")

        async def respond(msg: str) -> None:
            await self.discord.edit_original(interaction_token=interaction_token, content=msg)

        ctx = CommandContext(
            user_id=user.get("id", ""), user_name=user.get("username", "unknown"),
            channel_id=payload.get("channel_id", ""), raw_text="schedules edit",
            subcommand="aiuibuilder", arguments="", platform="discord", respond=respond,
            metadata={"interaction_id": payload.get("id", ""),
                      "interaction_token": interaction_token,
                      "guild_id": payload.get("guild_id", "")},
        )
        asyncio.create_task(self.router.run_schedule_edit(
            ctx, schedule_id, name=name, cron=cron, prompt=what))
        return {"type": DEFERRED_CHANNEL_MESSAGE, "data": {"flags": 64}}

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
