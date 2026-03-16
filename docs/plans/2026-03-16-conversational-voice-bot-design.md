# AIUI Conversational Voice Bot Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the manual `!voice` command bot with a full conversational AI assistant that auto-joins when users enter a voice channel and uses ElevenLabs Conversational AI for real-time voice interaction.

**Architecture:** ElevenLabs `AsyncConversation` with custom `AsyncAudioInterface` bridges Discord voice audio (via `discord-ext-voice-recv`) to the pre-configured agent (agent_2501kkjqajx0fmzbd60pf5w3byzd). Bot auto-joins/leaves voice channels. No typing needed.

**Tech Stack:** discord.py 2.7+, discord-ext-voice-recv (PR #56 fork), elevenlabs SDK (AsyncConversation), davey (DAVE crypto)

---

### Task 1: Add ElevenLabs SDK dependency and agent ID config

**Files:**
- Modify: `webhook-handler/requirements.txt`
- Modify: `webhook-handler/config.py`

**Step 1: Add elevenlabs SDK to requirements.txt**

Add this line to `webhook-handler/requirements.txt`:

```
elevenlabs>=2.39.0
```

**Step 2: Add agent_id config to config.py**

Add after the `elevenlabs_model_id` line in `webhook-handler/config.py`:

```python
    elevenlabs_agent_id: str = ""
```

**Step 3: Add ELEVENLABS_AGENT_ID to docker-compose.unified.yml**

In the webhook-handler environment section, add:

```yaml
      - ELEVENLABS_AGENT_ID=${ELEVENLABS_AGENT_ID:-}
```

**Step 4: Commit**

```bash
git add webhook-handler/requirements.txt webhook-handler/config.py docker-compose.unified.yml
git commit -m "feat: add elevenlabs SDK and agent_id config for conversational voice bot"
```

---

### Task 2: Rewrite voice_bot.py — audio resampling utilities

**Files:**
- Modify: `webhook-handler/voice_bot.py`

**Step 1: Write the resampling functions**

Replace the ENTIRE content of `webhook-handler/voice_bot.py` with the new file. Start with imports and resampling utilities:

```python
"""AIUI Conversational Voice Bot — ElevenLabs Conversational AI + Discord.

Auto-joins voice channels. Full duplex conversation via ElevenLabs agent.
No typing needed — just speak.
"""
import asyncio
import logging
import struct

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


def resample_48k_stereo_to_16k_mono(pcm_48k_stereo: bytes) -> bytes:
    """Convert 48kHz stereo S16LE to 16kHz mono S16LE.

    Discord delivers 48000Hz, 2 channels, 16-bit signed LE.
    ElevenLabs expects 16000Hz, 1 channel, 16-bit signed LE.
    Decimation factor = 3, stereo→mono = average L+R.
    """
    sample_count = len(pcm_48k_stereo) // 2  # 16-bit = 2 bytes per sample
    if sample_count < 2:
        return b""
    samples = struct.unpack(f"<{sample_count}h", pcm_48k_stereo)
    mono_16k = []
    # Step through stereo pairs (L, R) with stride 6 (3 stereo frames)
    for i in range(0, len(samples) - 1, 6):  # 6 = 2ch * 3 decimation
        left = samples[i]
        right = samples[i + 1] if i + 1 < len(samples) else left
        mono_16k.append((left + right) // 2)
    return struct.pack(f"<{len(mono_16k)}h", *mono_16k)


def resample_16k_mono_to_48k_stereo(pcm_16k_mono: bytes) -> bytes:
    """Convert 16kHz mono S16LE to 48kHz stereo S16LE.

    ElevenLabs delivers 16000Hz, 1 channel, 16-bit signed LE.
    Discord expects 48000Hz, 2 channels, 16-bit signed LE.
    Upsample factor = 3, mono→stereo = duplicate.
    """
    sample_count = len(pcm_16k_mono) // 2
    if sample_count == 0:
        return b""
    samples = struct.unpack(f"<{sample_count}h", pcm_16k_mono)
    stereo_48k = []
    for i in range(len(samples)):
        s = samples[i]
        s_next = samples[i + 1] if i + 1 < len(samples) else s
        # Linear interpolation: 3 output samples per input sample
        stereo_48k.extend([s, s])  # frame 0: L=s, R=s
        mid = (s + s_next) // 2
        stereo_48k.extend([mid, mid])  # frame 1: interpolated
        stereo_48k.extend([s_next, s_next])  # frame 2: next sample
    return struct.pack(f"<{len(stereo_48k)}h", *stereo_48k)
```

---

### Task 3: Write DiscordAudioInterface and AudioOutputSource

**Files:**
- Modify: `webhook-handler/voice_bot.py` (append after resampling functions)

**Step 1: Add the AsyncAudioInterface implementation and AudioSource**

Append to `voice_bot.py`:

```python
DISCORD_FRAME_SIZE = 3840  # 20ms at 48kHz stereo 16-bit
SILENCE_FRAME = b"\x00" * DISCORD_FRAME_SIZE


class AudioOutputSource(discord.AudioSource):
    """discord.py AudioSource that reads from an asyncio queue.

    Fed by DiscordAudioInterface.output() with 48kHz stereo PCM.
    Returns 20ms frames (3840 bytes) for Discord playback.
    """

    def __init__(self):
        self._buffer = bytearray()
        self._queue = asyncio.Queue()
        self._finished = False

    def feed(self, pcm_48k_stereo: bytes):
        """Called from DiscordAudioInterface.output() to queue audio."""
        self._buffer.extend(pcm_48k_stereo)
        # Drain full frames into the queue
        while len(self._buffer) >= DISCORD_FRAME_SIZE:
            frame = bytes(self._buffer[:DISCORD_FRAME_SIZE])
            self._buffer = self._buffer[DISCORD_FRAME_SIZE:]
            try:
                self._queue.put_nowait(frame)
            except asyncio.QueueFull:
                pass  # drop frames if backed up

    def read(self) -> bytes:
        """Called by discord.py voice client every 20ms."""
        try:
            return self._queue.get_nowait()
        except (asyncio.QueueEmpty, Exception):
            return SILENCE_FRAME

    def clear(self):
        """Clear buffered audio (on interrupt)."""
        self._buffer.clear()
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    def is_opus(self):
        return False

    def cleanup(self):
        self.clear()


if HAS_VOICE_RECV and HAS_ELEVENLABS_CONV:

    class DiscordAudioInterface(AsyncAudioInterface):
        """Bridges Discord voice ↔ ElevenLabs Conversational AI.

        Input:  Discord audio sink → resample 48k stereo → 16k mono → ElevenLabs
        Output: ElevenLabs → resample 16k mono → 48k stereo → Discord playback
        """

        def __init__(self, audio_output: AudioOutputSource):
            self._input_callback = None
            self._audio_output = audio_output

        async def start(self, input_callback):
            """Called when ElevenLabs session starts."""
            self._input_callback = input_callback
            logger.info("[ConvAI] Audio interface started")

        async def stop(self):
            """Called when ElevenLabs session ends."""
            self._input_callback = None
            logger.info("[ConvAI] Audio interface stopped")

        async def output(self, audio: bytes):
            """Called when agent produces audio (16kHz mono PCM)."""
            pcm_48k = resample_16k_mono_to_48k_stereo(audio)
            self._audio_output.feed(pcm_48k)

        async def interrupt(self):
            """Called when user interrupts the agent."""
            self._audio_output.clear()
            logger.info("[ConvAI] User interrupted agent")

        def feed_discord_audio(self, pcm_48k_stereo: bytes):
            """Called from Discord audio sink with raw 48kHz stereo PCM.

            Resamples to 16kHz mono and sends to ElevenLabs.
            This runs in a non-async thread context.
            """
            if self._input_callback is None:
                return
            pcm_16k = resample_48k_stereo_to_16k_mono(pcm_48k_stereo)
            if pcm_16k:
                # input_callback is async, schedule it
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.run_coroutine_threadsafe(
                            self._input_callback(pcm_16k), loop
                        )
                except RuntimeError:
                    pass


    class PassthroughSink(voice_recv.AudioSink):
        """Simple audio sink that forwards all PCM to DiscordAudioInterface."""

        def __init__(self, audio_interface: DiscordAudioInterface):
            super().__init__()
            self._audio_interface = audio_interface

        def wants_opus(self) -> bool:
            return False

        def write(self, user, data):
            if user is None or user.bot:
                return
            pcm = data.pcm
            if pcm:
                self._audio_interface.feed_discord_audio(pcm)

        def cleanup(self):
            pass
```

---

### Task 4: Write the ConversationalVoiceBot class

**Files:**
- Modify: `webhook-handler/voice_bot.py` (append after DiscordAudioInterface)

**Step 1: Add the bot class**

Append to `voice_bot.py`:

```python
class ConversationalVoiceBot(discord.Client):
    """Discord bot with ElevenLabs Conversational AI.

    Auto-joins voice channels when users enter.
    Auto-leaves when all users disconnect.
    Full duplex voice conversation via ElevenLabs agent.
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

    async def on_ready(self):
        logger.info(f"Conversational voice bot ready as {self.user}")

    async def on_voice_state_update(self, member, before, after):
        """Auto-join when a user enters a voice channel, auto-leave when empty."""
        # Ignore bot's own voice state changes
        if member.id == self.user.id:
            return

        # User joined a voice channel
        if after.channel and not before.channel:
            # Bot not already in a voice channel
            if not self.voice_clients:
                await self._start_session(after.channel, member)

        # User left a voice channel
        if before.channel and (not after.channel or after.channel != before.channel):
            # Check if the channel the bot is in is now empty (no non-bot users)
            for vc in self.voice_clients:
                if vc.channel and vc.channel.id == before.channel.id:
                    non_bot_members = [m for m in vc.channel.members if not m.bot]
                    if not non_bot_members:
                        await self._end_session()

    async def on_message(self, message: discord.Message):
        """Handle !voice diag command for debugging."""
        if message.author.bot:
            return
        if message.content.strip().lower() == "!voice diag":
            lines = ["**Voice Diagnostics**"]
            lines.append(f"Session active: `{self._session_active}`")
            lines.append(f"Conversation: `{self._conversation is not None}`")
            for vc in self.voice_clients:
                lines.append(f"Connected: `{vc.is_connected()}`")
                if hasattr(vc, 'is_listening'):
                    lines.append(f"Listening: `{vc.is_listening()}`")
            if not self.voice_clients:
                lines.append("Not in any voice channel")
            await message.channel.send("\n".join(lines))

    async def _start_session(self, voice_channel, member):
        """Join voice channel and start ElevenLabs conversation."""
        if self._session_active:
            return

        if not HAS_VOICE_RECV or not HAS_ELEVENLABS_CONV:
            logger.warning("Missing dependencies for conversational voice bot")
            return

        try:
            # Find a text channel in the same guild to post updates
            for ch in voice_channel.guild.text_channels:
                if ch.permissions_for(voice_channel.guild.me).send_messages:
                    self._text_channel = ch
                    break

            # Connect to voice with receiving
            vc = await voice_channel.connect(cls=voice_recv.VoiceRecvClient)

            # Set up audio pipeline
            self._audio_output = AudioOutputSource()
            self._audio_interface = DiscordAudioInterface(self._audio_output)

            # Start playback (continuous — reads from queue, silence when empty)
            vc.play(self._audio_output)

            # Start listening (feeds audio to ElevenLabs)
            sink = PassthroughSink(self._audio_interface)
            vc.listen(sink)

            # Start ElevenLabs conversation
            client = AsyncElevenLabs(api_key=self._elevenlabs_api_key)
            self._conversation = AsyncConversation(
                client=client,
                agent_id=self._agent_id,
                requires_auth=False,
                audio_interface=self._audio_interface,
                callback_agent_response=self._on_agent_response,
                callback_user_transcript=self._on_user_transcript,
            )
            await self._conversation.start_session()
            self._session_active = True

            logger.info(f"[ConvAI] Session started in {voice_channel.name}")
            if self._text_channel:
                await self._text_channel.send(
                    f"Joined **{voice_channel.name}** — AIUI voice assistant is active. "
                    f"Just speak!"
                )

        except Exception as e:
            logger.error(f"[ConvAI] Failed to start session: {e}", exc_info=True)
            await self._cleanup()

    async def _end_session(self):
        """End ElevenLabs conversation and leave voice channel."""
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
        """Clean up all resources."""
        self._session_active = False

        if self._conversation:
            try:
                await self._conversation.end_session()
            except Exception as e:
                logger.debug(f"[ConvAI] End session error: {e}")
            self._conversation = None

        for vc in self.voice_clients:
            try:
                if hasattr(vc, 'stop_listening'):
                    vc.stop_listening()
                if vc.is_playing():
                    vc.stop()
                await vc.disconnect()
            except Exception as e:
                logger.debug(f"[ConvAI] Disconnect error: {e}")

        self._audio_interface = None
        self._audio_output = None
        self._text_channel = None

    async def _on_agent_response(self, response: str):
        """Called when agent finishes speaking (full text)."""
        logger.info(f"[ConvAI] Agent: {response[:100]}")
        if self._text_channel:
            try:
                msg = response[:1900] if len(response) > 1900 else response
                await self._text_channel.send(f"> {msg}")
            except Exception:
                pass

    async def _on_user_transcript(self, transcript: str):
        """Called when user's speech is transcribed."""
        logger.info(f"[ConvAI] User: {transcript}")
        if self._text_channel:
            try:
                await self._text_channel.send(f"*You: {transcript}*")
            except Exception:
                pass


async def start_voice_bot(
    bot_token: str,
    elevenlabs_api_key: str,
    agent_id: str = "",
    **kwargs,  # Accept but ignore legacy params (webhook_url, voice_secret, etc.)
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
```

---

### Task 5: Update main.py to pass agent_id

**Files:**
- Modify: `webhook-handler/main.py:196-209`

**Step 1: Update the start_voice_bot call in lifespan**

Change the voice bot startup block to pass `agent_id`:

```python
    # Voice bot (Discord voice channel — runs as background task)
    voice_bot_task = None
    if settings.discord_bot_token and settings.elevenlabs_api_key:
        voice_bot_task = asyncio.create_task(start_voice_bot(
            bot_token=settings.discord_bot_token,
            elevenlabs_api_key=settings.elevenlabs_api_key,
            agent_id=settings.elevenlabs_agent_id,
        ))
        logger.info("Voice bot starting as background task")
    else:
        logger.info("Voice bot disabled (no DISCORD_BOT_TOKEN or ELEVENLABS_API_KEY)")
```

**Step 2: Commit**

```bash
git add webhook-handler/voice_bot.py webhook-handler/main.py
git commit -m "feat: rewrite voice bot with ElevenLabs Conversational AI + auto-join"
```

---

### Task 6: Deploy and test

**Step 1: Set ELEVENLABS_AGENT_ID in server .env**

```bash
ssh root@46.224.193.25 "echo 'ELEVENLABS_AGENT_ID=agent_2501kkjqajx0fmzbd60pf5w3byzd' >> /root/proxy-server/.env"
```

**Step 2: SCP files to server**

```bash
scp webhook-handler/voice_bot.py root@46.224.193.25:/root/proxy-server/webhook-handler/voice_bot.py
scp webhook-handler/requirements.txt root@46.224.193.25:/root/proxy-server/webhook-handler/requirements.txt
scp webhook-handler/config.py root@46.224.193.25:/root/proxy-server/webhook-handler/config.py
scp webhook-handler/main.py root@46.224.193.25:/root/proxy-server/webhook-handler/main.py
scp docker-compose.unified.yml root@46.224.193.25:/root/proxy-server/docker-compose.unified.yml
```

**Step 3: Rebuild webhook-handler**

```bash
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --build webhook-handler"
```

**Step 4: Verify container is healthy**

```bash
ssh root@46.224.193.25 "docker logs webhook-handler --tail 10"
```
Expected: "Conversational voice bot ready as aiui-teams#8536"

**Step 5: Test in Discord**

1. Join a voice channel — bot should auto-join
2. Bot should greet: "Hey! I'm AIUI. What would you like me to do?"
3. Say "check service status" — agent should call status webhook tool, speak result
4. Say "what workflows are running" — agent calls workflows tool, speaks result
5. Disconnect from voice — bot should auto-leave, session ends

**Step 6: Commit**

```bash
git add -A
git commit -m "feat: deploy conversational voice bot with ElevenLabs agent"
```
