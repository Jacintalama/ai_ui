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
from gateway import agent_router
from gateway import approvals
from gateway import commands as gateway_commands
from gateway.base import BasePlatformAdapter
from gateway.events import MessageEvent, MessageType, SessionSource
from gateway.owui import OWUIError, OWUIToolCallError, OWUIUserClient
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
# Distinguished from MODEL_DOWN: the model did answer, in the sense that it
# tried to call a tool, but there is no tool loop on this path to run it. A
# retry would only produce the same result, so this says what happened
# instead of inviting one.
AGENT_TOOL_CALL = "This agent tried to use one of its tools. It can't do that here yet."
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
TURN_EMPTY = ("The agent finished without saying anything. Ask it again and "
              "it may have more to say.")
PINNED = ("Right, I'll use %s for this conversation. Say \"stop using that\" "
          "to go back.")
UNPINNED = "Back to normal. I'll pick whichever agent fits each message."
PIN_GONE = ("%s is gone, so I answered normally. Ask me again if you want a "
            "different one.")
PINNED_UNSAVED = ("I'll use %s for now, but I could not save that, so it may "
                  "not last past this message.")
UNPINNED_UNSAVED = ("I could not clear that just now, so the agent may come "
                    "back. Try again in a moment.")

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
    except OWUIToolCallError as e:
        # Checked before the plainer OWUIError below: this is a subclass of
        # it, and except clauses match in order.
        log.warning("gateway: agent tried to call a tool (%s): %s",
                    e.status, e.message)
        return await _say(adapter, src.chat_id, AGENT_TOOL_CALL)
    except OWUIError as e:
        log.warning("gateway: open-webui failed (%s): %s", e.status, e.message)
        return await _say(adapter, src.chat_id, MODEL_DOWN)
    except Exception:                                  # noqa: BLE001
        log.exception("gateway: unexpected failure handling a %s message",
                      src.platform)
        return await _say(adapter, src.chat_id, UNEXPECTED)
    finally:
        await _stop_typing_quietly(adapter, src.chat_id)


async def _read_pin(key: str) -> dict | None:
    """The pinned agent for this conversation, or None. Never raises."""
    try:
        pin = await _tasks.get_state(key)
    except Exception:                                  # noqa: BLE001
        log.warning("gateway: could not read the agent pin", exc_info=True)
        return None
    return pin if isinstance(pin, dict) and pin.get("id") else None


async def _read_pending(src: SessionSource) -> dict | None:
    """The held approval for this conversation, or None. Never raises.

    Fails open exactly like _read_pin: a state store outage must not stop the
    bot answering, and the cost of missing a held turn is that the person
    repeats themselves.
    """
    try:
        held = await _tasks.get_state(approvals.pending_key(
            src.platform, src.chat_id))
    except Exception:                                  # noqa: BLE001
        log.warning("gateway: could not read a held approval", exc_info=True)
        return None
    return held if isinstance(held, dict) and held.get("calls") else None


async def _clear_pending(src: SessionSource) -> None:
    try:
        await _tasks.delete_state(approvals.pending_key(
            src.platform, src.chat_id))
    except Exception:                                  # noqa: BLE001
        log.warning("gateway: could not clear a held approval", exc_info=True)


async def _store_pending(src: SessionSource, pending: dict, agent: dict,
                         chat_id: str, text: str) -> bool:
    """Keep the held turn. Returns whether it was actually kept."""
    try:
        await _tasks.set_state(
            approvals.pending_key(src.platform, src.chat_id),
            {"agent_id": pending.get("agent_id") or agent["id"],
             "agent_name": agent.get("name") or agent["id"],
             "user_email": pending.get("user_email"),
             "calls": pending.get("calls") or [],
             "conversation": pending.get("conversation") or [],
             # Carried so the transcript still gets written when the turn
             # finishes, or an approved turn vanishes from the sidebar.
             "chat_id": chat_id, "user_text": text},
            ttl_seconds=approvals.PENDING_TTL_SECONDS)
        return True
    except Exception:                                  # noqa: BLE001
        log.warning("gateway: could not hold an approval", exc_info=True)
        return False


async def _resume_pending(adapter: BasePlatformAdapter, src: SessionSource,
                          held: dict, approved: bool, user_email: str,
                          owui: OWUIUserClient) -> str:
    """Pick a held turn back up. Deletes the record first, always."""
    # Deleted BEFORE anything runs. A second "yes" arriving while this one is
    # in flight would otherwise send the same email twice.
    await _clear_pending(src)
    if held.get("user_email") != user_email:
        # The key is per chat, so in a group, or after a re-link, the person
        # answering is not necessarily the person who was asked.
        return await _say(adapter, src.chat_id, approvals.NOT_YOURS)

    await adapter.send_typing(src.chat_id)
    out = await _tasks.agent_turn_resume(
        user_email=user_email, agent_id=held["agent_id"],
        conversation=held.get("conversation") or [],
        calls=held.get("calls") or [], approved=approved)

    agent = {"id": held["agent_id"], "name": held.get("agent_name")}
    chat_id = held.get("chat_id")
    chat = None
    if chat_id:
        try:
            chat = await owui.get_chat(chat_id)
        except Exception:                              # noqa: BLE001
            log.exception("gateway: could not fetch the transcript for chat "
                          "%s; delivering the answer anyway", chat_id)
    return await _deliver_turn(adapter, src, out, agent, chat_id,
                               held.get("user_text") or "", owui, chat)


