"""Discord interaction handler for /aiui slash commands."""
import asyncio
import logging
import re
import uuid
from typing import Any, Awaitable, Callable

from clients.discord import DiscordClient
from clients import connectors
from config import settings
from handlers.commands import CommandRouter, CommandContext
from handlers import connector_intent
from handlers.schedule_parse import parse_when
from handlers import schedule_picker
from datetime import datetime, timedelta, timezone

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match((email or "").strip()))


def _manila_now() -> datetime:
    """Current wall-clock time in Manila as a naive datetime. Manila is a fixed
    UTC+8 with no DST, so a constant offset avoids depending on the IANA tz
    database (tzdata) being present in the webhook-handler container."""
    return (datetime.now(timezone.utc) + timedelta(hours=8)).replace(tzinfo=None)


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
    is_app_delete, slug_from_delete_button,
    is_del_confirm, slug_from_del_confirm,
    is_del_cancel, slug_from_del_cancel,
    build_delete_confirm_components,
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
    is_panel_new,
    is_panel_myapps,
    build_template_picker_components,
    build_apps_select_components,
)
from handlers import cronjob_panel as cron
from handlers import onboarding
from handlers import recruiting_panel
from handlers import recruiting_review as rr
from handlers import video_panel as vid

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
CHANNEL_MESSAGE = 4        # CHANNEL_MESSAGE_WITH_SOURCE — new (ephemeral) message
UPDATE_MESSAGE = 7         # edit the message the component is attached to
EPHEMERAL = 64             # message flag


