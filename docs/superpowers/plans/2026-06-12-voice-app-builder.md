# Voice App Builder + TTS Cutout Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Voice users can build websites by conversation (template-or-blank → questions → confirm → build → "is it done?"), and the agent's TTS never cuts out mid-message.

**Architecture:** Conversation logic lives in the ElevenLabs agent prompt (managed as code via a new idempotent setup script). Three thin webhook tools (`list_templates`, `start_build`, `build_status`) plug into the existing `aiuibuilder` command path in webhook-handler. The TTS cutout is fixed in `voice_bot.py`: a 90s output queue with drop logging, and a watchdog that never reconnects while agent audio is queued/playing.

**Tech Stack:** Python 3.11 (FastAPI webhook-handler container), discord.py + discord-ext-voice-recv, ElevenLabs Conversational AI (agent `claude-sonnet-4-5`), pytest with `asyncio_mode = auto` (`webhook-handler/pytest.ini` — async tests need no marker; `@pytest.mark.asyncio` is harmless), Docker Compose on Hetzner.

**Local test env caveat:** `discord.py` IS installed locally, but `discord-ext-voice-recv` and `elevenlabs` are NOT — so `voice_bot.DiscordAudioInterface`/`PassthroughSink` (defined under `if HAS_VOICE_RECV and HAS_ELEVENLABS_CONV:`) do not exist in local runs. Tests must target the unconditional classes (`AudioOutputSource`, `ConversationalVoiceBot`); anything touching `DiscordAudioInterface` gets a `skipif`.

**Spec:** `docs/superpowers/specs/2026-06-12-voice-app-builder-design.md`

**Working directory for all test commands:** `webhook-handler/` (run `python -m pytest` from there).

**Captured live state (2026-06-12):** agent "AIUI Voice Assistant" has 11 standalone webhook tools (`report, rebuild, analyze, pr-review, workflows, sheets, deps, health, security, ask, status`) — none for App Builder. Server `.env` has no `VOICE_USER_EMAIL`. `DISCORD_USER_EMAIL_MAP` format is comma-separated `<snowflake>:<email>` (NOT JSON). Compose passes env via an explicit list (so the new var must be added there).

---

### Task 1: AudioOutputSource — stop dropping TTS audio silently

The output queue holds 200 frames = 4s. ElevenLabs streams faster than realtime; replies longer than ~6s lose their tail silently (`except queue.Full: pass`). Raise to 90s, count + log drops, expose in stats.

**Files:**
- Modify: `webhook-handler/voice_bot.py` (constants ~line 72, `AudioOutputSource.__init__`/`feed` ~lines 85-105, `_pipeline_stats` ~line 487, `_stats_reporter` ~line 508)
- Create: `webhook-handler/tests/test_voice_bot_audio.py`

- [ ] **Step 1: Write the failing tests**

Create `webhook-handler/tests/test_voice_bot_audio.py`:

```python
"""AudioOutputSource overflow behavior — the TTS mid-message cutout fix.

ElevenLabs streams TTS faster than realtime while Discord drains at exactly
50 fps, so the old 200-frame (4 s) queue overflowed on any reply longer than
~6 s and feed() silently dropped the tail: speech stopped mid-sentence.
"""
import sys

import pytest

# Other test modules stub sys.modules["discord"] / sys.modules["voice_bot"] so
# that `main` can be imported without audio deps. We need the real modules here
# — evict the stubs (modules already imported keep their stub references).
if "discord" in sys.modules and not hasattr(sys.modules["discord"], "AudioSource"):
    for _k in [k for k in sys.modules if k == "discord" or k.startswith("discord.")]:
        del sys.modules[_k]
pytest.importorskip("discord")
if "voice_bot" in sys.modules and not hasattr(sys.modules["voice_bot"], "ConversationalVoiceBot"):
    del sys.modules["voice_bot"]

import voice_bot as vb  # noqa: E402

DATA_FRAME = b"\x01" * vb.DISCORD_FRAME_SIZE


def _drain_data_frames(src) -> int:
    """Read until the queue is empty; count non-silence frames."""
    got = 0
    while True:
        frame = src.read()
        if frame == vb.SILENCE_FRAME:
            return got
        got += 1


def test_thirty_second_reply_plays_in_full():
    """1500 frames = 30 s of speech. The old 4 s queue dropped 1300 of them."""
    src = vb.AudioOutputSource()
    src.feed(DATA_FRAME * 1500)
    assert _drain_data_frames(src) == 1500
    assert src._dropped == 0


def test_queue_capacity_is_at_least_ninety_seconds():
    assert vb.OUTPUT_QUEUE_FRAMES >= 4500  # 90 s at 50 fps


def test_overflow_is_counted_and_logged(caplog):
    src = vb.AudioOutputSource()
    overflow = 10
    with caplog.at_level("WARNING"):
        src.feed(DATA_FRAME * (vb.OUTPUT_QUEUE_FRAMES + overflow))
    assert src._dropped == overflow
    assert any("output queue FULL" in r.message for r in caplog.records)


def test_pipeline_stats_expose_dropped():
    bot = vb.ConversationalVoiceBot(elevenlabs_api_key="k", agent_id="a")
    bot._audio_output = vb.AudioOutputSource()
    bot._audio_output._dropped = 7
    assert bot._pipeline_stats()["dropped"] == 7
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_voice_bot_audio.py -q`
Expected: FAIL — `AttributeError: module 'voice_bot' has no attribute 'OUTPUT_QUEUE_FRAMES'`, `'AudioOutputSource' object has no attribute '_dropped'`, and `KeyError: 'dropped'`. (`test_thirty_second_reply_plays_in_full` fails with `1500 != 200`.)

- [ ] **Step 3: Implement**

In `webhook-handler/voice_bot.py`, after `DISCORD_FRAME_SIZE`/`SILENCE_FRAME` (~line 73), add:

```python
# ElevenLabs streams TTS faster than realtime while the AudioPlayer drains at
# exactly 50 fps, so the queue must hold a WHOLE long reply, not a few seconds
# of it — overflow means audibly truncated speech. 4500 frames = 90 s
# (~17 MB worst-case, transient).
OUTPUT_QUEUE_FRAMES = 4500
```

In `AudioOutputSource.__init__`, change the queue line and add the counter:

```python
        self._queue = queue.Queue(maxsize=OUTPUT_QUEUE_FRAMES)
```
and after `self._reads = 0`:
```python
        self._dropped = 0  # frames lost to overflow == audibly cut speech
```

In `AudioOutputSource.feed`, replace the `except queue.Full: pass` block:

```python
                try:
                    self._queue.put_nowait(frame)
                except queue.Full:
                    self._dropped += 1
                    if self._dropped % 50 == 1:
                        logger.warning(
                            "[ConvAI] output queue FULL — dropped %d frames "
                            "(agent speech is being cut)", self._dropped,
                        )
```

In `_pipeline_stats` add after the `"reads"` entry:

```python
            "dropped": ao._dropped if ao else -1,
```

In `_stats_reporter`, include the new counter in the delta line — change the
deltas tuple and log call to:

```python
                deltas = {k: s[k] - prev.get(k, 0)
                          for k in ("sink_writes", "sink_rx", "gated", "fed",
                                    "reads", "dropped")}
                prev = {k: s[k] for k in deltas}
                logger.info(
                    "[ConvAI] stats5s writes=+%d rx=+%d gated=+%d fed=+%d reads=+%d "
                    "dropped=+%d q=%d has_content=%s connected=%s listening=%s "
                    "playing=%s player_alive=%s cb=%s",
                    deltas["sink_writes"], deltas["sink_rx"], deltas["gated"],
                    deltas["fed"], deltas["reads"], deltas["dropped"], s["q"],
                    s["has_content"], s["connected"], s["listening"],
                    s["playing"], s["player_alive"], s["cb_set"],
                )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_voice_bot_audio.py tests/test_voice_bot_recovery.py -q`
