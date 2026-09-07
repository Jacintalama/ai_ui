"""Saved agent-panel conversations, and the per-user working session.

Split out of routes_agent_chat so that module stays about HTTP and the round,
and so tests can swap the whole store for a dict the way
tests/test_routes_fusion_page.py does.

The in-memory session is the working copy; the row is the durable one. This
mirrors routes_fusion_page, which has run that arrangement in production since
2026-07-15.
"""
import json
import logging
import time
import uuid
from dataclasses import dataclass, field

from sqlalchemy import text

from db import session

log = logging.getLogger(__name__)

#: Drop a working session idle longer than this. Same value as the Fusion page.
SESSION_IDLE_SECONDS = 2 * 60 * 60


@dataclass
class RoomSession:
    """One person's working copy of an agent-panel conversation."""

    messages: list[dict] = field(default_factory=list)
    #: Notes standing in for the turns that no longer fit the budget. The
    #: room is permanent, so an agent has to keep knowing what was agreed
    #: this morning after the words themselves have been folded away.
    summary: str = ""
    #: How many turns the summary already covers, so the same ones are not
    #: summarised again on every message.
    summarised_upto: int = 0
    #: agent_id -> the held payload from routes_agent_turn._pending_payload.
    #: Server side only: it carries the held conversation and the owner's
    #: email, neither of which may ever reach a browser.
    pending: dict[str, dict] = field(default_factory=dict)
    streaming: bool = False
    last_used: float = field(default_factory=time.time)
    #: The saved conversation this session is working on, or None before the
    #: first message has been sent.
    chat_id: str | None = None
    #: Bumped on New chat. A running round captures it and refuses to write
    #: back when it changed, so an abandoned round cannot be stapled onto a
    #: conversation the person has since replaced.
    generation: int = 0


_SESSIONS: dict[str, RoomSession] = {}


def sweep(now: float | None = None) -> None:
    """Drop sessions idle longer than the TTL. Called lazily on access."""
    now = time.time() if now is None else now
    stale = [k for k, s in _SESSIONS.items()
             if now - s.last_used > SESSION_IDLE_SECONDS]
    for k in stale:
        del _SESSIONS[k]


def get_session(email: str) -> RoomSession:
    sweep()
    s = _SESSIONS.get(email)
    if s is None:
        s = RoomSession()
        _SESSIONS[email] = s
    s.last_used = time.time()
    return s


def title_from(message: str) -> str:
    """A conversation's name in the list, taken from its opening message."""
    one_line = " ".join((message or "").split())
    if not one_line:
        return "New chat"
    if len(one_line) <= 48:
        return one_line
    return one_line[:47].rstrip() + "…"


async def create_chat(email: str, title: str, s: RoomSession) -> str:
    chat_id = str(uuid.uuid4())
    async with session() as db:
        await db.execute(
            text("INSERT INTO tasks.agent_chats "
                 "(id, user_email, title, messages, summary, pending) "
                 "VALUES (:id, :email, :title, CAST(:messages AS JSONB), "
                 ":summary, CAST(:pending AS JSONB))"),
            {"id": chat_id, "email": email, "title": title,
             "messages": json.dumps(s.messages), "summary": s.summary,
             "pending": json.dumps(s.pending)})
        await db.commit()
    return chat_id


async def save_chat(email: str, s: RoomSession) -> None:
    """Write the session back to its row.

    Scoped by user_email, so a known conversation id alone is never enough to
    write into somebody else's conversation.
    """
    if not s.chat_id:
        return
    async with session() as db:
        await db.execute(
            text("UPDATE tasks.agent_chats "
                 "SET messages = CAST(:messages AS JSONB), "
                 "summary = :summary, "
                 "pending = CAST(:pending AS JSONB), updated_at = now() "
                 "WHERE id = :id AND user_email = :email"),
            {"messages": json.dumps(s.messages), "summary": s.summary,
             "pending": json.dumps(s.pending), "id": s.chat_id,
             "email": email})
        await db.commit()


async def newest_chat(email: str) -> dict | None:
    """This person's conversation.

    The panel keeps one permanent room rather than a list, so there is only
    ever one row that matters. Ordered anyway, because a database that once
    held two should hand back the one still being used rather than whichever
    it happened to find.
    """
    async with session() as db:
        row = (await db.execute(
            text("SELECT id, title, messages, summary, pending "
                 "FROM tasks.agent_chats WHERE user_email = :email "
                 "ORDER BY updated_at DESC LIMIT 1"),
            {"email": email})).mappings().first()
    return dict(row) if row else None


async def list_chats(email: str) -> list[dict]:
    async with session() as db:
        rows = (await db.execute(
            text("SELECT id, title FROM tasks.agent_chats "
                 "WHERE user_email = :email ORDER BY updated_at DESC LIMIT 100"),
            {"email": email})).mappings().all()
    return [dict(r) for r in rows]


async def load_chat(email: str, chat_id: str) -> dict | None:
    async with session() as db:
        row = (await db.execute(
            text("SELECT id, title, messages, summary, pending "
                 "FROM tasks.agent_chats WHERE id = :id AND user_email = :email"),
            {"id": chat_id, "email": email})).mappings().first()
    return dict(row) if row else None


async def delete_chat(email: str, chat_id: str) -> None:
    async with session() as db:
        await db.execute(
            text("DELETE FROM tasks.agent_chats "
                 "WHERE id = :id AND user_email = :email"),
            {"id": chat_id, "email": email})
        await db.commit()
