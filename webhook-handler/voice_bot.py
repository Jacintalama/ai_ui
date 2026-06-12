"""AIUI Conversational Voice Bot — ElevenLabs Conversational AI + Discord.

Auto-joins voice channels. Full duplex conversation via ElevenLabs agent.
No typing needed — just speak.
"""
import asyncio
import logging
import queue
import threading
import time
from collections import OrderedDict

try:
    import audioop  # removed from stdlib in Python 3.13
except ImportError:  # pragma: no cover - container runs 3.11
    audioop = None

import discord

try:
    from discord.ext import voice_recv
    HAS_VOICE_RECV = True
except ImportError:
    HAS_VOICE_RECV = False

try:
    from elevenlabs import AsyncElevenLabs
    from elevenlabs.conversational_ai.conversation import (
        AsyncConversation,
        AsyncAudioInterface,
    )
    HAS_ELEVENLABS_CONV = True
except ImportError:
    HAS_ELEVENLABS_CONV = False

logger = logging.getLogger(__name__)


# Per-direction resampling state (audioop.ratecv needs persistent state)
_resample_state_in = None
_resample_state_out = None


def resample_48k_stereo_to_16k_mono(pcm_48k_stereo: bytes) -> bytes:
    """Convert 48kHz stereo S16LE to 16kHz mono S16LE."""
    global _resample_state_in
    if audioop is None or len(pcm_48k_stereo) < 4:
        return b""
    try:
        mono_48k = audioop.tomono(pcm_48k_stereo, 2, 0.5, 0.5)
        mono_16k, _resample_state_in = audioop.ratecv(
            mono_48k, 2, 1, 48000, 16000, _resample_state_in
        )
        return mono_16k
    except (audioop.error, Exception):
        return b""


def resample_16k_mono_to_48k_stereo(pcm_16k_mono: bytes) -> bytes:
    """Convert 16kHz mono S16LE to 48kHz stereo S16LE."""
    global _resample_state_out
    if audioop is None or len(pcm_16k_mono) < 2:
        return b""
    try:
        mono_48k, _resample_state_out = audioop.ratecv(
            pcm_16k_mono, 2, 1, 16000, 48000, _resample_state_out
        )
        stereo_48k = audioop.tostereo(mono_48k, 2, 1, 1)
        return stereo_48k
    except (audioop.error, Exception):
        return b""


DISCORD_FRAME_SIZE = 3840  # 20ms at 48kHz stereo 16-bit
SILENCE_FRAME = b"\x00" * DISCORD_FRAME_SIZE
DISCONNECT_TIMEOUT = 8.0  # graceful voice disconnect budget before force-drop
# ElevenLabs streams TTS faster than realtime while the AudioPlayer drains at
# exactly 50 fps, so the queue must hold a WHOLE long reply, not a few seconds
# of it — overflow means audibly truncated speech. 4500 frames = 90 s
# (~17 MB worst-case, transient).
OUTPUT_QUEUE_FRAMES = 4500
# A real mic is exactly 50 frames/s (20 ms each); discord-ext-voice-recv has
# been seen spinning at >12,000 sink writes/s of filler (live 2026-06-12),
# which saturates the event loop (delayed replies) and drowns ElevenLabs ASR.
# Anything materially beyond realtime is garbage by definition.
MIC_FORWARD_MAX_PER_SEC = 100


def is_silence(pcm: bytes) -> bool:
    """True for all-zero (or empty) PCM. Discord only transmits while the
    user speaks, so silent frames are library filler, never the mic."""
    if not pcm:
        return True
    if audioop is not None:
        try:
            return audioop.rms(pcm, 2) == 0
        except Exception:
            pass
    return not pcm.strip(b"\x00")


