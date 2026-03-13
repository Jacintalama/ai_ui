# ElevenLabs Voice Discord Bot — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add voice interaction to the AIUI Discord bot using ElevenLabs Conversational AI, so users can speak commands in a Discord voice channel and hear spoken responses.

**Architecture:** ElevenLabs hosted agent (Claude LLM + TTS/STT) connected via webhook tools to the existing webhook-handler. A thin `voice-bridge` Discord bot container pipes audio between Discord voice channels and ElevenLabs WebSocket API.

**Tech Stack:** Python 3.11, discord.py[voice], elevenlabs SDK, PyNaCl, ffmpeg, FastAPI (existing webhook-handler)

**Design doc:** `docs/plans/2026-03-13-elevenlabs-voice-discord-design.md`

---

### Task 1: Voice Webhook Endpoint

Add `/webhook/voice/{command}` to the webhook-handler so ElevenLabs agent can call AIUI commands via HTTP.

**Files:**
- Modify: `webhook-handler/main.py`
- Modify: `webhook-handler/handlers/commands.py`

**Step 1: Add voice respond callback to commands.py**

Add a helper that collects command output instead of sending to Discord. Place it near the top of the file, after the `CommandContext` class (around line 31):

```python
class VoiceResponseCollector:
    """Collects command output for voice webhook responses."""

    def __init__(self):
        self.messages: list[str] = []

    async def respond(self, msg: str) -> None:
        self.messages.append(msg)

    @property
    def full_result(self) -> str:
        return "\n\n".join(self.messages)

    @property
    def spoken_summary(self) -> str:
        """First message, truncated for speech."""
        if not self.messages:
            return "No response."
        text = self.messages[-1]
        # Strip markdown formatting for speech
        import re
        text = re.sub(r'[*_`#\[\]()]', '', text)
        text = re.sub(r'\n+', '. ', text)
        if len(text) > 500:
            text = text[:497] + "..."
        return text
```

**Step 2: Add voice webhook route to main.py**

Add the route after the existing `/webhook/discord` endpoint (around line 445). Follow the existing route pattern:

```python
@app.post("/webhook/voice/{command}")
async def voice_webhook(
    command: str,
    request: Request,
    x_voice_secret: str = Header(None, alias="X-Voice-Secret"),
):
    """Handle tool calls from ElevenLabs voice agent."""
    expected_secret = os.environ.get("VOICE_WEBHOOK_SECRET", "")
    if not expected_secret or x_voice_secret != expected_secret:
        raise HTTPException(status_code=401, detail="Invalid voice webhook secret")

    body = await request.json()
    arguments = body.get("arguments", "")
    if body.get("owner") and body.get("repo"):
        arguments = f"{body['owner']}/{body['repo']} {arguments}".strip()

    from handlers.commands import VoiceResponseCollector
    collector = VoiceResponseCollector()

    ctx = CommandContext(
        user_id="voice-agent",
        user_name="Voice User",
        channel_id=body.get("channel_id", "voice"),
        raw_text=f"{command} {arguments}".strip(),
        subcommand=command,
        arguments=arguments,
        platform="voice",
        respond=collector.respond,
        metadata={"source": "elevenlabs"},
    )

    await command_router.execute(ctx)

    return {
        "spoken_summary": collector.spoken_summary,
        "full_result": collector.full_result,
        "post_to_text_channel": len(collector.full_result) > 500,
    }
```

**Step 3: Add VOICE_WEBHOOK_SECRET to config**

In `webhook-handler/config.py`, add to the `Settings` class:

```python
    voice_webhook_secret: str = ""
```

**Step 4: Test the endpoint manually**

Deploy to server and test:

```bash
# On server, test internally
docker exec webhook-handler curl -s -X POST http://localhost:8086/webhook/voice/status \
  -H "Content-Type: application/json" \
  -H "X-Voice-Secret: test-secret-123" \
  -d '{}' | python3 -m json.tool
```

Expected: JSON with `spoken_summary`, `full_result`, `post_to_text_channel` fields.

**Step 5: Commit**

```bash
git add webhook-handler/main.py webhook-handler/handlers/commands.py webhook-handler/config.py
git commit -m "feat: add /webhook/voice/{command} endpoint for ElevenLabs agent"
```

---

### Task 2: Voice Bridge Container

Create the Discord bot that joins voice channels and bridges audio to ElevenLabs.

**Files:**
- Create: `voice-bridge/main.py`
- Create: `voice-bridge/Dockerfile`
- Create: `voice-bridge/requirements.txt`

**Step 1: Create requirements.txt**

```
discord.py[voice]>=2.3.0
elevenlabs>=1.0.0
PyNaCl>=1.5.0
python-dotenv>=1.0.0
```

**Step 2: Create Dockerfile**

```dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg libffi-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
CMD ["python", "main.py"]
```

**Step 3: Create main.py**

This is the core bridge. It:
- Connects to Discord as a bot
- Registers `/aiui voice` slash command
- Joins/leaves voice channels
- Pipes audio between Discord and ElevenLabs WebSocket
- Posts full text results to the text channel

```python
"""AIUI Voice Bridge — Discord voice channel ↔ ElevenLabs Conversational AI."""
import asyncio
import logging
import os
import signal

