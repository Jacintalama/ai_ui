"""Which Open WebUI chat a platform conversation writes to.

Continuity is not a mechanism we maintain, it is the chat id. Because the
mapping points at a REAL Open WebUI chat, the conversation shows up in the
user's sidebar, is searchable, and feeds the Brain like any other chat, with
nothing of ours that can drift out of sync.
"""
import logging
import time
import uuid

from gateway.owui import OWUIError

log = logging.getLogger(__name__)


def title_from(text: str) -> str:
    """A chat title from the opening message. Sidebar-sized, one line."""
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return "New chat"
    return cleaned[:60]


def history_messages(chat: dict, limit: int = 20) -> list[dict]:
    """The prior turns, reduced to what a completion call needs.

    Capped because the whole transcript grows without bound and the model call
    pays for every token of it. The full history stays in Open WebUI.
    """
    out: list[dict] = []
    for msg in (chat.get("messages") or []):
        if not isinstance(msg, dict):
            continue
        role, content = msg.get("role"), msg.get("content")
        if not role or not isinstance(content, str) or not content.strip():
            continue
        out.append({"role": role, "content": content})
    # limit <= 0 means "send none", not "send everything". out[-0:] is the
    # WHOLE list, not none, so that case has to be handled explicitly or an
    # operator setting GATEWAY_HISTORY_TURNS=0 to mean "no history" would send
    # the entire transcript to the model instead.
    if limit <= 0:
        return []
    return out[-limit:]


def append_turn(chat: dict, user_text: str, assistant_text: str,
                model: str) -> dict:
    """Return a copy of `chat` with one user and one assistant message added.

    Writes BOTH representations Open WebUI keeps: the flat `messages` list and
    the `history` map keyed by id with `currentId` on the newest leaf. Writing
    only one produces a chat that exists in the sidebar and renders empty.
    """
    history = dict(chat.get("history") or {})
    # Copy each entry, not just the containers. A shallow copy would leave the
    # caller's own message dicts reachable through the returned object, so an
    # edit to one would reach back into the other, and the "does not mutate its
    # input" promise would only hold for the containers.
    hist_msgs = {
        key: (dict(value) if isinstance(value, dict) else value)
        for key, value in (history.get("messages") or {}).items()
    }
    messages = [
        dict(m) if isinstance(m, dict) else m
        for m in (chat.get("messages") or [])
    ]
    parent_id = history.get("currentId")
    stamp = int(time.time())

    user_id, asst_id = str(uuid.uuid4()), str(uuid.uuid4())
    user_msg = {
        "id": user_id, "parentId": parent_id, "childrenIds": [asst_id],
        "role": "user", "content": user_text, "timestamp": stamp,
    }
    asst_msg = {
        "id": asst_id, "parentId": user_id, "childrenIds": [],
        "role": "assistant", "content": assistant_text, "timestamp": stamp,
        "model": model, "modelName": model, "modelIdx": 0, "done": True,
    }
    if parent_id and parent_id in hist_msgs:
        prev = hist_msgs[parent_id]
        prev["childrenIds"] = list(prev.get("childrenIds") or []) + [user_id]
        # The same message lives in both structures and Open WebUI keeps them in
        # step: real chats there carry childrenIds on n-1 of n flat entries.
        # Updating only the map would leave every earlier turn's flat entry
        # permanently stale.
        for index, existing in enumerate(messages):
            if isinstance(existing, dict) and existing.get("id") == parent_id:
                messages[index] = prev
                break
    hist_msgs[user_id] = user_msg
    hist_msgs[asst_id] = asst_msg

    out = dict(chat)
    out["messages"] = messages + [user_msg, asst_msg]
    out["history"] = {"messages": hist_msgs, "currentId": asst_id}
    if not out.get("models"):
        out["models"] = [model]
    return out


async def get_or_create_chat(tasks, owui, platform: str, chat_id: str,
                             owui_user_id: str, first_text: str,
                             model: str) -> tuple[str, dict]:
    """Resolve this conversation to an Open WebUI chat, creating one if needed.

    Recovers in two situations that would otherwise wedge the conversation
    forever, leaving a database edit as the only fix:

    - The user deleted the mapped chat in the browser. Upstream Open WebUI's
      `GET /api/v1/chats/{id}` calls get_chat_by_id_and_user_id, which raises
      401, not 404, whenever the chat is absent OR belongs to someone else.
      That looks like an auth bug to a reader who doesn't know it, so both
      statuses are treated the same: the chat is gone, start a new one.
    - The platform account was re-paired to a different Open WebUI user (A
      unlinks, B links the same Telegram account). The stored session still
      names A as the owner, so a mismatch between the stored owui_user_id and
      the current one is treated exactly like no session at all. This is the
      only defense on OUR side against a cross-user chat read; without it,
      the sole thing stopping B from reading A's chat is Open WebUI's own
      ownership check.
    """
    stored = await tasks.gateway_get_session(platform, chat_id)
    owui_chat_id = (stored or {}).get("owui_chat_id")
    stored_owner = (stored or {}).get("owui_user_id")

    if owui_chat_id:
        if stored_owner != owui_user_id:
            log.warning(
                "gateway: session %s/%s pointed at owui_user_id=%s but the "
                "current user is %s; starting a new chat instead of reading "
                "theirs (likely a re-paired account)",
                platform, chat_id, stored_owner, owui_user_id)
        else:
            try:
                return owui_chat_id, await owui.get_chat(owui_chat_id)
            except OWUIError as e:
                if e.status not in (401, 404):
                    raise
                log.info("gateway: mapped chat %s is gone, starting a new one",
                         owui_chat_id)

    new_id = await owui.create_chat(title_from(first_text), model)
    await tasks.gateway_put_session(platform, chat_id, new_id, owui_user_id)
    return new_id, await owui.get_chat(new_id)