class MicForwardLimiter:
    """Token bucket capping mic forwarding at realtime + headroom.

    Protects the asyncio loop from the voice-recv flood: frames beyond
    MIC_FORWARD_MAX_PER_SEC per 1 s window are dropped BEFORE the expensive
    resample + run_coroutine_threadsafe submission.
    """

    def __init__(self, max_per_window: int = MIC_FORWARD_MAX_PER_SEC,
                 window_seconds: float = 1.0, clock=time.monotonic):
        self._max = max_per_window
        self._window = window_seconds
        self._clock = clock
        self._window_start = None
        self._count = 0
        self.dropped = 0

    def allow(self) -> bool:
        now = self._clock()
        if self._window_start is None or now - self._window_start >= self._window:
            self._window_start = now
            self._count = 0
        if self._count >= self._max:
            self.dropped += 1
            return False
        self._count += 1
        return True


class RecentFrameDedup:
    """Drops re-delivered mic frames.

    The round-4 flood (live 2026-06-12) was byte-duplicates of REAL audio —
    the receive lib replaying earlier packets at ~5,000/s. A plain rate cap
    then forwards mostly duplicates and the user's fresh words never reach
    ASR coherently. Keyed by RTP (ssrc, sequence, timestamp) when available,
    else by the PCM bytes' hash; live audio frames are never byte-identical,
    so fresh speech always passes."""

    def __init__(self, window: int = 500):  # ~10 s of real frames
        self._seen: OrderedDict = OrderedDict()
        self._window = window
        self.dropped = 0

    def is_dup(self, key) -> bool:
        if key in self._seen:
            self._seen.move_to_end(key)
            self.dropped += 1
            return True
        self._seen[key] = None
        if len(self._seen) > self._window:
            self._seen.popitem(last=False)
        return False


class AudioOutputSource(discord.AudioSource):
    """discord.py AudioSource that reads from a thread-safe queue.

    feed() is called from the asyncio thread (via output()).
    read() is called from discord.py's AudioPlayer thread.
    Uses queue.Queue (thread-safe) instead of asyncio.Queue.
    """

    def __init__(self, on_drained=None):
        self._lock = threading.Lock()
        self._buffer = bytearray()
        self._queue = queue.Queue(maxsize=OUTPUT_QUEUE_FRAMES)
        self._has_content = False
        self._empty_count = 0
        self._on_drained = on_drained
        self._reads = 0  # diagnostic: proves the AudioPlayer thread is alive
        self._dropped = 0  # frames lost to overflow == audibly cut speech

    def feed(self, pcm_48k_stereo: bytes):
        with self._lock:
            self._buffer.extend(pcm_48k_stereo)
            self._has_content = True
            self._empty_count = 0
            while len(self._buffer) >= DISCORD_FRAME_SIZE:
                frame = bytes(self._buffer[:DISCORD_FRAME_SIZE])
                self._buffer = self._buffer[DISCORD_FRAME_SIZE:]
                try:
                    self._queue.put_nowait(frame)
                except queue.Full:
                    self._dropped += 1
                    if self._dropped % 50 == 1:
                        logger.warning(
                            "[ConvAI] output queue FULL — dropped %d frames "
                            "(agent speech is being cut)", self._dropped,
                        )

    def read(self) -> bytes:
        self._reads += 1
        try:
            return self._queue.get_nowait()
        except queue.Empty:
            # Bridge micro-gaps between TTS chunks with silence, but END the
            # stream (b"" stops the AudioPlayer) once a reply has drained —
            # the bot must not transmit a continuous silence stream between
            # turns (continuous transmission is the receive-death trigger
            # observed live 2026-06-12). output() re-plays on the next reply.
            if self._has_content:
                self._empty_count += 1
                # 30 consecutive empty reads = ~600ms of silence after last audio
                if self._empty_count >= 30:
                    self._has_content = False
                    self._empty_count = 0
                    if self._on_drained:
                        self._on_drained()
                    return b""
                return SILENCE_FRAME
            return b""

    def clear(self):
        with self._lock:
            self._buffer.clear()
            self._has_content = False
            self._empty_count = 0
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def is_opus(self):
        return False

    def cleanup(self):
        self.clear()


