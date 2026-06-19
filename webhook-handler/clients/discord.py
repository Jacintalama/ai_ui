"""Discord API client for interaction followups and Ed25519 verification."""
import httpx
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

DISCORD_API_BASE = "https://discord.com/api/v10"


def verify_discord_signature(
    body: bytes,
    signature: str,
    timestamp: str,
    public_key: str,
) -> bool:
    """
    Verify a Discord interaction request via Ed25519.

    Args:
        body: Raw request body bytes
        signature: X-Signature-Ed25519 header
        timestamp: X-Signature-Timestamp header
        public_key: Application's public key (hex)

    Returns:
        True if the signature is valid
    """
    try:
        from nacl.signing import VerifyKey
        from nacl.exceptions import BadSignatureError

        verify_key = VerifyKey(bytes.fromhex(public_key))
        verify_key.verify(timestamp.encode() + body, bytes.fromhex(signature))
        return True
    except BadSignatureError:
        return False
    except Exception as e:
        logger.error(f"Discord signature verification error: {e}")
        return False


class DiscordClient:
    """Client for Discord interaction followups."""

    def __init__(self, application_id: str, bot_token: str):
        self.application_id = application_id
        self.bot_token = bot_token
        self.timeout = 30.0

    async def followup_message(
        self,
        interaction_token: str,
        content: str,
    ) -> bool:
        """
        Send a followup message for a deferred interaction.

        Args:
            interaction_token: The interaction token from the original payload
            content: Message content (max 2000 chars)

        Returns:
            True if successful
        """
        content = content[:2000]
        url = f"{DISCORD_API_BASE}/webhooks/{self.application_id}/{interaction_token}"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json={"content": content})
                if response.status_code in (200, 204):
                    logger.info("Discord followup message sent")
                    return True
                else:
                    logger.error(f"Discord followup error: {response.status_code} {response.text}")
                    return False
        except Exception as e:
            logger.error(f"Error sending Discord followup: {e}")
            return False

    async def edit_original(self, interaction_token: str, content: str = "",
                            components: list | None = None,
                            embeds: list | None = None) -> bool:
        """Edit the original deferred response message. Optionally attaches
        message `components` (buttons) and/or `embeds` (colored cards)."""
        url = (
            f"{DISCORD_API_BASE}/webhooks/{self.application_id}"
            f"/{interaction_token}/messages/@original"
        )
        body: dict = {"content": (content or "")[:2000]}
        if components is not None:
            body["components"] = components
        if embeds is not None:
            body["embeds"] = embeds
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.patch(url, json=body)
                if response.status_code in (200, 204):
                    logger.info("Discord original message edited")
                    return True
                logger.error(f"Discord edit error: {response.status_code} {response.text}")
                return False
        except Exception as e:
            logger.error(f"Error editing Discord message: {e}")
            return False

    async def post_channel_message(self, channel_id: str, content: str = "",
                                   components: list | None = None,
                                   embeds: list | None = None) -> bool:
        """Post a fresh message to a channel using the bot token.

        Unlike followup_message/edit_original (interaction token, 15-min TTL),
        this works indefinitely — used to report a build result that may finish
        after the interaction window closes. Optionally attaches message
        `components` (e.g. a Publish button). Requires the bot to have Send
        Messages in the channel. Never raises.
        """
        url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages"
        body: dict = {"content": (content or "")[:2000]}
        if components:
            body["components"] = components
        if embeds is not None:
            body["embeds"] = embeds
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    url,
                    headers={"Authorization": f"Bot {self.bot_token}"},
                    json=body,
                )
                if response.status_code in (200, 201):
                    return True
                logger.error(
                    f"Discord channel post error: {response.status_code} {response.text}"
                )
                return False
        except Exception as e:
            logger.error(f"Error posting Discord channel message: {e}")
            return False

    async def post_channel_file(
        self, channel_id: str, files: list[tuple[str, bytes, str]],
        content: str = "", components: list | None = None,
    ) -> bool:
        """Post a message with one or more file attachments (bot token, multipart).
        `files` = list of (filename, data, content_type). Discord allows <=10
        files. Never raises. Do NOT set Content-Type — httpx sets the multipart
        boundary itself."""
        url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages"
        body: dict = {"content": (content or "")[:2000],
                      "attachments": [{"id": i, "filename": fn}
                                      for i, (fn, _, _) in enumerate(files)]}
        if components:
            body["components"] = components
        multipart = {f"files[{i}]": (fn, data, ctype)
                     for i, (fn, data, ctype) in enumerate(files)}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    url,
                    headers={"Authorization": f"Bot {self.bot_token}"},
                    data={"payload_json": json.dumps(body)},
                    files=multipart,
                )
                if response.status_code in (200, 201):
                    return True
                logger.error(
                    f"Discord file post error: {response.status_code} {response.text}")
                return False
        except Exception as e:
            logger.error(f"Error posting Discord file: {e}")
            return False

    async def open_dm(self, user_id: str) -> str | None:
        """Open (or fetch) the bot↔user DM channel. Returns the DM channel id,
        or None on failure (never raises). Works when the user shares a server
        with the bot."""
        url = f"{DISCORD_API_BASE}/users/@me/channels"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    url,
                    headers={"Authorization": f"Bot {self.bot_token}"},
                    json={"recipient_id": user_id},
                )
                if response.status_code in (200, 201):
                    return response.json().get("id")
                logger.error(
                    f"Discord open_dm error: {response.status_code} {response.text}"
                )
                return None
        except Exception as e:
            logger.error(f"Error opening Discord DM: {e}")
            return None

    async def send_dm(self, user_id: str, content: str = "",
                      components: list | None = None) -> bool:
        """DM a user: open the DM channel then post. Best-effort — returns False
        (never raises) so a failed DM never breaks the caller's main action."""
        dm_id = await self.open_dm(user_id)
        if not dm_id:
            return False
        return await self.post_channel_message(
            dm_id, content=content, components=components
        )

    async def create_private_thread(self, parent_channel_id: str, name: str) -> str | None:
        """Create a private thread (type 12) under a text channel using the bot
        token. Returns the new thread id, or None on failure (never raises) so
        callers can fall back to posting in the parent channel. Requires the bot
        to have Create Private Threads."""
        url = f"{DISCORD_API_BASE}/channels/{parent_channel_id}/threads"
        body = {
            "name": name[:100],
            "type": 12,                    # PRIVATE_THREAD
            "invitable": False,
            "auto_archive_duration": 1440,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    url,
                    headers={"Authorization": f"Bot {self.bot_token}"},
                    json=body,
                )
                if response.status_code in (200, 201):
                    return response.json().get("id")
                logger.error(
                    f"Discord create thread error: {response.status_code} {response.text}"
                )
                return None
        except Exception as e:
            logger.error(f"Error creating Discord private thread: {e}")
            return None

    async def add_thread_member(self, thread_id: str, user_id: str) -> bool:
        """Add a user to a thread (so they see the private thread). Bot token.
        Never raises."""
        url = f"{DISCORD_API_BASE}/channels/{thread_id}/thread-members/{user_id}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.put(
                    url, headers={"Authorization": f"Bot {self.bot_token}"},
                )
                if response.status_code in (200, 204):
                    return True
                logger.error(
                    f"Discord add thread member error: {response.status_code} {response.text}"
                )
                return False
        except Exception as e:
            logger.error(f"Error adding Discord thread member: {e}")
            return False
