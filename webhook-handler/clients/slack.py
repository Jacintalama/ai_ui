"""Slack API client for posting messages."""
import httpx
import hmac
import hashlib
import time
from typing import Optional
import logging

logger = logging.getLogger(__name__)


def verify_slack_signature(
    body: bytes,
    timestamp: str,
    signature: str,
    signing_secret: str
) -> bool:
    """
    Verify Slack request signature.

    Args:
        body: Raw request body bytes
        timestamp: X-Slack-Request-Timestamp header
        signature: X-Slack-Signature header
        signing_secret: Slack app signing secret

    Returns:
        True if signature is valid
    """
    if not timestamp or not signature or not signing_secret:
        return False

    # Check timestamp freshness (5 minutes)
    try:
        if abs(time.time() - int(timestamp)) > 300:
            return False
    except ValueError:
        return False

    sig_basestring = f"v0:{timestamp}:{body.decode('utf-8')}"
    expected = "v0=" + hmac.new(
        signing_secret.encode(),
        sig_basestring.encode(),
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected, signature)


class SlackClient:
    """Client for Slack API operations."""

    def __init__(self, bot_token: str):
        self.bot_token = bot_token
        self.base_url = "https://slack.com/api"
        self.timeout = 30.0

    async def post_message(
        self,
        channel: str,
        text: str,
        thread_ts: Optional[str] = None,
        *,
        blocks=None,
        attachments=None,
    ) -> Optional[str]:
        """
        Post a message to a Slack channel.

        Args:
            channel: Channel ID
            text: Message text (supports markdown)
            thread_ts: Thread timestamp to reply in thread
            blocks: Block Kit blocks list (keyword-only)
            attachments: Legacy attachments list (keyword-only)

        Returns:
            Message timestamp if successful, None on error
        """
        url = f"{self.base_url}/chat.postMessage"
        headers = {
            "Authorization": f"Bearer {self.bot_token}",
            "Content-Type": "application/json"
        }
        payload = {
            "channel": channel,
            "text": text
        }
        if thread_ts:
            payload["thread_ts"] = thread_ts
        if blocks is not None:
            payload["blocks"] = blocks
        if attachments is not None:
            payload["attachments"] = attachments

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload, headers=headers)
                data = response.json()

                if data.get("ok"):
                    ts = data.get("ts")
                    logger.info(f"Posted Slack message to {channel}: {ts}")
                    return ts
                else:
                    logger.error(f"Slack API error: {data.get('error')}")
                    return None

        except Exception as e:
            logger.error(f"Error posting Slack message: {e}")
            return None

    async def get_user_email(self, user_id: str) -> Optional[str]:
        """Resolve a Slack user's profile email via users.info.

        Requires the `users:read.email` scope. Returns the lowercased email,
        or None if the call fails or the profile has no email. Never raises —
        callers treat None as "couldn't link this user".
        """
        if not user_id:
            return None
        url = f"{self.base_url}/users.info"
        headers = {"Authorization": f"Bearer {self.bot_token}"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, params={"user": user_id}, headers=headers)
                data = response.json()
            if not data.get("ok"):
                logger.warning(f"Slack users.info error: {data.get('error')}")
                return None
            email = (
                data.get("user", {}).get("profile", {}).get("email")
                or ""
            ).strip().lower()
            return email or None
        except Exception as e:
            logger.error(f"Error resolving Slack user email: {e}")
            return None

    async def open_modal(self, trigger_id: str, view: dict) -> bool:
        """Open a modal via views.open. The trigger_id comes from an
        interaction payload (button click) and is valid for ~3 seconds.
        Returns True on success; logs and returns False otherwise. Never raises.
        """
        url = f"{self.base_url}/views.open"
        headers = {
            "Authorization": f"Bearer {self.bot_token}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    url, json={"trigger_id": trigger_id, "view": view}, headers=headers
                )
                data = response.json()
            if data.get("ok"):
                logger.info("Slack modal opened")
                return True
            logger.error(f"Slack views.open error: {data.get('error')} {data.get('response_metadata')}")
            return False
        except Exception as e:
            logger.error(f"Error opening Slack modal: {e}")
            return False

    async def open_dm(self, user_id: str) -> Optional[str]:
        """Open a direct-message channel with a user via conversations.open.

        Returns the DM channel id on success, or None on error/empty input.
        Never raises. Requires the `im:write` scope at runtime.
        """
        if not user_id:
            return None
        url = f"{self.base_url}/conversations.open"
        headers = {
            "Authorization": f"Bearer {self.bot_token}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                data = (
                    await client.post(url, json={"users": user_id}, headers=headers)
                ).json()
            if data.get("ok"):
                return data.get("channel", {}).get("id")
            logger.error(f"Slack conversations.open error: {data.get('error')}")
            return None
        except Exception as e:
            logger.error(f"Error opening Slack DM: {e}")
            return None

    async def post_ephemeral(
        self,
        channel: str,
        user: str,
        text: str,
        *,
        blocks=None,
    ) -> bool:
        """Post an ephemeral message visible only to a specific user.

        Args:
            channel: Channel ID where the ephemeral appears
            user: User ID who sees the message
            text: Message text
            blocks: Optional Block Kit blocks list (keyword-only)

        Returns:
            True if successful, False on error. Never raises.
        """
        url = f"{self.base_url}/chat.postEphemeral"
        headers = {
            "Authorization": f"Bearer {self.bot_token}",
            "Content-Type": "application/json",
        }
        payload: dict = {"channel": channel, "user": user, "text": text}
        if blocks is not None:
            payload["blocks"] = blocks
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                data = (
                    await client.post(url, json=payload, headers=headers)
                ).json()
            if data.get("ok"):
                logger.info(f"Posted ephemeral to {channel} for {user}")
                return True
            logger.error(f"Slack chat.postEphemeral error: {data.get('error')}")
            return False
        except Exception as e:
            logger.error(f"Error posting Slack ephemeral: {e}")
            return False

    async def post_to_response_url(
        self,
        response_url: str,
        text: str,
        response_type: str = "ephemeral",
        replace_original: bool = False,
        *,
        blocks=None,
    ) -> bool:
        """
        Post to a Slack response_url (slash command / interaction callback).

        The response_url is pre-authenticated — no Bearer token needed.

        Args:
            response_url: Slack-provided callback URL
            text: Message text
            response_type: "ephemeral" (visible to invoker) or "in_channel"
            replace_original: Whether to replace the original message
            blocks: Optional Block Kit blocks list (keyword-only)

        Returns:
            True if successful
        """
        payload = {
            "text": text,
            "response_type": response_type,
            "replace_original": replace_original,
        }
        if blocks is not None:
            payload["blocks"] = blocks

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(response_url, json=payload)
                if response.status_code == 200:
                    logger.info(f"Posted to response_url ({response_type})")
                    return True
                else:
                    logger.error(f"response_url error: {response.status_code} {response.text}")
                    return False
        except Exception as e:
            logger.error(f"Error posting to response_url: {e}")
            return False

    def format_ai_response(self, analysis: str) -> str:
        """Format AI analysis for Slack (uses mrkdwn)."""
        return f":robot_face: *AI Analysis*\n\n{analysis}"