if HAS_VOICE_RECV and HAS_ELEVENLABS_CONV:

    class DiscordAudioInterface(AsyncAudioInterface):
        """Bridges Discord voice <-> ElevenLabs Conversational AI.

        Mutes mic input while agent is speaking to prevent noise from
        triggering interruptions.
        """

        def __init__(self, audio_output: AudioOutputSource, loop: asyncio.AbstractEventLoop):
            self._input_callback = None
            self._audio_output = audio_output
            self._loop = loop
            self._voice_client = None  # set by _start_session; play-on-demand
            self._frame_count = 0
            self._agent_speaking = False
            # Diagnostics: where do mic frames stop?
            self._sink_writes = 0  # packets seen by sink (pre user-filter)
            self._sink_rx = 0      # packets from real users (post-filter)
            self._gated = 0        # dropped by the agent-speaking mute gate
            self._silent_drops = 0  # all-zero filler frames dropped on sight
            self._mic_limiter = MicForwardLimiter()
            self._dedup = RecentFrameDedup()
            self._last_gate_log = 0.0
            self._last_flood_log = 0.0
            # Chain, don't clobber: the bot installs its activity stamp via
            # AudioOutputSource(on_drained=...); keep it firing.
            self._chained_on_drained = self._audio_output._on_drained
            self._audio_output._on_drained = self._on_playback_drained

        def _on_playback_drained(self):
            """Called from the AudioPlayer thread when queued audio finishes."""
            cb = self._chained_on_drained
            if cb is not None:
                try:
                    cb()
                except Exception:
                    pass

        async def start(self, input_callback):
            self._input_callback = input_callback
            logger.info("[ConvAI] Audio interface started — ready for audio")

        async def stop(self):
            self._input_callback = None
            self._agent_speaking = False
            logger.info("[ConvAI] Audio interface stopped")

        async def output(self, audio: bytes):
            pcm_48k = resample_16k_mono_to_48k_stereo(audio)
            self._audio_output.feed(pcm_48k)
            # Play on demand: the player exits between turns (no continuous
            # silence transmission), so start it whenever a reply arrives.
            vc = self._voice_client
            if vc is not None and not vc.is_playing():
                try:
                    vc.play(self._audio_output)
                except Exception:
                    # A dead-but-bound player can make play() raise — clear it.
                    try:
                        vc.stop()
                        vc.play(self._audio_output)
                    except Exception as e:
                        logger.warning(f"[ConvAI] play-on-demand failed: {e}")

        async def interrupt(self):
            self._audio_output.clear()
            logger.info("[ConvAI] User interrupted agent")

        def feed_discord_audio(self, pcm_48k_stereo: bytes, dedup_key=None):
            """Called from audio sink thread with raw Discord PCM.

            Flood containment first (observed live 2026-06-12: voice-recv
            spinning at >12,000 writes/s vs the 50/s of a real mic — the
            per-packet event loop submissions delayed replies and drowned
            ASR), then the agent-speaking mute gate.
            """
            self._sink_rx += 1
            cb = self._input_callback
            if cb is None:
                return
            # 1) Replayed frames carry nothing new — drop them so fresh
            #    speech doesn't have to compete with the replay storm.
            if self._dedup.is_dup(dedup_key if dedup_key is not None
                                  else hash(pcm_48k_stereo)):
                return
            # 2) All-zero frames are library filler, never the mic — drop on sight.
            if is_silence(pcm_48k_stereo):
                self._silent_drops += 1
                return
            # 3) Hard realtime cap on anything we'd forward.
            if not self._mic_limiter.allow():
                now = time.monotonic()
                if now - self._last_flood_log > 5.0:
                    self._last_flood_log = now
                    logger.warning(
                        "[ConvAI] mic flood: %d non-silent frames beyond realtime "
                        "dropped (voice-recv spinning?)", self._mic_limiter.dropped,
                    )
                return
            # 4) Mute while agent audio is playing — prevents noise interruption
            if not self._audio_output._queue.empty() or self._audio_output._has_content:
                self._gated += 1
                now = time.monotonic()
                if now - self._last_gate_log > 5.0:
                    self._last_gate_log = now
                    logger.info(
                        "[ConvAI] mic GATED (%d drops) q=%d has_content=%s empty_count=%d",
                        self._gated, self._audio_output._queue.qsize(),
                        self._audio_output._has_content, self._audio_output._empty_count,
                    )
                return
            self._frame_count += 1
            if self._frame_count % 500 == 1:
                logger.info(f"[ConvAI] Feeding audio frame {self._frame_count}, {len(pcm_48k_stereo)}b")
            pcm_16k = resample_48k_stereo_to_16k_mono(pcm_48k_stereo)
            if pcm_16k:
                asyncio.run_coroutine_threadsafe(cb(pcm_16k), self._loop)


    class PassthroughSink(voice_recv.AudioSink):
        """Forwards all user PCM directly to DiscordAudioInterface.

        No filtering — ElevenLabs ASR handles VAD and noise rejection.
        Filtering was causing garbled transcriptions by cutting up words.
        """

        def __init__(self, audio_interface: DiscordAudioInterface):
            super().__init__()
            self._audio_interface = audio_interface

        def wants_opus(self) -> bool:
            return False

        def write(self, user, data):
            self._audio_interface._sink_writes += 1
            if user is None:
                return
            if getattr(user, 'bot', False):
                return
            pcm = data.pcm
            if pcm:
                # RTP identity for replay detection; falls back to a PCM
                # content hash inside feed_discord_audio when unavailable.
                pkt = getattr(data, "packet", None)
                seq = getattr(pkt, "sequence", None)
                key = None
                if seq is not None:
                    key = (getattr(pkt, "ssrc", None), seq,
                           getattr(pkt, "timestamp", None))
                self._audio_interface.feed_discord_audio(pcm, dedup_key=key)

        def cleanup(self):
            pass