import discord
from discord import app_commands
from elevenlabs.client import ElevenLabs
from elevenlabs.conversational_ai.conversation import Conversation, AudioInterface

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DISCORD_BOT_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
ELEVENLABS_API_KEY = os.environ["ELEVENLABS_API_KEY"]
ELEVENLABS_AGENT_ID = os.environ["ELEVENLABS_AGENT_ID"]

# Mutex: one voice session at a time (3.8GB RAM constraint)
voice_lock = asyncio.Lock()


class DiscordAudioInterface(AudioInterface):
    """Bridge between Discord voice audio and ElevenLabs conversation."""

    def __init__(self, voice_client: discord.VoiceClient):
        self.voice_client = voice_client
        self._output_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._listening = False

    def start(self, input_callback):
        """Called by ElevenLabs SDK when conversation starts."""
        self._listening = True
        # Discord voice sink feeds audio to input_callback
        # input_callback expects PCM 16-bit 16kHz mono
        self._input_callback = input_callback
        logger.info("Audio interface started")

    def stop(self):
        """Called by ElevenLabs SDK when conversation ends."""
        self._listening = False
        logger.info("Audio interface stopped")

    def output(self, audio: bytes):
        """Called by ElevenLabs SDK with TTS audio to play."""
        self._output_queue.put_nowait(audio)

    def interrupt(self):
        """Called when user interrupts the agent."""
        # Clear queued audio
        while not self._output_queue.empty():
            try:
                self._output_queue.get_nowait()
            except asyncio.QueueEmpty:
                break


class VoiceBot(discord.Client):
    """Discord bot that bridges voice to ElevenLabs."""

    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.active_conversation: Conversation | None = None
        self.text_channel: discord.TextChannel | None = None

    async def setup_hook(self):
        """Register slash commands on startup."""

        @self.tree.command(name="aiui-voice", description="Join/leave voice channel for AIUI voice assistant")
        @app_commands.describe(action="join or stop")
        @app_commands.choices(action=[
            app_commands.Choice(name="join", value="join"),
            app_commands.Choice(name="stop", value="stop"),
        ])
        async def voice_command(interaction: discord.Interaction, action: str = "join"):
            if action == "join":
                await self._handle_join(interaction)
            elif action == "stop":
                await self._handle_stop(interaction)

        await self.tree.sync()
        logger.info("Slash commands synced")

    async def _handle_join(self, interaction: discord.Interaction):
        """Join the user's voice channel and start ElevenLabs session."""
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message(
                "You need to be in a voice channel first.", ephemeral=True
            )
            return

        if not voice_lock.locked():
            await interaction.response.defer()
        else:
            await interaction.response.send_message(
                "Another voice session is already active. Try again later.", ephemeral=True
            )
            return

        async with voice_lock:
            voice_channel = interaction.user.voice.channel
            self.text_channel = interaction.channel

            try:
                # Join voice channel
                vc = await voice_channel.connect()
                logger.info(f"Joined voice channel: {voice_channel.name}")

                # Create ElevenLabs conversation
                client = ElevenLabs(api_key=ELEVENLABS_API_KEY)
                audio_interface = DiscordAudioInterface(vc)

                self.active_conversation = Conversation(
                    client=client,
                    agent_id=ELEVENLABS_AGENT_ID,
                    requires_auth=True,
                    audio_interface=audio_interface,
                    callback_agent_response=lambda text: logger.info(f"Agent: {text}"),
                    callback_user_transcript=lambda text: logger.info(f"User: {text}"),
                )

                await interaction.followup.send(
                    "Joined voice. Speak naturally — I'm listening. "
                    "Use `/aiui-voice stop` or I'll leave after 5 min idle."
                )

                # Start the conversation (blocking until ended)
                self.active_conversation.start_session()

                # Wait for stop or idle timeout
                await self._wait_for_idle(vc, timeout=300)

            except Exception as e:
                logger.error(f"Voice session error: {e}", exc_info=True)
                if self.text_channel:
                    await self.text_channel.send(f"Voice session error: {e}")
            finally:
                await self._cleanup()

    async def _handle_stop(self, interaction: discord.Interaction):
        """Leave voice channel and end session."""
        await interaction.response.send_message("Leaving voice channel.")
        await self._cleanup()

    async def _wait_for_idle(self, vc: discord.VoiceClient, timeout: int = 300):
        """Wait until idle timeout or disconnect."""
        idle_seconds = 0
        while vc.is_connected():
            await asyncio.sleep(1)
            idle_seconds += 1
            if idle_seconds >= timeout:
                if self.text_channel:
                    await self.text_channel.send("Voice session ended (idle timeout).")
                break

    async def _cleanup(self):
        """End conversation and disconnect from voice."""
        if self.active_conversation:
            try:
                self.active_conversation.end_session()
            except Exception:
                pass
            self.active_conversation = None

        for vc in self.voice_clients:
            if vc.is_connected():
                await vc.disconnect()

        logger.info("Voice session cleaned up")


