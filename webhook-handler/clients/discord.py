"""Discord API client for interaction followups and Ed25519 verification."""
import httpx
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

    async def edit_original(
        self,
        interaction_token: str,
        content: str,
    ) -> bool:
        """
        Edit the original deferred response message.

        Args:
            interaction_token: The interaction token from the original payload
            content: New message content (max 2000 chars)

        Returns:
            True if successful
        """
        content = content[:2000]
        url = (
            f"{DISCORD_API_BASE}/webhooks/{self.application_id}"
            f"/{interaction_token}/messages/@original"
        )

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.patch(url, json={"content": content})
                if response.status_code in (200, 204):
                    logger.info("Discord original message edited")
                    return True
                else:
                    logger.error(f"Discord edit error: {response.status_code} {response.text}")
                    return False
        except Exception as e:
            logger.error(f"Error editing Discord message: {e}")
            return False

    async def post_channel_message(self, channel_id: str, content: str,
                                   components: list | None = None) -> bool:
        """Post a fresh message to a channel using the bot token.

        Unlike followup_message/edit_original (interaction token, 15-min TTL),
        this works indefinitely — used to report a build result that may finish
        after the interaction window closes. Optionally attaches message
        `components` (e.g. a Publish button). Requires the bot to have Send
        Messages in the channel. Never raises.
        """
        content = content[:2000]
        url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages"
        body: dict = {"content": content}
        if components:
            body["components"] = components
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
