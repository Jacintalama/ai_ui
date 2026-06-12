"""Self-healing behavior of the conversational voice bot.

Covers the three deaf-session defects observed live on 2026-06-11:
1. The DAVE watchdog refused to reconnect a deaf session because it required
   >100 mic frames — but a dead receive path delivers ZERO frames and even a
   real utterance is only ~50-100 frames, so it never fired (4.5 min deaf
   session with the watchdog alive).
2. A wedged graceful disconnect ("Timed out waiting for voice disconnection
   confirmation") left a ghost voice client attached to the guild.
3. That ghost blocked every subsequent session from starting.
"""
import asyncio
import sys
from types import SimpleNamespace

import pytest

# Other test modules stub sys.modules["discord"] / sys.modules["voice_bot"] so
# that `main` can be imported without audio deps. We need the real modules here
# — evict the stubs (modules already imported keep their stub references).
if "discord" in sys.modules and not hasattr(sys.modules["discord"], "AudioSource"):
    for _k in [k for k in sys.modules if k == "discord" or k.startswith("discord.")]:
        del sys.modules[_k]
pytest.importorskip("discord")  # skip whole module if discord.py isn't installed
if "voice_bot" in sys.modules and not hasattr(sys.modules["voice_bot"], "ConversationalVoiceBot"):
    del sys.modules["voice_bot"]

import voice_bot as vb  # noqa: E402
from voice_bot import ConversationalVoiceBot  # noqa: E402


def _make_bot() -> ConversationalVoiceBot:
    return ConversationalVoiceBot(elevenlabs_api_key="k", agent_id="a")


def _channel(*members):
    return SimpleNamespace(members=list(members), name="General")


USER = SimpleNamespace(bot=False, id=1, name="user")
BOT_MEMBER = SimpleNamespace(bot=True, id=999, name="aiui-teams")


# ---------------------------------------------------------------------------
# 1. Watchdog: must reconnect a deaf session even with zero mic frames
# ---------------------------------------------------------------------------

def test_watchdog_reconnects_deaf_session_with_zero_frames():
    bot = _make_bot()
    bot._session_active = True
    bot._session_voice_channel = _channel(USER, BOT_MEMBER)
    # Regression lock: zero frames fed (receive path dead) must NOT block recovery.
    bot._audio_interface = SimpleNamespace(_frame_count=0)
    assert bot._watchdog_should_reconnect(26.0) is True


def test_watchdog_waits_during_quiet_period():
    bot = _make_bot()
    bot._session_active = True
    bot._session_voice_channel = _channel(USER)
    assert bot._watchdog_should_reconnect(10.0) is False


def test_watchdog_idle_when_channel_has_no_users():
    bot = _make_bot()
    bot._session_active = True
    bot._session_voice_channel = _channel(BOT_MEMBER)
    assert bot._watchdog_should_reconnect(60.0) is False


def test_watchdog_idle_when_session_inactive():
    bot = _make_bot()
    bot._session_active = False
    bot._session_voice_channel = _channel(USER)
    assert bot._watchdog_should_reconnect(60.0) is False


# ---------------------------------------------------------------------------
# 2. Cleanup: a wedged graceful disconnect must be force-dropped
# ---------------------------------------------------------------------------

class WedgedVoiceClient:
    """Graceful disconnect hangs forever (wedged voice handshake)."""

    def __init__(self):
        self.force_disconnected = False
        self.cleaned_up = False

    def stop_listening(self):
        pass

    def is_playing(self):
        return False

    async def disconnect(self, force=False):
        if force:
            self.force_disconnected = True
            return
        await asyncio.sleep(60)

    def cleanup(self):
        self.cleaned_up = True


async def test_cleanup_force_drops_wedged_voice_client(monkeypatch):
    monkeypatch.setattr(vb, "DISCONNECT_TIMEOUT", 0.05)
    bot = _make_bot()
    bot._session_active = True
    vc = WedgedVoiceClient()
    monkeypatch.setattr(
        ConversationalVoiceBot, "voice_clients", property(lambda self: [vc])
    )
    await bot._cleanup()
    assert vc.force_disconnected, "wedged disconnect must fall back to force=True"
    assert vc.cleaned_up, "ghost client must be cleaned up so the guild slot frees"


# ---------------------------------------------------------------------------
# 3. Join with a lingering ghost client: clear it and start a fresh session
# ---------------------------------------------------------------------------

class GhostVoiceClient:
    def __init__(self):
        self.force_disconnected = False
        self.cleaned_up = False

    async def disconnect(self, force=False):
        self.force_disconnected = force

    def cleanup(self):
        self.cleaned_up = True


async def test_user_join_clears_ghost_and_starts_session(monkeypatch):
    bot = _make_bot()
    bot._session_active = False
    ghost = GhostVoiceClient()
    channel = SimpleNamespace(
        guild=SimpleNamespace(voice_client=ghost), name="General", members=[USER]
    )
    monkeypatch.setattr(
        ConversationalVoiceBot, "user", property(lambda self: SimpleNamespace(id=999))
    )
    started = []

    async def fake_start(ch, member):
        started.append(ch)

    monkeypatch.setattr(bot, "_start_session", fake_start)
    await bot.on_voice_state_update(
        USER, SimpleNamespace(channel=None), SimpleNamespace(channel=channel)
    )
    assert ghost.force_disconnected and ghost.cleaned_up
    assert started == [channel], "a fresh session must start after the ghost is cleared"


async def test_user_join_healthy_session_untouched(monkeypatch):
    """An ACTIVE session's voice client must never be torn down by a new join."""
    bot = _make_bot()
    bot._session_active = True
    live = GhostVoiceClient()
    channel = SimpleNamespace(
        guild=SimpleNamespace(voice_client=live), name="General", members=[USER]
    )
    monkeypatch.setattr(
        ConversationalVoiceBot, "user", property(lambda self: SimpleNamespace(id=999))
    )
    started = []

    async def fake_start(ch, member):
        started.append(ch)

    monkeypatch.setattr(bot, "_start_session", fake_start)
    await bot.on_voice_state_update(
        USER, SimpleNamespace(channel=None), SimpleNamespace(channel=channel)
    )
    assert not live.force_disconnected and not live.cleaned_up
    assert started == []


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
