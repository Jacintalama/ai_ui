"""MessageEvent in, reply sent. The only flow, shared by every platform.

The governing rule here is the opposite of the rest of this codebase. Build
post-processing fails open because nobody is watching. Here somebody is staring
at a chat window waiting, so NOTHING may fail silently: every path ends in a
sentence the person can read.
"""
import logging

from clients.tasks import TasksAPIError, TasksClient
from config import settings
from gateway.base import BasePlatformAdapter
from gateway.events import MessageEvent, MessageType
from gateway.owui import OWUIError, OWUIUserClient
from gateway.pairing import pairing_message
from gateway.sessions import append_turn, get_or_create_chat, history_messages

log = logging.getLogger(__name__)

GROUP_REFUSAL = (
    "I only work in direct messages for now. Message me privately and I'll "
    "answer there."
)
TASKS_DOWN = "I can't reach my memory right now. Try again in a moment."
MODEL_DOWN = "The model didn't answer just now. Try again in a moment."
UNEXPECTED = "Something went wrong on my side. Try again in a moment."
UNSUPPORTED_TYPE = "I can only read text and voice messages right now."

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

    # Refused before anything else runs. The Brain is injected into every model
    # call, so answering in a group would print one person's private memory to
    # the whole room, with no warning and no way to know in advance.
    if src.chat_type != "dm":
        return await _say(adapter, src.chat_id, GROUP_REFUSAL)

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
    owui = _owui_factory(token)

    text = await _resolve_text(event, owui, adapter)
    if text is None:
        return await _say(adapter, src.chat_id, UNSUPPORTED_TYPE)
    if not text.strip():
        # A sticker, an empty edit, a stray keystroke. Answering would be noise.
        return ""

    await adapter.send_typing(src.chat_id)
    chat_id, chat = await get_or_create_chat(
        _tasks, owui, src.platform, src.chat_id,
        identity["owui_user_id"], text, settings.gateway_model)

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

    Voice is filled in by the transcription task; everything except TEXT falls
    through to None until then.
    """
    if event.message_type is MessageType.TEXT:
        return event.text
    return None


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
