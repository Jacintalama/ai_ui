"""AIUI Voice Bridge -- Discord voice channel with TTS responses.

Users type commands in text chat, bot speaks the results in voice channel.
Uses the webhook-handler's /webhook/voice/{command} endpoint for processing
and ElevenLabs TTS API for speech output.
"""
import asyncio
import io
import logging
import os
import tempfile

import discord
import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DISCORD_BOT_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
ELEVENLABS_API_KEY = os.environ["ELEVENLABS_API_KEY"]
WEBHOOK_HANDLER_URL = os.environ.get("WEBHOOK_HANDLER_URL", "http://webhook-handler:8086")
VOICE_WEBHOOK_SECRET = os.environ.get("VOICE_WEBHOOK_SECRET", "")
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")
ELEVENLABS_MODEL_ID = os.environ.get("ELEVENLABS_MODEL_ID", "eleven_turbo_v2_5")

voice_lock = asyncio.Lock()

# Commands that the voice bot supports (maps to webhook-handler commands)
SUPPORTED_COMMANDS = {
    "status", "ask", "security", "health", "deps", "license",
    "sheets", "workflows", "pr-review", "analyze", "rebuild", "report",
}

HELP_TEXT = (
    "**Voice Bot Commands:**\n"
    "`!voice join` — Join your voice channel\n"
    "`!voice stop` — Leave voice channel\n"
    "`!voice status` — Check service health (spoken)\n"
    "`!voice ask <question>` — Ask AI a question (spoken)\n"
    "`!voice deps <owner/repo>` — Check dependencies (spoken)\n"
    "`!voice security <owner/repo>` — Security audit (spoken)\n"
    "`!voice health <owner/repo>` — Code health (spoken)\n"
    "`!voice workflows` — List n8n workflows (spoken)\n"
    "`!voice report` — End-of-day report (spoken)\n"
    "...and any other `/aiui` command\n\n"
    "Bot speaks the summary in voice and posts full results in text."
)


async def call_voice_webhook(command: str, arguments: str = "") -> dict:
    """Call the webhook-handler's voice endpoint."""
    url = f"{WEBHOOK_HANDLER_URL}/webhook/voice/{command}"
    body = {"arguments": arguments}

    # Parse owner/repo from arguments if present
    if "/" in arguments.split()[0] if arguments.split() else "":
        parts = arguments.split(maxsplit=1)
        owner_repo = parts[0].split("/")
        if len(owner_repo) == 2:
            body["owner"] = owner_repo[0]
            body["repo"] = owner_repo[1]
            body["arguments"] = parts[1] if len(parts) > 1 else ""

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            url,
            json=body,
            headers={"X-Voice-Secret": VOICE_WEBHOOK_SECRET},
        )
        resp.raise_for_status()
        return resp.json()


async def text_to_speech(text: str) -> bytes:
    """Convert text to speech using ElevenLabs TTS API. Returns MP3 bytes."""
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            url,
            headers={
                "xi-api-key": ELEVENLABS_API_KEY,
                "Content-Type": "application/json",
            },
            json={
                "text": text[:5000],  # ElevenLabs limit
                "model_id": ELEVENLABS_MODEL_ID,
            },
        )
        resp.raise_for_status()
        return resp.content