class DiscordCommandHandler:
    """Handles Discord interaction payloads."""

    def __init__(self, discord_client: DiscordClient, command_router: CommandRouter):
        self.discord = discord_client
        self.router = command_router
        # token -> {name, cron, prompt}: parsed-but-unconfirmed schedules. Popped
        # on Confirm/Cancel. In-memory and per-process (matches the rest of the
        # Discord flow); abandoned entries are tiny and harmless.
        self._pending_schedules: dict[str, dict] = {}
        # token -> accumulating picker selections (kind/freq/hour/weekday/date)
        # for the click date/time picker; resolved to a schedule on task-modal submit.
        self._pending_picks: dict[str, dict] = {}
        # Strong refs to fire-and-forget background tasks so they can't be
        # garbage-collected mid-flight; cleared by the done-callback.
        self._bg_tasks: set = set()

    def _spawn(self, coro) -> "asyncio.Task":
        """Launch a background task, keep a strong reference, and log any
        exception (a bare create_task drops the ref and swallows failures, so
        a button/modal/slash action could silently vanish)."""
        task = asyncio.create_task(coro)
        self._bg_tasks.add(task)
        task.add_done_callback(self._on_bg_task_done)
        return task

    def _on_bg_task_done(self, task: "asyncio.Task") -> None:
        self._bg_tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error("Discord background task failed: %r", exc, exc_info=exc)

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
        if data.get("name") == "video":
            return await self._handle_video_command(payload)
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
        attachment = self._first_attachment(data)

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
            attachment=attachment,
        )

        # Fire-and-forget: process in background, edit deferred response
        self._spawn(self.router.execute(ctx))

        # Immediate ACK — tells Discord we'll follow up (type 5 = DEFERRED)
        return {"type": DEFERRED_CHANNEL_MESSAGE}

    def _channel_notifiers(
        self, channel_id: str
    ) -> tuple[Callable[[str], Awaitable[None]], Callable[[str, str, str], Awaitable[None]]]:
        """Build the plain + rich channel notifiers for a ctx. The rich one
        posts a build-ready message with a Publish button."""
        async def notify_channel(msg: str) -> None:
            await self.discord.post_channel_message(channel_id, msg)

        async def notify_channel_rich(msg: str, slug: str, preview_url: str, owner: str) -> None:
            await self.discord.post_channel_message(
                channel_id, "", embeds=[build_ready_embed(slug, preview_url, msg)],
                components=build_ready_components(slug, preview_url, owner=owner),
            )
        return notify_channel, notify_channel_rich

    async def _handle_message_component(self, payload: dict[str, Any]) -> dict[str, Any]:
        """A button click. App Builder template buttons open a modal; Enhance
        opens an enhance modal; Publish/Unpublish route to the background; any
        other component is a harmless no-op (never a 500)."""
        data = payload.get("data", {})
        custom_id = data.get("custom_id", "")
        if cron.is_cron(custom_id):
            return await self._handle_cron_component(payload, custom_id)
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
        # Delete confirm/cancel checked before the bare delete button: their ids
        # ("aiuibuild:del-confirm:" / "aiuibuild:del-cancel:") are disjoint from
        # the delete prefix ("aiuibuild:del:"), but order keeps intent explicit.
        if is_del_confirm(custom_id):
            return await self._handle_delete_confirm_component(payload, custom_id)
        if is_del_cancel(custom_id):
            return {"type": UPDATE_MESSAGE,
                    "data": {"content": "Cancelled.", "components": []}}
        if is_app_delete(custom_id):
            try:
                slug = slug_from_delete_button(custom_id)
            except ValueError:
                logger.info(f"Ignoring malformed delete custom_id: {custom_id}")
                return {"type": DEFERRED_UPDATE_MESSAGE}
            return self._ephemeral_components(
                f"Delete `{slug}`? This can't be undone.",
                build_delete_confirm_components(slug), update=False)
        # --- Schedules (aiuisched:*) ---
        if is_sched_new(custom_id):
            token = uuid.uuid4().hex[:16]
            self._pending_picks[token] = {}
            card = schedule_picker.build_kind_card(token)
            return {"type": CHANNEL_MESSAGE_WITH_SOURCE, "data": {
                "content": card["content"], "components": card["components"], "flags": 64}}
        if custom_id.startswith(schedule_picker.PICK_PREFIX):
            return await self._handle_pick_component(payload, custom_id)
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
        if is_connect_resume(custom_id):
            return await self._handle_connect_resume(payload, custom_id)
        if is_sched_confirm(custom_id):
            return await self._handle_schedule_confirm(payload, custom_id)
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

        if is_panel_new(custom_id):
            return await self._handle_build_new(payload)

        if is_panel_myapps(custom_id):
            return await self._handle_my_apps(payload)

        # --- Recruiting outreach (aiuiout:*) ---
        if recruiting_panel.is_out_find(custom_id):
            return {"type": MODAL, "data": recruiting_panel.build_outreach_modal()}

        if recruiting_panel.is_rev_find(custom_id):
            return {"type": MODAL, "data": recruiting_panel.build_reverse_modal()}

        if rr.is_out_send(custom_id):
            return await self._handle_outreach_send(payload, custom_id)
        if rr.is_out_refresh(custom_id):
            return await self._handle_outreach_refresh(payload, custom_id)
        if rr.is_out_sel(custom_id):
            return await self._handle_outreach_select(payload, custom_id, data)
        if rr.is_out_edit(custom_id):
            values = data.get("values") or []
            if not values:
                return {"type": DEFERRED_UPDATE_MESSAGE}
            return await self._handle_outreach_edit_open(payload, custom_id, values[0])

        # --- Video studio (aiuivid:*) ---
        if vid.is_vid_new(custom_id):
            return {"type": MODAL, "data": vid.build_video_modal()}
        if vid.is_vid_list(custom_id):
            return await self._handle_video_route(
                payload, lambda ctx: self.router.run_video_list(ctx),
                raw_text="video list")
        if vid.is_vid_style(custom_id) or vid.is_vid_voice(custom_id):
            values = data.get("values") or []
            if not values:
                return {"type": DEFERRED_UPDATE_MESSAGE}
            is_style = vid.is_vid_style(custom_id)
            try:
                job_id = (vid.job_from_style(custom_id) if is_style
                          else vid.job_from_voice(custom_id))
            except ValueError:
                return {"type": DEFERRED_UPDATE_MESSAGE}
            field = {"style": values[0]} if is_style else {"voice": values[0]}
            self._spawn(self._run_video_set(payload, job_id, field))
            return {"type": DEFERRED_UPDATE_MESSAGE}
        if vid.is_vid_generate(custom_id):
            try:
                job_id = vid.job_from_generate(custom_id)
            except ValueError:
                return {"type": DEFERRED_UPDATE_MESSAGE}
            return await self._handle_video_route(
                payload, lambda ctx, j=job_id: self.router.run_video_generate(ctx, j),
                raw_text="video generate")
        if vid.is_vid_refine(custom_id):
            try:
                job_id = vid.job_from_refine(custom_id)
            except ValueError:
                return {"type": DEFERRED_UPDATE_MESSAGE}
            return {"type": MODAL, "data": vid.build_refine_modal(job_id)}
        if vid.is_vid_apply(custom_id):
            try:
                job_id = vid.job_from_apply(custom_id)
            except ValueError:
                return {"type": DEFERRED_UPDATE_MESSAGE}
            return await self._handle_video_route(
                payload, lambda ctx, j=job_id: self.router.run_video_apply(ctx, j),
                raw_text="video apply")
        if vid.is_vid_version(custom_id):
            values = data.get("values") or []
            if not values:
                return {"type": DEFERRED_UPDATE_MESSAGE}
            try:
                job_id = vid.job_from_version(custom_id)
                version_no = int(values[0])
            except ValueError:
                return {"type": DEFERRED_UPDATE_MESSAGE}
            return await self._handle_video_route(
                payload,
                lambda ctx, j=job_id, n=version_no: self.router.run_video_revert(ctx, j, n),
                raw_text="video revert")

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
            owner = await self.router._resolve_email_auto(user_id)
            await self.discord.edit_original(
                interaction_token=interaction_token, content="",
                embeds=[build_published_embed(slug, public_url)],
                components=build_published_components(
                    slug, public_url, owner=owner),
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
        self._spawn(self.router.run_panel_publish(ctx, slug))
        return {"type": DEFERRED_CHANNEL_MESSAGE}

    def _out_ctx(self, payload: dict[str, Any]) -> CommandContext:
        """Build a CommandContext for an outreach review component interaction.
        Its ``edit_message``/``respond`` edit the component's own message in
        place via the interaction token."""
        token = payload.get("token", "")
        member = payload.get("member", {})
        user = member.get("user", payload.get("user", {}))

        async def edit_message(msg: dict) -> None:
            await self.discord.edit_original(
                interaction_token=token, content=msg.get("content", ""),
                embeds=msg.get("embeds", []), components=msg.get("components", []))

        async def respond(text: str) -> None:
            await self.discord.edit_original(interaction_token=token, content=text)

        return CommandContext(
            user_id=user.get("id", ""), user_name=user.get("username", "unknown"),
            channel_id=payload.get("channel_id", ""), raw_text="outreach",
            subcommand="outreach", arguments="", platform="discord",
            respond=respond, edit_message=edit_message,
            metadata={"interaction_id": payload.get("id", ""), "interaction_token": token,
                      "guild_id": payload.get("guild_id", "")})

    async def _handle_outreach_select(
        self, payload: dict[str, Any], custom_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Recipient multi-select changed → patch the selection, re-render in place."""
        task_id = rr.task_id_from_sel(custom_id)
        selected = data.get("values") or []
        ctx = self._out_ctx(payload)
        self._spawn(self.router.run_outreach_select(ctx, task_id, selected, "", ""))
        return {"type": DEFERRED_UPDATE_MESSAGE}

    async def _handle_outreach_refresh(self, payload: dict[str, Any], custom_id: str) -> dict[str, Any]:
        """Refresh button → re-fetch candidates (no patch), re-render in place."""
        task_id = rr.task_id_from_refresh(custom_id)
        ctx = self._out_ctx(payload)
        self._spawn(self.router.run_outreach_select(ctx, task_id, None, "", ""))
        return {"type": DEFERRED_UPDATE_MESSAGE}

    async def _handle_outreach_edit_open(
        self, payload: dict[str, Any], custom_id: str, cid: str) -> dict[str, Any]:
        """Edit dropdown picked a candidate → open a prefilled edit modal. Must
        respond with the modal synchronously (Discord can't defer-then-modal)."""
        task_id = rr.task_id_from_edit(custom_id)
        member = payload.get("member", {})
        user = member.get("user", payload.get("user", {}))
        try:
            email = await self.router._resolve_email_auto(user.get("id", ""))
            st = await self.router._tasks_client.get_outreach_candidates(email, task_id)
        except Exception:  # noqa: BLE001
            return {"type": DEFERRED_UPDATE_MESSAGE}
        cand = next((c for c in st.get("candidates", []) if c.get("id") == cid), None)
        if cand is None:
            return {"type": DEFERRED_UPDATE_MESSAGE}
        return {"type": MODAL, "data": rr.build_edit_modal(task_id, cand)}

    async def _handle_outreach_editmodal(
        self, payload: dict[str, Any], custom_id: str, values: dict[str, str]) -> dict[str, Any]:
        """Edit modal submit → save the edited candidate, re-render in place."""
        task_id, cid = rr.ids_from_editmodal(custom_id)
        ctx = self._out_ctx(payload)
        self._spawn(self.router.run_outreach_edit_submit(
            ctx, task_id, cid, values.get("email", ""), values.get("subject", ""),
            values.get("body", ""), "", ""))
        return {"type": DEFERRED_UPDATE_MESSAGE}

    async def _handle_outreach_send(self, payload: dict[str, Any], custom_id: str) -> dict[str, Any]:
        """Send button → email the selected candidates, lock the message in place."""
        task_id = rr.task_id_from_send(custom_id)
        ctx = self._out_ctx(payload)
        self._spawn(self.router.run_outreach_send(ctx, task_id))
        return {"type": DEFERRED_UPDATE_MESSAGE}

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
        self._spawn(self.router.run_panel_unpublish(ctx, slug))
        return {"type": DEFERRED_CHANNEL_MESSAGE}

    async def _handle_delete_confirm_component(self, payload: dict[str, Any], custom_id: str) -> dict[str, Any]:
        """A delete-confirm button click → run_panel_delete in the background, ACK deferred."""
        try:
            slug = slug_from_del_confirm(custom_id)
        except ValueError:
            logger.info(f"Ignoring malformed delete-confirm custom_id: {custom_id}")
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
            raw_text=f"aiuibuilder delete {slug}",
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
        self._spawn(self.router.run_panel_delete(ctx, slug))
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

    async def _handle_cron_component(self, payload: dict[str, Any], custom_id: str) -> dict[str, Any]:
        data = payload.get("data", {})
        values = data.get("values") or []

        if cron.is_new(custom_id):
            return self._ephemeral_components(
                "How often should it run?", cron.build_frequency_components(), update=False)

        if cron.is_freq_button(custom_id):
            freq = cron.freq_from_button(custom_id)
            if freq == "hourly":
                return {"type": MODAL, "data": cron.build_create_modal("0 * * * *")}
            if freq == "custom":
                return {"type": MODAL, "data": cron.build_custom_cron_modal()}
            if freq == "weekly":
                return self._ephemeral_components(
                    "Which day?", cron.build_dow_select(), update=True)
            return self._ephemeral_components(
                "At what time? (Asia/Manila)", cron.build_hour_select(freq), update=True)

        if cron.is_dow_select(custom_id):
            if not values:
                return {"type": DEFERRED_UPDATE_MESSAGE}
            return self._ephemeral_components(
                "At what time? (Asia/Manila)",
                cron.build_hour_select("weekly", dow=values[0]), update=True)

        if cron.is_hour_select(custom_id):
            if not values:
                return {"type": DEFERRED_UPDATE_MESSAGE}
            try:
                freq, dow = cron.hour_context_from_select(custom_id)
                cron_expr = cron.cron_from_choice(freq, hour=int(values[0]), dow=dow)
            except ValueError:
                logger.info(f"Ignoring malformed cron hour custom_id: {custom_id}")
                return {"type": DEFERRED_UPDATE_MESSAGE}
            return {"type": MODAL, "data": cron.build_create_modal(cron_expr)}

        return await self._handle_cron_manage_component(payload, custom_id)

    async def _handle_cron_manage_component(self, payload: dict[str, Any], custom_id: str) -> dict[str, Any]:
        data = payload.get("data", {})
        values = data.get("values") or []

        if cron.is_list(custom_id):
            return await self._handle_panel_route(
                payload, lambda ctx: self.router.run_cron_list(ctx),
                raw_text="cronjob list")

        if cron.is_schedule_select(custom_id):
            if not values:
                return {"type": DEFERRED_UPDATE_MESSAGE}
            sid = values[0]
            return await self._handle_panel_route(
                payload, lambda ctx: self.router.run_cron_menu(ctx, sid),
                raw_text=f"cronjob menu {sid}")

        if cron.is_action(custom_id, "runnow"):
            sid = cron.id_from_action(custom_id, "runnow")
            return await self._handle_panel_route(
                payload, lambda ctx: self.router.run_cron_runnow(ctx, sid),
                raw_text="cronjob runnow")

        if cron.is_action(custom_id, "pause"):
            sid = cron.id_from_action(custom_id, "pause")
            return await self._handle_panel_route(
                payload, lambda ctx: self.router.run_cron_pause(ctx, sid),
                raw_text="cronjob pause")

        if cron.is_action(custom_id, "resume"):
            sid = cron.id_from_action(custom_id, "resume")
            return await self._handle_panel_route(
                payload, lambda ctx: self.router.run_cron_resume(ctx, sid),
                raw_text="cronjob resume")

        if cron.is_action(custom_id, "delete"):
            sid = cron.id_from_action(custom_id, "delete")
            return self._ephemeral_components(
                "Delete this schedule? This can't be undone.",
                cron.build_delete_confirm(sid), update=True)

        if cron.is_action(custom_id, "delconfirm"):
            sid = cron.id_from_action(custom_id, "delconfirm")
            return await self._handle_panel_route(
                payload, lambda ctx: self.router.run_cron_delete(ctx, sid),
                raw_text="cronjob delete")

        if custom_id == cron.DELCANCEL:
            return self._ephemeral_components("Cancelled.", [], update=True)

        logger.info(f"Ignoring unknown cron custom_id: {custom_id}")
        return {"type": DEFERRED_UPDATE_MESSAGE}

    @staticmethod
    def _ephemeral_components(content: str, components: list[dict], *, update: bool) -> dict[str, Any]:
        """Synchronous component response. update=True edits the current (ephemeral)
        message (type 7); update=False posts a new ephemeral message (type 4)."""
        return {
            "type": UPDATE_MESSAGE if update else CHANNEL_MESSAGE,
            "data": {"content": content, "components": components, "flags": EPHEMERAL},
        }

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
        self._spawn(run(ctx))
        return {"type": DEFERRED_CHANNEL_MESSAGE, "data": {"flags": 64}}

    async def _handle_video_route(
        self, payload: dict[str, Any], run: Callable[[CommandContext], Awaitable[None]],
        *, raw_text: str = "video",
    ) -> dict[str, Any]:
        """Build an ephemeral CommandContext for a video-studio component/modal
        interaction, schedule `run(ctx)` in the background, and ACK
        ephemeral-deferred (flags=64).

        Unlike `_handle_panel_route`, this binds the channel notifiers
        (`notify_channel` / `notify_channel_rich`) AND a channel-message poster
        (`notify_channel_msg`): generate/apply/revert gate their render watcher
        on `notify_channel` (and `_deliver_video` posts the finished MP4 to
        `channel_id` + the Refine/version controls via `notify_channel_msg`),
        and refine posts its proposal via `notify_channel_msg`. The interaction
        happens inside the user's private video thread, so `channel_id` is that
        thread and results land there."""
        interaction_token = payload.get("token", "")
        member = payload.get("member", {})
        user = member.get("user", payload.get("user", {}))
        channel_id = payload.get("channel_id", "")
        notify_channel, notify_channel_rich = self._channel_notifiers(channel_id)

        async def respond(msg: str) -> None:
            await self.discord.edit_original(
                interaction_token=interaction_token, content=msg,
            )

        async def respond_components(msg: str, components: list, embeds: list | None = None) -> None:
            await self.discord.edit_original(
                interaction_token=interaction_token, content=msg, components=components, embeds=embeds,
            )

        async def notify_channel_msg(msg: dict) -> None:
            await self.discord.post_channel_message(
                channel_id, content=msg.get("content", ""),
                embeds=msg.get("embeds"), components=msg.get("components"),
            )

        ctx = CommandContext(
            user_id=user.get("id", ""),
            user_name=user.get("username", "unknown"),
            channel_id=channel_id,
            raw_text=raw_text,
            subcommand="video",
            arguments="",
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
            notify_channel_msg=notify_channel_msg if channel_id else None,
        )
        self._spawn(run(ctx))
        return {"type": DEFERRED_CHANNEL_MESSAGE, "data": {"flags": 64}}

    async def _run_video_set(self, payload: dict[str, Any], job_id: str, field: dict) -> None:
        """Persist a style/voice pick on the draft. The select interaction is
        ACK'd with DEFERRED_UPDATE_MESSAGE (no message edit), so this needs no
        responder — the runner saves the field and logs any failure."""
        member = payload.get("member", {})
        user = member.get("user", payload.get("user", {}))
        ctx = CommandContext(
            user_id=user.get("id", ""), user_name=user.get("username", "unknown"),
            channel_id=payload.get("channel_id", ""), raw_text="video set",
            subcommand="video", arguments="", platform="discord",
            respond=lambda m: asyncio.sleep(0))
        await self.router.run_video_set_field(ctx, job_id, **field)

    async def _handle_video_command(self, payload: dict[str, Any]) -> dict[str, Any]:
        """`/video add` (push the attached screenshots onto the current draft) and
        `/video list` (list the caller's videos). ACK ephemeral-deferred."""
        data = payload.get("data", {})
        options = data.get("options", [])
        sub = options[0].get("name") if options else "list"
        interaction_token = payload.get("token", "")
        member = payload.get("member", {})
        user = member.get("user", payload.get("user", {}))
        channel_id = payload.get("channel_id", "")
        notify_channel, notify_channel_rich = self._channel_notifiers(channel_id)

        async def respond(msg: str) -> None:
            await self.discord.edit_original(interaction_token=interaction_token, content=msg)

        async def respond_components(msg: str, components: list, embeds: list | None = None) -> None:
            await self.discord.edit_original(
                interaction_token=interaction_token, content=msg, components=components)

        ctx = CommandContext(
            user_id=user.get("id", ""), user_name=user.get("username", "unknown"),
            channel_id=channel_id, raw_text=f"video {sub}", subcommand="video",
            arguments="", platform="discord", respond=respond,
            respond_components=respond_components,
            metadata={"interaction_token": interaction_token, "guild_id": payload.get("guild_id", "")},
            notify_channel=notify_channel if channel_id else None,
            notify_channel_rich=notify_channel_rich if channel_id else None)

        if sub == "add":
            urls = [a["url"] for a in self._all_attachments(data) if a.get("url")]
            self._spawn(self.router.run_video_add(ctx, urls))
        else:
            self._spawn(self.router.run_video_list(ctx))
        return {"type": DEFERRED_CHANNEL_MESSAGE, "data": {"flags": 64}}

    async def _handle_video_new_modal(self, payload: dict[str, Any]) -> dict[str, Any]:
        """'New video' modal submit → create a draft, open the user's private
        video thread, point the ephemeral ACK at it, post the voice-sample MP3s
        (best-effort) and the studio controls there. Mirrors the build-modal
        fire-and-forget pattern; ACK is ephemeral-deferred within 3s."""
        data = payload.get("data", {})
        title = self._extract_modal_value(data, vid.TITLE_INPUT)
        prompt = self._extract_modal_value(data, vid.PROMPT_INPUT)
        interaction_token = payload.get("token", "")
        member = payload.get("member", {})
        user = member.get("user", payload.get("user", {}))
        user_id = user.get("id", "")
        user_name = user.get("username", "unknown")
        channel_id = payload.get("channel_id", "")

        async def _open_studio() -> None:
            try:
                email = await self.router._resolve_email(user_id)
                if email is None:
                    await self.discord.edit_original(
                        interaction_token=interaction_token,
                        content=onboarding.not_linked_text_discord(),
                        components=onboarding.link_button_row(),
                    )
                    return
                draft = await self.router._tasks_client.create_video_draft(
                    email, title, prompt, "clean_product_demo", "amy")
                job_id = draft["id"]
                thread_id = await self._get_or_make_thread(
                    user_id, channel_id, user_name, kind="video")
                target = thread_id or channel_id
                if thread_id:
                    await self.discord.edit_original(
                        interaction_token=interaction_token,
                        content=f"Your video studio is ready → <#{thread_id}>",
                    )
                else:
                    await self.discord.edit_original(
                        interaction_token=interaction_token,
                        content="Your video studio is ready below.",
                    )
                voices = (await self.router._tasks_client.get_video_voices()).get("voices", [])
                # Best-effort: post the voice preview clips so the user can listen
                # before picking. A failure here must never block the studio.
                try:
                    files: list[tuple[str, bytes, str]] = []
                    for v in voices[:6]:
                        sample_url = v.get("sample_url")
                        vid_id = v.get("id") or "voice"
                        if not sample_url:
                            continue
                        blob = await self.router._tasks_client.fetch_bytes(sample_url)
                        files.append((f"{vid_id}.mp3", blob, "audio/mpeg"))
                    if files:
                        await self.discord.post_channel_file(
                            target, files[:10],
                            content="Voice previews — listen, then pick a voice below:")
                except Exception as exc:  # noqa: BLE001
                    logger.warning("video voice-sample post failed user=%s: %s", user_id, exc)
                await self.discord.post_channel_message(
                    target,
                    "Pick a style + voice, add 1-12 screenshots with `/video add`, "
                    "then hit **Generate video**.",
                    components=vid.build_studio_components(job_id, voices),
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("_handle_video_new_modal failed user=%s: %s", user_id, exc)
                try:
                    await self.discord.edit_original(
                        interaction_token=interaction_token,
                        content="Couldn't open the video studio — please try again.",
                    )
                except Exception:  # noqa: BLE001
                    pass

        self._spawn(_open_studio())
        return {"type": DEFERRED_CHANNEL_MESSAGE, "data": {"flags": 64}}

    async def _handle_modal_submit(self, payload: dict[str, Any]) -> dict[str, Any]:
        """An App Builder modal submission. Extract the description, route to the
        build in the background, and ACK deferred — mirrors the slash-command
        deferred pattern (the watcher posts the link via the bot token later)."""
        data = payload.get("data", {})
        custom_id = data.get("custom_id", "")
        if cron.is_create_modal(custom_id) or cron.is_custom_cron_modal(custom_id):
            return await self._handle_cron_modal_submit(payload, custom_id)
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
            self._spawn(self.router.run_panel_enhance(ctx, slug, change))
            return {"type": DEFERRED_CHANNEL_MESSAGE}
        if recruiting_panel.is_out_modal(custom_id):
            values = {c["custom_id"]: c.get("value", "")
                      for row in data.get("components", [])
                      for c in row.get("components", [])}
            role, location, jobdesc, count = recruiting_panel.parse_outreach_modal(values)
            interaction_token = payload.get("token", "")
            member = payload.get("member", {})
            user = member.get("user", payload.get("user", {}))
            channel_id = payload.get("channel_id", "")
            notify_channel, notify_channel_rich = self._channel_notifiers(channel_id)

            async def respond(msg: str) -> None:
                await self.discord.edit_original(
                    interaction_token=interaction_token, content=msg,
                )

            async def notify_channel_msg(msg: dict) -> None:
                await self.discord.post_channel_message(
                    channel_id, content=msg.get("content", ""),
                    embeds=msg.get("embeds"), components=msg.get("components"),
                )

            ctx = CommandContext(
                user_id=user.get("id", ""),
                user_name=user.get("username", "unknown"),
                channel_id=channel_id,
                raw_text="outreach find",
                subcommand="outreach",
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
                notify_channel_msg=notify_channel_msg if channel_id else None,
            )
            self._spawn(self.router.run_panel_outreach(ctx, role, location, jobdesc, count))
            return {"type": DEFERRED_CHANNEL_MESSAGE}
        if recruiting_panel.is_rev_modal(custom_id):
            values = {c["custom_id"]: c.get("value", "")
                      for row in data.get("components", [])
                      for c in row.get("components", [])}
            role, location, jobdesc, count = recruiting_panel.parse_outreach_modal(values)
            interaction_token = payload.get("token", "")
            member = payload.get("member", {})
            user = member.get("user", payload.get("user", {}))
            channel_id = payload.get("channel_id", "")
            notify_channel, notify_channel_rich = self._channel_notifiers(channel_id)

            async def respond(msg: str) -> None:
                await self.discord.edit_original(
                    interaction_token=interaction_token, content=msg,
                )

            async def notify_channel_msg(msg: dict) -> None:
                await self.discord.post_channel_message(
                    channel_id, content=msg.get("content", ""),
                    embeds=msg.get("embeds"), components=msg.get("components"),
                )

            ctx = CommandContext(
                user_id=user.get("id", ""),
                user_name=user.get("username", "unknown"),
                channel_id=channel_id,
                raw_text="reverse find",
                subcommand="outreach",
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
                notify_channel_msg=notify_channel_msg if channel_id else None,
            )
            self._spawn(self.router.run_panel_reverse(ctx, role, location, jobdesc, count))
            return {"type": DEFERRED_CHANNEL_MESSAGE}
        if rr.is_out_editmodal(custom_id):
            values = {c["custom_id"]: c.get("value", "")
                      for row in data.get("components", [])
                      for c in row.get("components", [])}
            return await self._handle_outreach_editmodal(payload, custom_id, values)
        if custom_id.startswith(schedule_picker.TASK_MODAL_PREFIX):
            return await self._handle_pick_task_submit(payload, custom_id)
        if is_sched_modal(custom_id):
            return await self._handle_schedule_modal_submit(payload)
        if is_sched_editmodal(custom_id):
            return self._handle_sched_edit_submit(payload, custom_id)
        if is_link_modal(custom_id):
            return self._handle_link_modal_submit(payload)
        if vid.is_vid_new_modal(custom_id):
            return await self._handle_video_new_modal(payload)
        if vid.is_vid_refine_modal(custom_id):
            try:
                job_id = vid.job_from_refine_modal(custom_id)
            except ValueError:
                return {"type": DEFERRED_UPDATE_MESSAGE}
            change = self._extract_modal_value(data, vid.REFINE_INPUT)
            return await self._handle_video_route(
                payload, lambda ctx, j=job_id, ch=change: self.router.run_video_refine(ctx, j, ch),
                raw_text="video refine")
        if not is_panel_modal(custom_id):
            logger.info(f"Ignoring unknown modal custom_id: {custom_id}")
            return {"type": DEFERRED_UPDATE_MESSAGE}
        return await self._handle_build_modal_submit(payload, custom_id)

    async def _handle_cron_modal_submit(self, payload: dict[str, Any], custom_id: str) -> dict[str, Any]:
        data = payload.get("data", {})
        name = self._extract_modal_value(data, "name") or ""
        prompt = self._extract_modal_value(data, "prompt") or ""
        if cron.is_custom_cron_modal(custom_id):
            cron_expr = (self._extract_modal_value(data, "cron") or "").strip()
        else:
            cron_expr = cron.cron_from_create_modal(custom_id)

        interaction_token = payload.get("token", "")
        member = payload.get("member", {})
        user = member.get("user", payload.get("user", {}))

        async def respond(msg: str) -> None:
            await self.discord.edit_original(interaction_token=interaction_token, content=msg)

        ctx = CommandContext(
            user_id=user.get("id", ""), user_name=user.get("username", "unknown"),
            channel_id=payload.get("channel_id", ""), raw_text="cronjob create",
            subcommand="cronjob", arguments="", platform="discord",
            respond=respond,
        )
        self._spawn(
            self.router.run_cron_create(ctx, cron_expr=cron_expr, name=name, prompt=prompt))
        return {"type": DEFERRED_CHANNEL_MESSAGE, "data": {"flags": EPHEMERAL}}

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
                # App Builder delivery goes to the user's BUILDER thread
                # (reused across builds), kept separate from the cron
                # scheduler's schedules thread.
                thread_id = await self._get_or_make_thread(
                    user_id, channel_id, user_name, kind="builder")
                if thread_id:
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

        self._spawn(_open_and_build())
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
                    "I couldn't read that. Tell me **what** to do and **when** — "
                    "e.g. *every morning*, *every Monday 9am*, or *every 30 minutes*."
                ),
                "flags": 64,
            }}
        cron, human = parsed
        name = f"{human}: {what[:60]}"
        return await self._offer_schedule_confirm(
            payload, name=name, cron=cron, prompt=what, human=human, run_once=False)

    async def _offer_schedule_confirm(
        self, payload: dict[str, Any], *, name: str, cron: str, prompt: str,
        human: str, run_once: bool = False,
    ) -> dict[str, Any]:
        """Park a resolved (name, cron, prompt, run_once) under a token, then show
        either a Connect-your-account card (when the prompt needs Gmail/Drive and
        the owner hasn't connected) or the Confirm card. Shared by the text-`when`
        path and the date/time picker path."""
        token = uuid.uuid4().hex[:16]
        self._pending_schedules[token] = {
            "name": name, "cron": cron, "prompt": prompt, "run_once": run_once}
        # Gate on connector intent: if the task needs Gmail/Drive and the owner
        # hasn't connected it, show Connect buttons instead of the confirm card.
        needs = connector_intent.detect(prompt)
        if needs & {"gmail", "drive"}:
            member = payload.get("member", {})
            user = member.get("user", payload.get("user", {}))
            owner = await self.router._resolve_email_auto(user.get("id", ""))
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
                        f"📅 **{human}** — {prompt[:150]}\n"
                        "This task needs access to your account. Connect below (link is valid "
                        "10 min), then hit **✅ I've connected — create it**."
                    ),
                    "components": build_connect_components(token=token, links=links),
                    "flags": 64,
                }}
        return {"type": CHANNEL_MESSAGE_WITH_SOURCE, "data": {
            "content": f"📅 **{human}** — {prompt[:200]}\nLook right?",
            "components": build_confirm_components(token),
            "flags": 64,
        }}

    async def _handle_pick_component(self, payload: dict[str, Any], custom_id: str) -> dict[str, Any]:
        """A picker button/select click: accumulate the choice and re-render the
        card. 'Set the task' opens the task modal; 'Type it instead' falls back to
        the original text modal."""
        try:
            field, token = schedule_picker.parse_pick_cid(custom_id)
        except ValueError:
            return {"type": DEFERRED_UPDATE_MESSAGE}
        if field == "typeit":
            return {"type": MODAL, "data": build_schedule_modal()}
        if field == "settask":
            return {"type": MODAL, "data": schedule_picker.build_task_modal(token)}
        picks = self._pending_picks.get(token)
        if picks is None:
            return {"type": UPDATE_MESSAGE, "data": {
                "content": "That setup expired — hit **➕ New schedule** to start over.",
                "components": []}}
        now = _manila_now()
        if field == "kindrep":
            picks.clear(); picks["kind"] = "rep"
        elif field == "kindonce":
            picks.clear(); picks["kind"] = "once"
        elif field in ("qtoday", "qtomorrow", "qnextmon"):
            picks["date"] = schedule_picker.quick_date_iso(field, now)
        else:
            values = (payload.get("data") or {}).get("values") or []
            if values:
                picks[field] = values[0]
                if field == "freq":
                    picks.pop("weekday", None)  # weekday is weekly-only
        return self._render_pick_card(token, picks, now)

    def _render_pick_card(self, token: str, picks: dict, now) -> dict[str, Any]:
        if picks.get("kind") == "once":
            card = schedule_picker.build_onetime_card(token, picks, now)
        else:
            card = schedule_picker.build_repeating_card(token, picks)
        return {"type": UPDATE_MESSAGE, "data": {
            "content": card["content"], "components": card["components"]}}

    async def _handle_pick_task_submit(self, payload: dict[str, Any], custom_id: str) -> dict[str, Any]:
        """The 'Set the task' modal submit: resolve the accumulated picks into a
        cron + run_once, then hand to the shared confirm path."""
        token = custom_id[len(schedule_picker.TASK_MODAL_PREFIX):]
        data = payload.get("data", {})
        what = self._extract_modal_value(data, schedule_picker.TASK_INPUT_ID)
        picks = self._pending_picks.pop(token, None)
        if not what or not picks:
            return {"type": CHANNEL_MESSAGE_WITH_SOURCE, "data": {
                "content": "That setup expired — hit **➕ New schedule** to start over.",
                "flags": 64}}
        now = _manila_now()
        try:
            cron, run_once, label = schedule_picker.picks_to_cron(picks, now=now)
        except schedule_picker.PastTimeError:
            return {"type": CHANNEL_MESSAGE_WITH_SOURCE, "data": {
                "content": "⏰ That time is already past — pick a future time.",
                "flags": 64}}
        name = f"{label}: {what[:60]}"
        return await self._offer_schedule_confirm(
            payload, name=name, cron=cron, prompt=what, human=label, run_once=run_once)

    async def _handle_schedule_confirm(self, payload: dict[str, Any], custom_id: str) -> dict[str, Any]:
        """Confirm button: create the parked schedule in the background, delivering
        its results to a private thread. ACK ephemeral-deferred within 3s."""
        try:
            token = token_from_confirm(custom_id)
        except ValueError:
            token = ""
        interaction_token = payload.get("token", "")
        self._spawn(
            self._create_pending_schedule(payload, token, interaction_token)
        )
        return {"type": DEFERRED_CHANNEL_MESSAGE, "data": {"flags": 64}}

    async def _create_pending_schedule(
        self, payload: dict[str, Any], token: str, interaction_token: str,
    ) -> None:
        """Shared create path for Confirm + 'I've connected' resume: pop the parked
        schedule, deliver results to the user's private thread (created/reused),
        create the schedule, and edit the card. Guarantees a terminal follow-up."""
        member = payload.get("member", {})
        user = member.get("user", payload.get("user", {}))
        user_id = user.get("id", "")
        user_name = user.get("username", "unknown")
        channel_id = payload.get("channel_id", "")
        try:
            pending = self._pending_schedules.pop(token, None)
            if not pending:
                await self.discord.edit_original(
                    interaction_token=interaction_token,
                    content="That schedule request expired — please set it up again.",
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
                run_once=pending.get("run_once", False),
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("_create_pending_schedule failed user=%s: %s", user_id, exc)

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

        self._spawn(_do())
        return {"type": DEFERRED_UPDATE_MESSAGE}

    async def _get_or_make_thread(
        self, user_id: str, channel_id: str, user_name: str, *, kind: str,
    ) -> str | None:
        """Reuse the user's private thread or create one. Returns the thread id
        (and adds the user as a member) or None if a thread couldn't be opened.

        ``kind`` selects which per-user thread slot is used so the App Builder
        and the cron scheduler keep separate threads:
          - ``"builder"``   → builder-thread slot, new threads ``aiui-apps-<user>``
          - ``"schedules"`` → schedules-thread slot, new threads ``schedules-<user>``
        """
        if kind == "builder":
            get_thread = self.router.get_user_builder_thread
            set_thread = self.router.set_user_builder_thread
            name = f"aiui-apps-{user_name}"
        elif kind == "schedules":
            get_thread = self.router.get_user_thread
            set_thread = self.router.set_user_thread
            name = f"schedules-{user_name}"
        elif kind == "video":
            get_thread = self.router.get_user_video_thread
            set_thread = self.router.set_user_video_thread
            name = f"aiui-video-{user_name}"
        else:  # pragma: no cover - defensive
            raise ValueError(f"unknown thread kind: {kind!r}")
        thread_id = await get_thread(user_id)
        if not thread_id:
            thread_id = await self.discord.create_private_thread(
                channel_id, name[:90]
            )
            if thread_id:
                await set_thread(user_id, thread_id)
        if thread_id:
            await self.discord.add_thread_member(thread_id, user_id)
        return thread_id

    async def _handle_build_new(self, payload: dict[str, Any]) -> dict[str, Any]:
        """'🚀 Build an app' (in #app-builder) → post the template picker into the
        user's private thread (create/reuse), and point the ephemeral ACK at it."""
        interaction_token = payload.get("token", "")
        member = payload.get("member", {})
        user = member.get("user", payload.get("user", {}))
        user_id = user.get("id", "")
        user_name = user.get("username", "unknown")
        channel_id = payload.get("channel_id", "")

        async def _do() -> None:
            try:
                email = await self.router._resolve_email_auto(user_id)
                templates = await self.router._tasks_client.list_templates(email)
                components = build_template_picker_components(templates)
                thread_id = await self._get_or_make_thread(
                    user_id, channel_id, user_name, kind="builder")
                if thread_id:
                    await self.discord.post_channel_message(
                        thread_id,
                        "Pick a template — or **Blank** to start from scratch:",
                        components=components,
                    )
                    await self.discord.edit_original(
                        interaction_token=interaction_token,
                        content=f"🚀 Your builder is ready in <#{thread_id}>",
                    )
                else:
                    # Couldn't open a thread — fall back to an ephemeral picker.
                    await self.discord.edit_original(
                        interaction_token=interaction_token,
                        content="Pick a template — or **Blank** to start from scratch:",
                        components=components,
                    )
            except Exception as exc:  # noqa: BLE001
                logger.error("_handle_build_new failed user=%s: %s", user_id, exc)
                await self.discord.edit_original(
                    interaction_token=interaction_token,
                    content="Couldn't open the builder — please try again.",
                )

        self._spawn(_do())
        return {"type": DEFERRED_CHANNEL_MESSAGE, "data": {"flags": 64}}

    async def _handle_my_apps(self, payload: dict[str, Any]) -> dict[str, Any]:
        """'📂 My apps' (in #app-builder) → post the user's existing apps as a
        dropdown into their private thread (create/reuse), or an empty-state
        message if they have none. Requires a linked account."""
        interaction_token = payload.get("token", "")
        member = payload.get("member", {})
        user = member.get("user", payload.get("user", {}))
        user_id = user.get("id", "")
        user_name = user.get("username", "unknown")
        channel_id = payload.get("channel_id", "")

        async def _do() -> None:
            try:
                email = await self.router._resolve_email(user_id)
                if email is None:
                    await self.discord.edit_original(
                        interaction_token=interaction_token,
                        content=onboarding.not_linked_text_discord(),
                        components=onboarding.link_button_row(),
                    )
                    return
                projects = await self.router._tasks_client.list_projects(email)
                thread_id = await self._get_or_make_thread(
                    user_id, channel_id, user_name, kind="builder")
                if thread_id:
                    if projects:
                        await self.discord.post_channel_message(
                            thread_id,
                            "Your apps:",
                            components=build_apps_select_components(projects),
                        )
                    else:
                        await self.discord.post_channel_message(
                            thread_id,
                            "📂 No apps yet — hit 🚀 Build an app",
                        )
                    await self.discord.edit_original(
                        interaction_token=interaction_token,
                        content=f"📂 Your apps are in <#{thread_id}>",
                    )
                else:
                    # Couldn't open a thread — fall back to an ephemeral reply.
                    if projects:
                        await self.discord.edit_original(
                            interaction_token=interaction_token,
                            content="Your apps:",
                            components=build_apps_select_components(projects),
                        )
                    else:
                        await self.discord.edit_original(
                            interaction_token=interaction_token,
                            content="📂 No apps yet — hit 🚀 Build an app",
                        )
            except Exception as exc:  # noqa: BLE001
                logger.error("_handle_my_apps failed user=%s: %s", user_id, exc)
                await self.discord.edit_original(
                    interaction_token=interaction_token,
                    content="Couldn't open your apps — please try again.",
                )

        self._spawn(_do())
        return {"type": DEFERRED_CHANNEL_MESSAGE, "data": {"flags": 64}}

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
                        content=onboarding.not_linked_text_discord(),
                        components=onboarding.link_button_row(),
                    )
                    return
                thread_id = await self._get_or_make_thread(
                    user_id, channel_id, user_name, kind="schedules")
                if thread_id:
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

        self._spawn(_do())
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

        self._spawn(_do())
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
                # Notify the requester (best-effort — never block the admin action).
                dm_text, dm_components = onboarding.approval_dm_discord(approve)
                await self.discord.send_dm(
                    discord_id, content=dm_text, components=dm_components,
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("link decision failed id=%s: %s", discord_id, exc)

        self._spawn(_do())
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
        self._spawn(self.router.run_schedule_edit(
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
    def _first_attachment(data: dict) -> dict | None:
        """Pull the first resolved slash-command attachment (Discord option
        type 11) as {url, filename, content_type, size}, or None. The
        aiuibuilder subcommand has at most one file option, so first wins."""
        atts = (data.get("resolved") or {}).get("attachments") or {}
        for a in atts.values():
            return {
                "url": a.get("url"),
                "filename": a.get("filename"),
                "content_type": a.get("content_type"),
                "size": a.get("size"),
            }
        return None

    @staticmethod
    def _all_attachments(data: dict) -> list[dict]:
        """All resolved slash-command attachments (Discord option type 11), in
        resolved-map order, as {url, filename, content_type, size}."""
        atts = (data.get("resolved") or {}).get("attachments") or {}
        return [{"url": a.get("url"), "filename": a.get("filename"),
                 "content_type": a.get("content_type"), "size": a.get("size")}
                for a in atts.values()]

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
            # Take the first STRING option by TYPE, not position — a type-11
            # ATTACHMENT option (the build/enhance file) may arrive in any order,
            # and its value is a snowflake id, not the command text.
            arguments = ""
            for o in sub_options:
                if o.get("type", 3) == 3:  # STRING
                    arguments = o.get("value", "")
                    break
            return (subcommand, arguments)

        # Direct string option (type 3)
        if first.get("type") == 3:
            value = first.get("value", "")
            return CommandRouter.parse_command(value)

        # Fallback: treat name as subcommand
        return (first.get("name", "status"), first.get("value", ""))
