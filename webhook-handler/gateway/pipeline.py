"""MessageEvent in, reply sent. The only flow, shared by every platform.

The governing rule here is the opposite of the rest of this codebase. Build
post-processing fails open because nobody is watching. Here somebody is staring
at a chat window waiting, so NOTHING may fail silently: every path ends in a
sentence the person can read.
"""
import logging
import os

from clients.tasks import TasksAPIError, TasksClient
from config import settings
from gateway import commands as gateway_commands
from gateway.base import BasePlatformAdapter
from gateway.events import MessageEvent, MessageType
from gateway.owui import OWUIError, OWUIUserClient
from gateway.pairing import pairing_message
from gateway.platforms.telegram import ClipTooLarge
from gateway.sessions import append_turn, get_or_create_chat, history_messages

log = logging.getLogger(__name__)

GROUP_REFUSAL = (
    "I only work in direct messages for now. Message me privately and I'll "
    "answer there."
)
TASKS_DOWN = "I can't reach my memory right now. Try again in a moment."
MODEL_DOWN = "The model didn't answer just now. Try again in a moment."
UNEXPECTED = "Something went wrong on my side. Try again in a moment."
UNSUPPORTED_TYPE = (
    "I can read text and voice messages. I can't do anything with that one yet."
)
TRANSCRIBE_FAILED = (
    "I couldn't make out that voice message. Could you send it again or type it?"
)
CLIP_TOO_LONG = (
    "That voice message is too long for me. I can handle up to 2 minutes."
)

# Whisper on this box is CPU only, so a long clip would hold a worker for
# minutes while the sender stares at nothing. Keep this in step with the
# sentence in CLIP_TOO_LONG.
MAX_VOICE_SECONDS = 120

# Distinguishable from any real message text, so a person cannot type them.
_FAILED = "\x00gateway-transcribe-failed"
_TOO_LONG = "\x00gateway-clip-too-long"

#: Seams. main.py sets _tasks at startup; tests replace both.
_tasks = None


def _owui_factory(token: str) -> OWUIUserClient:
    return OWUIUserClient(settings.openwebui_url, token)


def configure(tasks_client: TasksClient) -> None:
    """Hand the pipeline its tasks client. Called once, from the app lifespan."""
    global _tasks
    _tasks = tasks_client


def link_url() -> str:
    return f"{settings.gateway_public_url.rstrip('/')}/tasks/gateway/link"


async def handle_event(event: MessageEvent, adapter: BasePlatformAdapter) -> str:
    """Run one inbound message end to end and return what was sent.

    Returning the text as well as sending it lets a synchronous caller (the CLI)
    answer inline without a second delivery mechanism.

    Every exit from here delivers a sentence. The person is waiting, so an
    exception that escaped would leave them staring at silence.
    """
    src = event.source

    try:
        return await _run(event, adapter)
    except TasksAPIError as e:
        log.warning("gateway: tasks failed (%s): %s", e.status, e.message)
        return await _say(adapter, src.chat_id, TASKS_DOWN)
    except OWUIError as e:
        log.warning("gateway: open-webui failed (%s): %s", e.status, e.message)
        return await _say(adapter, src.chat_id, MODEL_DOWN)
    except Exception:                                  # noqa: BLE001
        log.exception("gateway: unexpected failure handling a %s message",
                      src.platform)
        return await _say(adapter, src.chat_id, UNEXPECTED)
    finally:
        await _stop_typing_quietly(adapter, src.chat_id)