async def _choose_agent(owui: OWUIUserClient, text: str,
                        src: SessionSource) -> tuple[dict | None, str | None, str | None]:
    """Returns (agent, reply, notice).

    reply  means the message was a setting: answer with this and call no model.
    notice means say this alongside the model's answer.

    Never raises. Listing models, routing, and the state store can all fail,
    and none of them is a reason to leave somebody staring at silence.
    """
    key = agent_router.pin_key(src.platform, src.chat_id)

    # Read up front: a state failure here reads as "no pin" (never raises),
    # which is the fail-open choice for everything below it, including the
    # unpin check right after.
    pin = await _read_pin(key)

    # Clearing a pin needs no candidate list, so this is checked before
    # list_models runs. Otherwise an Open WebUI outage would make "stop using
    # that" unreachable: the message would fall through to the default model
    # and the pin would stay in the store, unclearable until listing recovers.
    # Only short circuits when there is actually a pin to clear: "back to
    # normal" and the like are plausible things to say for real, and with no
    # pin set there is nothing to clear, so swallowing the message here would
    # mean it never gets answered. Fall through and treat it as an ordinary
    # message instead.
    if pin and agent_router.is_unpin_request(text):
        cleared = await _forget_pin(key)
        return None, (UNPINNED if cleared else UNPINNED_UNSAVED), None

    try:
        models = await owui.list_models()
        cands = agent_router.candidates(models)
    except Exception:                                  # noqa: BLE001
        log.warning("gateway: could not list the caller's models, using the "
                    "default model", exc_info=True)
        return None, None, None

    asked = agent_router.match_pin_request(text, cands)
    if asked:
        try:
            await _tasks.set_state(key, {"id": asked["id"],
                                         "name": asked["name"]})
        except Exception:                              # noqa: BLE001
            log.warning("gateway: could not save the agent pin", exc_info=True)
            return asked, PINNED_UNSAVED % asked["name"], None
        return asked, PINNED % asked["name"], None

    # Saying a name in a sentence beats the sticky pin for this one message.
    # Pinned to Jack and you write "hi mary, any news"? You meant Mary, and the
    # pin stays where it was for the message after.
    spoken = agent_router.match_mention(text, cands)
    if spoken:
        return spoken, None, None

    if pin:
        # It may have been deleted on the web since it was pinned here. Return
        # the matching CANDIDATE, not the stored pin: the candidate always
        # carries the agent's current name, so a rename since the pin was
        # made shows up in the "via" tag instead of the stale name captured
        # at pin time. It also always has a name, where a pin row might not,
        # so this can never raise on agent["name"] after the model has
        # already answered.
        match = next((c for c in cands if c["id"] == pin["id"]), None)
        if match:
            return match, None, None
        # A pin naming a deleted agent already produces its own notice below,
        # so whether the cleanup delete itself succeeds is not reported here.
        await _forget_pin(key)
        return None, None, PIN_GONE % pin.get("name", "That agent")

    chosen = await agent_router.pick(
        owui, text, cands, settings.gateway_router_model)
    return chosen, None, None


