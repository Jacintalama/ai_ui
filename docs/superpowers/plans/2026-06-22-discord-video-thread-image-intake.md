# Discord video drop-to-add screenshot intake — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users add screenshots to a Discord video by dropping/posting images into their private video thread, matching the website's drag-and-drop.

**Architecture:** Hook the bot's existing Gateway `on_message` (`voice_bot.py`) — which already has `message_content` intent — to detect image attachments in the `#video-generation` channel and its threads. A new discord.py-free unit (`handlers/video_intake.py`) decides scope and reuses `CommandRouter.run_video_add` to do the backend work. `/video add` is unchanged.

**Tech Stack:** Python, FastAPI, discord.py (Gateway), httpx, pytest + pytest-asyncio. Work in worktree `C:/Users/alama/Desktop/Lukas Work/IO-integrate` on branch `fix/video-thread-image-intake`. Run tests from the `webhook-handler/` directory.

---

## File Structure

- **Create** `webhook-handler/handlers/video_intake.py` — `extract_image_drop(message)` (pure attribute reads, no discord.py import) + `VideoThreadIntake` (scope policy + reuse of `run_video_add`). Single responsibility: turn an image-drop into the right action.
- **Create** `webhook-handler/tests/test_video_intake.py` — unit tests for both, no discord.py needed.
- **Modify** `webhook-handler/voice_bot.py` — `__init__` gains `video_intake`; `on_message` delegates image-drops; `start_voice_bot` forwards `video_intake`.
- **Modify** `webhook-handler/main.py` — build `VideoThreadIntake` and pass to `start_voice_bot`.
- **Modify** `webhook-handler/handlers/video_panel.py` — embed copy.
- **Modify** `webhook-handler/handlers/discord_commands.py` — studio message copy.
- **Modify** `webhook-handler/tests/test_video_panel.py` — assert new discoverability copy.

---

## Task 1: VideoThreadIntake unit + message-extraction helper

**Files:**
- Create: `webhook-handler/handlers/video_intake.py`
- Test: `webhook-handler/tests/test_video_intake.py`

- [ ] **Step 1: Write the failing tests**

Create `webhook-handler/tests/test_video_intake.py`:

