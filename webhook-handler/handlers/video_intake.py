"""Drop-to-add screenshot intake for the Discord #video-generation channel.

Users drop image attachments into their private video thread (the website's
drag-and-drop, ported to Discord). The gateway adapter (voice_bot.on_message)
calls extract_image_drop() to turn a discord.py message into plain primitives,
then VideoThreadIntake.handle_image_drop() decides scope and reuses
CommandRouter.run_video_add() for all backend work. No discord.py import here,
so the policy is unit-testable without the gateway library.
"""
import logging
import re

from handlers.commands import CommandContext

logger = logging.getLogger("video_intake")

_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif")

_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)

_CHANNEL_NUDGE = (
    "To add screenshots, click **New video** to start — your screenshots go "
    "in your private video thread."
)


def _is_image(att: dict) -> bool:
    ct = (att.get("content_type") or "").lower()
    if ct.startswith("image/"):
        return True
    return (att.get("filename") or "").lower().endswith(_IMAGE_EXTS)


def extract_image_drop(message) -> dict | None:
    """Plain primitives from a discord.py message that carries attachments, or
    None if it carries none. Pure attribute reads (getattr with defaults) so it
    works on real discord.py objects and on simple test fakes alike. A channel
    with a `parent_id` is a thread; otherwise it is a top-level channel."""
    attachments = [
        {"url": a.url, "content_type": getattr(a, "content_type", None),
         "filename": getattr(a, "filename", None)}
        for a in (getattr(message, "attachments", None) or [])
    ]
    if not attachments:
        return None
    channel = message.channel
    parent_id = getattr(channel, "parent_id", None)
    parent = getattr(channel, "parent", None)
    author = message.author
    return {
        "author_id": str(author.id),
        "author_name": getattr(author, "display_name", None) or getattr(author, "name", "unknown"),
        "channel_id": str(channel.id),
        "channel_name": getattr(channel, "name", None),
        "is_thread": parent_id is not None,
        "parent_channel_id": str(parent_id) if parent_id else None,
        "parent_channel_name": getattr(parent, "name", None) if parent is not None else None,
        "attachments": attachments,
    }


def extract_url_message(message) -> dict | None:
    """Plain primitives from a discord.py message whose text carries an http(s)
    URL and that has NO image attachment (attachment-bearing messages are handled
    by extract_image_drop). Returns the first URL found, or None. A channel with
    a parent_id is a thread."""
    if getattr(message, "attachments", None):
        return None
    content = getattr(message, "content", "") or ""
    m = _URL_RE.search(content)
    if not m:
        return None
    # Trim trailing punctuation the greedy match swept up from prose / markdown
    # links, e.g. "see (https://site.com)." -> "https://site.com".
    url = m.group(0).rstrip(".,;:!?)]}'\"")
    channel = message.channel
    parent_id = getattr(channel, "parent_id", None)
    parent = getattr(channel, "parent", None)
    author = message.author
    return {
        "author_id": str(author.id),
        "author_name": getattr(author, "display_name", None) or getattr(author, "name", "unknown"),
        "channel_id": str(channel.id),
        "channel_name": getattr(channel, "name", None),
        "is_thread": parent_id is not None,
        "parent_channel_id": str(parent_id) if parent_id else None,
        "parent_channel_name": getattr(parent, "name", None) if parent is not None else None,
        "url": url,
    }


def looks_like_chat_request(text: str) -> bool:
    """True only for substantive plain text worth classifying — not a command, a
    bare URL, the voice-diag word, or a one/two-word chatter message."""
    t = (text or "").strip()
    if not t or t.lower() == "!voice diag":
        return False
    if t[0] in "!/":
        return False
    if _URL_RE.search(t):
        return False
    return len(t.split()) >= 3 and len(t) >= 12


def extract_chat_message(message) -> dict | None:
    """Plain primitives from an ordinary text message (no attachment, not a bare
    URL, substantive enough to classify), or None. Mirrors extract_url_message's
    attribute reads so it works on real discord.py messages and test fakes."""
    if getattr(message, "attachments", None):
        return None
    content = getattr(message, "content", "") or ""
    if not looks_like_chat_request(content):
        return None
    channel = message.channel
    parent_id = getattr(channel, "parent_id", None)
    author = message.author
    return {
        "author_id": str(author.id),
        "author_name": getattr(author, "display_name", None) or getattr(author, "name", "unknown"),
        "channel_id": str(channel.id),
        "channel_name": getattr(channel, "name", None),
        "is_thread": parent_id is not None,
        "text": content.strip(),
    }


