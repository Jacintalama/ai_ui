# Voice Input for Discord Bot — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add voice input so users can speak commands in Discord voice channels instead of typing `!voice <command>`.

**Architecture:** `discord-ext-voice-recv` (PR #56 fork with DAVE support) captures per-user PCM audio inside the existing webhook-handler container. Energy-based silence detection segments utterances, ElevenLabs batch STT transcribes them, and the existing command router + TTS pipeline handles the response.

**Tech Stack:** discord.py 2.7+, discord-ext-voice-recv (PR #56 fork), davey (DAVE crypto), ElevenLabs STT/TTS API, httpx

---

### Task 1: Update Dependencies

**Files:**
- Modify: `webhook-handler/requirements.txt`
- Modify: `webhook-handler/Dockerfile`

**Step 1: Add voice-recv and davey to requirements.txt**

Add these lines to `webhook-handler/requirements.txt`:

```
davey>=0.1.4
git+https://github.com/vocolboy/discord-ext-voice-recv.git@main
```

Note: We install from vocolboy's fork (PR #56) which has comprehensive DAVE receive support. The official PyPI release does NOT support DAVE yet.

**Step 2: Add git to Dockerfile for pip git installs**

The Dockerfile needs `git` installed so pip can clone from GitHub. Update the `apt-get` line:

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*
```

**Step 3: Verify build works**

Run on server:
```bash
docker compose -f docker-compose.unified.yml build webhook-handler
```
Expected: Build succeeds, `discord-ext-voice-recv` and `davey` install without errors.

**Step 4: Commit**

```bash
git add webhook-handler/requirements.txt webhook-handler/Dockerfile
git commit -m "feat: add discord-ext-voice-recv and davey dependencies for voice input"
```

---

### Task 2: Add STT Function

**Files:**
- Modify: `webhook-handler/voice_bot.py`

**Step 1: Add speech_to_text_stt() function**

Add this function to `voice_bot.py` after the existing `text_to_speech()` function (after line 71):

```python
async def speech_to_text(api_key: str, audio_pcm: bytes,
                         sample_rate: int = 48000, channels: int = 2) -> str:
    """Convert PCM audio to text using ElevenLabs STT API.

    Args:
        api_key: ElevenLabs API key.
        audio_pcm: Raw PCM audio (16-bit signed, little-endian).
        sample_rate: Sample rate of the PCM audio (default 48000 from Discord).
        channels: Number of channels (default 2 = stereo from Discord).

    Returns:
        Transcribed text, or empty string on failure.
    """
    import io
    import struct
    import wave

    # Convert raw PCM to WAV in-memory (ElevenLabs auto-detects WAV format)
    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(audio_pcm)
    wav_bytes = wav_buffer.getvalue()

    url = "https://api.elevenlabs.io/v1/speech-to-text"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            url,
            headers={"xi-api-key": api_key},
            data={"model_id": "scribe_v2", "tag_audio_events": "false"},
            files={"file": ("audio.wav", wav_bytes, "audio/wav")},
        )
        if resp.status_code != 200:
            logger.error(f"STT API error {resp.status_code}: {resp.text}")
            return ""
        result = resp.json()
        return result.get("text", "").strip()
```

**Step 2: Verify import**

The function uses `io`, `wave` (stdlib) and `httpx` (already imported). No new imports needed at file level.

---

### Task 3: Add Audio Sink with Silence Detection

**Files:**
- Modify: `webhook-handler/voice_bot.py`

**Step 1: Add imports at top of voice_bot.py**

Add after the existing imports (after line 12):

```python
import struct
import io
import wave
from collections import defaultdict
```

And add the voice_recv import:

```python
try:
    from discord.ext import voice_recv
    HAS_VOICE_RECV = True
except ImportError:
    HAS_VOICE_RECV = False
    logger.warning("discord-ext-voice-recv not installed — voice input disabled")
```

**Step 2: Add VoiceInputSink class**

Add this class before the `VoiceBot` class:

```python
class VoiceInputSink(voice_recv.AudioSink):
    """Captures per-user audio with silence detection.

    When a user speaks and then goes silent for SILENCE_DURATION seconds,
    the captured audio is queued for processing.
    """

    SILENCE_THRESHOLD = 300       # RMS energy below this = silence
    SILENCE_DURATION = 1.5        # seconds of silence to end utterance
    MIN_SPEECH_FRAMES = 15        # minimum ~300ms of speech to process
    MAX_UTTERANCE_FRAMES = 1500   # 30 seconds max (1500 * 20ms)
    FRAME_SIZE = 3840             # 20ms of 48kHz stereo 16-bit PCM

    def __init__(self, allowed_user_id: int, on_utterance):
        """
        Args:
            allowed_user_id: Only process audio from this Discord user ID.
            on_utterance: async callback(user_id, pcm_bytes) called when
                          an utterance is detected.
        """
        super().__init__()
        self._allowed_user_id = allowed_user_id
        self._on_utterance = on_utterance
        self._buffer = bytearray()
        self._speech_frames = 0
        self._silence_frames = 0
        self._is_speaking = False
        self._loop = None

    def wants_opus(self) -> bool:
        return False

    @staticmethod
    def _rms(pcm: bytes) -> float:
        """Calculate RMS energy of 16-bit PCM audio."""
        if len(pcm) < 2:
            return 0.0
        count = len(pcm) // 2
        samples = struct.unpack(f"<{count}h", pcm[:count * 2])
        return (sum(s * s for s in samples) / count) ** 0.5

    def write(self, user, data):
        if user is None or user.id != self._allowed_user_id:
            return

        pcm = data.pcm
        if not pcm:
            return

        energy = self._rms(pcm)
        silence_frames_needed = int(self.SILENCE_DURATION / 0.02)  # 75 frames

        if energy > self.SILENCE_THRESHOLD:
            # Speech detected
            self._is_speaking = True
            self._silence_frames = 0
            self._speech_frames += 1
            self._buffer.extend(pcm)

            # Safety cap
            if self._speech_frames >= self.MAX_UTTERANCE_FRAMES:
                self._flush_utterance(user.id)
        else:
            if self._is_speaking:
                self._silence_frames += 1
                self._buffer.extend(pcm)  # include trailing silence

                if self._silence_frames >= silence_frames_needed:
                    self._flush_utterance(user.id)

    def _flush_utterance(self, user_id: int):
        """Send captured audio for processing and reset state."""
        if self._speech_frames >= self.MIN_SPEECH_FRAMES:
            pcm_bytes = bytes(self._buffer)
            if self._loop and self._on_utterance:
                asyncio.run_coroutine_threadsafe(
                    self._on_utterance(user_id, pcm_bytes),
                    self._loop,
                )
        # Reset
        self._buffer.clear()
        self._speech_frames = 0
        self._silence_frames = 0
        self._is_speaking = False

    def cleanup(self):
        self._buffer.clear()
```

Note: `write()` is called from a non-async thread by discord-ext-voice-recv, so we use `asyncio.run_coroutine_threadsafe()` to dispatch the async callback.

---

### Task 4: Modify VoiceBot to Use Voice Receiving

**Files:**
- Modify: `webhook-handler/voice_bot.py`

**Step 1: Add voice input state to VoiceBot.__init__**

Add these instance variables in `__init__` (after `self._model_id = model_id`):

```python
self._listening_user_id = None  # user ID we're listening to
self._processing = False         # prevent concurrent STT calls
```

**Step 2: Modify _handle_join to use VoiceRecvClient and start listening**

Replace the existing `_handle_join` method:

```python
async def _handle_join(self, message: discord.Message):
    if not message.author.voice or not message.author.voice.channel:
        await message.channel.send("You need to be in a voice channel first.")
        return

    for vc in self.voice_clients:
        if vc.is_connected():
            await vc.disconnect()

    voice_channel = message.author.voice.channel
    try:
        if HAS_VOICE_RECV:
            vc = await voice_channel.connect(cls=voice_recv.VoiceRecvClient)
        else:
            vc = await voice_channel.connect()

        self._listening_user_id = message.author.id
        self._text_channel = message.channel

        if HAS_VOICE_RECV:
            sink = VoiceInputSink(
                allowed_user_id=message.author.id,
                on_utterance=self._on_utterance,
            )
            sink._loop = asyncio.get_event_loop()
            vc.listen(sink)
            mode_text = "I'm listening — speak a command or type `!voice <command>`."
        else:
            mode_text = "Voice input unavailable — type `!voice <command>` instead."

        logger.info(f"Joined voice channel: {voice_channel.name}")
        await message.channel.send(
            f"Joined **{voice_channel.name}**.\n"
            f"{mode_text}\n"
            "Type `!voice stop` to disconnect."
        )
    except Exception as e:
        logger.error(f"Failed to join voice: {e}", exc_info=True)
        await message.channel.send(f"Failed to join voice: {e}")
```

**Step 3: Add _on_utterance callback**

Add this method to the VoiceBot class:

```python
async def _on_utterance(self, user_id: int, pcm_bytes: bytes):
    """Called when VoiceInputSink detects end of an utterance."""
    if self._processing or self._speaking:
        return  # skip if already handling a command or speaking

    self._processing = True
    try:
        # Transcribe
        transcript = await speech_to_text(
            self._elevenlabs_api_key, pcm_bytes,
        )
        if not transcript or len(transcript) < 2:
            return

        logger.info(f"Voice transcript: {transcript}")

        # Find voice client
        vc = None
        for v in self.voice_clients:
            if v.is_connected():
                vc = v
                break
        if not vc:
            return

        # Parse command from transcript
        command, arguments = self._parse_transcript(transcript)

        # Post transcript to text channel so user can see what was heard
        if self._text_channel:
            await self._text_channel.send(f"🎙 Heard: *\"{transcript}\"* → `{command} {arguments}`".strip())

        # Execute command
        try:
            result = await call_voice_webhook(
                self._webhook_url, self._voice_secret, command, arguments,
            )
            spoken = result.get("spoken_summary", "No response.")
            full = result.get("full_result", "")
            post_full = result.get("post_to_text_channel", False)

            if post_full and full and self._text_channel:
                if len(full) > 1900:
                    full = full[:1900] + "\n...(truncated)"
                await self._text_channel.send(full)

            await self._speak(vc, spoken,
                              self._text_channel or vc.channel)
        except Exception as e:
            logger.error(f"Voice command error: {e}", exc_info=True)
            if self._text_channel:
                await self._text_channel.send(f"Error: {e}")
    finally:
        self._processing = False
```

**Step 4: Add _parse_transcript method**

Add this method to VoiceBot:

```python
@staticmethod
def _parse_transcript(transcript: str) -> tuple[str, str]:
    """Parse a voice transcript into (command, arguments).

    Examples:
        "status" → ("status", "")
        "ask what is the weather" → ("ask", "what is the weather")
        "health owner/repo" → ("health", "owner/repo")
        "what time is it" → ("ask", "what time is it")
    """
    words = transcript.lower().strip().split()
    if not words:
        return ("ask", transcript)

    first = words[0].rstrip(".,!?")

    # Direct command match
    if first in SUPPORTED_COMMANDS:
        return (first, " ".join(words[1:]))

    # Two-word command match (e.g., "pr review" → "pr-review")
    if len(words) >= 2:
        two_word = f"{first}-{words[1].rstrip('.,!?')}"
        if two_word in SUPPORTED_COMMANDS:
            return (two_word, " ".join(words[2:]))

    # Default to "ask"
    return ("ask", transcript)
```

**Step 5: Update _handle_stop to clean up listening state**

Replace `_handle_stop`:

```python
async def _handle_stop(self, message: discord.Message):
    disconnected = False
    for vc in self.voice_clients:
        if vc.is_connected():
            if HAS_VOICE_RECV and hasattr(vc, 'stop_listening'):
                vc.stop_listening()
            await vc.disconnect()
            disconnected = True
    self._listening_user_id = None
    self._text_channel = None
    if disconnected:
        await message.channel.send("Left voice channel.")
    else:
        await message.channel.send("I'm not in a voice channel.")
```

**Step 6: Add _text_channel to __init__**

Add to `__init__`:
```python
self._text_channel = None
```

---

### Task 5: Deploy and Test

**Step 1: SCP changed files to server**

```bash
scp webhook-handler/voice_bot.py root@46.224.193.25:/root/proxy-server/webhook-handler/voice_bot.py
scp webhook-handler/requirements.txt root@46.224.193.25:/root/proxy-server/webhook-handler/requirements.txt
scp webhook-handler/Dockerfile root@46.224.193.25:/root/proxy-server/webhook-handler/Dockerfile
```

**Step 2: Rebuild webhook-handler on server**

```bash
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --build webhook-handler"
```
Expected: Container rebuilds with new dependencies, starts successfully.

**Step 3: Verify container is healthy**

```bash
ssh root@46.224.193.25 "docker ps | grep webhook-handler"
```
Expected: Status shows "healthy"

**Step 4: Check logs for voice-recv loading**

```bash
ssh root@46.224.193.25 "docker logs webhook-handler --tail 30"
```
Expected: "Voice bot ready as ..." without voice-recv import errors.

**Step 5: Test in Discord**

1. Join a voice channel
2. Type `!voice join` — bot should say "I'm listening — speak a command..."
3. Say "status" — bot should transcribe, execute status command, speak result
4. Say "ask what time is it" — bot should transcribe and answer
5. Type `!voice stop` — bot disconnects

**Step 6: Commit**

```bash
git add webhook-handler/voice_bot.py webhook-handler/requirements.txt webhook-handler/Dockerfile
git commit -m "feat: add voice input — discord-ext-voice-recv + ElevenLabs STT"
```