```python
"""Unit tests for the drop-to-add video screenshot intake. No discord.py:
extract_image_drop reads attributes off plain fakes, and VideoThreadIntake is
fed primitives, so these run without the gateway library installed."""
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from handlers.video_intake import VideoThreadIntake, extract_image_drop


def _intake(channel_id="999", channel_name="video-generation"):
    router = MagicMock()
    router.run_video_add = AsyncMock()
    discord = MagicMock()
    discord.post_channel_message = AsyncMock()
    intake = VideoThreadIntake(router, discord, video_channel_id=channel_id,
                               video_channel_name=channel_name)
    return intake, router, discord


def _img(url, ct="image/png", fn="shot.png"):
    return {"url": url, "content_type": ct, "filename": fn}


# --- VideoThreadIntake.handle_image_drop ---

@pytest.mark.asyncio
async def test_image_in_video_thread_calls_run_video_add():
    intake, router, discord = _intake()
    await intake.handle_image_drop(
        author_id="100", author_name="alice", channel_id="thread1",
        channel_name="aiui-video-alice", is_thread=True,
        parent_channel_id="999", parent_channel_name="video-generation",
        attachments=[_img("http://cdn/1.png"), _img("http://cdn/2.png")])
    router.run_video_add.assert_awaited_once()
    ctx, urls = router.run_video_add.await_args.args
    assert urls == ["http://cdn/1.png", "http://cdn/2.png"]
    assert ctx.user_id == "100"
    assert ctx.platform == "discord"
    discord.post_channel_message.assert_not_called()


@pytest.mark.asyncio
async def test_non_image_attachment_ignored():
    intake, router, discord = _intake()
    await intake.handle_image_drop(
        author_id="100", author_name="alice", channel_id="thread1",
        channel_name="t", is_thread=True, parent_channel_id="999",
        parent_channel_name="video-generation",
        attachments=[{"url": "http://cdn/x.pdf",
                      "content_type": "application/pdf", "filename": "x.pdf"}])
    router.run_video_add.assert_not_called()
    discord.post_channel_message.assert_not_called()


@pytest.mark.asyncio
async def test_image_in_main_channel_posts_nudge():
    intake, router, discord = _intake()
    await intake.handle_image_drop(
        author_id="100", author_name="alice", channel_id="999",
        channel_name="video-generation", is_thread=False,
        parent_channel_id=None, parent_channel_name=None,
        attachments=[_img("http://cdn/1.png")])
    router.run_video_add.assert_not_called()
    discord.post_channel_message.assert_awaited_once()
    cid, msg = discord.post_channel_message.await_args.args
    assert cid == "999"
    assert "New video" in msg


@pytest.mark.asyncio
async def test_image_in_unrelated_thread_ignored():
    intake, router, discord = _intake()
    await intake.handle_image_drop(
        author_id="100", author_name="alice", channel_id="thread2",
        channel_name="aiui-apps-alice", is_thread=True,
        parent_channel_id="555", parent_channel_name="app-builder",
        attachments=[_img("http://cdn/1.png")])
    router.run_video_add.assert_not_called()
    discord.post_channel_message.assert_not_called()


@pytest.mark.asyncio
async def test_mixed_attachments_forwards_only_images():
    intake, router, discord = _intake()
    await intake.handle_image_drop(
        author_id="100", author_name="alice", channel_id="thread1",
        channel_name="t", is_thread=True, parent_channel_id="999",
        parent_channel_name="video-generation",
        attachments=[_img("http://cdn/a.png"),
                     {"url": "http://cdn/b.pdf",
                      "content_type": "application/pdf", "filename": "b.pdf"},
                     _img("http://cdn/c.jpg", ct=None, fn="c.JPG")])
    router.run_video_add.assert_awaited_once()
    _, urls = router.run_video_add.await_args.args
    assert urls == ["http://cdn/a.png", "http://cdn/c.jpg"]


@pytest.mark.asyncio
async def test_channel_match_by_name_when_no_id():
    intake, router, discord = _intake(channel_id=None, channel_name="video-generation")
    await intake.handle_image_drop(
        author_id="100", author_name="alice", channel_id="threadX",
        channel_name="t", is_thread=True, parent_channel_id="anything",
        parent_channel_name="Video-Generation",
        attachments=[_img("http://cdn/1.png")])
    router.run_video_add.assert_awaited_once()


# --- extract_image_drop ---

def test_extract_thread_message():
    msg = SimpleNamespace(
        author=SimpleNamespace(id=100, bot=False, name="alice", display_name="Alice"),
        attachments=[SimpleNamespace(url="http://cdn/1.png",
                                     content_type="image/png", filename="1.png")],
        channel=SimpleNamespace(id=555, name="aiui-video-alice",
                                parent_id=999, parent=SimpleNamespace(name="video-generation")),
    )
    info = extract_image_drop(msg)
    assert info["author_id"] == "100"
    assert info["author_name"] == "Alice"
    assert info["channel_id"] == "555"
    assert info["is_thread"] is True
    assert info["parent_channel_id"] == "999"
    assert info["parent_channel_name"] == "video-generation"
    assert info["attachments"][0]["url"] == "http://cdn/1.png"


def test_extract_plain_channel_message():
    msg = SimpleNamespace(
        author=SimpleNamespace(id=100, bot=False, name="alice", display_name="Alice"),
        attachments=[SimpleNamespace(url="http://cdn/1.png",
                                     content_type="image/png", filename="1.png")],
        channel=SimpleNamespace(id=999, name="video-generation"),  # no parent_id
    )
    info = extract_image_drop(msg)
    assert info["is_thread"] is False
    assert info["parent_channel_id"] is None
    assert info["channel_id"] == "999"


def test_extract_no_attachments_returns_none():
    msg = SimpleNamespace(
        author=SimpleNamespace(id=100, bot=False, name="alice", display_name="Alice"),
        attachments=[],
        channel=SimpleNamespace(id=999, name="video-generation"),
    )
    assert extract_image_drop(msg) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd webhook-handler && python -m pytest tests/test_video_intake.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'handlers.video_intake'`.