class VideoThreadIntake:
    """Decide what to do with an image-drop in #video-generation or its threads,
    and act (reusing CommandRouter.run_video_add for the thread case)."""

    def __init__(self, router, discord_client, *, video_channel_id=None,
                 video_channel_name="video-generation"):
        self._router = router
        self._discord = discord_client
        self._channel_id = (video_channel_id or "").strip() or None
        self._channel_name = (video_channel_name or "video-generation").strip().lower()

    def _is_video_channel(self, channel_id, channel_name) -> bool:
        if self._channel_id:
            return channel_id == self._channel_id
        return bool(channel_name) and channel_name.strip().lower() == self._channel_name

    async def handle_image_drop(self, *, author_id, author_name, channel_id,
                                channel_name, is_thread, parent_channel_id,
                                parent_channel_name, attachments) -> None:
        urls = [a["url"] for a in attachments if _is_image(a) and a.get("url")]
        if not urls:
            return
        if is_thread and self._is_video_channel(parent_channel_id, parent_channel_name):
            ctx = self._thread_ctx(author_id, author_name, channel_id)
            await self._router.run_video_add(ctx, urls)
        elif (not is_thread) and self._is_video_channel(channel_id, channel_name):
            await self._discord.post_channel_message(channel_id, _CHANNEL_NUDGE)
        # else: image dropped somewhere unrelated — ignore.

    async def handle_url_paste(self, *, author_id, author_name, channel_id,
                               channel_name, is_thread, parent_channel_id,
                               parent_channel_name, url) -> None:
        """A URL pasted in a video thread → capture that site onto the draft. A
        URL anywhere else is ignored (the image nudge already directs users)."""
        if is_thread and self._is_video_channel(parent_channel_id, parent_channel_name):
            ctx = self._thread_ctx(author_id, author_name, channel_id)
            await self._router.run_video_capture(ctx, url)

    async def handle_chat(self, *, author_id, author_name, channel_id,
                          is_thread, text, channel_name=None) -> None:
        """A plain-English message. In the user's private app thread (aiui-apps-*)
        it's a conversation about that app (answer + refine); in a channel it goes
        to the intent router. Other private threads (schedules-* / aiui-video-*) are
        owned by their own flows, so chat there is ignored."""
        if is_thread:
            if (channel_name or "").lower().startswith("aiui-apps-"):
                ctx = self._app_thread_ctx(author_id, author_name, channel_id)
                ctx.arguments = text
                await self._router.handle_builder_thread_message(ctx, text)
            return
        ctx = self._thread_ctx(author_id, author_name, channel_id)
        ctx.arguments = text
        await self._router.handle_chat_message(ctx)

    def _thread_ctx(self, author_id, author_name, channel_id) -> CommandContext:
        """A CommandContext whose responders post NEW messages into the thread
        (no interaction token exists for a gateway message)."""
        async def respond(msg):
            await self._discord.post_channel_message(channel_id, msg)

        async def respond_components(msg, components, embeds=None):
            await self._discord.post_channel_message(channel_id, msg, components=components)

        return CommandContext(
            user_id=author_id, user_name=author_name, channel_id=channel_id,
            raw_text="video add", subcommand="video", arguments="",
            platform="discord", respond=respond,
            respond_components=respond_components,
        )

    def _app_thread_ctx(self, author_id, author_name, channel_id) -> CommandContext:
        """Thread ctx for the private app conversation. Like _thread_ctx but also
        sets notify_channel, so a build/enhance started from the thread delivers its
        result back into the thread."""
        async def respond(msg):
            await self._discord.post_channel_message(channel_id, msg)

        async def respond_components(msg, components, embeds=None):
            await self._discord.post_channel_message(channel_id, msg, components=components)

        return CommandContext(
            user_id=author_id, user_name=author_name, channel_id=channel_id,
            raw_text="app chat", subcommand="aiuibuilder", arguments="",
            platform="discord", respond=respond,
            respond_components=respond_components,
            notify_channel=respond,
        )
