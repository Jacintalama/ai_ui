"""AIUI Voice Bridge -- Discord voice channel <-> ElevenLabs Conversational AI."""
import asyncio
import logging
import os

import discord
from discord import app_commands
from elevenlabs.client import ElevenLabs
from elevenlabs.conversational_ai.conversation import Conversation, AudioInterface

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DISCORD_BOT_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
ELEVENLABS_API_KEY = os.environ["ELEVENLABS_API_KEY"]
ELEVENLABS_AGENT_ID = os.environ["ELEVENLABS_AGENT_ID"]

# Mutex: one voice session at a time
voice_lock = asyncio.Lock()


class DiscordAudioInterface(AudioInterface):
    """Bridge between Discord voice audio and ElevenLabs conversation.

    NOTE: This is a working skeleton. Discord provides PCM 48kHz stereo,
    ElevenLabs expects 16kHz mono. Audio resampling via audioop or ffmpeg
    subprocess may be needed during testing. The ElevenLabs SDK's
    DefaultAudioInterface uses pyaudio for system mic/speaker -- we override
    it to use Discord's voice connection instead.
    """

    def __init__(self, voice_client: discord.VoiceClient):
        self.voice_client = voice_client
        self._output_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._listening = False
        self._input_callback = None

    def start(self, input_callback):
        """Called by ElevenLabs SDK when conversation starts."""
        self._listening = True
        self._input_callback = input_callback
        logger.info("Audio interface started")

    def stop(self):
        """Called by ElevenLabs SDK when conversation ends."""
        self._listening = False
        logger.info("Audio interface stopped")

    def output(self, audio: bytes):
        """Called by ElevenLabs SDK with TTS audio to play in Discord."""
        self._output_queue.put_nowait(audio)

    def interrupt(self):
        """Called when user interrupts the agent."""
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

        @self.tree.command(
            name="aiui-voice",
            description="Join/leave voice channel for AIUI voice assistant",
        )
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

    async def on_ready(self):
        logger.info(f"Voice bridge ready as {self.user}")

    async def _handle_join(self, interaction: discord.Interaction):
        """Join the user's voice channel and start ElevenLabs session."""
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message(
                "You need to be in a voice channel first.", ephemeral=True
            )
            return

        if voice_lock.locked():
            await interaction.response.send_message(
                "Another voice session is already active. Try again later.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        async with voice_lock:
            voice_channel = interaction.user.voice.channel
            self.text_channel = interaction.channel

            try:
                vc = await voice_channel.connect()
                logger.info(f"Joined voice channel: {voice_channel.name}")

                client = ElevenLabs(api_key=ELEVENLABS_API_KEY)
                audio_interface = DiscordAudioInterface(vc)

                self.active_conversation = Conversation(
                    client=client,
                    agent_id=ELEVENLABS_AGENT_ID,
                    requires_auth=True,
                    audio_interface=audio_interface,
                    callback_agent_response=self._on_agent_response,
                    callback_user_transcript=self._on_user_transcript,
                )

                await interaction.followup.send(
                    "Joined voice. Speak naturally -- I'm listening. "
                    "Use `/aiui-voice stop` or I'll leave after 5 min idle."
                )

                self.active_conversation.start_session()
                await self._wait_for_idle(vc, timeout=300)

            except Exception as e:
                logger.error(f"Voice session error: {e}", exc_info=True)
                if self.text_channel:
                    try:
                        await self.text_channel.send(f"Voice session error: {e}")
                    except Exception:
                        pass
            finally:
                await self._cleanup()

    async def _handle_stop(self, interaction: discord.Interaction):
        """Leave voice channel and end session."""
        await interaction.response.send_message("Leaving voice channel.")
        await self._cleanup()

    def _on_agent_response(self, text: str):
        """Called when agent produces a text response."""
        logger.info(f"Agent: {text}")
        if self.text_channel:
            asyncio.create_task(self.text_channel.send(f"**AIUI Voice:** {text[:1900]}"))
        self._last_activity = asyncio.get_event_loop().time()

    def _on_user_transcript(self, text: str):
        """Called when user speech is transcribed."""
        logger.info(f"User: {text}")
        self._last_activity = asyncio.get_event_loop().time()

    async def _wait_for_idle(self, vc: discord.VoiceClient, timeout: int = 300):
        """Wait until idle timeout or disconnect. Resets on activity."""
        self._last_activity = asyncio.get_event_loop().time()
        while vc.is_connected():
            await asyncio.sleep(1)
            idle = asyncio.get_event_loop().time() - self._last_activity
            if idle >= timeout:
                if self.text_channel:
                    try:
                        await self.text_channel.send(
                            "Voice session ended (idle timeout)."
                        )
                    except Exception:
                        pass
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
                try:
                    await vc.disconnect()
                except Exception:
                    pass

        logger.info("Voice session cleaned up")


def main():
    bot = VoiceBot()
    bot.run(DISCORD_BOT_TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