class VoiceBot(discord.Client):
    """Discord bot that speaks command results in voice channels."""

    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True
        super().__init__(intents=intents)
        self._speaking = False

    async def on_ready(self):
        logger.info(f"Voice bridge ready as {self.user}")

    async def on_message(self, message: discord.Message):
        """Handle !voice text commands."""
        if message.author.bot:
            return
        if not message.content.startswith("!voice"):
            return

        parts = message.content.strip().split(maxsplit=2)
        # parts[0] = "!voice", parts[1] = action, parts[2] = arguments
        action = parts[1].strip().lower() if len(parts) > 1 else "help"
        arguments = parts[2].strip() if len(parts) > 2 else ""

        if action == "join":
            await self._handle_join(message)
        elif action == "stop":
            await self._handle_stop(message)
        elif action == "help":
            await message.channel.send(HELP_TEXT)
        elif action in SUPPORTED_COMMANDS:
            await self._handle_command(message, action, arguments)
        else:
            # Treat unknown actions as "ask" query
            full_query = f"{action} {arguments}".strip()
            await self._handle_command(message, "ask", full_query)

    async def _handle_join(self, message: discord.Message):
        """Join the user's voice channel."""
        if not message.author.voice or not message.author.voice.channel:
            await message.channel.send("You need to be in a voice channel first.")
            return

        # Disconnect from existing voice if any
        for vc in self.voice_clients:
            if vc.is_connected():
                await vc.disconnect()

        voice_channel = message.author.voice.channel
        try:
            await voice_channel.connect()
            logger.info(f"Joined voice channel: {voice_channel.name}")
            await message.channel.send(
                f"Joined **{voice_channel.name}**. "
                "I'll speak command results here.\n"
                "Try `!voice status` or `!voice ask <question>`\n"
                "Type `!voice stop` to disconnect."
            )
        except Exception as e:
            logger.error(f"Failed to join voice: {e}", exc_info=True)
            await message.channel.send(f"Failed to join voice: {e}")

    async def _handle_stop(self, message: discord.Message):
        """Leave voice channel."""
        disconnected = False
        for vc in self.voice_clients:
            if vc.is_connected():
                await vc.disconnect()
                disconnected = True
        if disconnected:
            await message.channel.send("Left voice channel.")
        else:
            await message.channel.send("I'm not in a voice channel.")

    async def _handle_command(self, message: discord.Message, command: str, arguments: str):
        """Execute a command, post results, and speak the summary."""
        # Find active voice client
        vc = None
        for v in self.voice_clients:
            if v.is_connected():
                vc = v
                break

        if not vc:
            await message.channel.send(
                "I'm not in a voice channel. Use `!voice join` first."
            )
            return

        # Show typing indicator
        async with message.channel.typing():
            try:
                # Call webhook-handler
                logger.info(f"Executing command: {command} {arguments}")
                result = await call_voice_webhook(command, arguments)

                spoken = result.get("spoken_summary", "No response.")
                full = result.get("full_result", "")
                post_full = result.get("post_to_text_channel", False)

                # Post full result to text channel if long
                if post_full and full:
                    # Truncate for Discord 2000 char limit
                    if len(full) > 1900:
                        full = full[:1900] + "\n...(truncated)"
                    await message.channel.send(full)

                # Speak the summary in voice
                await self._speak(vc, spoken, message.channel)

            except httpx.HTTPStatusError as e:
                error_msg = f"Command failed: HTTP {e.response.status_code}"
                logger.error(f"{error_msg}: {e.response.text}")
                await message.channel.send(error_msg)
            except Exception as e:
                logger.error(f"Command error: {e}", exc_info=True)
                await message.channel.send(f"Error: {e}")

    async def _speak(self, vc: discord.VoiceClient, text: str,
                     fallback_channel: discord.TextChannel):
        """Convert text to speech and play in voice channel."""
        if self._speaking:
            logger.info("Already speaking, queueing skipped")
            return

        self._speaking = True
        tmp_path = None
        try:
            # Get TTS audio from ElevenLabs
            logger.info(f"TTS: {text[:100]}...")
            audio_bytes = await text_to_speech(text)
            logger.info(f"TTS audio received: {len(audio_bytes)} bytes")

            # Write to temp file (FFmpeg needs a seekable source)
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                f.write(audio_bytes)
                tmp_path = f.name

            # Play in Discord voice channel
            source = discord.FFmpegPCMAudio(tmp_path)
            vc.play(source)

            # Wait for playback to finish
            while vc.is_playing():
                await asyncio.sleep(0.5)

        except Exception as e:
            logger.error(f"TTS error: {e}", exc_info=True)
            await fallback_channel.send(f"(Could not speak: {e})")
        finally:
            self._speaking = False
            # Clean up temp file
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass


def main():
    bot = VoiceBot()
    bot.run(DISCORD_BOT_TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