Expected: all PASS (recovery suite proves no regression).

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/voice_bot.py webhook-handler/tests/test_voice_bot_audio.py
git commit -m "fix(voice): 90s TTS output queue with drop logging — long replies no longer cut"
```

---

### Task 2: Watchdog must not kill the session while the agent is speaking

`_watchdog_should_reconnect` fires after 25 s without a **user** transcript even while the agent is mid-speech (long answers get the session torn down and re-greeted). Guard on agent audio, and restart the deafness countdown when playback drains. Also remove the dead `_wait_and_unmute`.

**Files:**
- Modify: `webhook-handler/voice_bot.py` (`DiscordAudioInterface.__init__`/`_on_playback_drained` ~lines 152-169, `ConversationalVoiceBot.__init__` ~line 263, `_start_session` ~lines 350+374, `_wait_and_unmute` ~lines 540-564 (delete), `_on_user_transcript` ~line 572, `_watchdog_should_reconnect` ~line 581, `_dave_watchdog` ~line 615)
- Test: `webhook-handler/tests/test_voice_bot_recovery.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `webhook-handler/tests/test_voice_bot_recovery.py`:

```python
# ---------------------------------------------------------------------------
# 4. Watchdog: never reconnect while the agent is speaking (mid-speech cutout)
# ---------------------------------------------------------------------------

def test_watchdog_waits_while_agent_audio_queued():
    """A long agent reply must not be treated as user deafness."""
    bot = _make_bot()
    bot._session_active = True
    bot._session_voice_channel = _channel(USER)
    ao = vb.AudioOutputSource()
    ao.feed(b"\x01" * vb.DISCORD_FRAME_SIZE)  # audio queued, not yet played
    bot._audio_output = ao
    assert bot._watchdog_should_reconnect(60.0) is False


def test_watchdog_waits_while_playback_not_drained():
    bot = _make_bot()
    bot._session_active = True
    bot._session_voice_channel = _channel(USER)
    ao = vb.AudioOutputSource()
    ao._has_content = True  # queue empty but drain grace not elapsed
    bot._audio_output = ao
    assert bot._watchdog_should_reconnect(60.0) is False


def test_watchdog_fires_after_agent_audio_drained():
    bot = _make_bot()
    bot._session_active = True
    bot._session_voice_channel = _channel(USER)
    bot._audio_output = vb.AudioOutputSource()  # empty, drained
    assert bot._watchdog_should_reconnect(26.0) is True


def test_playback_drain_resets_activity_clock():
    """The 25 s deafness countdown starts AFTER the agent finishes speaking.

    The bot wires its activity stamp as AudioOutputSource(on_drained=...);
    read() fires it after 30 consecutive empty reads following content.
    """
    bot = _make_bot()
    bot._last_activity_time = 0.0
    ao = vb.AudioOutputSource(on_drained=bot._mark_activity)
    ao.feed(b"\x01" * vb.DISCORD_FRAME_SIZE)
    while ao.read() != vb.SILENCE_FRAME:
        pass
    for _ in range(30):  # 30 consecutive empty reads triggers the drain hook
        ao.read()
    assert bot._last_activity_time > 0.0


@pytest.mark.skipif(
    not hasattr(vb, "DiscordAudioInterface"),
    reason="voice deps (voice_recv/elevenlabs) not installed locally",
)
def test_audio_interface_chains_drain_hook():
    """DiscordAudioInterface must CHAIN the bot's on_drained, not clobber it
    (it historically overwrote audio_output._on_drained)."""
    fired = []
    ao = vb.AudioOutputSource(on_drained=lambda: fired.append(1))
    vb.DiscordAudioInterface(ao, asyncio.new_event_loop())
    ao.feed(b"\x01" * vb.DISCORD_FRAME_SIZE)
    while ao.read() != vb.SILENCE_FRAME:
        pass
    for _ in range(30):
        ao.read()
    assert fired, "bot's drain hook must still fire through the interface"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_voice_bot_recovery.py -q`