async def _forget_pin(key: str) -> bool:
    """Clear a pin, never raising. Returns whether the delete succeeded.

    A pin we cannot clear is not worth a failed reply, but the caller still
    needs to know so it can tell the truth about what happened instead of
    promising something that did not happen.
    """
    try:
        await _tasks.delete_state(key)
    except Exception:                                  # noqa: BLE001
        log.warning("gateway: could not clear the agent pin", exc_info=True)
        return False
    return True


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

    email = identity.get("email")
    if not email:
        log.error("gateway: resolve said linked but sent no email")
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

    # Checked before commands so that "/help" during a pending approval is
    # not swallowed: it is not a verdict, so it drops the held action and
    # then runs as the command it is.
    held = await _read_pending(src)
    drop_notice = None
    if held:
        answer_given = approvals.verdict(text)
        if answer_given is None:
            await _clear_pending(src)
            drop_notice = approvals.DROPPED
        else:
            return await _resume_pending(
                adapter, src, held, answer_given, email, owui)
    elif approvals.verdict(text) is not None:
        # A bare "yes" or "no" with nothing held, most often the TTL beating
        # the reply to it, has nothing left to confirm. Sending it to the
        # model gets an answer to a question that was never asked; this says
        # plainly that there is nothing waiting.
        return await _say(adapter, src.chat_id, approvals.EXPIRED)

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
            return await _say(adapter, src.chat_id, _with_notice(drop_notice, reply))

    await adapter.send_typing(src.chat_id)

    agent, reply, notice = await _choose_agent(owui, text, src)

    # A pin request is a setting, not a question. Answering it with a model
    # would spend a call and a turn of history saying "ok".
    if reply:
        return await _say(adapter, src.chat_id, _with_notice(drop_notice, reply))

    # Merged once, here: a dropped approval from earlier in this same message
    # rides along with whatever _choose_agent has to say, so it reaches the
    # person exactly once instead of being said twice or lost.
    notice = "\n\n".join(n for n in (drop_notice, notice) if n) or None

    model = agent["id"] if agent else settings.gateway_model

    chat_id, chat = await get_or_create_chat(
        _tasks, owui, src.platform, src.chat_id,
        owui_user_id, text, model)

    messages = history_messages(chat, settings.gateway_history_turns)
    messages.append({"role": "user", "content": text})
    if agent:
        # An agent goes through the tasks service, which owns the tool loop.
        # Open WebUI does not run tools for an API caller, so calling it
        # directly here is what produced "It can't do that here yet".
        out = await _tasks.agent_turn(
            user_email=email, agent_id=agent["id"],
            messages=messages)
        return await _deliver_turn(adapter, src, out, agent, chat_id, text,
                                   owui, chat, notice=notice)

    answer = await owui.chat_completion(messages, model, chat_id=chat_id)

    # Persist before delivering, but never let a persist failure swallow a
    # good answer: the person is waiting and the answer already exists.
    try:
        await owui.update_chat(
            chat_id, append_turn(chat, text, answer, model))
    except Exception:                              # noqa: BLE001
        log.exception("gateway: could not write the transcript to chat %s; "
                      "delivering the answer anyway", chat_id)

    # Tagged on delivery, not in the transcript. The stored turn already
    # records the model that produced it, and the web UI shows that, so
    # writing the tag into the text too would duplicate it there.
    # A notice rides along with the answer rather than replacing it: the person
    # asked a real question and still deserves it answered.
    if notice:
        answer = "%s\n\n%s" % (notice, answer)

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


def _with_notice(notice: str | None, text: str) -> str:
    """Keep a notice attached to whatever we end up saying.

    A dropped approval has to be reported on EVERY path out of _run, not
    just the one that reaches the model. Losing it means somebody's held
    action disappeared without a word.
    """
    return "%s\n\n%s" % (notice, text) if notice else text


async def _deliver_turn(adapter: BasePlatformAdapter, src: SessionSource,
                        out: dict, agent: dict, chat_id: str | None,
                        text: str, owui, chat,
                        notice: str | None = None) -> str:
    """Say what came back from an agent turn, held or finished.

    Notes ride along with the answer rather than replacing it: a refused
    write that nobody is told about is the worst outcome, because the person
    believes it happened.

    `notice` is prepended to whatever gets said, on every exit, because this
    function is the one that actually calls `_say`. Prepending it to a
    RETURN VALUE instead would only reach the caller, and none of this
    function's chat-platform callers read the return value; they already
    saw the message go out.
    """
    pending = out.get("pending")
    if isinstance(pending, dict) and pending.get("calls"):
        kept = await _store_pending(src, pending, agent, chat_id or "", text)
        question = approvals.prompt(agent.get("name") or agent["id"],
                                    pending["calls"])
        if not kept:
            # Never ask a question that cannot be answered.
            question = (question + "\n\n" + "I could not hold this, so the "
                        "answer may not reach me. Ask again if nothing "
                        "happens.")
        return await _say(adapter, src.chat_id, _with_notice(notice, question))

    answer = (out.get("answer") or "").strip()
    notes = [n for n in (out.get("notes") or []) if isinstance(n, str)]
    if notes:
        note_text = "\n".join(notes)
        answer = (answer + "\n\n" + note_text) if answer else note_text
    # Nothing on this path may fail silently.
    answer = answer or TURN_EMPTY

    if owui is not None and chat is not None and chat_id:
        # Persist before delivering, but never let a persist failure swallow
        # a good answer: the person is waiting and the answer already exists.
        try:
            await owui.update_chat(
                chat_id, append_turn(chat, text, answer, agent["id"]))
        except Exception:                              # noqa: BLE001
            log.exception("gateway: could not write the transcript to chat "
                          "%s; delivering the answer anyway", chat_id)

    name = agent.get("name") or agent["id"]
    return await _say(
        adapter, src.chat_id,
        _with_notice(notice, "%s:\n%s" % (name, answer)))


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