- [ ] **Step 3: Write the implementation**

Create `webhook-handler/handlers/video_intake.py`:

```python
"""Drop-to-add screenshot intake for the Discord #video-generation channel.

Users drop image attachments into their private video thread (the website's
drag-and-drop, ported to Discord). The gateway adapter (voice_bot.on_message)
calls extract_image_drop() to turn a discord.py message into plain primitives,
then VideoThreadIntake.handle_image_drop() decides scope and reuses
CommandRouter.run_video_add() for all backend work. No discord.py import here,
so the policy is unit-testable without the gateway library.
"""
import logging

from handlers.commands import CommandContext

logger = logging.getLogger("video_intake")

_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif")

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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd webhook-handler && python -m pytest tests/test_video_intake.py -q`
Expected: PASS (9 passed).

- [ ] **Step 5: Commit**

```bash
git -C "C:/Users/alama/Desktop/Lukas Work/IO-integrate" add webhook-handler/handlers/video_intake.py webhook-handler/tests/test_video_intake.py
git -C "C:/Users/alama/Desktop/Lukas Work/IO-integrate" commit -m "feat(video): VideoThreadIntake + extract_image_drop for drop-to-add screenshots

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Wire intake into the Gateway `on_message`

**Files:**
- Modify: `webhook-handler/voice_bot.py` (`__init__` ~line 405-427; `on_message` ~line 468-485; `start_voice_bot` ~line 939-953)

- [ ] **Step 1: Add the `video_intake` field to `__init__`**

In `ConversationalVoiceBot.__init__`, change the signature and store the intake. Find:

```python
    def __init__(self, elevenlabs_api_key: str, agent_id: str):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True
        super().__init__(intents=intents)
        self._elevenlabs_api_key = elevenlabs_api_key
        self._agent_id = agent_id
```

Replace with:

```python
    def __init__(self, elevenlabs_api_key: str, agent_id: str, video_intake=None):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True
        super().__init__(intents=intents)
        self._elevenlabs_api_key = elevenlabs_api_key
        self._agent_id = agent_id
        self._video_intake = video_intake
```

- [ ] **Step 2: Delegate image-drops in `on_message`**

At the END of `on_message` (after the `!voice diag` block, still inside the method), add:

```python
        # Drop-to-add screenshots: an image posted in #video-generation or one
        # of its threads is ingested as a screenshot. Best-effort; an error here
        # must never crash the gateway loop.
        if self._video_intake is not None and getattr(message, "attachments", None):
            from handlers.video_intake import extract_image_drop
            info = extract_image_drop(message)
            if info is not None:
                try:
                    await self._video_intake.handle_image_drop(**info)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("video image-drop intake failed: %s", exc)
```

- [ ] **Step 3: Forward `video_intake` from `start_voice_bot`**

Find:

```python
async def start_voice_bot(
    bot_token: str,
    elevenlabs_api_key: str,
    agent_id: str = "",
    **kwargs,
):
    """Start the conversational voice bot as a background task."""
    if not agent_id:
        logger.warning("Voice bot disabled: no ELEVENLABS_AGENT_ID configured")
        return

    bot = ConversationalVoiceBot(
        elevenlabs_api_key=elevenlabs_api_key,
        agent_id=agent_id,
    )
```

Replace with:

```python
async def start_voice_bot(
    bot_token: str,
    elevenlabs_api_key: str,
    agent_id: str = "",
    video_intake=None,
    **kwargs,
):
    """Start the conversational voice bot as a background task."""
    if not agent_id:
        logger.warning("Voice bot disabled: no ELEVENLABS_AGENT_ID configured")
        return

    bot = ConversationalVoiceBot(
        elevenlabs_api_key=elevenlabs_api_key,
        agent_id=agent_id,
        video_intake=video_intake,
    )