def main():
    bot = VoiceBot()

    # Graceful shutdown
    loop = asyncio.new_event_loop()

    def shutdown_handler():
        logger.info("Shutting down...")
        loop.create_task(bot.close())

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, shutdown_handler)
        except NotImplementedError:
            pass  # Windows

    bot.run(DISCORD_BOT_TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
```

> **Note:** The `DiscordAudioInterface` is a skeleton. The exact audio piping between discord.py's voice receive/send and ElevenLabs SDK will need refinement during implementation — discord.py provides PCM audio at 48kHz stereo, while ElevenLabs expects 16kHz mono. An ffmpeg-based resampler bridge will be needed. This is the most complex part and may require iteration.

**Step 4: Test locally (optional)**

```bash
cd voice-bridge
pip install -r requirements.txt
DISCORD_BOT_TOKEN=test ELEVENLABS_API_KEY=test ELEVENLABS_AGENT_ID=test python -c "from main import VoiceBot; print('Import OK')"
```

Expected: "Import OK" (verifies no syntax errors)

**Step 5: Commit**

```bash
git add voice-bridge/
git commit -m "feat: add voice-bridge container for Discord voice + ElevenLabs"
```

---

### Task 3: Docker Compose Integration

Add voice-bridge to the production stack.

**Files:**
- Modify: `docker-compose.unified.yml`

**Step 1: Add voice-bridge service**

Add after the `webhook-handler` service block (around line 135). Follow the existing service pattern:

```yaml
  voice-bridge:
    build: ./voice-bridge
    container_name: voice-bridge
    restart: unless-stopped
    environment:
      - DISCORD_BOT_TOKEN=${DISCORD_BOT_TOKEN:-}
      - ELEVENLABS_API_KEY=${ELEVENLABS_API_KEY:-}
      - ELEVENLABS_AGENT_ID=${ELEVENLABS_AGENT_ID:-}
      - WEBHOOK_HANDLER_URL=http://webhook-handler:8086
      - LOG_LEVEL=${LOG_LEVEL:-INFO}
    networks:
      - backend
    depends_on:
      - webhook-handler
    healthcheck:
      test: ["CMD", "python", "-c", "print('ok')"]
      interval: 30s
      timeout: 10s
      retries: 3
```

**Step 2: Add VOICE_WEBHOOK_SECRET to webhook-handler env**

In the webhook-handler service environment section (around line 115), add:

```yaml
      - VOICE_WEBHOOK_SECRET=${VOICE_WEBHOOK_SECRET:-}
```

**Step 3: Commit**

```bash
git add docker-compose.unified.yml
git commit -m "feat: add voice-bridge service to docker-compose"
```

---

### Task 4: ElevenLabs Agent Setup (Manual)

Configure the voice agent on the ElevenLabs dashboard. This is a manual step — no code changes.

**Step 1: Create ElevenLabs account**

Go to https://elevenlabs.io and sign up. Creator plan ($22/mo) includes 250 conversational minutes.

**Step 2: Create a new agent**

Navigate to Agents Platform → Create Agent:
- **Name:** AIUI Voice Assistant
- **LLM Provider:** Anthropic Claude
- **API Key:** Use your existing `ANTHROPIC_API_KEY`
- **System prompt:**

```
You are AIUI, a voice assistant for a software development team. Users speak commands to you and you execute them using your available tools.

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
Be concise in speech. Technical details go to the text channel.
```

**Step 3: Add webhook tools**

For each command, add a Server Tool with:
- **Type:** Webhook
- **Method:** POST
- **URL:** `https://ai-ui.coolestdomain.win/webhook/voice/{command_name}`
- **Headers:** `X-Voice-Secret: <your-secret>`
- **Parameters:** Define based on command (e.g., `owner`, `repo`, `arguments`)

Create tools for: `status`, `ask`, `security`, `health`, `deps`, `license`, `pr-review`, `sheets`, `analyze`, `rebuild`, `workflows`, `report`

**Step 4: Choose a voice**

Pick a voice from the 11Labs library. Recommended: a clear, professional voice (e.g., "Rachel" or "Adam").

**Step 5: Copy agent ID**

Copy the agent ID from the dashboard. Add to `.env` on server:

```bash
ELEVENLABS_API_KEY=<your-key>
ELEVENLABS_AGENT_ID=<agent-id>
VOICE_WEBHOOK_SECRET=<generate-a-random-secret>
```

**Step 6: Test the agent**

Use the 11Labs dashboard "Test" feature to verify the agent can call your webhook tools and get responses.

---

### Task 5: Discord Bot Setup (Manual)

Configure Discord Developer Portal for voice permissions.

**Step 1: Enable privileged intents**

Go to Discord Developer Portal → Your App → Bot:
- Enable **Server Members Intent**
- Enable **Message Content Intent**
- Enable **Presence Intent** (optional)

**Step 2: Enable voice permissions**

Go to OAuth2 → URL Generator:
- Scopes: `bot`, `applications.commands`
- Bot Permissions: `Connect`, `Speak`, `Use Voice Activity`, `Send Messages`

**Step 3: Get bot token**

If you need a separate bot token for the voice bridge (recommended to keep voice separate from webhook interactions), create a new application. Otherwise, use the existing `DISCORD_BOT_TOKEN`.

Add to `.env`:

```bash
DISCORD_BOT_TOKEN=<bot-token-with-voice-permissions>
```

**Step 4: Invite bot to server**

Use the generated OAuth2 URL to invite the bot to your Discord server with voice permissions.

---

### Task 6: Deploy and Test End-to-End

**Step 1: Push code to server**

```bash
scp -r voice-bridge/ root@46.224.193.25:/root/proxy-server/voice-bridge/
scp webhook-handler/main.py root@46.224.193.25:/root/proxy-server/webhook-handler/main.py
scp webhook-handler/handlers/commands.py root@46.224.193.25:/root/proxy-server/webhook-handler/handlers/commands.py
scp webhook-handler/config.py root@46.224.193.25:/root/proxy-server/webhook-handler/config.py
scp docker-compose.unified.yml root@46.224.193.25:/root/proxy-server/docker-compose.unified.yml
```

**Step 2: Add env vars on server**

```bash
ssh root@46.224.193.25 'cat >> /root/proxy-server/.env << EOF
ELEVENLABS_API_KEY=<your-key>
ELEVENLABS_AGENT_ID=<agent-id>
VOICE_WEBHOOK_SECRET=<random-secret>
EOF'
```

**Step 3: Build and start**

```bash
ssh root@46.224.193.25 'cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --build voice-bridge webhook-handler'
```

**Step 4: Verify containers**

```bash
ssh root@46.224.193.25 'docker ps | grep -E "voice-bridge|webhook-handler"'
```

Expected: Both containers running.

**Step 5: Test voice webhook endpoint**

```bash
ssh root@46.224.193.25 'curl -s -X POST http://localhost:8086/webhook/voice/status \
  -H "Content-Type: application/json" \
  -H "X-Voice-Secret: <your-secret>" \
  -d "{}" | python3 -m json.tool'
```

Expected: JSON with spoken_summary and full_result.

**Step 6: Test in Discord**

1. Join a voice channel in your Discord server
2. Type `/aiui-voice join` in a text channel
3. Bot should join your voice channel
4. Say "What's the status of our services?"
5. Bot should speak back the health status
6. Say "Check the security of our repo"
7. Bot should say "Running security audit..." then speak summary when done
8. Type `/aiui-voice stop` to disconnect

**Step 7: Commit final state**

```bash
git add -A
git commit -m "feat: ElevenLabs voice integration for Discord — full deployment"
```

---

## Audio Bridge Refinement Note

The `DiscordAudioInterface` in Task 2 is a skeleton. The audio piping between discord.py and ElevenLabs requires:

1. **Discord → ElevenLabs:** discord.py provides PCM 48kHz stereo. ElevenLabs expects 16kHz mono. Need ffmpeg subprocess or `audioop` for resampling.
2. **ElevenLabs → Discord:** ElevenLabs returns audio (format TBD from SDK). discord.py expects PCM 48kHz stereo via `FFmpegPCMAudio` or similar source.
3. **Voice Activity Detection:** discord.py can listen to specific users. Need to handle multiple speakers and silence detection.

This will likely require 1-2 iterations during Task 6 testing. The ElevenLabs Python SDK docs and discord.py voice receive examples should be referenced:
- https://elevenlabs.io/docs/agents-platform/libraries/python
- https://discordpy.readthedocs.io/en/stable/api.html#voiceclient
