"""Slack webhook event handler."""
from typing import Any, Optional
import re
import logging

from clients.openwebui import OpenWebUIClient
from clients.slack import SlackClient
from handlers import onboarding
from handlers import intent_router, intent_cards
from config import settings

logger = logging.getLogger(__name__)


class SlackWebhookHandler:
    """Handler for Slack Events API."""

    def __init__(
        self,
        openwebui_client: OpenWebUIClient,
        slack_client: SlackClient,
        ai_model: str = "gpt-4-turbo",
        ai_system_prompt: str = ""
    ):
        self.openwebui = openwebui_client
        self.slack = slack_client
        self.ai_model = ai_model
        self.ai_system_prompt = ai_system_prompt
        self.router = None  # set in main.py to the shared CommandRouter

    async def _try_intent(self, text: str, channel: str, thread_ts=None,
                          user_id: str = "") -> bool:
        """Flag-gated. Runs the shared clarify->recap->confirm loop and renders it
        in Slack. Returns True when handled; False for a plain answer so the caller's
        normal AI reply runs."""
        if not settings.intent_router_enabled or self.router is None:
            return False
        step = await self.router.plan_chat_step(
            user_id or channel, text, threshold=0.6)
        if step.kind == "answer":
            return False
        if step.kind == "confirm":
            await self.slack.post_message(
                channel=channel, text=step.text,
                blocks=intent_cards.confirm_blocks_slack(step.token, step.text),
                thread_ts=thread_ts)
            return True
        # clarify or suggest -> a plain message
        await self.slack.post_message(
            channel=channel, text=step.text, thread_ts=thread_ts)
        return True

    async def handle_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Handle a Slack Events API payload.

        Args:
            payload: Slack event payload

        Returns:
            Result dict with success status
        """
        event_type = payload.get("type")

        # Handle URL verification challenge
        if event_type == "url_verification":
            challenge = payload.get("challenge", "")
            return {"challenge": challenge}

        # Handle event callbacks
        if event_type == "event_callback":
            event = payload.get("event", {})
            return await self._handle_event_callback(event)

        logger.info(f"Ignoring Slack event type: {event_type}")
        return {"success": True, "message": f"Event type '{event_type}' not handled"}

    async def _handle_event_callback(self, event: dict[str, Any]) -> dict[str, Any]:
        """Route event callbacks by type."""
        event_type = event.get("type")

        if event_type == "app_mention":
            return await self._handle_mention(event)
        elif event_type == "message" and event.get("channel_type") == "im":
            return await self._handle_direct_message(event)
        else:
            logger.info(f"Ignoring Slack event: {event_type}")
            return {"success": True, "message": f"Slack event '{event_type}' not handled"}

    async def _handle_mention(self, event: dict[str, Any]) -> dict[str, Any]:
        """Handle @mention in a channel."""
        text = event.get("text", "")
        channel = event.get("channel", "")
        thread_ts = event.get("thread_ts") or event.get("ts")
        user = event.get("user", "unknown")

        # Skip bot messages
        if event.get("bot_id"):
            return {"success": True, "message": "Skipped bot message"}

        # Remove the @mention from the text
        clean_text = re.sub(r"<@[A-Z0-9]+>", "", text).strip()

        logger.info(f"Slack mention from {user} in {channel}: {clean_text[:100]}")

        if onboarding.looks_like_getting_started(clean_text):
            await self.slack.post_message(
                channel=channel,
                text="Welcome — here's how to start.",
                blocks=onboarding.welcome_blocks_slack(),
                thread_ts=thread_ts,
            )
            return {"success": True, "message": "Welcome card sent"}

        if await self._try_intent(clean_text, channel, thread_ts=thread_ts, user_id=user):
            return {"success": True, "message": "Intent handled"}

        system_prompt = self.ai_system_prompt or (
            "You are a helpful AI assistant responding in Slack. "
            "Be concise and use Slack markdown formatting."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": clean_text}
        ]

        analysis = await self.openwebui.chat_completion(
            messages=messages,
            model=self.ai_model
        )

        if not analysis:
            return {"success": False, "error": "Failed to get AI response"}

        response_text = self.slack.format_ai_response(analysis)
        section_text = response_text[:2900] if len(response_text) > 2900 else response_text
        answer_block = {"type": "section", "text": {"type": "mrkdwn", "text": section_text}}
        ts = await self.slack.post_message(
            channel=channel,
            text=response_text,
            thread_ts=thread_ts,
            blocks=[answer_block, onboarding.buttons_footer_slack()],
        )

        if not ts:
            return {"success": False, "error": "Failed to post Slack message"}

        return {"success": True, "message": "Mention handled, response posted"}

    async def _handle_direct_message(self, event: dict[str, Any]) -> dict[str, Any]:
        """Handle direct message to bot."""
        # Only respond to a freshly-typed user message. Skip bot echoes (bot_id)
        # and ANY subtype event (message_changed, message_deleted, bot_message,
        # etc.). Editing the schedules panel in place fires `message_changed` in
        # the DM, whose text/user live under event["message"]; without this guard
        # the bot treats its own edit as a blank user message and replies
        # "your message came through blank".
        if event.get("bot_id") or event.get("subtype"):
            return {"success": True, "message": "Skipped non-user message"}

        text = event.get("text", "")
        channel = event.get("channel", "")
        user = event.get("user", "unknown")

        if not text.strip():
            return {"success": True, "message": "Skipped empty message"}

        logger.info(f"Slack DM from {user}: {text[:100]}")

        if onboarding.looks_like_getting_started(text):
            await self.slack.post_message(
                channel=channel,
                text="Welcome — here's how to start.",
                blocks=onboarding.welcome_blocks_slack(),
            )
            return {"success": True, "message": "Welcome card sent"}

        if await self._try_intent(text, channel, user_id=user):
            return {"success": True, "message": "Intent handled"}

        system_prompt = self.ai_system_prompt or (
            "You are a helpful AI assistant responding to direct messages in Slack. "
            "Be concise and helpful."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ]

        analysis = await self.openwebui.chat_completion(messages=messages, model=self.ai_model)

        if not analysis:
            return {"success": False, "error": "Failed to get AI response"}

        response_text = self.slack.format_ai_response(analysis)
        section_text = response_text[:2900] if len(response_text) > 2900 else response_text
        answer_block = {"type": "section", "text": {"type": "mrkdwn", "text": section_text}}
        await self.slack.post_message(
            channel=channel,
            text=response_text,
            blocks=[answer_block, onboarding.buttons_footer_slack()],
        )

        return {"success": True, "message": "DM handled, response sent"}