```

- [ ] **Step 4: Syntax-check the file**

Run: `cd webhook-handler && python -m py_compile voice_bot.py && echo OK`
Expected: `OK` (no syntax error). (Runtime import of discord.py is validated at deploy via the healthz smoke; `main.py` imports `voice_bot` at module top, so any import error fails container start.)

- [ ] **Step 5: Run the full suite (no regressions)**

Run: `cd webhook-handler && python -m pytest -q`
Expected: all pass (the suite does not import `voice_bot`; this confirms nothing else broke).

- [ ] **Step 6: Commit**

```bash
git -C "C:/Users/alama/Desktop/Lukas Work/IO-integrate" add webhook-handler/voice_bot.py
git -C "C:/Users/alama/Desktop/Lukas Work/IO-integrate" commit -m "feat(video): gateway on_message delegates image-drops to VideoThreadIntake

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Build the intake in `main.py` and pass it to the voice bot

**Files:**
- Modify: `webhook-handler/main.py` (after the Discord-client block ~line 202; the `start_voice_bot(...)` call ~line 228)

- [ ] **Step 1: Build the intake after the Discord client exists**

Immediately AFTER the Discord client block (the `else: logger.info("Discord integration disabled ...")` around line 202) and BEFORE the `# Generic handler` block, insert:

```python
    # Video thread image-drop intake (drop screenshots into the video thread).
    # Needs a DiscordClient to post replies; if Discord isn't configured the
    # intake stays None and the voice bot simply won't ingest dropped images.
    video_intake = None
    if discord_client is not None and command_router is not None:
        from handlers.video_intake import VideoThreadIntake
        video_intake = VideoThreadIntake(
            command_router, discord_client,
            video_channel_id=os.environ.get("VIDEO_CHANNEL_ID"),
            video_channel_name=os.environ.get("VIDEO_CHANNEL_NAME", "video-generation"),
        )
```

(`import os` is already present at the top of `main.py`; confirm it is, add it if missing.)

- [ ] **Step 2: Pass `video_intake` into `start_voice_bot`**

Find:

```python
        voice_bot_task = asyncio.create_task(start_voice_bot(
            bot_token=settings.discord_bot_token,
            elevenlabs_api_key=settings.elevenlabs_api_key,
            agent_id=settings.elevenlabs_agent_id,
        ))
```

Replace with:

```python
        voice_bot_task = asyncio.create_task(start_voice_bot(
            bot_token=settings.discord_bot_token,
            elevenlabs_api_key=settings.elevenlabs_api_key,
            agent_id=settings.elevenlabs_agent_id,
            video_intake=video_intake,
        ))
```

- [ ] **Step 3: Syntax-check**

Run: `cd webhook-handler && python -m py_compile main.py && echo OK`
Expected: `OK`.

- [ ] **Step 4: Run the full suite**

Run: `cd webhook-handler && python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git -C "C:/Users/alama/Desktop/Lukas Work/IO-integrate" add webhook-handler/main.py
git -C "C:/Users/alama/Desktop/Lukas Work/IO-integrate" commit -m "feat(video): construct VideoThreadIntake and wire it into the voice bot

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Discoverability copy (panel embed + studio message)

**Files:**
- Modify: `webhook-handler/handlers/video_panel.py` (`build_video_embed` ~line 47-54)
- Modify: `webhook-handler/handlers/discord_commands.py` (studio message ~line 966-971)
- Test: `webhook-handler/tests/test_video_panel.py` (~line 341)

- [ ] **Step 1: Write the failing copy assertion**

In `webhook-handler/tests/test_video_panel.py`, add after `test_video_embed_has_expected_keys`:

```python
def test_video_embed_mentions_dropping_screenshots():
    embed = build_video_embed()
    assert "drop" in embed["description"].lower()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd webhook-handler && python -m pytest tests/test_video_panel.py::test_video_embed_mentions_dropping_screenshots -q`
Expected: FAIL (current copy says "add … with /video add", no "drop").

- [ ] **Step 3: Update the embed copy**

In `webhook-handler/handlers/video_panel.py`, in `build_video_embed`, find:

```python
            "> add 1-12 screenshots with  /video add\n"