async def _run(event: MessageEvent, adapter: BasePlatformAdapter) -> str:
    """The flow proper. Errors here are caught and turned into a sentence by
    the caller, `handle_event`, which owns the try/except/finally."""
    src = event.source

    # First, and inside the caller's try so even a delivery failure here is
    # reported. The Brain is injected into every model call, so answering in a
    # group would print one person's private memory to the whole room, with no
    # warning and no way to know in advance. Refusing before identity is even
    # resolved means no code path exists for that to happen.
    if src.chat_type != "dm":
        return await _say(adapter, src.chat_id, GROUP_REFUSAL)

    identity = await _tasks.gateway_resolve(
        src.platform, src.user_id or src.chat_id, src.user_name or "")

    if not identity.get("linked"):
        code = identity.get("code")
        if not code:
            log.error("gateway: resolve said unlinked but sent no code")
            return await _say(adapter, src.chat_id, UNEXPECTED)
        # Never log the code.
        return await _say(adapter, src.chat_id, pairing_message(code, link_url()))

    token = identity.get("owui_token")
    if not token:
        log.error("gateway: resolve said linked but sent no token")
        return await _say(adapter, src.chat_id, UNEXPECTED)

    owui_user_id = identity.get("owui_user_id")
    if not owui_user_id:
        log.error("gateway: resolve said linked but sent no user id")
        return await _say(adapter, src.chat_id, UNEXPECTED)
    owui = _owui_factory(token)

    text = await _resolve_text(event, owui, adapter)
    if text is None:
        return await _say(adapter, src.chat_id, UNSUPPORTED_TYPE)
    if text == _FAILED:
        return await _say(adapter, src.chat_id, TRANSCRIBE_FAILED)
    if text == _TOO_LONG:
        return await _say(adapter, src.chat_id, CLIP_TOO_LONG)
    if not text.strip():
        # A sticker, an empty edit, a stray keystroke. Answering would be noise.
        return ""

    # Commands run before the model, so /resume and /help still work when the
    # model is down. Those are how someone recovers, so routing them through a
    # model call would make them useless exactly when they are needed. A command
    # never reaches Open WebUI and never lands in the user's chat history.
    if gateway_commands.is_command(text):
        try:
            reply = await gateway_commands.handle(
                text, _tasks, src, owui_user_id)
        except TasksAPIError:
            # Logged here and re-raised, not handled here. handle_event still
            # owns the single conversion to TASKS_DOWN, but its message cannot
            # say whether a command or the chat flow failed, and an operator
            # reading logs needs to know which.
            log.warning("gateway: %s failed against tasks", text.split()[0])
            raise
        if reply is not None:
            return await _say(adapter, src.chat_id, reply)

    await adapter.send_typing(src.chat_id)
    chat_id, chat = await get_or_create_chat(
        _tasks, owui, src.platform, src.chat_id,
        owui_user_id, text, settings.gateway_model)

    messages = history_messages(chat, settings.gateway_history_turns)
    messages.append({"role": "user", "content": text})
    answer = await owui.chat_completion(
        messages, settings.gateway_model, chat_id=chat_id)

    # Persist before delivering, but never let a persist failure swallow a
    # good answer: the person is waiting and the answer already exists.
    try:
        await owui.update_chat(
            chat_id, append_turn(chat, text, answer, settings.gateway_model))
    except Exception:                              # noqa: BLE001
        log.exception("gateway: could not write the transcript to chat %s; "
                      "delivering the answer anyway", chat_id)

    return await _say(adapter, src.chat_id, answer)


async def _resolve_text(event: MessageEvent, owui: OWUIUserClient,
                        adapter: BasePlatformAdapter) -> str | None:
    """The text to send the model, or None for a type we do not handle.

    Returns the sentinel _FAILED when the type IS handled but this particular
    message could not be turned into text. That distinction matters: an
    unhandled type and a broken voice memo need different sentences.
    """
    if event.message_type is MessageType.TEXT:
        return event.text
    if event.message_type is MessageType.VOICE:
        return await _transcribe_voice(event, owui, adapter)
    return None


def voice_prompt(transcript: str) -> str:
    """Mark a transcript as speech so the model answers like it was spoken.

    Without this the model reads a transcription artifact as if it were typed,
    and hedges about the odd punctuation instead of just answering.
    """
    return f'[The user sent a voice message. Here is what they said: "{transcript}"]'


async def _transcribe_voice(event: MessageEvent, owui: OWUIUserClient,
                            adapter: BasePlatformAdapter) -> str:
    """Download the clip, transcribe it, and always remove the temp file."""
    if not event.media_ref:
        log.warning("gateway: a voice event arrived with no media reference")
        return _FAILED

    # Refused before the download, not after. The duration arrives in the
    # inbound payload, so a ten minute clip costs us nothing to reject; waiting
    # for the byte count would mean fetching the whole thing first.
    if event.media_duration and event.media_duration > MAX_VOICE_SECONDS:
        return _TOO_LONG

    # Transcription is the slow part of a voice turn, so the indicator goes up
    # here rather than after it.
    await adapter.send_typing(event.source.chat_id)

    path = None
    try:
        path = await adapter.download_media(event.media_ref)
        transcript = await owui.transcribe(path)
    except (ClipTooLarge, ValueError):
        # ClipTooLarge is the adapter's own size guard (Telegram's
        # download_media). ValueError is kept too, belt and braces, for any
        # adapter that has not been migrated to the specific exception yet.
        # A distinct sentence, because "too long" is something the sender can
        # act on and "it broke" is not.
        return _TOO_LONG
    except Exception as e:                              # noqa: BLE001
        log.warning("gateway: transcription failed: %r", e)
        return _FAILED
    finally:
        if path:
            try:
                os.unlink(path)
            except OSError:
                log.warning("gateway: could not remove the temp clip %s", path)

    if not transcript.strip():
        return _FAILED
    return voice_prompt(transcript)


async def _say(adapter: BasePlatformAdapter, chat_id: str, text: str) -> str:
    await adapter.send_chunked(chat_id, text)
    return text


async def _stop_typing_quietly(adapter: BasePlatformAdapter, chat_id: str) -> None:
    """Clear the typing indicator without ever raising.

    This runs in a finally, and an exception raised in a finally replaces any
    pending return. The answer has already been delivered by then, so a failure
    here would report a failure for a call that actually worked.
    """
    try:
        await adapter.stop_typing(chat_id)
    except Exception:                                  # noqa: BLE001
        log.warning("gateway: could not clear the typing indicator on %s",
                    chat_id, exc_info=True)
