"""Telegram, over webhooks rather than long polling.

Long polling would need a permanently running task holding an open connection.
Caddy already routes /webhook/* to this service, so a webhook costs nothing and
survives a restart.
"""
import hmac
import logging
import os
import tempfile

import httpx

from config import settings
from gateway.base import BasePlatformAdapter
from gateway.events import MessageEvent, MessageType, SessionSource

log = logging.getLogger(__name__)

TELEGRAM_MAX_MESSAGE = 4096
SECRET_HEADER = "x-telegram-bot-api-secret-token"

# The second half of the clip guard. The duration cap lives in the pipeline,
# because it can be applied before anything is downloaded; this one cannot,
# since getFile is what tells us the size.
MAX_VOICE_BYTES = 10 * 1024 * 1024


class TelegramAdapter(BasePlatformAdapter):
    def __init__(self, token: str = "", webhook_secret: str = "",
                 public_url: str = ""):
        self._token = token or settings.telegram_bot_token
        self._secret = webhook_secret or settings.telegram_webhook_secret
        self._public_url = (public_url or settings.gateway_public_url).rstrip("/")

    @property
    def _api(self) -> str:
        return f"https://api.telegram.org/bot{self._token}"

    async def _call(self, method: str, **payload) -> dict:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(f"{self._api}/{method}", json=payload)
        if resp.status_code >= 400:
            raise httpx.HTTPStatusError(resp.text, request=resp.request,
                                        response=resp)
        return resp.json()

    # --- contract ------------------------------------------------------------

    async def connect(self) -> bool:
        """Point Telegram at our webhook.

        Returns False rather than raising: one unreachable platform must not
        stop the service from starting.
        """
        try:
            await self._call(
                "setWebhook",
                url=f"{self._public_url}/webhook/telegram",
                secret_token=self._secret,
                allowed_updates=["message"],
                drop_pending_updates=True,
            )
        except Exception as e:                          # noqa: BLE001
            log.error("gateway: could not register the Telegram webhook: %r", e)
            return False
        log.info("gateway: Telegram webhook registered")
        return True

    async def disconnect(self) -> None:
        try:
            await self._call("deleteWebhook")
        except Exception as e:                          # noqa: BLE001
            log.warning("gateway: could not remove the Telegram webhook: %r", e)

    def verify_webhook(self, payload: dict, headers: dict) -> bool:
        """Telegram echoes the secret we set in setWebhook on every delivery.

        Constant-time compare, matching what clients/github.py and
        clients/slack.py already do for the same job. This is the only
        authentication on a publicly reachable route, and a plain == leaks a
        prefix through timing. Still fails closed when the secret is unset.
        """
        got = {k.lower(): v for k, v in (headers or {}).items()}.get(SECRET_HEADER)
        if not self._secret or not isinstance(got, str):
            return False
        return hmac.compare_digest(got, self._secret)

    def parse_inbound(self, payload: dict, headers: dict) -> MessageEvent | None:
        """One Telegram update to a MessageEvent, or None if we do not handle it.

        Only `message` is handled. Edits, button presses and channel posts parse
        to None, which is how they get ignored without a branch downstream.
        """
        message = (payload or {}).get("message")
        if not isinstance(message, dict):
            return None
        chat = message.get("chat")
        if not isinstance(chat, dict) or not chat.get("id"):
            return None
        # isinstance, not `or {}`: that idiom only degrades on a FALSY value, so
        # a truthy non-dict reached .get() and raised, which the route turned
        # into a 500 and Telegram then re-delivered forever.
        sender = message.get("from")
        if not isinstance(sender, dict):
            sender = {}

        raw_type = chat.get("type") or ""
        source = SessionSource(
            platform="telegram",
            chat_id=str(chat["id"]),
            # "private" is the only thing that becomes "dm". Everything else
            # keeps its real name so the pipeline refuses it.
            chat_type="dm" if raw_type == "private" else (raw_type or "unknown"),
            user_id=str(sender.get("id") or chat["id"]),
            user_name=sender.get("first_name") or sender.get("username") or "",
        )
        common = {"source": source, "message_id": str(message.get("message_id") or "")}

        voice = message.get("voice") or message.get("audio")
        if isinstance(voice, dict) and voice.get("file_id"):
            duration = voice.get("duration")
            return MessageEvent(
                text="", message_type=MessageType.VOICE,
                media_ref=voice["file_id"],
                media_duration=duration if isinstance(duration, int) else None,
                **common)

        photo = message.get("photo")
        if isinstance(photo, list) and photo:
            # Telegram sends sizes smallest first; the last is the largest.
            largest = photo[-1]
            return MessageEvent(
                text=message.get("caption") or "",
                message_type=MessageType.PHOTO,
                media_ref=largest.get("file_id") if isinstance(largest, dict) else None,
                **common)

        document = message.get("document")
        if isinstance(document, dict) and document.get("file_id"):
            return MessageEvent(text=message.get("caption") or "",
                                message_type=MessageType.DOCUMENT,
                                media_ref=document["file_id"], **common)

        return MessageEvent(text=message.get("text") or "",
                            message_type=MessageType.TEXT, **common)

    async def send(self, chat_id: str, text: str) -> None:
        """Deliver one chunk. Never raises: the caller is already replying."""
        try:
            await self._call("sendMessage", chat_id=chat_id, text=text,
                             disable_web_page_preview=True)
        except Exception as e:                          # noqa: BLE001
            log.error("gateway: Telegram sendMessage failed: %r", e)

    async def send_typing(self, chat_id: str) -> None:
        try:
            await self._call("sendChatAction", chat_id=chat_id, action="typing")
        except Exception:                               # noqa: BLE001
            pass        # Cosmetic. Never let it cost a reply.

    async def download_media(self, ref: str) -> str:
        """Exchange a file_id for bytes on disk. Caller deletes the path.

        Saved as .ogg, never Telegram's native .oga: Open WebUI checks the
        extension against a list that contains "ogg" and not "oga", so the
        wrong suffix is rejected before the audio is ever looked at.
        """
        info = await self._call("getFile", file_id=ref)
        result = (info or {}).get("result") or {}
        file_path = result.get("file_path")
        if not file_path:
            raise RuntimeError("Telegram getFile returned no path")
        size = result.get("file_size") or 0
        if size > MAX_VOICE_BYTES:
            raise ValueError("file too large")

        url = f"https://api.telegram.org/file/bot{self._token}/{file_path}"
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.content

        fd, path = tempfile.mkstemp(suffix=".ogg", prefix="gateway-voice-")
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        return path