```

Replace with:

```python
            "> drop your screenshots in the thread (or /video add)\n"
```

- [ ] **Step 4: Update the studio message copy**

In `webhook-handler/handlers/discord_commands.py`, in `_handle_video_new_modal`, find:

```python
                await self.discord.post_channel_message(
                    target,
                    "Pick a style + voice, add 1-12 screenshots with `/video add`, "
                    "then hit **Generate video**.",
                    components=vid.build_studio_components(job_id, voices),
                )
```

Replace the message string so the block reads:

```python
                await self.discord.post_channel_message(
                    target,
                    "Pick a style + voice, then **drop your screenshots here** "
                    "(or use `/video add`), then hit **Generate video**.",
                    components=vid.build_studio_components(job_id, voices),
                )
```

- [ ] **Step 5: Run the panel tests to verify pass**

Run: `cd webhook-handler && python -m pytest tests/test_video_panel.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git -C "C:/Users/alama/Desktop/Lukas Work/IO-integrate" add webhook-handler/handlers/video_panel.py webhook-handler/handlers/discord_commands.py webhook-handler/tests/test_video_panel.py
git -C "C:/Users/alama/Desktop/Lukas Work/IO-integrate" commit -m "feat(video): tell users they can drop screenshots in the thread

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the entire webhook-handler suite**

Run: `cd webhook-handler && python -m pytest -q`
Expected: all tests pass (the prior ~903 + the new `test_video_intake.py` and the panel assertion). If anything fails, fix before proceeding — do not deploy on red.

- [ ] **Step 2: Confirm the branch is clean and review the diff**

Run: `git -C "C:/Users/alama/Desktop/Lukas Work/IO-integrate" status --short && git -C "C:/Users/alama/Desktop/Lukas Work/IO-integrate" log --oneline integrate/video-recruiting..HEAD`
Expected: clean tree; commits from Tasks 1-4 listed.

---

## Task 6: Deploy to production (GATED — confirm with the user first)

**Do not run until the user confirms.** Production deploy is outward-facing. webhook-handler is NOT covered by the orchestrator; deploy per-file (never `scp -r`) then rebuild. Per CLAUDE.md / memory.

- [ ] **Step 1: Confirm SSH access**

Run: `ssh -o ConnectTimeout=15 root@46.224.193.25 "echo ok"`
Expected: `ok`.

- [ ] **Step 2: Copy each changed file individually**

```bash
H=root@46.224.193.25; P=/root/proxy-server
scp webhook-handler/handlers/video_intake.py     $H:$P/webhook-handler/handlers/video_intake.py
scp webhook-handler/voice_bot.py                 $H:$P/webhook-handler/voice_bot.py
scp webhook-handler/main.py                      $H:$P/webhook-handler/main.py
scp webhook-handler/handlers/video_panel.py      $H:$P/webhook-handler/handlers/video_panel.py
scp webhook-handler/handlers/discord_commands.py $H:$P/webhook-handler/handlers/discord_commands.py
```

(Run from the `webhook-handler/`'s parent, i.e. the worktree root. Tests are not deployed.)

- [ ] **Step 3: Rebuild the container**

```bash
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --build webhook-handler"
```

- [ ] **Step 4: Verify it came up healthy (catches any voice_bot/main import error)**

```bash
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml ps webhook-handler"
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml logs --tail 60 webhook-handler"
```
Expected: state `Up`; logs show "Voice bot starting as background task" and "Conversational voice bot ready as …"; no traceback. Note: `VIDEO_CHANNEL_ID` is optional — without it the intake matches by channel name `video-generation` (the live channel's name), which is correct.

- [ ] **Step 5: Live e2e (human)**

In `#video-generation`: New video → modal → thread → drop a screenshot image into the thread → expect a reply "Added screenshots — 1/12 so far" + a Generate button. Then drop in the main channel → expect the nudge.
