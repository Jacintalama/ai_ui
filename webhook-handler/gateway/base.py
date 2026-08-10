"""The adapter contract, and the one piece of shared behaviour worth sharing.

hermes-agent declares three abstract methods because their adapters are
long-lived clients with callbacks. Ours are webhook driven, so parsing the
inbound payload is a real half of the job and belongs in the contract. That is
the one deliberate deviation.

Everything else has a working default here, which is what keeps a new platform
a small file rather than a copy of the whole flow.
"""
import logging
from abc import ABC, abstractmethod
from typing import Any

log = logging.getLogger(__name__)


def chunk_text(text: str, limit: int) -> list[str]:
    """Split `text` into pieces no longer than `limit`.

    Prefers paragraph breaks, falls back to line breaks, and hard-slices only
    when a single line is genuinely longer than the limit. `limit <= 0` means
    the platform has no cap.
    """
    text = text or ""
    if not text:
        return []
    if limit <= 0 or len(text) <= limit:
        return [text]

    chunks: list[str] = []
    buf = ""
    for para in text.split("\n\n"):
        joined = f"{buf}\n\n{para}" if buf else para
        if len(joined) <= limit:
            buf = joined
            continue
        if buf:
            chunks.append(buf)
            buf = ""
        if len(para) <= limit:
            buf = para
            continue
        for line in _hard_lines(para, limit):
            if buf and len(buf) + 1 + len(line) <= limit:
                buf = f"{buf}\n{line}"
            else:
                if buf:
                    chunks.append(buf)
                buf = line
    if buf:
        chunks.append(buf)
    return [c for c in chunks if c]


def _hard_lines(para: str, limit: int) -> list[str]:
    out: list[str] = []
    for line in para.split("\n"):
        while len(line) > limit:
            out.append(line[:limit])
            line = line[limit:]
        out.append(line)
    return out


class BasePlatformAdapter(ABC):
    """One platform's transport. No conversation logic lives here."""

    #: Set by the registry from the PlatformEntry, so chunking needs no subclass.
    max_message_length: int = 0
    name: str = ""

    @abstractmethod
    async def connect(self) -> bool:
        """Make the platform able to reach us. Telegram: setWebhook. CLI: no-op.

        Returns False rather than raising when the platform is misconfigured,
        so one broken adapter cannot stop the service from starting.
        """

    @abstractmethod
    async def disconnect(self) -> None:
        """Undo connect(). Telegram: deleteWebhook."""

    @abstractmethod
    def parse_inbound(self, payload: dict, headers: dict) -> "Any | None":
        """Payload -> MessageEvent, or None for anything we do not handle.

        Must be pure and synchronous: no network, no disk. Returning None is
        the normal way to ignore edits, reactions and other update kinds.
        """

    @abstractmethod
    async def send(self, chat_id: str, text: str) -> None:
        """Deliver one message. Chunking is handled by send_chunked."""

    # --- defaulted below: override only when a platform can do better --------

    async def send_chunked(self, chat_id: str, text: str) -> None:
        for piece in chunk_text(text, self.max_message_length):
            await self.send(chat_id, piece)

    async def send_typing(self, chat_id: str) -> None:
        """A visible "working on it". Silent no-op where the platform has none."""

    async def stop_typing(self, chat_id: str) -> None:
        """Most platforms expire the indicator on their own."""

    def verify_webhook(self, payload: dict, headers: dict) -> bool:
        """True by default. A platform with a signature or secret overrides."""
        return True

    async def download_media(self, ref: str) -> str:
        """Fetch `ref` to a temp path. Platforms without media do not implement it."""
        raise NotImplementedError(f"{self.name} cannot download media")