Expected: the new tests FAIL (`_watchdog_should_reconnect` returns True while audio queued; `_last_activity_time`/`_mark_activity` don't exist); the chaining test SKIPS locally (no voice deps). The 7 existing tests still pass.

- [ ] **Step 3: Implement**

In `webhook-handler/voice_bot.py`:

1. Add `import time` to the top-level imports (after `import threading`).

2. `DiscordAudioInterface.__init__` — CHAIN the existing drain hook instead of
clobbering it. Replace the line
`self._audio_output._on_drained = self._on_playback_drained` with:

```python
            # Chain, don't clobber: the bot installs its activity stamp via
            # AudioOutputSource(on_drained=...); keep it firing.
            self._chained_on_drained = self._audio_output._on_drained
            self._audio_output._on_drained = self._on_playback_drained
```

3. Replace `_on_playback_drained` (drop the stale "unmute" wording):

```python
        def _on_playback_drained(self):
            """Called from the AudioPlayer thread when queued audio finishes."""
            cb = self._chained_on_drained
            if cb is not None:
                try:
                    cb()
                except Exception:
                    pass
```

4. `ConversationalVoiceBot.__init__`: rename `self._last_user_transcript_time = 0.0` → `self._last_activity_time = 0.0`.

5. Add next to `_on_user_transcript`:

```python
    def _mark_activity(self):
        """Conversational activity stamp (user spoke OR agent finished speaking).
        Called from the AudioPlayer thread on drain — float assignment is atomic."""
        self._last_activity_time = time.monotonic()
```

6. `_start_session`: install the activity stamp on the audio source —

```python
            self._audio_output = AudioOutputSource(on_drained=self._mark_activity)
            self._audio_interface = DiscordAudioInterface(
                self._audio_output, asyncio.get_running_loop()
            )
```
and replace the two lines `import time` / `self._last_user_transcript_time = time.monotonic()` with:
```python
            self._last_activity_time = time.monotonic()
```

7. `_on_user_transcript`: replace `import time` + `self._last_user_transcript_time = time.monotonic()` with `self._mark_activity()`.

8. `_watchdog_should_reconnect` — add the speaking guard after the `elapsed <= 25` check, and update the docstring's first paragraph:

```python
    def _watchdog_should_reconnect(self, elapsed: float) -> bool:
        """Decide whether the session is deaf and needs a fresh connection.

        Reconnect when no conversational activity (user transcript OR agent
        playback finishing) for 25+ seconds while a non-bot user is in the
        channel — but NEVER while agent audio is queued or playing: a long
        reply is not deafness, and reconnecting would cut it mid-sentence.
        Deliberately NOT gated on mic frame counts: the worst failure mode
        delivers ZERO frames (voice receive dead), and a single short
        utterance is only ~50-100 frames, so any frame threshold keeps the
        watchdog inert exactly when it's needed (observed live 2026-06-11:
        4.5 min deaf session, watchdog never fired).
        """
        if not self._session_active or elapsed <= 25:
            return False
        ao = self._audio_output
        if ao is not None and (ao._has_content or not ao._queue.empty()):
            return False  # agent is speaking
        ch = self._session_voice_channel
        if not ch:
            return False
        try:
            if not [m for m in ch.members if not m.bot]:
                return False  # nobody to hear; channel-empty handler ends the session
        except Exception:
            return False
        return True
```

9. `_dave_watchdog`: change `elapsed = time.monotonic() - self._last_user_transcript_time` → `self._last_activity_time` (the inline `import time` there may stay or go — top-level import now exists).

10. Delete the whole `_wait_and_unmute` method (dead since the queue-state mute gate; nothing calls it).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_voice_bot_recovery.py tests/test_voice_bot_audio.py -q`
Expected: all PASS (11 recovery + 4 audio).

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/voice_bot.py webhook-handler/tests/test_voice_bot_recovery.py
git commit -m "fix(voice): watchdog never reconnects mid-speech; activity clock resets on playback drain"
```

---

### Task 3: Expose the active voice session's text channel

The build watcher needs a Discord channel to post "ready" into. Voice sessions already pick a text channel (`_text_channel`); expose it module-level for `main.py`.

**Files:**
- Modify: `webhook-handler/voice_bot.py` (module tail: `start_voice_bot` ~line 665)
- Test: `webhook-handler/tests/test_voice_bot_recovery.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `webhook-handler/tests/test_voice_bot_recovery.py`:

```python
# ---------------------------------------------------------------------------
# 5. current_text_channel_id — voice build watcher posts here
# ---------------------------------------------------------------------------

def test_current_text_channel_id_none_without_bot(monkeypatch):
    monkeypatch.setattr(vb, "_active_bot", None)
    assert vb.current_text_channel_id() is None


def test_current_text_channel_id_none_without_session_channel(monkeypatch):
    monkeypatch.setattr(vb, "_active_bot", SimpleNamespace(_text_channel=None))
    assert vb.current_text_channel_id() is None


def test_current_text_channel_id_returns_id(monkeypatch):
    monkeypatch.setattr(
        vb, "_active_bot",
        SimpleNamespace(_text_channel=SimpleNamespace(id=42)),
    )
    assert vb.current_text_channel_id() == "42"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_voice_bot_recovery.py -q`
Expected: 3 new FAIL — `AttributeError: module 'voice_bot' has no attribute '_active_bot'`.

- [ ] **Step 3: Implement**

In `webhook-handler/voice_bot.py`, just above `async def start_voice_bot(`:

```python
# The running bot instance (one per process). Lets the web layer (voice build
# watcher) target the active session's text channel without holding the task.
_active_bot = None


def current_text_channel_id() -> str | None:
    """Channel id of the active voice session's text channel, else None."""
    bot = _active_bot
    ch = getattr(bot, "_text_channel", None) if bot is not None else None
    return str(ch.id) if ch is not None else None
```

In `start_voice_bot`, after `bot = ConversationalVoiceBot(...)`:

```python
    global _active_bot
    _active_bot = bot
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_voice_bot_recovery.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/voice_bot.py webhook-handler/tests/test_voice_bot_recovery.py
git commit -m "feat(voice): expose active session text channel for build notifications"
```

---

### Task 4: Voice identity — `VOICE_USER_EMAIL`

**Files:**
- Modify: `webhook-handler/config.py` (Voice section ~line 129)
- Modify: `webhook-handler/handlers/commands.py` (`_resolve_email_for_ctx` ~line 1761)
- Create: `webhook-handler/tests/test_voice_app_builder.py`

- [ ] **Step 1: Write the failing tests**

Create `webhook-handler/tests/test_voice_app_builder.py`:

```python
"""Voice App Builder flow: identity, run_voice_build, run_voice_build_status."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from config import settings
from handlers.commands import CommandRouter, CommandContext
from clients.tasks import TasksAPIError


def _voice_ctx(captured, command="aiuibuilder", arguments="", notify=None):
    async def respond(msg):
        captured.append(msg)
    return CommandContext(
        user_id="voice-agent", user_name="Voice User", channel_id="voice",
        raw_text=f"{command} {arguments}".strip(), subcommand=command,
        arguments=arguments, platform="voice", respond=respond,
        metadata={"source": "elevenlabs"}, notify_channel=notify,
    )


def _router(tasks_client):
    if not isinstance(getattr(tasks_client, "resolve_link", None), AsyncMock):
        tasks_client.resolve_link = AsyncMock(return_value=None)
    return CommandRouter(
        openwebui_client=MagicMock(),
        n8n_client=MagicMock(api_key=""),
        discord_user_email_map={},
        tasks_client=tasks_client,
    )


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_voice_email_resolves_from_setting(monkeypatch):
    monkeypatch.setattr(settings, "voice_user_email", "Owner@Example.COM")
    router = _router(MagicMock())
    email = await router._resolve_email_for_ctx(_voice_ctx([]))
    assert email == "owner@example.com"


@pytest.mark.asyncio
async def test_voice_email_none_when_unset(monkeypatch):
    monkeypatch.setattr(settings, "voice_user_email", "")
    router = _router(MagicMock())
    assert await router._resolve_email_for_ctx(_voice_ctx([])) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_voice_app_builder.py -q`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'voice_user_email'` (monkeypatch refuses to set a missing attribute).

- [ ] **Step 3: Implement**

`webhook-handler/config.py` — in the Voice section after `elevenlabs_agent_id`:

```python
    # Owner of voice-started App Builder builds (spoken flow has no per-user
    # identity; single-operator by design).
    voice_user_email: str = ""
```

`webhook-handler/handlers/commands.py` — in `_resolve_email_for_ctx`, before the `if ctx.platform == "slack":` branch:

```python
        if ctx.platform == "voice":
            return (settings.voice_user_email or "").strip().lower() or None
```

(`settings` is already imported at module top.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_voice_app_builder.py -q`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/config.py webhook-handler/handlers/commands.py webhook-handler/tests/test_voice_app_builder.py
git commit -m "feat(voice): VOICE_USER_EMAIL identity for voice-started builds"
```

---

### Task 5: `run_voice_build` — explicit template key + description

**Files:**
- Modify: `webhook-handler/handlers/commands.py` (`_start_build` ~line 1512 — add return; new method after `run_panel_build` ~line 1556)
- Test: `webhook-handler/tests/test_voice_app_builder.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `webhook-handler/tests/test_voice_app_builder.py`:

```python
# ---------------------------------------------------------------------------
# run_voice_build
# ---------------------------------------------------------------------------

CATALOG = [
    {"key": "restaurant", "label": "Restaurant", "description": "menus"},
    {"key": "portfolio", "label": "Portfolio", "description": "showcase"},
]


@pytest.mark.asyncio
async def test_voice_build_not_linked_spoken(monkeypatch):
    monkeypatch.setattr(settings, "voice_user_email", "")
    captured = []
    tc = MagicMock(); tc.start_build = AsyncMock()
    await _router(tc).run_voice_build(_voice_ctx(captured), None, "a cafe site")
    assert captured and "VOICE_USER_EMAIL" in captured[-1]
    tc.start_build.assert_not_awaited()


@pytest.mark.asyncio
async def test_voice_build_template_happy_path(monkeypatch):
    monkeypatch.setattr(settings, "voice_user_email", "o@x.com")
    captured = []
    tc = MagicMock()
    tc.list_templates = AsyncMock(return_value=CATALOG)
    tc.start_build = AsyncMock(return_value={"task_id": "t9", "slug": "marios-1234"})
    watched = {}
    async def fake_watch(self, ctx, email, task_id, slug):
        watched["args"] = (email, task_id, slug)
    monkeypatch.setattr(CommandRouter, "_watch_build", fake_watch)
    async def notify(msg):
        pass

    result = await _router(tc).run_voice_build(
        _voice_ctx(captured, notify=notify), "Restaurant", "a site called Marios",
    )
    import asyncio as _a; await _a.sleep(0)
    assert result == {"task_id": "t9", "slug": "marios-1234"}
    tc.start_build.assert_awaited_once()
    assert tc.start_build.call_args.kwargs.get("template_key") == "restaurant"
    assert tc.start_build.call_args.args[1] == "a site called Marios"
    assert any("marios-1234" in m for m in captured)
    assert watched["args"] == ("o@x.com", "t9", "marios-1234")


@pytest.mark.asyncio
async def test_voice_build_blank_project_no_template(monkeypatch):
    monkeypatch.setattr(settings, "voice_user_email", "o@x.com")
    captured = []
    tc = MagicMock()
    tc.start_build = AsyncMock(return_value={"task_id": "t1", "slug": "s-1"})
    result = await _router(tc).run_voice_build(_voice_ctx(captured), None, "a blog")
    assert result == {"task_id": "t1", "slug": "s-1"}
    assert tc.start_build.call_args.kwargs.get("template_key") is None
    tc.list_templates.assert_not_called()  # no catalog fetch for blank builds


@pytest.mark.asyncio
async def test_voice_build_unknown_template_spoken_error(monkeypatch):
    monkeypatch.setattr(settings, "voice_user_email", "o@x.com")
    captured = []
    tc = MagicMock()
    tc.list_templates = AsyncMock(return_value=CATALOG)
    tc.start_build = AsyncMock()
    result = await _router(tc).run_voice_build(
        _voice_ctx(captured), "spaceship", "a site")
    assert result is None
    tc.start_build.assert_not_awaited()
    assert any("spaceship" in m for m in captured)


@pytest.mark.asyncio
async def test_voice_build_empty_description_rejected(monkeypatch):
    monkeypatch.setattr(settings, "voice_user_email", "o@x.com")
    captured = []
    tc = MagicMock(); tc.start_build = AsyncMock()
    result = await _router(tc).run_voice_build(_voice_ctx(captured), None, "   ")
    assert result is None
    tc.start_build.assert_not_awaited()
    assert any("describe" in m.lower() for m in captured)


@pytest.mark.asyncio
async def test_voice_build_tasks_error_spoken(monkeypatch):
    monkeypatch.setattr(settings, "voice_user_email", "o@x.com")
    captured = []
    tc = MagicMock()
    tc.start_build = AsyncMock(side_effect=TasksAPIError(429, "busy"))
    result = await _router(tc).run_voice_build(_voice_ctx(captured), None, "a blog")
    assert result is None
    assert captured, "expected a spoken error"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_voice_app_builder.py -q`
Expected: new tests FAIL — `AttributeError: 'CommandRouter' object has no attribute 'run_voice_build'`.

- [ ] **Step 3: Implement**

`webhook-handler/handlers/commands.py`:

1. `_start_build` — return the result so the voice layer can remember it. Change the signature line and the tail:

```python
    async def _start_build(
        self, ctx: CommandContext, email: str, template_key: str | None,
        description: str, *, template_label: str | None = None,
    ) -> dict | None:
        """Start a one-shot build and wire the result watcher.

        Shared by the `/aiui aiuibuilder build` text path, the App Builder
        channel button/modal path, and the voice flow. `description` must be
        non-empty (callers validate). `template_label`, when given, is named
        in the ack. Returns the tasks-service result ({"slug", "task_id"})
        on success, None on failure."""
        try:
            result = await self._tasks_client.start_build(
                email, description, template_key=template_key)
        except TasksAPIError as e:
            await ctx.respond(self._format_build_error(e))
            return None
```
and at the end of the method (after the watcher wiring) add:
```python
        return result
```

2. After `run_panel_build`, add:

```python
    async def run_voice_build(
        self, ctx: CommandContext, template_key: str | None, description: str,
    ) -> dict | None:
        """Voice entry: explicit template key (or None for blank) + spoken
        description. Unknown keys are a spoken error, never a silent blank
        build — the user explicitly picked a template. Returns
        {"slug", "task_id"} on success so the voice layer can remember the
        last build for the build_status tool."""
        email = await self._resolve_email_for_ctx(ctx)
        if not email:
            await ctx.respond(
                "Voice builds aren't linked to an account yet — the operator "
                "needs to set VOICE_USER_EMAIL on the server."
            )
            return None
        description = (description or "").strip()
        if not description:
            await ctx.respond("Please describe the app you want to build.")
            return None
        template_key = (template_key or "").strip().lower() or None
        template_label = None
        if template_key:
            try:
                catalog = await self._tasks_client.list_templates(email)
            except TasksAPIError:
                catalog = []
            labels = {
                t["key"]: t.get("label", t["key"])
                for t in catalog if t.get("key")
            }
            if template_key not in labels:
                await ctx.respond(
                    f"I don't know a template called {template_key}. "
                    "Ask me to list templates, or build without one."
                )
                return None
            template_label = labels[template_key]
        return await self._start_build(
            ctx, email, template_key, description,
            template_label=template_label,
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_voice_app_builder.py tests/test_aiuibuilder_build.py tests/test_panel_build.py -q`
Expected: all PASS (existing build suites prove the `_start_build` return change is non-breaking).

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/handlers/commands.py webhook-handler/tests/test_voice_app_builder.py
git commit -m "feat(voice): run_voice_build — template-or-blank build entry for the voice agent"
```

---

### Task 6: `run_voice_build_status` — "is my build done?"

**Files:**
- Modify: `webhook-handler/handlers/commands.py` (after `run_voice_build`)
- Test: `webhook-handler/tests/test_voice_app_builder.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `webhook-handler/tests/test_voice_app_builder.py`:

```python
# ---------------------------------------------------------------------------
# run_voice_build_status
# ---------------------------------------------------------------------------

async def _status_reply(status_payload, *, error=None):
    captured = []
    tc = MagicMock()
    if error is not None:
        tc.get_build_status = AsyncMock(side_effect=error)
    else:
        tc.get_build_status = AsyncMock(return_value=status_payload)
    await _router(tc).run_voice_build_status(
        _voice_ctx(captured), "o@x.com", "t9", slug="marios-1234")
    return captured


@pytest.mark.asyncio
async def test_build_status_running():
    captured = await _status_reply({"status": "running"})
    assert any("still building" in m.lower() for m in captured)


@pytest.mark.asyncio
async def test_build_status_completed_names_url():
    captured = await _status_reply(
        {"status": "completed", "preview_url": "https://x/preview-app/marios-1234/"})
    joined = " ".join(captured).lower()
    assert "ready" in joined and "marios-1234" in joined


@pytest.mark.asyncio
async def test_build_status_failed():
    captured = await _status_reply({"status": "failed"})
    assert any("failed" in m.lower() for m in captured)


@pytest.mark.asyncio
async def test_build_status_needs_input_includes_detail():
    captured = await _status_reply(
        {"status": "needs_input", "error": "Which city is the restaurant in?"})
    joined = " ".join(captured)
    assert "Which city" in joined


@pytest.mark.asyncio
async def test_build_status_api_error_spoken():
    captured = await _status_reply(None, error=TasksAPIError(0, "down"))
    assert any("try again" in m.lower() for m in captured)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_voice_app_builder.py -q`
Expected: new tests FAIL — `AttributeError: ... no attribute 'run_voice_build_status'`.

- [ ] **Step 3: Implement**

`webhook-handler/handlers/commands.py`, after `run_voice_build`:

```python
    async def run_voice_build_status(
        self, ctx: CommandContext, email: str, task_id: str, slug: str = "",
    ) -> None:
        """Speak the state of a build. The voice layer picks the task_id
        (explicit from the agent, else the remembered last voice build)."""
        name = slug or "your app"
        try:
            st = await self._tasks_client.get_build_status(email, task_id)
        except TasksAPIError:
            await ctx.respond(
                "I couldn't reach the builder to check — try again in a moment."
            )
            return
        status = st.get("status")
        if status == "completed":
            url = (st.get("preview_url") or "").strip()
            tail = f" The preview link is in the text channel: {url}" if url else ""
            await ctx.respond(f"Good news — {name} is ready.{tail}")
        elif status == "failed":
            await ctx.respond(
                f"The build for {name} failed. You can ask me to build it again."
            )
        elif status == "needs_input":
            detail = (st.get("error") or "").strip()
            tail = f" It needs to know: {detail}" if detail else ""
            await ctx.respond(f"The build for {name} is paused.{tail}")
        else:
            await ctx.respond(
                f"{name} is still building — I'll post the link in the text "
                "channel the moment it's ready."
            )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_voice_app_builder.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/handlers/commands.py webhook-handler/tests/test_voice_app_builder.py
git commit -m "feat(voice): run_voice_build_status — spoken build progress"
```

---

### Task 7: Voice webhook wiring in `main.py`

Special-case the three commands, remember the last voice build, and give voice ctxs a real `notify_channel` (active session's text channel at notify time, else alert channel).

**Files:**
- Modify: `webhook-handler/main.py` (import ~line 29; new helpers before `voice_webhook` ~line 519; `voice_webhook` body)
- Modify: any test stubbing `sys.modules["voice_bot"]` (must gain `current_text_channel_id`) — find with `grep -rn "voice_bot" webhook-handler/tests/*.py | grep -i "modules"`; known: `tests/test_discord_e2e_local.py`, `tests/test_format_schedule_result.py`
- Test: `webhook-handler/tests/test_voice_webhook_wiring.py` (create — separate module because it imports `main` with stubbed deps, mirroring `test_format_schedule_result.py`)

- [ ] **Step 1: Look at the existing stub preamble**

Read the top of `webhook-handler/tests/test_format_schedule_result.py` and copy its `sys.modules` stub pattern exactly (it stubs `discord`/`voice_bot` so `main` imports without audio deps). Whatever shape it uses, ADD `current_text_channel_id = lambda: None` to the fake `voice_bot` module there and in `tests/test_discord_e2e_local.py` (otherwise `from voice_bot import ... current_text_channel_id` in `main.py` breaks those suites).

- [ ] **Step 2: Write the failing tests**

Create `webhook-handler/tests/test_voice_webhook_wiring.py` (adapt the stub preamble from Step 1 — the snippet below shows the required shape):

```python
"""/webhook/voice/{command} routing: special-cases + last-build memory."""
import sys
import types

import pytest
from unittest.mock import AsyncMock, MagicMock

# Stub audio deps BEFORE importing main (same pattern as
# test_format_schedule_result.py — keep in sync with it).
if "voice_bot" not in sys.modules or not hasattr(sys.modules["voice_bot"], "start_voice_bot"):
    fake_vb = types.ModuleType("voice_bot")
    async def _start_voice_bot(**kwargs):
        return None
    fake_vb.start_voice_bot = _start_voice_bot
    fake_vb.current_text_channel_id = lambda: None
    sys.modules["voice_bot"] = fake_vb

import main  # noqa: E402
from config import settings  # noqa: E402


class _Req:
    def __init__(self, body):
        self._body = body
    async def json(self):
        return self._body


@pytest.fixture()
def voice_setup(monkeypatch):
    monkeypatch.setattr(settings, "voice_webhook_secret", "s3cret")
    monkeypatch.setattr(settings, "voice_user_email", "o@x.com")
    router = MagicMock()
    router.execute = AsyncMock()
    router.run_voice_build = AsyncMock(return_value={"task_id": "t9", "slug": "m-1"})
    router.run_voice_build_status = AsyncMock()
    monkeypatch.setattr(main, "command_router", router)
    main._last_voice_build.clear()
    return router


@pytest.mark.asyncio
async def test_list_templates_routes_to_aiuibuilder(voice_setup):
    await main.voice_webhook("list_templates", _Req({}), x_voice_secret="s3cret")
    ctx = voice_setup.execute.await_args.args[0]
    assert ctx.subcommand == "aiuibuilder"
    assert ctx.arguments == "templates"
    assert ctx.platform == "voice"


@pytest.mark.asyncio
async def test_start_build_remembers_last_build(voice_setup):
    resp = await main.voice_webhook(
        "start_build",
        _Req({"template_key": "restaurant", "description": "a cafe"}),
        x_voice_secret="s3cret",
    )
    voice_setup.run_voice_build.assert_awaited_once()
    args = voice_setup.run_voice_build.await_args.args
    assert args[1] == "restaurant" and args[2] == "a cafe"
    assert main._last_voice_build["task_id"] == "t9"
    assert main._last_voice_build["slug"] == "m-1"
    assert "spoken_summary" in resp


@pytest.mark.asyncio
async def test_build_status_uses_remembered_build(voice_setup):
    main._last_voice_build.update(
        {"task_id": "t9", "slug": "m-1", "email": "o@x.com"})
    await main.voice_webhook("build_status", _Req({}), x_voice_secret="s3cret")
    voice_setup.run_voice_build_status.assert_awaited_once()
    args = voice_setup.run_voice_build_status.await_args
    assert args.args[1] == "o@x.com" and args.args[2] == "t9"
    assert args.kwargs.get("slug") == "m-1"


@pytest.mark.asyncio
async def test_build_status_without_memory_speaks_no_build(voice_setup):
    resp = await main.voice_webhook("build_status", _Req({}), x_voice_secret="s3cret")
    voice_setup.run_voice_build_status.assert_not_awaited()
    assert "haven't started" in resp["spoken_summary"].lower()


@pytest.mark.asyncio
async def test_generic_command_unchanged(voice_setup):
    await main.voice_webhook(
        "status", _Req({"arguments": ""}), x_voice_secret="s3cret")
    ctx = voice_setup.execute.await_args.args[0]
    assert ctx.subcommand == "status"


@pytest.mark.asyncio
async def test_bad_secret_rejected(voice_setup):
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        await main.voice_webhook("status", _Req({}), x_voice_secret="wrong")
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/test_voice_webhook_wiring.py -q`
Expected: FAIL — `AttributeError: module 'main' has no attribute '_last_voice_build'`; `run_voice_build` never awaited (generic passthrough hits `execute` instead).

- [ ] **Step 4: Implement**

`webhook-handler/main.py`:

1. Change the voice import (line 29):

```python
from voice_bot import start_voice_bot, current_text_channel_id
```

2. Above `@app.post("/webhook/voice/{command}")` add:

```python
# Last voice-started build (single voice identity by design). Lets the agent's
# build_status tool answer "is my build done?" even after a session reconnect.
_last_voice_build: dict = {}


async def _post_to_discord_channel(channel_id: str, content: str) -> None:
    """Plain bot-token channel message (same pattern as the alert forwarder)."""
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    headers = {
        "Authorization": f"Bot {settings.discord_bot_token}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(url, json={"content": content[:1990]}, headers=headers)
        resp.raise_for_status()


def _voice_notify_channel():
    """notify_channel for voice-started builds. The target is resolved at
    NOTIFY time (builds finish minutes later): the active voice session's
    text channel when one exists, else the alert channel."""
    if not settings.discord_bot_token:
        return None

    async def notify(msg: str) -> None:
        channel_id = current_text_channel_id() or settings.discord_alert_channel_id
        if not channel_id:
            logger.warning("voice notify dropped (no channel configured): %s", msg[:80])
            return
        await _post_to_discord_channel(channel_id, msg)

    return notify
```

3. Replace the body of `voice_webhook` after the secret check with:

```python
    body = await request.json()
    collector = VoiceResponseCollector()

    def _ctx(subcommand: str, arguments: str) -> CommandContext:
        return CommandContext(
            user_id="voice-agent",
            user_name="Voice User",
            channel_id=body.get("channel_id", "voice"),
            raw_text=f"{subcommand} {arguments}".strip(),
            subcommand=subcommand,
            arguments=arguments,
            platform="voice",
            respond=collector.respond,
            metadata={"source": "elevenlabs"},
            notify_channel=_voice_notify_channel(),
        )

    if command == "list_templates":
        await command_router.execute(_ctx("aiuibuilder", "templates"))
    elif command == "start_build":
        result = await command_router.run_voice_build(
            _ctx("aiuibuilder", "build"),
            body.get("template_key"),
            body.get("description") or "",
        )
        if result:
            _last_voice_build.clear()
            _last_voice_build.update({
                "task_id": result.get("task_id", ""),
                "slug": result.get("slug", ""),
                "email": (settings.voice_user_email or "").strip().lower(),
            })
    elif command == "build_status":
        task_id = (body.get("task_id") or "").strip() or _last_voice_build.get("task_id", "")
        if not task_id:
            await collector.respond(
                "I haven't started any build for you yet — ask me to build "
                "something first."
            )
        else:
            await command_router.run_voice_build_status(
                _ctx("aiuibuilder", "build-status"),
                _last_voice_build.get("email")
                or (settings.voice_user_email or "").strip().lower(),
                task_id,
                slug=_last_voice_build.get("slug", ""),
            )
    else:
        arguments = body.get("arguments", "")
        if body.get("owner") and body.get("repo"):
            arguments = f"{body['owner']}/{body['repo']} {arguments}".strip()
        await command_router.execute(_ctx(command, arguments))

    return {
        "spoken_summary": collector.spoken_summary,
        "full_result": collector.full_result,
        "post_to_text_channel": len(collector.full_result) > 500,
    }
```

4. Update the fake `voice_bot` stubs found in Step 1 (`tests/test_discord_e2e_local.py`, `tests/test_format_schedule_result.py`, plus any other hit): add `current_text_channel_id = lambda: None` (match each file's stub style).

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_voice_webhook_wiring.py tests/test_format_schedule_result.py tests/test_discord_e2e_local.py -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add webhook-handler/main.py webhook-handler/tests/
git commit -m "feat(voice): App Builder webhook tools — list_templates/start_build/build_status wiring"
```

---

### Task 8: `setup_voice_agent.py` — agent config as code

Idempotently pushes the prompt + 3 tools to ElevenLabs. Stdlib-only (`urllib`) so it runs on the VPS host. Never prints secrets.

**Files:**
- Create: `webhook-handler/scripts/setup_voice_agent.py`
- Create: `webhook-handler/tests/test_setup_voice_agent_script.py`

- [ ] **Step 1: Write the failing tests**

Create `webhook-handler/tests/test_setup_voice_agent_script.py`:

```python
"""Pure logic of scripts/setup_voice_agent.py (no HTTP)."""
import importlib.util
import pathlib

_spec = importlib.util.spec_from_file_location(
    "setup_voice_agent",
    pathlib.Path(__file__).resolve().parents[1] / "scripts" / "setup_voice_agent.py",
)
sva = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sva)


def test_three_tools_defined_with_secret_header():
    tools = sva.build_tool_definitions("sssh")
    names = [t["name"] for t in tools]
    assert names == ["list_templates", "start_build", "build_status"]
    for t in tools:
        assert t["type"] == "webhook"
        api = t["api_schema"]
        assert api["url"] == f"https://ai-ui.coolestdomain.win/webhook/voice/{t['name']}"
        assert api["method"] == "POST"
        assert api["request_headers"]["X-Voice-Secret"] == "sssh"


def test_start_build_schema_requires_description():
    tools = {t["name"]: t for t in sva.build_tool_definitions("x")}
    body = tools["start_build"]["api_schema"]["request_body_schema"]
    assert body["required"] == ["description"]
    assert "template_key" in body["properties"]
    body_status = tools["build_status"]["api_schema"]["request_body_schema"]
    assert body_status["required"] == []


def test_plan_tool_changes_is_idempotent():
    wanted = sva.build_tool_definitions("x")
    existing = [
        {"id": "tool_1", "tool_config": {"name": "start_build"}},
        {"id": "tool_2", "tool_config": {"name": "status"}},  # unrelated, untouched
    ]
    creates, updates = sva.plan_tool_changes(existing, wanted)
    assert [t["name"] for t in creates] == ["list_templates", "build_status"]
    assert [u[0] for u in updates] == ["tool_1"]


def test_merged_tool_ids_preserves_existing():
    merged = sva.merged_tool_ids(["a", "b"], ["b", "c", "d"])
    assert merged == ["a", "b", "c", "d"]


def test_prompt_contains_flow_and_keeps_existing_capabilities():
    p = sva.AGENT_PROMPT
    assert "template, or a blank project" in p
    assert "list_templates" in p and "start_build" in p and "build_status" in p
    assert "never read the whole list aloud" in p.lower()
    # the pre-existing capabilities must survive the prompt rewrite
    for cap in ("status:", "pr-review", "Default repository"):
        assert cap in p
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_setup_voice_agent_script.py -q`
Expected: FAIL — `FileNotFoundError` (script doesn't exist).

- [ ] **Step 3: Implement**

Create `webhook-handler/scripts/setup_voice_agent.py`:

```python
#!/usr/bin/env python3
"""Push the AIUI voice agent config (prompt + App Builder tools) to ElevenLabs.

Config-as-code for the ElevenLabs Conversational AI agent — the prompt and the
three App Builder webhook tools live HERE, not in the dashboard. Idempotent:
tools are matched by name (create or update), the agent prompt is replaced,
and tool_ids are merged (existing tools are never dropped).

Usage (on the VPS host — stdlib only, no pip deps):
    python3 scripts/setup_voice_agent.py --env-file /root/proxy-server/.env --dry-run
    python3 scripts/setup_voice_agent.py --env-file /root/proxy-server/.env

Reads ELEVENLABS_API_KEY, ELEVENLABS_AGENT_ID, VOICE_WEBHOOK_SECRET from the
environment (or --env-file). Never prints secret values.
"""
import argparse
import json
import os
import sys
import urllib.request

API = "https://api.elevenlabs.io"
WEBHOOK_BASE = "https://ai-ui.coolestdomain.win/webhook/voice"

AGENT_PROMPT = """You are A.I.U.I. (pronounced "ay-eye-you-eye"), a voice assistant for a software development team. Users speak commands to you and you execute them using your available tools.

When a user asks you to do something:
1. Identify which tool matches their request
2. Call the tool with the right parameters
3. Summarize the result conversationally for speech
4. For long results, say a brief summary and mention "I've posted the full details in the text channel"

Available tools map to these capabilities:
- status: check if services are running
- ask: answer general questions
- security: security audit a code repository
- health: code health assessment
- deps: check for outdated dependencies
- license: check license compliance
- pr-review: review a GitHub pull request (needs PR number)
- sheets: write a report to Google Sheets
- analyze: extract business requirements from a repo
- rebuild: research and plan rebuilding an app
- workflows: list automation workflows
- report: generate end-of-day summary
Default repository is TheLukasHenry/proxy-server unless the user specifies otherwise.

## Building websites (App Builder)
When the user wants to create or build a website or app, run this flow one question at a time:
1. First ask: "Would you like to start from a template, or a blank project?"
2. If they choose template: ask what kind of site it is, then call list_templates and suggest the 2 or 3 closest matching templates by label, conversationally. Never read the whole list aloud.
3. Ask for a short description: the site's name plus one or two details (purpose, style, or color).
4. Read back one short summary line, for example: "A restaurant site called Mario's, from the restaurant template — should I build it?" Wait for a clear yes.
5. On yes, call start_build with description, and template_key ONLY when the user picked a template (omit it for a blank project).
6. After it starts: say it takes a few minutes, the preview link will be posted in the text channel, and they can ask "is my build done?" anytime.
7. When they ask whether it's done, call build_status and relay the answer in one sentence.

Be concise in speech — one or two short sentences per reply. Technical details go to the text channel.
IMPORTANT: Common voice commands users will say:
- "status" (may sound like "tadous", "stados", "sta-dus")
- "health" followed by a repository like "jacintalama/devtech"
- "security", "deps", "workflows", "report", "analyze", "rebuild"
- "sheets", "pr review", "license"
- "create a website", "build me a site", "make an app" — start the App Builder flow above
Language instructions: Always respond in the same language the user is speaking. If the user switches languages, follow them. Do not default to English unless the user speaks English."""


def _str_prop(description: str) -> dict:
    return {"type": "string", "description": description}


def build_tool_definitions(secret: str) -> list[dict]:
    """The three App Builder webhook tools, shaped like the live tools
    (captured 2026-06-12 from GET /v1/convai/tools)."""
    def tool(name: str, description: str, required: list, props: dict) -> dict:
        return {
            "type": "webhook",
            "name": name,
            "description": description,
            "response_timeout_secs": 30,
            "disable_interruptions": True,
            "api_schema": {
                "url": f"{WEBHOOK_BASE}/{name}",
                "method": "POST",
                "request_headers": {"X-Voice-Secret": secret},
                "request_body_schema": {
                    "type": "object",
                    "required": required,
                    "description": f"Request body for {name}",
                    "properties": props,
                },
                "content_type": "application/json",
            },
        }

    return [
        tool(
            "list_templates",
            "List the available App Builder website templates (key, label, "
            "description). Call this when the user wants to start from a "
            "template, then suggest the 2-3 closest matches — never read "
            "the whole list aloud.",
            [],
            {"reason": _str_prop("Optional: what kind of site the user wants")},
        ),
        tool(
            "start_build",
            "Start building a website/app with the App Builder. Call ONLY "
            "after the user confirmed the summary. Takes a few minutes; the "
            "preview link is posted to the Discord text channel.",
            ["description"],
            {
                "description": _str_prop(
                    "One or two sentences describing the site: name, purpose, "
                    "style. Example: a restaurant site called Mario's with a "
                    "menu page"
                ),
                "template_key": _str_prop(
                    "Template key exactly as returned by list_templates, e.g. "
                    "restaurant. OMIT for a blank project."
                ),
            },
        ),
        tool(
            "build_status",
            "Check whether the current website build is finished. Use when "
            "the user asks if their build/site is done or ready.",
            [],
            {
                "task_id": _str_prop(
                    "Optional build task id; omit to use the most recent build"
                ),
            },
        ),
    ]


def plan_tool_changes(existing: list[dict], wanted: list[dict]):
    """(creates, updates) — match by tool name; unrelated tools untouched."""
    by_name = {
        (t.get("tool_config") or {}).get("name"): t.get("id")
        for t in existing
    }
    creates = [w for w in wanted if w["name"] not in by_name]
    updates = [(by_name[w["name"]], w) for w in wanted if w["name"] in by_name]
    return creates, updates


def merged_tool_ids(current_ids: list, new_ids: list) -> list:
    """Existing ids first (never dropped), new ones appended, de-duplicated."""
    out = list(current_ids or [])
    for i in new_ids:
        if i not in out:
            out.append(i)
    return out


# --- everything below talks to the API (not unit-tested) -------------------

def _read_env_file(path: str) -> None:
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _req(method: str, path: str, key: str, payload: dict | None = None) -> dict:
    body = json.dumps(payload).encode() if payload is not None else None
    r = urllib.request.Request(
        API + path, data=body, method=method,
        headers={"xi-api-key": key, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(r, timeout=30) as resp:
        raw = resp.read()
    return json.loads(raw) if raw else {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file", help="parse KEY=VALUE pairs into the env first")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.env_file:
        _read_env_file(args.env_file)

    key = os.environ.get("ELEVENLABS_API_KEY", "")
    agent_id = os.environ.get("ELEVENLABS_AGENT_ID", "")
    secret = os.environ.get("VOICE_WEBHOOK_SECRET", "")
    missing = [n for n, v in [("ELEVENLABS_API_KEY", key),
                              ("ELEVENLABS_AGENT_ID", agent_id),
                              ("VOICE_WEBHOOK_SECRET", secret)] if not v]
    if missing:
        print("Missing env:", ", ".join(missing))
        return 1

    wanted = build_tool_definitions(secret)
    existing = _req("GET", "/v1/convai/tools", key).get("tools", [])
    creates, updates = plan_tool_changes(existing, wanted)
    print(f"tools: {len(existing)} existing; create {[t['name'] for t in creates]}; "
          f"update {[u[1]['name'] for u in updates]}")

    agent = _req("GET", f"/v1/convai/agents/{agent_id}", key)
    prompt_cfg = (agent.get("conversation_config", {})
                  .get("agent", {}).get("prompt", {}))
    current_ids = prompt_cfg.get("tool_ids") or []
    prompt_changes = prompt_cfg.get("prompt") != AGENT_PROMPT
    print(f"agent: {len(current_ids)} tool ids; prompt update needed: {prompt_changes}")

    if args.dry_run:
        print("dry-run: no changes written")
        return 0

    new_ids = []
    for cfg in creates:
        created = _req("POST", "/v1/convai/tools", key, {"tool_config": cfg})
        new_ids.append(created["id"])
        print(f"created tool {cfg['name']}")
    for tool_id, cfg in updates:
        _req("PATCH", f"/v1/convai/tools/{tool_id}", key, {"tool_config": cfg})
        new_ids.append(tool_id)
        print(f"updated tool {cfg['name']}")

    payload = {"conversation_config": {"agent": {"prompt": {
        "prompt": AGENT_PROMPT,
        "tool_ids": merged_tool_ids(current_ids, new_ids),
    }}}}
    _req("PATCH", f"/v1/convai/agents/{agent_id}", key, payload)

    final = _req("GET", f"/v1/convai/agents/{agent_id}", key)
    ids = (final.get("conversation_config", {}).get("agent", {})
           .get("prompt", {}).get("tool_ids") or [])
    print(f"done: agent now has {len(ids)} tools")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_setup_voice_agent_script.py -q`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/scripts/setup_voice_agent.py webhook-handler/tests/test_setup_voice_agent_script.py
git commit -m "feat(voice): ElevenLabs agent config as code — App Builder prompt + 3 webhook tools"
```

---

### Task 9: Compose env passthrough + full suite green

**Files:**
- Modify: `docker-compose.unified.yml` (webhook-handler environment list, after line 140 `ELEVENLABS_AGENT_ID`)

- [ ] **Step 1: Add the env line**

After `- ELEVENLABS_AGENT_ID=${ELEVENLABS_AGENT_ID:-}` add:

```yaml
      - VOICE_USER_EMAIL=${VOICE_USER_EMAIL:-}
```

- [ ] **Step 2: Run the FULL webhook-handler suite**

Run: `python -m pytest tests/ -q`
Expected: everything passes (was 667 before this work; now ~695). Zero failures — fix anything that broke before proceeding.

- [ ] **Step 3: Commit**

```bash
git add docker-compose.unified.yml
git commit -m "chore(compose): pass VOICE_USER_EMAIL to webhook-handler"
```

---

### Task 10: Push + deploy + agent setup + smoke

Per repo rules: commit first, never `scp -r`, one scp per file, never touch `.env` beyond the single approved append, never print secrets.

- [ ] **Step 1: Push to fork/main**

```bash
git fetch fork
git rebase fork/main
gh auth switch -u Jacintalama
git -c credential.helper= -c "credential.helper=!f() { echo username=Jacintalama; echo password=$(gh auth token); }; f" push fork integrate-slack-pr4:main
```
Expected: push succeeds (includes the two earlier voice commits ff884a055/b666d0bbf already on this branch).

- [ ] **Step 2: scp the changed files (one per file)**

```bash
scp webhook-handler/voice_bot.py root@46.224.193.25:/root/proxy-server/webhook-handler/voice_bot.py
scp webhook-handler/main.py root@46.224.193.25:/root/proxy-server/webhook-handler/main.py
scp webhook-handler/config.py root@46.224.193.25:/root/proxy-server/webhook-handler/config.py
scp webhook-handler/handlers/commands.py root@46.224.193.25:/root/proxy-server/webhook-handler/handlers/commands.py
ssh root@46.224.193.25 "mkdir -p /root/proxy-server/webhook-handler/scripts"
scp webhook-handler/scripts/setup_voice_agent.py root@46.224.193.25:/root/proxy-server/webhook-handler/scripts/setup_voice_agent.py
scp docker-compose.unified.yml root@46.224.193.25:/root/proxy-server/docker-compose.unified.yml
```

- [ ] **Step 3: Append VOICE_USER_EMAIL (single line; approved 2026-06-12)**

The map format is `<snowflake>:<email>[,...]`. Print MASKED candidates first; pick the entry matching the operator (session user `al***@gmail.com`); never echo the full address:

```bash
ssh root@46.224.193.25 "python3 - <<'PY'
raw = [l for l in open('/root/proxy-server/.env')
       if l.startswith('DISCORD_USER_EMAIL_MAP=')][0].split('=', 1)[1].strip().strip('\"')
for pair in raw.split(','):
    did, _, email = pair.partition(':')
    e = email.strip()
    print(did.strip()[:4] + '...', e[:2] + '***@' + e.split('@', 1)[1])
PY"
```
Then append the chosen one **only if absent** (replace `<N>` with the chosen entry index):
```bash
ssh root@46.224.193.25 "grep -q '^VOICE_USER_EMAIL=' /root/proxy-server/.env || python3 - <<'PY'
raw = [l for l in open('/root/proxy-server/.env')
       if l.startswith('DISCORD_USER_EMAIL_MAP=')][0].split('=', 1)[1].strip().strip('\"')
email = raw.split(',')[<N>].partition(':')[2].strip()
with open('/root/proxy-server/.env', 'a') as f:
    f.write('\nVOICE_USER_EMAIL=' + email + '\n')
print('appended VOICE_USER_EMAIL (masked):', email[:2] + '***')
PY"
```

- [ ] **Step 4: Rebuild + verify container**

```bash
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --build webhook-handler && sleep 10 && docker compose -f docker-compose.unified.yml ps webhook-handler"
```
Expected: `Up` (healthy may take a minute). Then confirm the voice bot booted:
```bash
ssh root@46.224.193.25 "cd /root/proxy-server && docker logs --since 2m \$(docker compose -f docker-compose.unified.yml ps -q webhook-handler) 2>&1 | grep -E 'voice bot ready|Voice bot starting'"
```
Expected: `Conversational voice bot ready as aiui-teams#8536`.

- [ ] **Step 5: Run the agent setup script (dry-run, then real)**

```bash
ssh root@46.224.193.25 "cd /root/proxy-server/webhook-handler && python3 scripts/setup_voice_agent.py --env-file /root/proxy-server/.env --dry-run"
```
Expected: `tools: 11 existing; create ['list_templates', 'start_build', 'build_status']; update []` and `prompt update needed: True`. Then run without `--dry-run`.
Expected: `done: agent now has 14 tools`.

- [ ] **Step 6: Webhook smokes (secret stays on the server)**

```bash
ssh root@46.224.193.25 "python3 - <<'PY'
import json, urllib.request
env = {}
for line in open('/root/proxy-server/.env'):
    if '=' in line and not line.startswith('#'):
        k, _, v = line.strip().partition('=')
        env[k] = v.strip().strip('\"')
def call(cmd, body):
    r = urllib.request.Request(
        'https://ai-ui.coolestdomain.win/webhook/voice/' + cmd,
        data=json.dumps(body).encode(),
        headers={'X-Voice-Secret': env['VOICE_WEBHOOK_SECRET'],
                 'Content-Type': 'application/json'})
    return json.load(urllib.request.urlopen(r, timeout=60))
t = call('list_templates', {})
print('templates spoken:', t['spoken_summary'][:120])
print('templates full has restaurant:', 'restaurant' in t['full_result'].lower())
s = call('build_status', {})
print('status spoken:', s['spoken_summary'][:120])
PY"
```
Expected: templates summary lists template names; `build_status` says it hasn't started any build yet. (Do NOT smoke `start_build` — it would launch a real build; the live voice test covers it.)

- [ ] **Step 7: Commit nothing (deploy step) — update server deploy-state only if the orchestrator state is used**

Not needed for webhook-handler (not orchestrator-managed). Skip.

---

### Task 11: Live voice verification (needs the user)

- [ ] **Step 1: Arm the log monitor** (Monitor tool; re-arm if the container was rebuilt since):

```
ssh root@46.224.193.25 "cd /root/proxy-server && CID=$(docker compose -f docker-compose.unified.yml ps -q webhook-handler) && docker logs --since 5s -f $CID 2>&1" | grep --line-buffered -E "\[ConvAI\] (Voice state|Session started|stats5s|mic GATED|User:|Agent:|ElevenLabs ended|Ending session|Channel empty|Failed to start|DAVE|Clearing ghost|Graceful disconnect|output queue FULL|User interrupted)|voice handshake|Timed out waiting for voice"
```

- [ ] **Step 2: Ask the user to run the flow**

1. Join the General voice channel; wait for the greeting.
2. Say "Create me a website."
3. Expect: "template or blank?" → answer "template" → expect "what kind?" → answer (e.g. "a restaurant") → expect 2-3 suggestions → pick one → give a name/description → confirm the read-back summary with "yes".
4. Expect: build-started message (a few minutes, link in text channel), then ask "is my build done?" once or twice.
5. Confirm the preview link lands in the text channel when done.
6. Also verify the cutout fix: ask "explain what all your tools can do" (a deliberately long answer) — it must play to the end, no cut, no re-greet.

- [ ] **Step 3: Read the monitor evidence**

Healthy run: `stats5s ... dropped=+0` throughout; no `DAVE: No speech detected` while `has_content=True`; `User:`/`Agent:` transcript lines for each turn; build watcher posts `... is ready (preview): ...` to the text channel.

- [ ] **Step 4: Update memory + mark tasks complete**

Update `MEMORY.md` / project memory with the shipped feature + any new lessons; mark the session task list complete.

---

## Self-review notes (done at planning time)

- Spec coverage: cutout fix (Tasks 1-2), text-channel helper (3), identity (4), build/status entry points (5-6), webhook wiring + memory + notify (7), agent config-as-code (8), compose (9), rollout (10), live verify (11). `_wait_and_unmute` removal in Task 2. All spec sections have tasks.
- The `_start_build` return-value change is verified non-breaking by running the existing build suites in Task 5 Step 4.
- Existing `sys.modules["voice_bot"]` stubs MUST gain `current_text_channel_id` (Task 7) or `main.py`'s new import breaks unrelated suites — this is the one cross-cutting hazard; Task 7 Step 5 runs those suites explicitly.
- ElevenLabs API shapes for tool create/patch were captured live on 2026-06-12 (GET /v1/convai/tools). If POST/PATCH rejects a field, compare against a GET of an existing tool and trim to the accepted shape — `_req` raises `urllib.error.HTTPError`; read `e.read()` for the validation message.
- `DiscordAudioInterface` doesn't exist without voice deps (local runs): the drain hook is wired via `AudioOutputSource(on_drained=...)` (testable locally) and the interface CHAINS it (skipif-gated test; exercised for real on the server).