class ConversationalVoiceBot(discord.Client):
    """Discord bot with ElevenLabs Conversational AI.

    Auto-joins voice channels. Full duplex voice conversation.
    """

    def __init__(self, elevenlabs_api_key: str, agent_id: str):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True
        super().__init__(intents=intents)
        self._elevenlabs_api_key = elevenlabs_api_key
        self._agent_id = agent_id
        self._conversation = None
        self._audio_interface = None
        self._audio_output = None
        self._text_channel = None
        self._session_active = False
        self._session_end_handled = False
        self._last_activity_time = 0.0
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 3
        self._watchdog_task = None
        self._stats_task = None
        self._session_voice_channel = None
        self._transcript_count = 0  # usable transcripts this session
        self._last_deltas: dict = {}  # latest stats5s deltas (deafness signature)

    async def on_ready(self):
        logger.info(f"Conversational voice bot ready as {self.user}")

    async def on_voice_state_update(self, member, before, after):
        if member.id == self.user.id:
            return

        logger.info(f"[ConvAI] Voice state: {member.name} before={getattr(before.channel, 'name', None)} after={getattr(after.channel, 'name', None)}")

        # User joined a voice channel
        if after.channel and not before.channel:
            guild_vc = after.channel.guild.voice_client
            if guild_vc and not self._session_active:
                # Ghost from a previous wedged teardown ("Timed out waiting for
                # voice disconnection confirmation") — it blocks every new
                # session until force-dropped.
                logger.warning("[ConvAI] Clearing ghost voice client before new session")
                try:
                    await guild_vc.disconnect(force=True)
                except Exception:
                    pass
                try:
                    guild_vc.cleanup()
                except Exception:
                    pass
                guild_vc = None
            if not guild_vc:
                await self._start_session(after.channel, member)

        # User left a voice channel — check if channel is now empty
        if before.channel and (not after.channel or after.channel != before.channel):
            if self._session_active:
                for vc in self.voice_clients:
                    if vc.channel and vc.channel.id == before.channel.id:
                        non_bot_members = [m for m in vc.channel.members if not m.bot]
                        if not non_bot_members:
                            logger.info(f"[ConvAI] Channel empty, ending session")
                            await self._end_session()

    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if message.content.strip().lower() == "!voice diag":
            lines = ["**Voice Diagnostics**"]
            lines.append(f"Session active: `{self._session_active}`")
            lines.append(f"Conversation: `{self._conversation is not None}`")
            lines.append(f"HAS_VOICE_RECV: `{HAS_VOICE_RECV}`")
            lines.append(f"HAS_ELEVENLABS_CONV: `{HAS_ELEVENLABS_CONV}`")
            for vc in self.voice_clients:
                lines.append(f"Connected: `{vc.is_connected()}`")
                if hasattr(vc, 'is_listening'):
                    lines.append(f"Listening: `{vc.is_listening()}`")
            if not self.voice_clients:
                lines.append("Not in any voice channel")
            stats = self._pipeline_stats()
            lines.append("Pipeline: " + ", ".join(f"{k}=`{v}`" for k, v in stats.items()))
            await message.channel.send("\n".join(lines))

    async def _start_session(self, voice_channel, member):
        if self._session_active:
            return

        if not HAS_VOICE_RECV or not HAS_ELEVENLABS_CONV:
            logger.warning("Missing deps for conversational voice bot")
            return

        try:
            for ch in voice_channel.guild.text_channels:
                if ch.permissions_for(voice_channel.guild.me).send_messages:
                    self._text_channel = ch
                    break

            vc = await voice_channel.connect(cls=voice_recv.VoiceRecvClient)

            # Reset resampling state for fresh session
            global _resample_state_in, _resample_state_out
            _resample_state_in = None
            _resample_state_out = None

            self._transcript_count = 0
            self._last_deltas = {}
            self._audio_output = AudioOutputSource(on_drained=self._mark_activity)
            self._audio_interface = DiscordAudioInterface(
                self._audio_output, asyncio.get_running_loop()
            )
            # No vc.play() here: the player starts on demand when agent audio
            # arrives and exits between turns (no continuous transmission).
            self._audio_interface._voice_client = vc

            sink = PassthroughSink(self._audio_interface)
            vc.listen(sink)

            client = AsyncElevenLabs(api_key=self._elevenlabs_api_key)
            self._conversation = AsyncConversation(
                client=client,
                agent_id=self._agent_id,
                requires_auth=False,
                audio_interface=self._audio_interface,
                callback_agent_response=self._on_agent_response,
                callback_user_transcript=self._on_user_transcript,
                callback_end_session=self._on_session_end,
            )
            await self._conversation.start_session()
            self._session_active = True
            self._session_end_handled = False
            self._session_voice_channel = voice_channel
            self._last_activity_time = time.monotonic()

            # Start DAVE watchdog — auto-reconnect if no user speech detected
            if self._watchdog_task:
                self._watchdog_task.cancel()
            self._watchdog_task = asyncio.create_task(self._dave_watchdog())

            # Pipeline stats every 5s — shows which stage stalls when the bot goes deaf
            if self._stats_task:
                self._stats_task.cancel()
            self._stats_task = asyncio.create_task(self._stats_reporter())

            logger.info(
                f"[ConvAI] Session started in {voice_channel.name} "
                f"(encryption mode={getattr(vc, 'mode', '?')})"
            )
            if self._text_channel:
                await self._text_channel.send(
                    f"Joined **{voice_channel.name}** — AIUI voice assistant is active. "
                    f"Just speak!"
                )

        except Exception as e:
            logger.error(f"[ConvAI] Failed to start session: {e}", exc_info=True)
            await self._cleanup()

    async def _end_session(self):
        if not self._session_active:
            return
        logger.info("[ConvAI] Ending session")
        if self._text_channel:
            try:
                await self._text_channel.send("Voice session ended.")
            except Exception:
                pass
        await self._cleanup()

    async def _cleanup(self):
        if not self._session_active and self._conversation is None:
            return
        self._session_active = False
        conv = self._conversation
        self._conversation = None

        # Cancel watchdog
        if self._watchdog_task and not self._watchdog_task.done():
            self._watchdog_task.cancel()
            self._watchdog_task = None

        if self._stats_task and not self._stats_task.done():
            self._stats_task.cancel()
            self._stats_task = None

        # Disconnect from Discord FIRST (fast, prevents stuck bot in channel)
        for vc in self.voice_clients:
            try:
                if hasattr(vc, 'stop_listening'):
                    vc.stop_listening()
                if vc.is_playing():
                    vc.stop()
                await asyncio.wait_for(vc.disconnect(), timeout=DISCONNECT_TIMEOUT)
            except Exception as e:
                # A wedged voice handshake leaves a ghost client attached to
                # the guild that blocks all future sessions — force-drop it.
                logger.warning(f"[ConvAI] Graceful disconnect failed ({e!r}) — forcing")
                try:
                    await vc.disconnect(force=True)
                except Exception:
                    pass
                try:
                    vc.cleanup()
                except Exception:
                    pass

        # End ElevenLabs session with timeout (can hang)
        if conv:
            try:
                await asyncio.wait_for(conv.end_session(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("[ConvAI] end_session timed out after 5s, forcing close")
            except Exception as e:
                logger.debug(f"[ConvAI] End session error: {e}")

        self._audio_interface = None
        self._audio_output = None
        self._text_channel = None

    async def _on_session_end(self):
        """Called when ElevenLabs ends the conversation.

        NOTE: ElevenLabs SDK fires this callback MANY times.
        We use _session_end_handled to ensure we only act once.
        """
        if self._session_end_handled:
            return
        self._session_end_handled = True
        logger.info("[ConvAI] ElevenLabs ended the session")
        if self._text_channel:
            try:
                await self._text_channel.send("*(Voice session ended by agent)*")
            except Exception:
                pass
        await self._cleanup()

    async def _on_agent_response(self, response: str):
        logger.info(f"[ConvAI] Agent: {response[:100]}")
        if self._text_channel:
            try:
                msg = response[:1900] if len(response) > 1900 else response
                await self._text_channel.send(f"> {msg}")
            except Exception:
                pass

    def _pipeline_stats(self) -> dict:
        """Snapshot of every stage of the mic pipeline (diagnostics)."""
        ai = self._audio_interface
        ao = self._audio_output
        vc = self.voice_clients[0] if self.voice_clients else None
        player = getattr(vc, '_player', None) if vc else None
        return {
            "sink_writes": ai._sink_writes if ai else -1,
            "sink_rx": ai._sink_rx if ai else -1,
            "gated": ai._gated if ai else -1,
            "silent": ai._silent_drops if ai else -1,
            "flooded": ai._mic_limiter.dropped if ai else -1,
            "dup": ai._dedup.dropped if ai else -1,
            "fed": ai._frame_count if ai else -1,
            "reads": ao._reads if ao else -1,
            "dropped": ao._dropped if ao else -1,
            "q": ao._queue.qsize() if ao else -1,
            "has_content": ao._has_content if ao else None,
            "connected": bool(vc and vc.is_connected()),
            "listening": bool(vc and getattr(vc, 'is_listening', lambda: False)()),
            "playing": bool(vc and vc.is_playing()),
            "player_alive": bool(player and player.is_alive()),
            "cb_set": bool(ai and ai._input_callback is not None),
        }

    async def _stats_reporter(self):
        """Log per-5s deltas for each pipeline stage.

        Reading the line when the bot is deaf:
        - writes/rx +0 while user speaks -> Discord receive layer dead (voice-recv)
        - rx grows but gated grows too   -> mute gate stuck closed
        - fed grows but no transcripts   -> audio reaching ElevenLabs is garbage
        - reads +0                       -> AudioPlayer thread stalled (gate can never reopen)
        """
        prev = {}
        try:
            while self._session_active:
                await asyncio.sleep(5)
                if not self._session_active:
                    break
                s = self._pipeline_stats()
                deltas = {k: s[k] - prev.get(k, 0)
                          for k in ("sink_writes", "sink_rx", "gated", "silent",
                                    "flooded", "dup", "fed", "reads", "dropped")}
                prev = {k: s[k] for k in deltas}
                logger.info(
                    "[ConvAI] stats5s writes=+%d rx=+%d gated=+%d silent=+%d "
                    "flooded=+%d dup=+%d fed=+%d reads=+%d dropped=+%d q=%d "
                    "has_content=%s connected=%s listening=%s "
                    "playing=%s player_alive=%s cb=%s",
                    deltas["sink_writes"], deltas["sink_rx"], deltas["gated"],
                    deltas["silent"], deltas["flooded"], deltas["dup"],
                    deltas["fed"], deltas["reads"], deltas["dropped"], s["q"],
                    s["has_content"], s["connected"], s["listening"],
                    s["playing"], s["player_alive"], s["cb_set"],
                )
                self._last_deltas = deltas
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[ConvAI] Stats reporter error: {e}", exc_info=True)

    def _mark_activity(self):
        """Conversational activity stamp (user spoke OR agent finished speaking).
        Called from the AudioPlayer thread on drain — float assignment is atomic."""
        self._last_activity_time = time.monotonic()

    def _zero_flood_active(self) -> bool:
        """Latest stats window shows the receive path flooding junk with
        nothing reaching ElevenLabs — the deafness signature."""
        d = self._last_deltas or {}
        junk = d.get("silent", 0) + d.get("flooded", 0) + d.get("dup", 0)
        return junk > 2000 and d.get("fed", 0) == 0

    async def _on_user_transcript(self, transcript: str):
        # Filter out noise transcripts ("...", empty, or very short)
        cleaned = transcript.strip().strip(".")
        if len(cleaned) < 2:
            return
        self._mark_activity()
        self._transcript_count += 1
        self._reconnect_attempts = 0  # Reset on successful speech
        logger.info(f"[ConvAI] User: {transcript}")
        if self._text_channel:
            try:
                await self._text_channel.send(f"*You: {transcript}*")
            except Exception:
                pass

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
        if not self._session_active:
            return False
        # A session that NEVER produced a transcript while the receive path
        # floods junk is deaf from the start — reconnect fast (in-place listen
        # restarts were tried live 2026-06-12 and made things worse; a fresh
        # voice session is the only known cure).
        threshold = 12 if (self._transcript_count == 0
                           and self._zero_flood_active()) else 25
        if elapsed <= threshold:
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

    async def _dave_watchdog(self):
        """Self-heal deaf sessions: reconnect when no user speech is heard."""
        try:
            # Wait 10s after session start for the greeting to finish
            await asyncio.sleep(10)

            while self._session_active:
                await asyncio.sleep(5)
                if not self._session_active:
                    break

                elapsed = time.monotonic() - self._last_activity_time
                if self._watchdog_should_reconnect(elapsed):
                    if self._reconnect_attempts >= self._max_reconnect_attempts:
                        logger.warning("[ConvAI] DAVE: Max reconnect attempts reached, giving up")
                        if self._text_channel:
                            try:
                                await self._text_channel.send(
                                    "*(Voice quality issue — couldn't establish clear audio. "
                                    "Try disconnecting and rejoining.)*"
                                )
                            except Exception:
                                pass
                        break

                    self._reconnect_attempts += 1
                    logger.info(f"[ConvAI] DAVE: No speech detected for {elapsed:.0f}s, "
                                f"reconnecting (attempt {self._reconnect_attempts}/{self._max_reconnect_attempts})")

                    if self._text_channel:
                        try:
                            await self._text_channel.send(
                                f"*(Reconnecting for better audio... attempt {self._reconnect_attempts})*"
                            )
                        except Exception:
                            pass

                    # Save channel ref before cleanup
                    voice_channel = self._session_voice_channel
                    text_channel = self._text_channel

                    # Clean up current session
                    await self._cleanup()

                    # Small delay for Discord to process disconnect
                    await asyncio.sleep(3)

                    # Reconnect if user is still in the channel
                    if voice_channel:
                        non_bot = [m for m in voice_channel.members if not m.bot]
                        if non_bot:
                            self._text_channel = text_channel
                            await self._start_session(voice_channel, non_bot[0])
                    break  # New session starts its own watchdog

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[ConvAI] Watchdog error: {e}", exc_info=True)


# The running bot instance (one per process). Lets the web layer (voice build
# watcher) target the active session's text channel without holding the task.
_active_bot = None


def current_text_channel_id() -> str | None:
    """Channel id of the active voice session's text channel, else None."""
    bot = _active_bot
    ch = getattr(bot, "_text_channel", None) if bot is not None else None
    return str(ch.id) if ch is not None else None


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
    global _active_bot
    _active_bot = bot
    try:
        await bot.start(bot_token)
    except Exception as e:
        logger.error(f"Voice bot error: {e}", exc_info=True)
    finally:
        if not bot.is_closed():
            await bot.close()
