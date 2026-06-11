"""AIUI Conversational Voice Bot — ElevenLabs Conversational AI + Discord.

Auto-joins voice channels. Full duplex conversation via ElevenLabs agent.
No typing needed — just speak.
"""
import asyncio
import audioop
import logging
import queue
import threading

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
    if len(pcm_48k_stereo) < 4:
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
    if len(pcm_16k_mono) < 2:
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


class AudioOutputSource(discord.AudioSource):
    """discord.py AudioSource that reads from a thread-safe queue.

    feed() is called from the asyncio thread (via output()).
    read() is called from discord.py's AudioPlayer thread.
    Uses queue.Queue (thread-safe) instead of asyncio.Queue.
    """

    def __init__(self, on_drained=None):
        self._lock = threading.Lock()
        self._buffer = bytearray()
        self._queue = queue.Queue(maxsize=200)
        self._has_content = False
        self._empty_count = 0
        self._on_drained = on_drained
        self._reads = 0  # diagnostic: proves the AudioPlayer thread is alive

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
                    pass

    def read(self) -> bytes:
        self._reads += 1
        try:
            return self._queue.get_nowait()
        except queue.Empty:
            # Track when audio finishes playing (buffer drained after having content)
            if self._has_content:
                self._empty_count += 1
                # 30 consecutive empty reads = ~600ms of silence after last audio
                # Short enough for fast mic unmute, long enough to bridge
                # micro-gaps between audio chunks from ElevenLabs
                if self._empty_count >= 30:
                    self._has_content = False
                    self._empty_count = 0
                    if self._on_drained:
                        self._on_drained()
            return SILENCE_FRAME

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
            self._frame_count = 0
            self._agent_speaking = False
            # Diagnostics: where do mic frames stop?
            self._sink_writes = 0  # packets seen by sink (pre user-filter)
            self._sink_rx = 0      # packets from real users (post-filter)
            self._gated = 0        # dropped by the agent-speaking mute gate
            # Wire drain callback — unmute mic only after audio finishes playing
            self._audio_output._on_drained = self._on_playback_drained

        def _on_playback_drained(self):
            """Called from AudioPlayer thread when buffered audio queue empties."""
            # Don't unmute here — _on_agent_response handles unmuting
            # This just signals that queued audio finished playing
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

        async def interrupt(self):
            self._audio_output.clear()
            logger.info("[ConvAI] User interrupted agent")

        def feed_discord_audio(self, pcm_48k_stereo: bytes):
            """Called from audio sink thread with raw Discord PCM.

            Mute while audio queue has content (agent is speaking).
            Unmute instantly when queue empties — no timer delay.
            """
            self._sink_rx += 1
            cb = self._input_callback
            if cb is None:
                return
            # Mute while agent audio is playing — prevents noise interruption
            if not self._audio_output._queue.empty() or self._audio_output._has_content:
                self._gated += 1
                if self._gated % 250 == 1:
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
                self._audio_interface.feed_discord_audio(pcm)

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
        self._last_user_transcript_time = 0.0
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 3
        self._watchdog_task = None
        self._stats_task = None
        self._session_voice_channel = None

    async def on_ready(self):
        logger.info(f"Conversational voice bot ready as {self.user}")

    async def on_voice_state_update(self, member, before, after):
        if member.id == self.user.id:
            return

        logger.info(f"[ConvAI] Voice state: {member.name} before={getattr(before.channel, 'name', None)} after={getattr(after.channel, 'name', None)}")

        # User joined a voice channel
        if after.channel and not before.channel:
            if not after.channel.guild.voice_client:
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

            self._audio_output = AudioOutputSource()
            self._audio_interface = DiscordAudioInterface(
                self._audio_output, asyncio.get_running_loop()
            )

            vc.play(self._audio_output)

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
            import time
            self._last_user_transcript_time = time.monotonic()

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
                await vc.disconnect()
            except Exception as e:
                logger.debug(f"[ConvAI] Disconnect error: {e}")

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
            "fed": ai._frame_count if ai else -1,
            "reads": ao._reads if ao else -1,
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
                          for k in ("sink_writes", "sink_rx", "gated", "fed", "reads")}
                prev = {k: s[k] for k in deltas}
                logger.info(
                    "[ConvAI] stats5s writes=+%d rx=+%d gated=+%d fed=+%d reads=+%d "
                    "q=%d has_content=%s connected=%s listening=%s playing=%s player_alive=%s cb=%s",
                    deltas["sink_writes"], deltas["sink_rx"], deltas["gated"],
                    deltas["fed"], deltas["reads"], s["q"], s["has_content"],
                    s["connected"], s["listening"], s["playing"],
                    s["player_alive"], s["cb_set"],
                )
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[ConvAI] Stats reporter error: {e}", exc_info=True)

    async def _wait_and_unmute(self):
        """Wait for audio to finish playing, then unmute mic.

        Requires 3 continuous seconds of empty queue before unmuting.
        If new audio arrives during the wait, resets the timer.
        This bridges tool call gaps (agent says "Checking..." → 1-3s tool call → speaks result).
        """
        if not self._audio_output or not self._audio_interface:
            return
        try:
            empty_seconds = 0.0
            for _ in range(750):  # max 15 seconds total
                await asyncio.sleep(0.02)
                if self._audio_output._queue.empty() and not self._audio_output._has_content:
                    empty_seconds += 0.02
                    if empty_seconds >= 3.0:
                        break
                else:
                    empty_seconds = 0.0  # Reset — new audio arrived

            if self._audio_interface:
                self._audio_interface._agent_speaking = False
                logger.info("[ConvAI] Agent finished speaking — mic unmuted")
        except asyncio.CancelledError:
            pass

    async def _on_user_transcript(self, transcript: str):
        # Filter out noise transcripts ("...", empty, or very short)
        cleaned = transcript.strip().strip(".")
        if len(cleaned) < 2:
            return
        import time
        self._last_user_transcript_time = time.monotonic()
        self._reconnect_attempts = 0  # Reset on successful speech
        logger.info(f"[ConvAI] User: {transcript}")
        if self._text_channel:
            try:
                await self._text_channel.send(f"*You: {transcript}*")
            except Exception:
                pass

    async def _dave_watchdog(self):
        """Monitor DAVE audio quality. Auto-reconnect if no speech detected."""
        import time
        try:
            # Wait 15s after session start for greeting to finish
            await asyncio.sleep(15)

            while self._session_active:
                await asyncio.sleep(10)
                if not self._session_active:
                    break

                elapsed = time.monotonic() - self._last_user_transcript_time
                # If 25+ seconds since last transcript and audio is flowing
                if elapsed > 25 and self._audio_interface and self._audio_interface._frame_count > 100:
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
    try:
        await bot.start(bot_token)
    except Exception as e:
        logger.error(f"Voice bot error: {e}", exc_info=True)
    finally:
        if not bot.is_closed():
            await bot.close()
