"""Slack interactivity handler: App Builder panel buttons and modal submits.

Slack delivers interactive payloads (button clicks, modal submissions) to a
single Interactivity Request URL as `payload=<json>` form data. main.py parses
that and hands the decoded dict here. Mirrors handlers/discord_commands.py's
button -> modal -> build flow, adapted to Block Kit / views.
"""
import asyncio
import logging
from typing import Any, Optional

from clients.slack import SlackClient
from handlers.commands import CommandRouter, CommandContext
from handlers.slack_app_builder_panel import (
    PANEL_NEW_ID,
    PANEL_MYAPPS_ID,
    TEMPLATE_SELECT_ACTION_ID,
    PUBLISH_PREFIX,
    UNPUBLISH_PREFIX,
    STATUS_PREFIX,
    ENHANCE_PREFIX,
    ENHANCE_MODAL_PREFIX,
    build_modal_view,
    build_template_picker_blocks,
    build_ready_attachment,
    build_published_attachment,
    build_apps_list_blocks,
    build_enhance_modal_view,
    description_from_view,
    enhance_text_from_view,
    is_action,
    is_enhance_modal,
    is_panel_button,
    is_panel_modal,
    slug_from_action,
    slug_from_enhance_modal,
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

        for prefix, handler in (
            (PUBLISH_PREFIX, self._do_publish),
            (UNPUBLISH_PREFIX, self._do_unpublish),
            (STATUS_PREFIX, self._do_status),
            (ENHANCE_PREFIX, self._do_open_enhance),
        ):
            if is_action(action_id, prefix):
                slug = slug_from_action(action_id, prefix)
                if prefix == ENHANCE_PREFIX:
                    await handler(payload, slug)
                else:
                    task = asyncio.create_task(handler(payload, slug))
                    self.router._background_tasks.add(task)
                    task.add_done_callback(self.router._background_tasks.discard)
                return {}

        if action_id == PANEL_NEW_ID:
            # Entry-panel "Build an app": post the template picker into the
            # user's DM and leave an ephemeral pointer in the origin channel.
            # Falls back to an ephemeral picker in-channel if the DM won't open.
            user_id = (payload.get("user") or {}).get("id", "")
            origin = (payload.get("channel") or {}).get("id", "")

            async def _do() -> None:
                try:
                    email = await self.router._resolve_email_for_ctx(
                        self._slack_ctx(user_id)
                    )
                    templates = await self.router._tasks_client.list_templates(email or "")
                    blocks = build_template_picker_blocks(templates)
                    dm = await self.slack.open_dm(user_id)
                    if dm:
                        await self.slack.post_message(
                            channel=dm, text="Pick a template", blocks=blocks
                        )
                        if origin:
                            await self.slack.post_ephemeral(
                                origin, user_id, "\U0001f4e9 Sent to your DM."
                            )
                    elif origin:
                        await self.slack.post_ephemeral(
                            origin, user_id, "Pick a template", blocks=blocks
                        )
                except Exception as exc:  # noqa: BLE001
                    logger.error("Slack PANEL_NEW _do failed user=%s: %s", user_id, exc)

            task = asyncio.create_task(_do())
            self.router._background_tasks.add(task)
            task.add_done_callback(self.router._background_tasks.discard)
            return {}

        if action_id == PANEL_MYAPPS_ID:
            # Entry-panel "My apps": resolve email (DM the not-linked message if
            # unlinked), fetch the user's apps, and post the apps list into their
            # DM. Falls back to an ephemeral list in the origin channel if the DM
            # won't open. Mirrors the `aiuibuilder list` rendering, DM-targeted.
            user_id = (payload.get("user") or {}).get("id", "")
            origin = (payload.get("channel") or {}).get("id", "")

            async def _do_myapps() -> None:
                try:
                    email = await self._bail_if_not_linked(user_id)
                    if not email:
                        return  # _bail_if_not_linked already DM'd the not-linked message
                    projects = await self.router._tasks_client.list_projects(email)
                    dm = await self.slack.open_dm(user_id)
                    if dm:
                        if projects:
                            await self.slack.post_message(
                                channel=dm,
                                text="Your apps",
                                blocks=build_apps_list_blocks(projects),
                            )
                        else:
                            await self.slack.post_message(
                                channel=dm,
                                text="\U0001f4c2 No apps yet — hit \U0001f680 Build an app",
                            )
                        if origin:
                            await self.slack.post_ephemeral(
                                origin, user_id, "\U0001f4e9 Sent to your DM."
                            )
                    elif origin:
                        if projects:
                            await self.slack.post_ephemeral(
                                origin, user_id, "Your apps",
                                blocks=build_apps_list_blocks(projects),
                            )
                        else:
                            await self.slack.post_ephemeral(
                                origin, user_id,
                                "\U0001f4c2 No apps yet — hit \U0001f680 Build an app",
                            )
                except Exception as exc:  # noqa: BLE001
                    logger.error("Slack PANEL_MYAPPS _do failed user=%s: %s", user_id, exc)

            task = asyncio.create_task(_do_myapps())
            self.router._background_tasks.add(task)
            task.add_done_callback(self.router._background_tasks.discard)
            return {}

        logger.info(f"Ignoring unknown Slack action_id: {action_id}")
        return {}

    def _slack_ctx(self, user_id: str, user_name: str = "user") -> CommandContext:
        """Minimal context just for email resolution / not-linked messaging."""
        async def _noop(_: str) -> None:
            ...

        return CommandContext(
            user_id=user_id,
            user_name=user_name,
            channel_id="",
            raw_text="",
            subcommand="aiuibuilder",
            arguments="",
            platform="slack",
            respond=_noop,
            metadata={},
        )

    async def _email_for(self, user_id: str) -> Optional[str]:
        return await self.router._resolve_email_for_ctx(self._slack_ctx(user_id))

    async def _bail_if_not_linked(self, user_id: str) -> Optional[str]:
        """Return the caller's email, or DM the not-linked message and return None."""
        email = await self._email_for(user_id)
        if email:
            return email
        dm = await self.slack.open_dm(user_id)
        if dm:
            await self.slack.post_message(
                channel=dm,
                text=self.router._not_linked_text(self._slack_ctx(user_id)),
            )
        return None

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

            # Note: if open_dm fails here, origin_channel is kept as an ephemeral
            # fallback (build path). The enhance path has no origin_channel fallback
            # (it originates from a DM card), so _start_enhance bails explicitly.
            async def _start() -> None:
                try:
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
                except Exception as exc:  # noqa: BLE001
                    logger.error("Slack build _start failed user=%s: %s", user_id, exc)

            task = asyncio.create_task(_start())
            self.router._background_tasks.add(task)
            task.add_done_callback(self.router._background_tasks.discard)
            return {}  # empty 200 closes the modal

        if is_enhance_modal(callback_id):
            slug = slug_from_enhance_modal(callback_id)
            prompt = enhance_text_from_view(view)

            async def _start_enhance() -> None:
                try:
                    email = await self._bail_if_not_linked(user_id)
                    if not email:
                        return
                    dm = await self.slack.open_dm(user_id)
                    # The enhance path always originates from a DM card, so there is no
                    # origin_channel fallback. If the DM cannot be opened, bail
                    # observably instead of running the enhance and silently swallowing
                    # all output. (Contrast with the build path's _start, which keeps
                    # origin_channel as an ephemeral fallback when open_dm fails.)
                    if not dm:
                        logger.error(
                            "Slack enhance: open_dm returned None for user=%s slug=%s",
                            user_id, slug,
                        )
                        return
                    await self.slack.post_message(
                        channel=dm, text=f"Enhancing {slug}..."
                    )
                    ctx = self._dm_context(
                        payload,
                        dm_id=dm,
                        origin_channel="",
                        user_id=user_id,
                        user_name=user_name,
                        subcommand="aiuibuilder",
                        raw_text=f"aiuibuilder enhance {slug}",
                    )
                    await self.router.run_panel_enhance(ctx, slug, prompt)
                except Exception as exc:  # noqa: BLE001
                    logger.error("Slack enhance _start_enhance failed user=%s: %s", user_id, exc)

            task = asyncio.create_task(_start_enhance())
            self.router._background_tasks.add(task)
            task.add_done_callback(self.router._background_tasks.discard)
            return {}

        logger.info(f"Ignoring unknown Slack callback_id: {callback_id}")
        return {}

    # ------------------------------------------------------------------
    # D10 — Publish / Unpublish management handlers
    # ------------------------------------------------------------------

    async def _do_publish(self, payload: dict[str, Any], slug: str) -> None:
        """Handle a Publish button click — resolves email, publishes, DMs result."""
        user_id: str = payload.get("user", {}).get("id", "")
        try:
            email = await self._bail_if_not_linked(user_id)
            if not email:
                return
            # Call _tasks_client.publish_app directly (not router.run_panel_publish) because
            # the router's run_panel_* methods render Discord-style text via ctx.respond and
            # discard the result; we need the returned public_url to build the Slack attachment.
            result = await self.router._tasks_client.publish_app(email, slug)
            dm = await self.slack.open_dm(user_id)
            if dm:
                await self.slack.post_message(
                    channel=dm,
                    text=f"Published: {slug}",
                    attachments=[build_published_attachment(slug, result.get("public_url", ""))],
                )
        except Exception as exc:  # noqa: BLE001
            logger.error("_do_publish failed slug=%s user=%s: %s", slug, user_id, exc)
            try:
                dm = await self.slack.open_dm(user_id)
                if dm:
                    await self.slack.post_message(
                        channel=dm,
                        text=f"Couldn't publish {slug}: {exc}. Try /aiui aiuibuilder status {slug}.",
                    )
            except Exception as inner:  # noqa: BLE001
                logger.error("_do_publish error DM failed: %s", inner)

    async def _do_unpublish(self, payload: dict[str, Any], slug: str) -> None:
        """Handle an Unpublish button click — resolves email, unpublishes, DMs result."""
        user_id: str = payload.get("user", {}).get("id", "")
        try:
            email = await self._bail_if_not_linked(user_id)
            if not email:
                return
            await self.router._tasks_client.unpublish_app(email, slug)
            dm = await self.slack.open_dm(user_id)
            if dm:
                await self.slack.post_message(
                    channel=dm,
                    text=f"Unpublished: {slug}",
                    attachments=[build_ready_attachment(slug)],
                )
        except Exception as exc:  # noqa: BLE001
            logger.error("_do_unpublish failed slug=%s user=%s: %s", slug, user_id, exc)
            try:
                dm = await self.slack.open_dm(user_id)
                if dm:
                    await self.slack.post_message(
                        channel=dm,
                        text=f"Couldn't unpublish {slug}: {exc}. Try /aiui aiuibuilder status {slug}.",
                    )
            except Exception as inner:  # noqa: BLE001
                logger.error("_do_unpublish error DM failed: %s", inner)

    # ------------------------------------------------------------------
    # D11 — Status handler
    # ------------------------------------------------------------------

    async def _do_status(self, payload: dict[str, Any], slug: str) -> None:
        """Handle a Status button click — resolves email, fetches status, DMs summary."""
        user_id: str = payload.get("user", {}).get("id", "")
        try:
            email = await self._bail_if_not_linked(user_id)
            if not email:
                return
            # Call _tasks_client.get_project_status directly (not router.run_panel_status) because
            # the router's run_panel_* methods render Discord-style text via ctx.respond and discard
            # the result; we need the returned dict to format a Slack-specific DM summary.
            status = await self.router._tasks_client.get_project_status(email, slug)
            dm = await self.slack.open_dm(user_id)
            if dm:
                published_str = "yes" if status.get("published") else "no"
                lines = [
                    f"{status.get('name', slug)} ({slug})",
                    f"Published: {published_str}",
                ]
                if status.get("public_url"):
                    lines.append(f"URL: {status['public_url']}")
                await self.slack.post_message(channel=dm, text="\n".join(lines))
        except Exception as exc:  # noqa: BLE001
            logger.error("_do_status failed slug=%s user=%s: %s", slug, user_id, exc)
            try:
                dm = await self.slack.open_dm(user_id)
                if dm:
                    await self.slack.post_message(
                        channel=dm,
                        text=f"Couldn't get status for {slug}: {exc}. Try /aiui aiuibuilder status {slug}.",
                    )
            except Exception as inner:  # noqa: BLE001
                logger.error("_do_status error DM failed: %s", inner)

    # ------------------------------------------------------------------
    # D12 — Enhance modal opener
    # ------------------------------------------------------------------

    async def _do_open_enhance(self, payload: dict[str, Any], slug: str) -> None:
        """Handle an Enhance button click — opens the enhance modal synchronously."""
        trigger_id = payload.get("trigger_id", "")
        try:
            await self.slack.open_modal(trigger_id, build_enhance_modal_view(slug))
        except Exception as exc:  # noqa: BLE001
            logger.error("_do_open_enhance failed slug=%s: %s", slug, exc)
