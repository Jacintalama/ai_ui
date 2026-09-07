# Agents Chat Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a round-table chat panel on the AI Agents page where every agent in the room answers your message in its own bubble, arriving live.

**Architecture:** A dedicated surface inside the tasks service, modelled directly on the Fusion chat page (`routes_fusion_page.py`). The browser posts a message, then opens one SSE stream; the server walks the room, calls `_turn_for` per agent in process, and pushes each finished answer as its own event. Conversations live in a new `tasks.agent_chats` table. Nothing reads or writes Open WebUI's chat.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy async + Postgres, `sse_starlette.EventSourceResponse`, vendored HTMX plus its SSE extension, server-rendered HTML fragments, pytest.

**Spec:** `docs/superpowers/specs/2026-09-07-agents-chat-panel-design.md`

## Global Constraints

Every task's requirements implicitly include these.

- **Agents run one at a time, never in parallel.** A turn can run tools and this box has 3.8GB of RAM. This is already the rule in `/agents/chat`.
- **The round's history is built once, before the first agent runs, and every agent receives that same content.** One agent's answer from this round must never appear in another agent's input this round. Feeding agents each other's labelled replies is what taught the model to invent whole exchanges between agents (see `_turn_for`'s docstring, `routes_agent_turn.py:474`).
- **Every database read and write is scoped by `user_email`.** Knowing a conversation id is never enough to reach it.
- **Nothing in this feature touches Open WebUI's `chat` table, the pipes, or `/agents/speak`.**
- **Every HTML fragment that can travel over SSE must be a single line with no literal newline in it.** A newline is a `data:` field separator, so a multi-line fragment arrives cut into pieces.
- **Migrations must be idempotent.** `db.py` re-runs every migration on each startup.
- **Routes live under the `/tasks` prefix**, which is already routed to this service end to end. No gateway, Caddy or compose change is needed anywhere in this plan.
- **Room cap is 4 agents.** Agents run serially, so a room of ten is a ten-minute round.
- `git add` named paths only, never `-A`: this repo carries an untracked `apps/` tree.
- No Claude, Anthropic or AI attribution in any commit message. No `Co-Authored-By` trailer.
- No em dashes or en dashes in any copy a person reads, including UI strings.
- Running `python -m pytest tests/ -q` locally produces roughly 130 pre-existing errors from the `db_session` fixture, because there is no local Postgres. They say `ERROR at setup` and are not your change. Run only the files this plan names.

---

### Task 1: Storage

The table and the per-user working session. Nothing HTTP.

**Files:**
- Create: `mcp-servers/tasks/migrations/047_agent_chats.sql`
- Create: `mcp-servers/tasks/agent_chat_store.py`
- Test: `mcp-servers/tasks/tests/test_agent_chat_store.py`

**Interfaces:**
- Consumes: `db.session` (existing async session factory).
- Produces:
  - `RoomSession` dataclass with fields `messages: list[dict]`, `room: list[str]`, `pending: dict[str, dict]`, `streaming: bool`, `last_used: float`, `chat_id: str | None`, `generation: int`
  - `get_session(email: str) -> RoomSession`
  - `sweep(now: float | None = None) -> None`
  - `title_from(message: str) -> str`
  - `create_chat(email: str, title: str, s: RoomSession) -> str` (async)
  - `save_chat(email: str, s: RoomSession) -> None` (async)
  - `list_chats(email: str) -> list[dict]` (async)
  - `load_chat(email: str, chat_id: str) -> dict | None` (async)
  - `delete_chat(email: str, chat_id: str) -> None` (async)
  - `SESSION_IDLE_SECONDS`, `_SESSIONS`

- [ ] **Step 1: Write the failing test**

Create `mcp-servers/tasks/tests/test_agent_chat_store.py`:

```python
"""The panel's working session and its saved conversations.

Only the in-memory half runs here. The SQL half needs a real Postgres and is
verified in the container: this repo's destructive DB tests once wiped nine
production projects, so they are not run locally.
"""
import time

import agent_chat_store as store


def test_a_session_is_private_to_one_person():
    store._SESSIONS.clear()
    a = store.get_session("a@example.com")
    b = store.get_session("b@example.com")
    a.room.append("agent-a")
    a.messages.append({"role": "user", "content": "hi"})
    assert b.room == []
    assert b.messages == []


def test_get_session_returns_the_same_object_for_one_person():
    store._SESSIONS.clear()
    first = store.get_session("same@example.com")
    first.room.append("agent-a")
    assert store.get_session("same@example.com").room == ["agent-a"]


def test_sweep_drops_only_the_idle_session():
    store._SESSIONS.clear()
    store.get_session("fresh@example.com")
    stale = store.get_session("stale@example.com")
    stale.last_used = time.time() - store.SESSION_IDLE_SECONDS - 1
    store.sweep()
    assert "fresh@example.com" in store._SESSIONS
    assert "stale@example.com" not in store._SESSIONS


def test_title_from_collapses_whitespace_and_shortens():
    assert store.title_from("  hello   team  ") == "hello team"
    assert store.title_from("") == "New chat"
    assert store.title_from("   ") == "New chat"
    long_title = store.title_from("x" * 100)
    assert len(long_title) == 48
    assert long_title.endswith("…")
```

- [ ] **Step 2: Run the test to verify it fails**

Run from `mcp-servers/tasks/`:

```bash
python -m pytest tests/test_agent_chat_store.py -q
```

Expected: collection error, `ModuleNotFoundError: No module named 'agent_chat_store'`.

- [ ] **Step 3: Write the migration**

Create `mcp-servers/tasks/migrations/047_agent_chats.sql`:

```sql
-- 047: saved conversations for the agent chat panel on the AI Agents page.
--
-- Its own table, deliberately nothing to do with Open WebUI's chat. Borrowing
-- that chat is what the previous attempt did, and it failed because Open WebUI
-- renders message.output rather than message.content. The panel draws its own
-- messages, so it needs its own store.
--
-- messages/room/pending are JSONB because a conversation is only ever read and
-- written as a unit, the same reasoning as 032_fusion_chats.
--
-- `pending` holds an approval question nobody has answered yet, keyed by agent
-- id, so a service restart does not turn a waiting Yes/No into a dead button.
--
-- Idempotent: db.py re-runs every migration on each startup.
CREATE TABLE IF NOT EXISTS tasks.agent_chats (
  id         TEXT PRIMARY KEY,
  user_email TEXT NOT NULL,
  title      TEXT NOT NULL DEFAULT 'New chat',
  messages   JSONB NOT NULL DEFAULT '[]'::jsonb,
  room       JSONB NOT NULL DEFAULT '[]'::jsonb,
  pending    JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The panel's only list query: this person's conversations, newest first.
CREATE INDEX IF NOT EXISTS agent_chats_user_updated
  ON tasks.agent_chats (user_email, updated_at DESC);
```

- [ ] **Step 4: Write the store**

Create `mcp-servers/tasks/agent_chat_store.py`:

```python
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
    #: Agent ids in speaking order. The room, not every agent they own.
    room: list[str] = field(default_factory=list)
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
                 "(id, user_email, title, messages, room, pending) "
                 "VALUES (:id, :email, :title, CAST(:messages AS JSONB), "
                 "CAST(:room AS JSONB), CAST(:pending AS JSONB))"),
            {"id": chat_id, "email": email, "title": title,
             "messages": json.dumps(s.messages), "room": json.dumps(s.room),
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
                 "room = CAST(:room AS JSONB), "
                 "pending = CAST(:pending AS JSONB), updated_at = now() "
                 "WHERE id = :id AND user_email = :email"),
            {"messages": json.dumps(s.messages), "room": json.dumps(s.room),
             "pending": json.dumps(s.pending), "id": s.chat_id,
             "email": email})
        await db.commit()


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
            text("SELECT id, title, messages, room, pending "
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
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
python -m pytest tests/test_agent_chat_store.py -q
```

Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add mcp-servers/tasks/agent_chat_store.py \
        mcp-servers/tasks/migrations/047_agent_chats.sql \
        mcp-servers/tasks/tests/test_agent_chat_store.py
git commit -m "Give the agent chat panel its own conversations table and session"
```

---

### Task 2: The HTML fragments

Every piece of markup the panel renders. Pure functions, no I/O, so they are cheap to test exactly.

**Files:**
- Create: `mcp-servers/tasks/agent_chat_render.py`
- Test: `mcp-servers/tasks/tests/test_agent_chat_render.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `esc(s: str) -> str`
  - `user_bubble(text: str) -> str`
  - `agent_bubble(name: str, content: str) -> str`
  - `approval_bubble(name: str, agent_id: str, calls: list[dict]) -> str`
  - `working(name: str) -> str`
  - `note(text: str) -> str`
  - `stream_block() -> str`
  - `empty_thread() -> str`
  - `chips(agents: list[dict], room: list[str]) -> str`
  - `chat_list(chats: list[dict], active_id: str | None) -> str`
  - `thread(messages: list[dict]) -> str`

- [ ] **Step 1: Write the failing test**

Create `mcp-servers/tasks/tests/test_agent_chat_render.py`:

```python
"""The panel's markup.

Two rules here are load-bearing rather than cosmetic. Every fragment is one
line, because some of them travel as SSE data where a newline is a field
separator. And an approval bubble shows the tool call only: the held
conversation and the owner's email stay on the server.
"""
import agent_chat_render as render

CALLS = [{"function": {"name": "send_email",
                       "arguments": '{"to": "boss@example.com"}'}}]


def _fragments():
    return [
        render.user_bubble("hi team"),
        render.agent_bubble("Ada", "hello"),
        render.approval_bubble("Ada", "agent-research-assistant-0001", CALLS),
        render.working("Ada"),
        render.note("something happened"),
        render.stream_block(),
        render.empty_thread(),
        render.chips([{"id": "agent-a", "name": "Ada"}], ["agent-a"]),
        render.chat_list([{"id": "c1", "title": "About the invoices"}], "c1"),
        render.thread([{"role": "user", "content": "hi"},
                       {"role": "assistant", "agent_name": "Ada",
                        "content": "hello"}]),
    ]


def test_no_fragment_contains_a_newline():
    for fragment in _fragments():
        assert "\n" not in fragment, fragment
        assert "\r" not in fragment, fragment


def test_every_agent_answer_is_its_own_row():
    html = render.thread([
        {"role": "user", "content": "hi team"},
        {"role": "assistant", "agent_name": "Ada", "content": "Ada here"},
        {"role": "assistant", "agent_name": "Mia", "content": "Mia here"},
    ])
    assert html.count('class="am agent"') == 2
    assert "Ada here" in html and "Mia here" in html


def test_user_text_is_escaped():
    assert "<script>" not in render.user_bubble("<script>alert(1)</script>")
    assert "&lt;script&gt;" in render.user_bubble("<script>alert(1)</script>")


def test_agent_answer_is_escaped():
    assert "<img" not in render.agent_bubble("Ada", '<img onerror=x>')


def test_approval_shows_the_call_and_offers_both_answers():
    html = render.approval_bubble("Ada", "agent-a", CALLS)
    assert "send_email" in html
    assert "boss@example.com" in html
    assert ">Yes<" in html and ">No<" in html
    assert 'hx-post="/tasks/agents/chat/approve"' in html


def test_approval_never_leaks_the_held_conversation():
    # _pending_payload carries these two next to the calls. Neither may reach
    # a browser, so the renderer is only ever handed the calls.
    html = render.approval_bubble("Ada", "agent-a", CALLS)
    assert "conversation" not in html
    assert "user_email" not in html


def test_stream_block_closes_the_connection_and_has_both_targets():
    html = render.stream_block()
    assert 'sse-connect="/tasks/agents/chat/stream"' in html
    assert 'sse-close="close"' in html
    assert 'sse-swap="message"' in html
    assert 'sse-swap="working"' in html


def test_chips_mark_who_is_in_the_room():
    html = render.chips([{"id": "agent-a", "name": "Ada"},
                         {"id": "agent-m", "name": "Mia"}], ["agent-a"])
    assert html.count("chip") >= 2
    assert "chip in" in html
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
python -m pytest tests/test_agent_chat_render.py -q
```

Expected: collection error, `ModuleNotFoundError: No module named 'agent_chat_render'`.

- [ ] **Step 3: Write the renderer**

Create `mcp-servers/tasks/agent_chat_render.py`:

```python
"""HTML fragments for the agent chat panel.

Every function here returns ONE line with no newline in it. Several of these
fragments travel as SSE `data:`, where a newline is a field separator, so a
multi-line fragment arrives cut into pieces.

Server-rendered rather than assembled in the browser, following the Fusion
page: the panel then has no client-side model of the conversation that can
drift from the server's.
"""
import html


def esc(s: str) -> str:
    return html.escape(s or "")


def _initial(name: str) -> str:
    return esc((name or "?").strip()[:1].upper())


def user_bubble(text: str) -> str:
    return f'<div class="am user"><div class="ab">{esc(text)}</div></div>'


def agent_bubble(name: str, content: str) -> str:
    """One agent's finished answer: its own row, its own name, its own avatar.

    This is the entire feature. Nothing is stacked into another agent's bubble,
    because the panel draws the bubbles itself.
    """
    return ('<div class="am agent">'
            f'<div class="aav">{_initial(name)}</div>'
            '<div class="abody">'
            f'<div class="awho">{esc(name)}</div>'
            f'<div class="atext md">{esc(content)}</div>'
            '</div></div>')


def approval_bubble(name: str, agent_id: str, calls: list[dict]) -> str:
    """An agent that stopped to ask permission.

    Handed only the calls, never the whole pending payload: that also carries
    the held conversation and the owner's email, and neither belongs in a
    browser.
    """
    items = []
    for call in calls or []:
        fn = call.get("function") if isinstance(call, dict) else None
        fn = fn if isinstance(fn, dict) else {}
        name_txt = esc(str(fn.get("name") or ""))
        args_txt = esc(str(fn.get("arguments") or ""))
        items.append(f'<li><code>{name_txt}</code> '
                     f'<span class="aargs">{args_txt}</span></li>')
    aid = esc(agent_id)
    return (f'<div class="am agent awaiting" id="await-{aid}">'
            f'<div class="aav">{_initial(name)}</div>'
            '<div class="abody">'
            f'<div class="awho">{esc(name)}</div>'
            f'<div class="atext">{esc(name)} wants to run:</div>'
            f'<ul class="acalls">{"".join(items)}</ul>'
            '<div class="aactions">'
            '<button class="btn primary" type="button" '
            'hx-post="/tasks/agents/chat/approve" '
            f'hx-vals=\'{{"agent_id": "{aid}", "approved": "yes"}}\' '
            f'hx-target="#await-{aid}" hx-swap="outerHTML">Yes</button>'
            '<button class="btn" type="button" '
            'hx-post="/tasks/agents/chat/approve" '
            f'hx-vals=\'{{"agent_id": "{aid}", "approved": "no"}}\' '
            f'hx-target="#await-{aid}" hx-swap="outerHTML">No</button>'
            '</div></div></div>')


def working(name: str) -> str:
    """Which agent is running right now.

    A round of three agents that each use tools can hold the stream open for
    minutes. Without this line a slow round is indistinguishable from a broken
    one.
    """
    return f'<div class="aworking">{esc(name)} is working...</div>'


def note(text: str) -> str:
    """A system line in the thread: a skipped agent, a refusal, a hint."""
    return f'<div class="am note">{esc(text)}</div>'


def stream_block() -> str:
    """The element that opens the SSE connection for one round.

    One connection with two swap targets: finished bubbles append to the live
    thread, and the working line replaces itself. `sse-close` stops the browser
    reconnecting, which would otherwise re-run a round that has already been
    paid for.
    """
    return ('<div class="astream" hx-ext="sse" '
            'sse-connect="/tasks/agents/chat/stream" sse-close="close">'
            '<div class="alive" sse-swap="message" hx-swap="beforeend"></div>'
            '<div class="awork" sse-swap="working" hx-swap="innerHTML"></div>'
            '</div>')


def empty_thread() -> str:
    return ('<div class="aempty">Pick who is in the room, then ask. '
            'Each agent answers in its own message.</div>')


def chips(agents: list[dict], room: list[str]) -> str:
    """Who is available and who is in the room.

    Replaces itself (hx-swap outerHTML into #agent-room), so it carries its own
    id.
    """
    if not agents:
        return ('<div class="achips" id="agent-room">'
                '<span class="asidenote">You have no agents yet. '
                'Make one and it will show up here.</span></div>')
    out = []
    for a in agents:
        aid = esc(str(a.get("id") or ""))
        name = esc(str(a.get("name") or a.get("id") or ""))
        inroom = str(a.get("id")) in (room or [])
        cls = "chip in" if inroom else "chip"
        url = ("/tasks/agents/chat/room/remove" if inroom
               else "/tasks/agents/chat/room/add")
        out.append(f'<button class="{cls}" type="button" hx-post="{url}" '
                   f'hx-vals=\'{{"agent_id": "{aid}"}}\' '
                   'hx-target="#agent-room" hx-swap="outerHTML">'
                   f'{name}</button>')
    return f'<div class="achips" id="agent-room">{"".join(out)}</div>'


#: This fragment replaces itself, so it has to carry its own hx-get and
#: hx-trigger. Without them the first swap installs an element that is no
#: longer listening, and the list goes deaf for the rest of the page's life.
#: The Fusion sidebar had exactly that bug.
_CHATLIST_HX = ('id="agent-chatlist" hx-get="/tasks/agents/chat/chats" '
                'hx-trigger="load, agent-chats-changed from:body" '
                'hx-swap="outerHTML"')


def chat_list(chats: list[dict], active_id: str | None) -> str:
    if not chats:
        return (f'<p class="asidenote" {_CHATLIST_HX}>No saved conversations '
                'yet.</p>')
    rows = []
    for c in chats:
        cid = esc(str(c.get("id") or ""))
        title = esc(str(c.get("title") or "New chat"))
        active = " active" if str(c.get("id")) == active_id else ""
        rows.append(
            f'<div class="achatrow{active}">'
            f'<button class="achatopen" type="button" '
            f'hx-get="/tasks/agents/chat/chat/{cid}" '
            f'hx-target="#agent-thread" hx-swap="innerHTML" '
            f'title="{title}">{title}</button>'
            f'<button class="achatdel" type="button" '
            f'hx-delete="/tasks/agents/chat/chat/{cid}" '
            f'hx-target="#agent-chatlist" hx-swap="outerHTML" '
            f'hx-confirm="Delete this conversation?" '
            f'title="Delete">&times;</button>'
            '</div>')
    return f'<div class="achatlist" {_CHATLIST_HX}>{"".join(rows)}</div>'


def thread(messages: list[dict]) -> str:
    """A saved conversation replayed.

    Roles other than user and assistant are the round bookkeeping (see
    routes_agent_chat) and render as nothing.
    """
    out = []
    for m in messages or []:
        role = m.get("role")
        content = m.get("content") or ""
        if role == "user":
            out.append(user_bubble(content))
        elif role == "assistant":
            name = str(m.get("agent_name") or "Agent")
            if content:
                out.append(agent_bubble(name, content))
            awaiting = m.get("awaiting")
            if isinstance(awaiting, dict) and awaiting.get("calls"):
                out.append(approval_bubble(name, str(m.get("agent_id") or ""),
                                           awaiting["calls"]))
    return "".join(out) if out else empty_thread()
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
python -m pytest tests/test_agent_chat_render.py -q
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/agent_chat_render.py \
        mcp-servers/tasks/tests/test_agent_chat_render.py
git commit -m "Render the agent panel's messages, chips and conversation list"
```

---

### Task 3: The round and the stream

The core. Send a message, then one SSE stream in which each agent answers in turn.

**Files:**
- Create: `mcp-servers/tasks/routes_agent_chat.py`
- Test: `mcp-servers/tasks/tests/test_agent_chat_round.py`

**Interfaces:**
- Consumes: `agent_chat_store` (Task 1), `agent_chat_render` (Task 2), and from `routes_agent_turn`: `_agents_for(user_email) -> list[dict]` and `_turn_for(user_email, agent, messages, names) -> dict` with keys `answer`, `notes`, `agent`, optionally `pending`.
- Produces:
  - `router` (FastAPI `APIRouter`, no prefix, routes carry the full `/tasks/...` path)
  - `POST /tasks/agents/chat/send`
  - `GET /tasks/agents/chat/stream`
  - `_history_for_round(messages: list[dict]) -> list[dict]`
  - `_run_round(email: str, s: RoomSession, agents: list[dict])` async generator of SSE event dicts
  - `_drop(messages: list[dict], marker: dict) -> None`
  - `MAX_ROOM = 4`
  - Module-level seams for tests: `_agents_for`, `_turn_for`, `store`, `render`

- [ ] **Step 1: Write the failing test**

Create `mcp-servers/tasks/tests/test_agent_chat_round.py`:

```python
"""One message, one bubble per agent, in order.

The assertion that matters most is test_agents_do_not_see_each_other: feeding
agents each other's replies is what taught the model to invent whole exchanges
between agents, and nothing but this test stops that coming back.
"""
import importlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

EMAIL = "panel-owner@example.com"
ADA = {"id": "agent-a", "name": "Ada"}
MIA = {"id": "agent-m", "name": "Mia"}


def _hdr(email=EMAIL):
    return {"X-User-Email": email}


def _app(monkeypatch, turn=None, agents=(ADA, MIA)):
    import agent_chat_store
    import routes_agent_chat
    importlib.reload(agent_chat_store)
    importlib.reload(routes_agent_chat)

    seen = []

    async def default_turn(email, agent, messages, names=()):
        seen.append({"agent": agent["id"], "messages": [dict(m) for m in messages]})
        return {"answer": f'{agent["name"]} here', "notes": [],
                "agent": {"id": agent["id"], "name": agent["name"]}}

    async def agents_for(email):
        return list(agents)

    monkeypatch.setattr(routes_agent_chat, "_agents_for", agents_for)
    monkeypatch.setattr(routes_agent_chat, "_turn_for", turn or default_turn)
    # The store's SQL half needs a real Postgres. Swap it out so these tests
    # measure the round rather than the "database is down" path.
    async def noop_create(email, title, s):
        return "chat-1"

    async def noop_save(email, s):
        return None

    monkeypatch.setattr(routes_agent_chat.store, "create_chat", noop_create)
    monkeypatch.setattr(routes_agent_chat.store, "save_chat", noop_save)

    app = FastAPI()
    app.include_router(routes_agent_chat.router)
    return app, routes_agent_chat, seen


def _seat(mod, room):
    s = mod.store.get_session(EMAIL)
    s.room = list(room)
    return s


def test_send_requires_identity(monkeypatch):
    app, _, _ = _app(monkeypatch)
    r = TestClient(app).post("/tasks/agents/chat/send", data={"message": "hi"})
    assert r.status_code == 401


def test_send_with_an_empty_room_asks_you_to_pick_someone(monkeypatch):
    app, mod, _ = _app(monkeypatch)
    _seat(mod, [])
    c = TestClient(app)
    r = c.post("/tasks/agents/chat/send", data={"message": "hi"}, headers=_hdr())
    assert r.status_code == 200
    assert "Pick at least one agent" in r.text
    assert mod.store.get_session(EMAIL).messages == []


def test_send_records_the_message_and_opens_a_stream(monkeypatch):
    app, mod, _ = _app(monkeypatch)
    _seat(mod, ["agent-a"])
    c = TestClient(app)
    r = c.post("/tasks/agents/chat/send", data={"message": "hi team"},
               headers=_hdr())
    assert "hi team" in r.text
    assert 'sse-connect="/tasks/agents/chat/stream"' in r.text
    assert r.headers.get("HX-Trigger") == "agent-chats-changed"
    s = mod.store.get_session(EMAIL)
    assert s.messages[-1] == {"role": "user", "content": "hi team"}


def test_every_agent_in_the_room_gets_its_own_bubble_in_order(monkeypatch):
    app, mod, _ = _app(monkeypatch)
    _seat(mod, ["agent-a", "agent-m"])
    c = TestClient(app)
    c.post("/tasks/agents/chat/send", data={"message": "hi team"}, headers=_hdr())
    body = c.get("/tasks/agents/chat/stream", headers=_hdr()).text
    assert body.count('class="am agent"') == 2
    assert body.index("Ada here") < body.index("Mia here")


def test_agents_do_not_see_each_other(monkeypatch):
    app, mod, seen = _app(monkeypatch)
    _seat(mod, ["agent-a", "agent-m"])
    c = TestClient(app)
    c.post("/tasks/agents/chat/send", data={"message": "hi team"}, headers=_hdr())
    c.get("/tasks/agents/chat/stream", headers=_hdr())
    assert [t["agent"] for t in seen] == ["agent-a", "agent-m"]
    # Identical input, and Ada's answer is nowhere in Mia's.
    assert seen[0]["messages"] == seen[1]["messages"]
    assert "Ada here" not in str(seen[1]["messages"])


def test_a_reconnecting_stream_does_not_re_run_the_round(monkeypatch):
    app, mod, seen = _app(monkeypatch)
    _seat(mod, ["agent-a"])
    c = TestClient(app)
    c.post("/tasks/agents/chat/send", data={"message": "hi"}, headers=_hdr())
    c.get("/tasks/agents/chat/stream", headers=_hdr())
    again = c.get("/tasks/agents/chat/stream", headers=_hdr())
    assert len(seen) == 1, "the reconnect re-ran the round"
    assert "am agent" not in again.text


def test_a_stream_with_nothing_to_answer_just_closes(monkeypatch):
    app, mod, seen = _app(monkeypatch)
    _seat(mod, ["agent-a"])
    r = TestClient(app).get("/tasks/agents/chat/stream", headers=_hdr())
    assert seen == []
    assert "event: close" in r.text


def test_an_agent_that_no_longer_exists_is_skipped_and_the_round_goes_on(
        monkeypatch):
    app, mod, seen = _app(monkeypatch)
    _seat(mod, ["agent-gone", "agent-m"])
    c = TestClient(app)
    c.post("/tasks/agents/chat/send", data={"message": "hi"}, headers=_hdr())
    body = c.get("/tasks/agents/chat/stream", headers=_hdr()).text
    assert [t["agent"] for t in seen] == ["agent-m"]
    assert "no longer exists" in body
    assert "Mia here" in body


def test_a_failed_agent_does_not_take_the_round_down(monkeypatch):
    async def turn(email, agent, messages, names=()):
        if agent["id"] == "agent-a":
            # _turn_for never raises; a blown-up turn comes back as a sentence.
            return {"answer": "Ada could not finish that just now.", "notes": [],
                    "agent": {"id": "agent-a", "name": "Ada"}}
        return {"answer": "Mia here", "notes": [],
                "agent": {"id": "agent-m", "name": "Mia"}}

    app, mod, _ = _app(monkeypatch, turn=turn)
    _seat(mod, ["agent-a", "agent-m"])
    c = TestClient(app)
    c.post("/tasks/agents/chat/send", data={"message": "hi"}, headers=_hdr())
    body = c.get("/tasks/agents/chat/stream", headers=_hdr()).text
    assert "could not finish" in body
    assert "Mia here" in body


def test_the_working_line_names_the_agent(monkeypatch):
    app, mod, _ = _app(monkeypatch)
    _seat(mod, ["agent-a"])
    c = TestClient(app)
    c.post("/tasks/agents/chat/send", data={"message": "hi"}, headers=_hdr())
    body = c.get("/tasks/agents/chat/stream", headers=_hdr()).text
    assert "event: working" in body
    assert "Ada is working" in body


def test_history_for_round_keeps_only_real_turns():
    import routes_agent_chat as mod
    got = mod._history_for_round([
        {"role": "user", "content": "hi"},
        {"role": "assistant", "agent_id": "agent-a", "agent_name": "Ada",
         "content": "hello"},
        {"role": "assistant", "content": "   "},
        {"role": "round", "content": ""},
    ])
    assert got == [{"role": "user", "content": "hi"},
                   {"role": "assistant", "content": "hello"}]
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
python -m pytest tests/test_agent_chat_round.py -q
```

Expected: collection error, `ModuleNotFoundError: No module named 'routes_agent_chat'`.

- [ ] **Step 3: Write the routes and the round**

Create `mcp-servers/tasks/routes_agent_chat.py`:

```python
"""The agent chat panel on the AI Agents page.

One message, one answer per agent in the room, each in its own bubble. The
panel draws its own messages, so a reply being its own message is not a trick
played on somebody else's renderer, which is what the previous attempt was and
why it failed.

Shape copied from routes_fusion_page: server-rendered fragments, vendored
HTMX, a per-user in-memory working session over a durable row, and one SSE
stream per turn. All routes sit under /tasks, already routed to this service
end to end, so nothing outside this service changes.
"""
import logging

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sse_starlette.sse import EventSourceResponse

import agent_chat_render as render
import agent_chat_store as store
from auth import CurrentUser, current_user
from routes_agent_turn import _agents_for, _turn_for
from routes_agents import _pending_for_page

log = logging.getLogger(__name__)

router = APIRouter()

#: Agents run one at a time, so a room is a queue. Four is already a slow round.
MAX_ROOM = 4


def _history_for_round(messages: list[dict]) -> list[dict]:
    """The conversation every agent in this round sees. Built ONCE.

    Role and content only: agent_id and agent_name are ours, for drawing the
    bubbles, and mean nothing to a model. Empty turns are dropped because empty
    content is rejected upstream. Bookkeeping roles fall out here too.
    """
    out = []
    for m in messages or []:
        role = m.get("role")
        content = (m.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            out.append({"role": role, "content": content})
    return out


def _drop(messages: list[dict], marker: dict) -> None:
    """Remove `marker` by identity.

    Not list.remove, which matches by equality: two empty bookkeeping dicts
    compare equal, so remove() can delete the wrong one.
    """
    for i, m in enumerate(messages):
        if m is marker:
            del messages[i]
            return


async def _run_round(email: str, s: store.RoomSession, agents: list[dict],
                     request: Request | None = None):
    """Yield one SSE event per thing that happens in a round.

    Agents run one at a time, never in parallel: a turn can run tools and this
    box has 3.8GB of RAM.
    """
    by_id = {str(a.get("id")): a for a in agents}
    names = [a.get("name") for a in agents if a.get("name")]
    # Built once, before the first agent runs, and handed unchanged to every
    # agent. See the module docstring of routes_agent_turn for what happens
    # when agents read each other's labelled replies.
    history = _history_for_round(s.messages)

    for agent_id in list(s.room):
        if request is not None and await request.is_disconnected():
            break
        agent = by_id.get(agent_id)
        if agent is None:
            line = ("An agent that was in this room no longer exists, "
                    "so it was skipped.")
            s.messages.append({"role": "note", "content": line})
            yield {"event": "message", "data": render.note(line)}
            continue

        name = str(agent.get("name") or agent_id)
        yield {"event": "working", "data": render.working(name)}
        out = await _turn_for(email, agent, history, names)
        answer = out.get("answer") or ""

        raw_pending = out.get("pending")
        page_pending = (_pending_for_page(raw_pending)
                        if isinstance(raw_pending, dict) else None)
        if page_pending:
            # Hold the full payload server side: it carries the held
            # conversation and the owner's email, neither of which belongs in
            # a browser. The browser gets the calls only.
            s.pending[agent_id] = raw_pending
            s.messages.append({"role": "assistant", "agent_id": agent_id,
                               "agent_name": name, "content": answer,
                               "awaiting": page_pending})
            if answer:
                yield {"event": "message",
                       "data": render.agent_bubble(name, answer)}
            yield {"event": "message",
                   "data": render.approval_bubble(name, agent_id,
                                                  page_pending["calls"])}
            # And on to the next agent. Pausing the one that asked is the
            # point; silently losing everybody else is not.
            continue

        s.messages.append({"role": "assistant", "agent_id": agent_id,
                           "agent_name": name, "content": answer})
        yield {"event": "message", "data": render.agent_bubble(name, answer)}

    yield {"event": "working", "data": ""}


@router.post("/tasks/agents/chat/send", include_in_schema=False)
async def agent_chat_send(message: str = Form(...),
                          user: CurrentUser = Depends(current_user)
                          ) -> HTMLResponse:
    body = (message or "").strip()
    if not body:
        raise HTTPException(status_code=400, detail="empty message")
    s = store.get_session(user.email)
    if not s.room:
        return HTMLResponse(render.note(
            "Pick at least one agent first, then ask again."))
    if s.streaming:
        return HTMLResponse(render.note("Still answering, one moment."))

    s.messages.append({"role": "user", "content": body})
    s.streaming = True
    # First message of an unsaved conversation: write the row now so it appears
    # in the list immediately. Best effort, because a database problem must not
    # cost somebody their turn; the conversation simply stays unsaved.
    if s.chat_id is None:
        try:
            s.chat_id = await store.create_chat(
                user.email, store.title_from(body), s)
        except Exception:                                   # noqa: BLE001
            log.exception("agent chat: could not create the conversation row; "
                          "continuing unsaved")

    resp = HTMLResponse(render.user_bubble(body) + render.stream_block())
    resp.headers["HX-Trigger"] = "agent-chats-changed"
    return resp


@router.get("/tasks/agents/chat/stream", include_in_schema=False)
async def agent_chat_stream(request: Request,
                            user: CurrentUser = Depends(current_user)
                            ) -> EventSourceResponse:
    s = store.get_session(user.email)

    async def gen():
        # Only ever answer an unanswered message. A browser reconnects an
        # EventSource by itself, and without this the reconnect re-runs the
        # whole round: an infinite loop that costs real money.
        if not s.messages or s.messages[-1].get("role") != "user":
            # Do NOT clear s.streaming here. A reconnect can reach this branch
            # while the owning round is still running, and clearing it would
            # drop the double-submit guard mid-turn.
            yield {"event": "close", "data": ""}
            return

        # Claim the round before the first await, by flipping the tail off
        # "user". Anything reconnecting from here on fails the check above.
        my_generation = s.generation
        claim = {"role": "round", "content": ""}
        s.messages.append(claim)
        try:
            agents = await _agents_for(user.email)
            async for event in _run_round(user.email, s, agents, request):
                yield event
        finally:
            still_ours = (s.generation == my_generation
                          and any(m is claim for m in s.messages))
            if still_ours:
                # An answer now holds the tail, so the bookkeeping marker has
                # done its job. If nothing answered, it stays: the tail must
                # not fall back to "user" or a reconnect re-runs the round.
                if s.messages[-1] is not claim:
                    _drop(s.messages, claim)
                try:
                    await store.save_chat(user.email, s)
                except Exception:                           # noqa: BLE001
                    log.exception("agent chat: could not save conversation %s",
                                  s.chat_id)
            s.streaming = False
            yield {"event": "close", "data": ""}

    return EventSourceResponse(gen())
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
python -m pytest tests/test_agent_chat_round.py -q
```

Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/routes_agent_chat.py \
        mcp-servers/tasks/tests/test_agent_chat_round.py
git commit -m "Run one agent chat round per message and stream each reply as it lands"
```

---

### Task 4: Approvals

An agent that stops to ask gets Yes and No in its bubble. Answering resumes only that agent.

**Files:**
- Modify: `mcp-servers/tasks/routes_agent_turn.py` (extract the resume body into a callable; the route delegates)
- Modify: `mcp-servers/tasks/routes_agent_chat.py` (add the approve route)
- Test: `mcp-servers/tasks/tests/test_agent_chat_approval.py`

**Interfaces:**
- Consumes: `_run_round` and `store` from Task 3, `render.approval_bubble` from Task 2.
- Produces:
  - `routes_agent_turn._resume_turn(user_email: str, agent_id: str, conversation: list[dict], calls: list[dict], approved: bool) -> dict` returning `{"answer": str, "notes": list}` or a `_pending_payload` shape
  - `POST /tasks/agents/chat/approve` in `routes_agent_chat`
  - `routes_agent_chat._clear_awaiting(messages: list[dict], agent_id: str) -> None`

- [ ] **Step 1: Write the failing test**

Create `mcp-servers/tasks/tests/test_agent_chat_approval.py`:

```python
"""Yes and No on an agent that stopped to ask.

The security property under test is that the held conversation never leaves the
server: the browser is handed tool names and arguments, and hands back an id
and an answer.
"""
import importlib

from fastapi import FastAPI
from fastapi.testclient import TestClient

EMAIL = "panel-owner@example.com"
ADA = {"id": "agent-a", "name": "Ada"}
MIA = {"id": "agent-m", "name": "Mia"}
CALLS = [{"id": "call-1",
          "function": {"name": "send_email",
                       "arguments": '{"to": "boss@example.com"}'}}]
HELD = [{"role": "user", "content": "email the boss"},
        {"role": "assistant", "content": "", "tool_calls": CALLS}]


def _hdr(email=EMAIL):
    return {"X-User-Email": email}


def _app(monkeypatch, turn):
    import agent_chat_store
    import routes_agent_chat
    importlib.reload(agent_chat_store)
    importlib.reload(routes_agent_chat)

    resumed = []

    async def agents_for(email):
        return [ADA, MIA]

    async def resume_turn(user_email, agent_id, conversation, calls, approved):
        resumed.append({"agent_id": agent_id, "approved": approved,
                        "conversation": conversation, "calls": calls})
        return {"answer": "Sent it." if approved else "I did not run that.",
                "notes": []}

    async def noop_create(email, title, s):
        return "chat-1"

    async def noop_save(email, s):
        return None

    monkeypatch.setattr(routes_agent_chat, "_agents_for", agents_for)
    monkeypatch.setattr(routes_agent_chat, "_turn_for", turn)
    monkeypatch.setattr(routes_agent_chat, "_resume_turn", resume_turn)
    monkeypatch.setattr(routes_agent_chat.store, "create_chat", noop_create)
    monkeypatch.setattr(routes_agent_chat.store, "save_chat", noop_save)

    app = FastAPI()
    app.include_router(routes_agent_chat.router)
    return app, routes_agent_chat, resumed


def _asking_turn(who="agent-a"):
    async def turn(email, agent, messages, names=()):
        if agent["id"] == who:
            return {"answer": "May I send this?", "notes": [],
                    "agent": {"id": agent["id"], "name": agent["name"]},
                    "pending": {"agent_id": agent["id"], "user_email": EMAIL,
                                "calls": CALLS, "conversation": HELD}}
        return {"answer": f'{agent["name"]} here', "notes": [],
                "agent": {"id": agent["id"], "name": agent["name"]}}
    return turn


def _ask(app, room=("agent-a", "agent-m")):
    c = TestClient(app)
    import routes_agent_chat as mod
    mod.store.get_session(EMAIL).room = list(room)
    c.post("/tasks/agents/chat/send", data={"message": "email the boss"},
           headers=_hdr())
    body = c.get("/tasks/agents/chat/stream", headers=_hdr()).text
    return c, body


def test_the_question_reaches_the_page_with_both_answers(monkeypatch):
    app, _, _ = _app(monkeypatch, _asking_turn())
    _, body = _ask(app)
    assert "send_email" in body
    assert ">Yes<" in body and ">No<" in body


def test_the_held_conversation_never_reaches_the_page(monkeypatch):
    app, _, _ = _app(monkeypatch, _asking_turn())
    _, body = _ask(app)
    # The stream carries the call, so the person can see what they are
    # approving.
    assert "send_email" in body
    # It does not carry the held conversation the resume will replay, nor the
    # owner's email. Both sit next to the calls in _pending_payload.
    assert "email the boss" not in body
    assert "tool_calls" not in body
    assert EMAIL not in body


def test_the_round_carries_on_past_the_agent_that_asked(monkeypatch):
    app, _, _ = _app(monkeypatch, _asking_turn())
    _, body = _ask(app)
    assert "Mia here" in body, "pausing Ada must not silently lose Mia"


def test_yes_resumes_only_that_agent(monkeypatch):
    app, mod, resumed = _app(monkeypatch, _asking_turn())
    c, _ = _ask(app)
    r = c.post("/tasks/agents/chat/approve",
               data={"agent_id": "agent-a", "approved": "yes"}, headers=_hdr())
    assert r.status_code == 200
    assert len(resumed) == 1
    assert resumed[0]["agent_id"] == "agent-a"
    assert resumed[0]["approved"] is True
    assert resumed[0]["conversation"] == HELD
    assert "Sent it." in r.text


def test_no_refuses_and_says_so(monkeypatch):
    app, mod, resumed = _app(monkeypatch, _asking_turn())
    c, _ = _ask(app)
    r = c.post("/tasks/agents/chat/approve",
               data={"agent_id": "agent-a", "approved": "no"}, headers=_hdr())
    assert resumed[0]["approved"] is False
    assert "did not run that" in r.text


def test_answering_twice_does_not_run_it_twice(monkeypatch):
    app, mod, resumed = _app(monkeypatch, _asking_turn())
    c, _ = _ask(app)
    c.post("/tasks/agents/chat/approve",
           data={"agent_id": "agent-a", "approved": "yes"}, headers=_hdr())
    again = c.post("/tasks/agents/chat/approve",
                   data={"agent_id": "agent-a", "approved": "yes"},
                   headers=_hdr())
    assert len(resumed) == 1
    assert "no longer waiting" in again.text


def test_answering_a_question_nobody_asked_does_nothing(monkeypatch):
    app, mod, resumed = _app(monkeypatch, _asking_turn())
    c = TestClient(app)
    r = c.post("/tasks/agents/chat/approve",
               data={"agent_id": "agent-m", "approved": "yes"}, headers=_hdr())
    assert resumed == []
    assert "no longer waiting" in r.text


def test_someone_elses_session_cannot_answer_your_question(monkeypatch):
    app, mod, resumed = _app(monkeypatch, _asking_turn())
    c, _ = _ask(app)
    r = c.post("/tasks/agents/chat/approve",
               data={"agent_id": "agent-a", "approved": "yes"},
               headers=_hdr("stranger@example.com"))
    assert resumed == []
    assert "no longer waiting" in r.text


def test_an_answered_question_leaves_the_thread(monkeypatch):
    app, mod, _ = _app(monkeypatch, _asking_turn())
    c, _ = _ask(app)
    c.post("/tasks/agents/chat/approve",
           data={"agent_id": "agent-a", "approved": "yes"}, headers=_hdr())
    replayed = mod.render.thread(mod.store.get_session(EMAIL).messages)
    assert ">Yes<" not in replayed
    assert "Sent it." in replayed
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
python -m pytest tests/test_agent_chat_approval.py -q
```

Expected: FAIL, `AttributeError: <module 'routes_agent_chat'> does not have the attribute '_resume_turn'`.

- [ ] **Step 3: Extract the resume body so it can be called in process**

In `mcp-servers/tasks/routes_agent_turn.py`, replace the body of the `resume` route (currently at `routes_agent_turn.py:183`) with a delegation, and move the logic verbatim into a new module-level function directly above it. Behaviour must not change; `tests/test_agent_turn_resume.py` is the check.

```python
async def _resume_turn(user_email: str, agent_id: str, conversation: list[dict],
                       calls: list[dict], approved: bool) -> dict:
    """Continue a turn that stopped to ask.

    Split out of the route so callers inside this process (the agent chat
    panel) can resume without an HTTP hop and without holding the internal
    secret, the same way the Fusion page calls fusion_engine directly.

    The access level is READ AGAIN here rather than trusted from when the
    question was asked. Between the two there is a window in which the agent
    can be edited or deleted, and somebody who has second thoughts and turns an
    agent down to read only has turned it down.
    """
    token, tools, level = await _resolve_agent(user_email, agent_id)
    mode = agent_access.effective_mode(level, None, agent_access.SURFACE_CHANNEL)
    if mode not in _RESUMABLE:
        return {"answer": "This agent is set to read only now, so I did not "
                          "run that.", "notes": []}

    convo = list(conversation)
    for call in calls:
        call = call if isinstance(call, dict) else {}
        fn = call.get("function")
        fn = fn if isinstance(fn, dict) else {}
        raw_name = fn.get("name")
        name = raw_name.strip() if isinstance(raw_name, str) else ""
        if approved:
            # tools, not anything the caller sent: same rule as the turn
            # endpoint, and the reason execute_tool_call takes this argument.
            result = await execute_tool_call(call, user_email, tools or None)
        else:
            result = (REFUSED_BY_OWNER + ", so " + (name or "that tool")
                      + " was not run.")
        # Every tool_call in the held assistant message needs a matching tool
        # message before the next completion, approved or not.
        convo.append({"role": "tool", "tool_call_id": call.get("id"),
                      "name": name, "content": result})

    run_id = await agent_activity.start_run(
        agent_id, user_email, agent_activity.SOURCE_CHANNEL)
    outcome = "failed"
    try:
        answer, notes = await _chat(
            token=token, model=agent_id, messages=convo,
            tool_ids=tools or None, user_email=user_email,
            tool_mode=mode,
            refusal_reason=agent_access.refusal_reason(
                level, None, agent_access.SURFACE_CHANNEL),
            max_iterations=CHANNEL_MAX_TOOL_ITERATIONS,
            timeout=CHANNEL_HTTP_TIMEOUT_SECONDS)
        outcome = "completed"
        return {"answer": answer, "notes": notes}
    except agent_access.ApprovalRequired as err:
        outcome = STATUS_WAITING
        return _pending_payload(user_email, agent_id, err)
    finally:
        await agent_activity.finish_run(run_id, outcome)


@router.post("/turn/resume")
async def resume(body: ResumeIn,
                 x_internal_secret: str = Header(default="")) -> dict:
    """Continue a turn that stopped to ask. Internal only.

    The work is in _resume_turn so in-process callers can reach it without
    holding the internal secret.
    """
    _require_internal(x_internal_secret)
    return await _resume_turn(user_email=body.user_email,
                              agent_id=body.agent_id,
                              conversation=body.conversation,
                              calls=body.calls, approved=body.approved)
```

- [ ] **Step 4: Run the existing resume tests to prove the extraction changed nothing**

```bash
python -m pytest tests/test_agent_turn_resume.py tests/test_agent_turn_endpoint.py -q
```

Expected: all pass, same counts as before the edit.

- [ ] **Step 5: Add the approve route**

In `mcp-servers/tasks/routes_agent_chat.py`, add `_resume_turn` to the import from `routes_agent_turn`:

```python
from routes_agent_turn import _agents_for, _resume_turn, _turn_for
```

Then add these two below `_drop`:

```python
def _clear_awaiting(messages: list[dict], agent_id: str) -> None:
    """Take the question off the stored message once it has been answered, so
    a replayed conversation does not offer Yes and No on something already
    decided."""
    for m in messages:
        if m.get("agent_id") == agent_id and m.get("awaiting"):
            m.pop("awaiting", None)


def _name_for(agent_id: str, agents: list[dict]) -> str:
    for a in agents:
        if str(a.get("id")) == agent_id:
            return str(a.get("name") or agent_id)
    return agent_id
```

And this route at the end of the module:

```python
@router.post("/tasks/agents/chat/approve", include_in_schema=False)
async def agent_chat_approve(agent_id: str = Form(...),
                             approved: str = Form(...),
                             user: CurrentUser = Depends(current_user)
                             ) -> HTMLResponse:
    """Answer one agent's request to run a tool.

    The question lives in the asker's own session, so there is nothing to look
    up by id and nothing a stranger can address. The held conversation goes
    from here straight into _resume_turn without ever having been in a browser.
    """
    s = store.get_session(user.email)
    pending = s.pending.pop(agent_id, None)
    if not isinstance(pending, dict) or not pending.get("calls"):
        return HTMLResponse(render.note(
            "That question is no longer waiting for an answer."))
    # Belt and braces. The payload names who was asked; the session is already
    # per person, so these can only disagree if something upstream changed.
    if pending.get("user_email") and pending["user_email"] != user.email:
        log.warning("agent chat: refused an approval from the wrong person")
        return HTMLResponse(render.note(
            "That question is no longer waiting for an answer."))

    yes = (approved or "").strip().lower() in ("yes", "true", "1", "on")
    agents = await _agents_for(user.email)
    name = _name_for(agent_id, agents)
    out = await _resume_turn(user_email=user.email, agent_id=agent_id,
                             conversation=list(pending.get("conversation") or []),
                             calls=list(pending.get("calls") or []),
                             approved=yes)
    answer = out.get("answer") or ""
    _clear_awaiting(s.messages, agent_id)

    raw_pending = out.get("pending")
    page_pending = (_pending_for_page(raw_pending)
                    if isinstance(raw_pending, dict) else None)
    if page_pending:
        # It asked again. Same rules: hold the payload, show the calls.
        s.pending[agent_id] = raw_pending
        s.messages.append({"role": "assistant", "agent_id": agent_id,
                           "agent_name": name, "content": answer,
                           "awaiting": page_pending})
        html = ((render.agent_bubble(name, answer) if answer else "")
                + render.approval_bubble(name, agent_id, page_pending["calls"]))
    else:
        s.messages.append({"role": "assistant", "agent_id": agent_id,
                           "agent_name": name, "content": answer})
        html = render.agent_bubble(name, answer)

    try:
        await store.save_chat(user.email, s)
    except Exception:                                       # noqa: BLE001
        log.exception("agent chat: could not save after an approval")
    return HTMLResponse(html)
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
python -m pytest tests/test_agent_chat_approval.py tests/test_agent_chat_round.py -q
```

Expected: 9 passed in the approval file, 11 in the round file.

- [ ] **Step 7: Commit**

```bash
git add mcp-servers/tasks/routes_agent_turn.py \
        mcp-servers/tasks/routes_agent_chat.py \
        mcp-servers/tasks/tests/test_agent_chat_approval.py
git commit -m "Answer an agent's request to run a tool from the panel"
```

---

### Task 5: The room and saved conversations

Picking who is in the room, starting a new conversation, and reopening or deleting an old one.

**Files:**
- Modify: `mcp-servers/tasks/routes_agent_chat.py`
- Test: `mcp-servers/tasks/tests/test_agent_chat_rooms.py`

**Interfaces:**
- Consumes: everything from Tasks 1 to 4.
- Produces these routes, all returning HTML fragments:
  - `GET /tasks/agents/chat/room`
  - `POST /tasks/agents/chat/room/add` (Form `agent_id`)
  - `POST /tasks/agents/chat/room/remove` (Form `agent_id`)
  - `POST /tasks/agents/chat/new`
  - `GET /tasks/agents/chat/chats`
  - `GET /tasks/agents/chat/chat/{chat_id}`
  - `DELETE /tasks/agents/chat/chat/{chat_id}`

- [ ] **Step 1: Write the failing test**

Create `mcp-servers/tasks/tests/test_agent_chat_rooms.py`:

```python
"""Who is in the room, and the conversations you can come back to."""
import importlib

from fastapi import FastAPI
from fastapi.testclient import TestClient

EMAIL = "panel-owner@example.com"
ADA = {"id": "agent-a", "name": "Ada"}
MIA = {"id": "agent-m", "name": "Mia"}
EXTRAS = [{"id": f"agent-{i}", "name": f"A{i}"} for i in range(6)]


def _hdr(email=EMAIL):
    return {"X-User-Email": email}


def _fake_store(mod, monkeypatch):
    """Swap the chat table for a dict, so these tests measure the routes
    instead of the "database is down" path the routes deliberately swallow."""
    rows: dict[str, dict] = {}
    seq = {"n": 0}

    async def create(email, title, s):
        seq["n"] += 1
        cid = f"chat-{seq['n']}"
        rows[cid] = {"id": cid, "user_email": email, "title": title,
                     "messages": list(s.messages), "room": list(s.room),
                     "pending": dict(s.pending)}
        return cid

    async def save(email, s):
        row = rows.get(s.chat_id or "")
        if row and row["user_email"] == email:
            row.update(messages=list(s.messages), room=list(s.room),
                       pending=dict(s.pending))

    async def listing(email):
        return [{"id": r["id"], "title": r["title"]}
                for r in rows.values() if r["user_email"] == email]

    async def load(email, chat_id):
        row = rows.get(chat_id)
        return dict(row) if row and row["user_email"] == email else None

    async def delete(email, chat_id):
        row = rows.get(chat_id)
        if row and row["user_email"] == email:
            del rows[chat_id]

    monkeypatch.setattr(mod.store, "create_chat", create)
    monkeypatch.setattr(mod.store, "save_chat", save)
    monkeypatch.setattr(mod.store, "list_chats", listing)
    monkeypatch.setattr(mod.store, "load_chat", load)
    monkeypatch.setattr(mod.store, "delete_chat", delete)
    return rows


def _app(monkeypatch, agents=(ADA, MIA)):
    import agent_chat_store
    import routes_agent_chat
    importlib.reload(agent_chat_store)
    importlib.reload(routes_agent_chat)

    async def agents_for(email):
        return list(agents)

    async def turn(email, agent, messages, names=()):
        return {"answer": f'{agent["name"]} here', "notes": [],
                "agent": {"id": agent["id"], "name": agent["name"]}}

    monkeypatch.setattr(routes_agent_chat, "_agents_for", agents_for)
    monkeypatch.setattr(routes_agent_chat, "_turn_for", turn)
    rows = _fake_store(routes_agent_chat, monkeypatch)
    app = FastAPI()
    app.include_router(routes_agent_chat.router)
    return app, routes_agent_chat, rows


def test_the_room_starts_empty_and_lists_your_agents(monkeypatch):
    app, _, _ = _app(monkeypatch)
    r = TestClient(app).get("/tasks/agents/chat/room", headers=_hdr())
    assert "Ada" in r.text and "Mia" in r.text
    assert "chip in" not in r.text


def test_adding_and_removing_an_agent(monkeypatch):
    app, mod, _ = _app(monkeypatch)
    c = TestClient(app)
    c.post("/tasks/agents/chat/room/add", data={"agent_id": "agent-a"},
           headers=_hdr())
    assert mod.store.get_session(EMAIL).room == ["agent-a"]
    c.post("/tasks/agents/chat/room/remove", data={"agent_id": "agent-a"},
           headers=_hdr())
    assert mod.store.get_session(EMAIL).room == []


def test_adding_the_same_agent_twice_does_not_seat_it_twice(monkeypatch):
    app, mod, _ = _app(monkeypatch)
    c = TestClient(app)
    for _ in range(3):
        c.post("/tasks/agents/chat/room/add", data={"agent_id": "agent-a"},
               headers=_hdr())
    assert mod.store.get_session(EMAIL).room == ["agent-a"]


def test_an_agent_you_do_not_own_cannot_be_seated(monkeypatch):
    app, mod, _ = _app(monkeypatch)
    c = TestClient(app)
    c.post("/tasks/agents/chat/room/add", data={"agent_id": "agent-someone-else"},
           headers=_hdr())
    assert mod.store.get_session(EMAIL).room == []


def test_the_room_is_capped(monkeypatch):
    app, mod, _ = _app(monkeypatch, agents=EXTRAS)
    c = TestClient(app)
    for a in EXTRAS:
        c.post("/tasks/agents/chat/room/add", data={"agent_id": a["id"]},
               headers=_hdr())
    assert len(mod.store.get_session(EMAIL).room) == mod.MAX_ROOM


def test_new_clears_the_thread_but_keeps_the_room(monkeypatch):
    app, mod, _ = _app(monkeypatch)
    c = TestClient(app)
    c.post("/tasks/agents/chat/room/add", data={"agent_id": "agent-a"},
           headers=_hdr())
    c.post("/tasks/agents/chat/send", data={"message": "hi"}, headers=_hdr())
    c.get("/tasks/agents/chat/stream", headers=_hdr())
    before = mod.store.get_session(EMAIL).generation
    r = c.post("/tasks/agents/chat/new", headers=_hdr())
    s = mod.store.get_session(EMAIL)
    assert s.messages == []
    assert s.chat_id is None
    assert s.room == ["agent-a"]
    assert s.generation == before + 1
    assert r.headers.get("HX-Trigger") == "agent-chats-changed"


def test_a_saved_conversation_can_be_reopened(monkeypatch):
    app, mod, _ = _app(monkeypatch)
    c = TestClient(app)
    c.post("/tasks/agents/chat/room/add", data={"agent_id": "agent-a"},
           headers=_hdr())
    c.post("/tasks/agents/chat/send", data={"message": "about the invoices"},
           headers=_hdr())
    c.get("/tasks/agents/chat/stream", headers=_hdr())
    listing = c.get("/tasks/agents/chat/chats", headers=_hdr())
    assert "about the invoices" in listing.text
    c.post("/tasks/agents/chat/new", headers=_hdr())
    opened = c.get("/tasks/agents/chat/chat/chat-1", headers=_hdr())
    assert "about the invoices" in opened.text
    assert "Ada here" in opened.text
    assert mod.store.get_session(EMAIL).chat_id == "chat-1"


def test_you_cannot_open_or_delete_someone_elses_conversation(monkeypatch):
    app, mod, rows = _app(monkeypatch)
    c = TestClient(app)
    c.post("/tasks/agents/chat/room/add", data={"agent_id": "agent-a"},
           headers=_hdr())
    c.post("/tasks/agents/chat/send", data={"message": "private"},
           headers=_hdr())
    c.get("/tasks/agents/chat/stream", headers=_hdr())
    stranger = _hdr("stranger@example.com")
    assert c.get("/tasks/agents/chat/chat/chat-1",
                 headers=stranger).status_code == 404
    c.delete("/tasks/agents/chat/chat/chat-1", headers=stranger)
    assert "chat-1" in rows, "a stranger deleted somebody else's conversation"


def test_deleting_your_own_conversation(monkeypatch):
    app, mod, rows = _app(monkeypatch)
    c = TestClient(app)
    c.post("/tasks/agents/chat/room/add", data={"agent_id": "agent-a"},
           headers=_hdr())
    c.post("/tasks/agents/chat/send", data={"message": "bye"}, headers=_hdr())
    c.get("/tasks/agents/chat/stream", headers=_hdr())
    c.delete("/tasks/agents/chat/chat/chat-1", headers=_hdr())
    assert rows == {}
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
python -m pytest tests/test_agent_chat_rooms.py -q
```

Expected: FAIL, 404 responses on `/tasks/agents/chat/room` and the rest.

- [ ] **Step 3: Add the routes**

Append to `mcp-servers/tasks/routes_agent_chat.py`:

```python
@router.get("/tasks/agents/chat/room", include_in_schema=False)
async def agent_chat_room(user: CurrentUser = Depends(current_user)
                          ) -> HTMLResponse:
    s = store.get_session(user.email)
    return HTMLResponse(render.chips(await _agents_for(user.email), s.room))


@router.post("/tasks/agents/chat/room/add", include_in_schema=False)
async def agent_chat_room_add(agent_id: str = Form(...),
                              user: CurrentUser = Depends(current_user)
                              ) -> HTMLResponse:
    s = store.get_session(user.email)
    agents = await _agents_for(user.email)
    # Only your own agents, checked here rather than trusted from the form.
    # Seating a stranger's agent would run it as you.
    known = {str(a.get("id")) for a in agents}
    if agent_id in known and agent_id not in s.room and len(s.room) < MAX_ROOM:
        s.room.append(agent_id)
    return HTMLResponse(render.chips(agents, s.room))


@router.post("/tasks/agents/chat/room/remove", include_in_schema=False)
async def agent_chat_room_remove(agent_id: str = Form(...),
                                 user: CurrentUser = Depends(current_user)
                                 ) -> HTMLResponse:
    s = store.get_session(user.email)
    if agent_id in s.room:
        s.room.remove(agent_id)
    return HTMLResponse(render.chips(await _agents_for(user.email), s.room))


@router.post("/tasks/agents/chat/new", include_in_schema=False)
async def agent_chat_new(user: CurrentUser = Depends(current_user)
                         ) -> HTMLResponse:
    s = store.get_session(user.email)
    s.messages.clear()
    s.pending.clear()
    s.streaming = False
    # Detach from the saved row. It stays; this session just stops being about
    # it, so the next message starts a new conversation rather than appending
    # to the one that was walked away from.
    s.chat_id = None
    # Invalidate any round still running against the old conversation, so its
    # result is discarded instead of landing in the fresh one.
    s.generation += 1
    # The room is deliberately kept: picking the same people again every time
    # would be the main annoyance of a panel like this.
    resp = HTMLResponse(render.empty_thread())
    resp.headers["HX-Trigger"] = "agent-chats-changed"
    return resp


@router.get("/tasks/agents/chat/chats", include_in_schema=False)
async def agent_chat_chats(user: CurrentUser = Depends(current_user)
                           ) -> HTMLResponse:
    s = store.get_session(user.email)
    return HTMLResponse(
        render.chat_list(await store.list_chats(user.email), s.chat_id))


@router.get("/tasks/agents/chat/chat/{chat_id}", include_in_schema=False)
async def agent_chat_open(chat_id: str,
                          user: CurrentUser = Depends(current_user)
                          ) -> HTMLResponse:
    row = await store.load_chat(user.email, chat_id)
    if row is None:
        raise HTTPException(status_code=404, detail="no such conversation")
    s = store.get_session(user.email)
    s.messages = list(row.get("messages") or [])
    s.room = list(row.get("room") or [])
    s.pending = dict(row.get("pending") or {})
    s.chat_id = str(row["id"])
    s.streaming = False
    # Anything still running against the previous conversation is now orphaned.
    s.generation += 1
    resp = HTMLResponse(render.thread(s.messages))
    resp.headers["HX-Trigger"] = "agent-chats-changed"
    return resp


@router.delete("/tasks/agents/chat/chat/{chat_id}", include_in_schema=False)
async def agent_chat_delete(chat_id: str,
                            user: CurrentUser = Depends(current_user)
                            ) -> HTMLResponse:
    await store.delete_chat(user.email, chat_id)
    s = store.get_session(user.email)
    if s.chat_id == chat_id:
        s.messages.clear()
        s.pending.clear()
        s.chat_id = None
        s.generation += 1
    return HTMLResponse(
        render.chat_list(await store.list_chats(user.email), s.chat_id))
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python -m pytest tests/test_agent_chat_rooms.py tests/test_agent_chat_round.py tests/test_agent_chat_approval.py -q
```

Expected: 10 + 11 + 9 passed.

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/routes_agent_chat.py \
        mcp-servers/tasks/tests/test_agent_chat_rooms.py
git commit -m "Pick who is in the room, and keep the conversations you have had"
```

---

### Task 6: Put the panel on the page

Wire the router in, add the panel markup to the agents page, and give it styles and the small amount of client script it needs.

**Files:**
- Modify: `mcp-servers/tasks/main.py`
- Modify: `mcp-servers/tasks/static/agents.html`
- Create: `mcp-servers/tasks/static/agent-chat.css`
- Create: `mcp-servers/tasks/static/agent-chat.js`
- Test: `mcp-servers/tasks/tests/test_agent_chat_page.py`

**Interfaces:**
- Consumes: `routes_agent_chat.router` from Tasks 3 to 5.
- Produces: the panel visible at `/tasks/agents`.

- [ ] **Step 1: Write the failing test**

Create `mcp-servers/tasks/tests/test_agent_chat_page.py`:

```python
"""The panel is actually on the page.

A route nobody reaches is not a feature. This checks the page carries the
panel, its scripts, and the elements the fragments target, because the last
attempt shipped with the server side correct and the screen wrong.
"""
import pathlib

PAGE = pathlib.Path(__file__).resolve().parents[1] / "static" / "agents.html"


def _page() -> str:
    return PAGE.read_text(encoding="utf-8")


def test_the_page_loads_htmx_and_its_sse_extension():
    html = _page()
    assert "/tasks/static/vendor/htmx.min.js" in html
    assert "/tasks/static/vendor/sse.js" in html


def test_the_page_loads_the_panel_styles_and_script():
    html = _page()
    assert "/tasks/static/agent-chat.css" in html
    assert "/tasks/static/agent-chat.js" in html


def test_the_panel_has_the_targets_the_fragments_swap_into():
    html = _page()
    for target in ('id="agent-panel"', 'id="agent-room"', 'id="agent-thread"',
                   'id="agent-chatlist"'):
        assert target in html, target


def test_the_page_is_two_columns():
    html = _page()
    assert 'class="agents-layout"' in html
    assert 'class="agents-main"' in html


def test_the_composer_posts_to_send_and_appends_to_the_thread():
    html = _page()
    assert 'hx-post="/tasks/agents/chat/send"' in html
    assert 'hx-target="#agent-thread"' in html
    assert 'hx-swap="beforeend"' in html


def test_the_router_is_wired_in():
    main = (pathlib.Path(__file__).resolve().parents[1] / "main.py").read_text(
        encoding="utf-8")
    assert "routes_agent_chat" in main
    assert "agent_chat_router" in main
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
python -m pytest tests/test_agent_chat_page.py -q
```

Expected: 6 failed.

- [ ] **Step 3: Wire the router into main.py**

In `mcp-servers/tasks/main.py`, next to the other agent router imports near line 20:

```python
from routes_agent_chat import router as agent_chat_router
```

and next to the other `include_router` calls near line 131:

```python
app.include_router(agent_chat_router)  # /tasks/agents/chat, the panel
```

- [ ] **Step 4: Add the panel to the page**

In `mcp-servers/tasks/static/agents.html`, add the vendor and panel assets before `</head>`:

```html
<script src="/tasks/static/vendor/htmx.min.js"></script>
<script src="/tasks/static/vendor/sse.js"></script>
<link rel="stylesheet" href="/tasks/static/agent-chat.css">
```

Now make the page two columns. `.container` (`static/agents.html:50`) holds a flat sequence of children, so wrap the existing main-column content rather than restyling every child. Four exact edits:

1. Immediately after the `<div class="container">` line and the comment under it, open two wrappers:

```html
<div class="agents-layout">
<div class="agents-main">
```

2. Immediately after `<div class="grid" id="template-gallery"></div>`, close the main column:

```html
</div><!-- .agents-main -->
```

3. Add the panel there, as the second child of the layout, then close the layout:

(the `<aside>` below, followed by `</div><!-- .agents-layout -->`)

4. Leave every `<div class="modal-overlay" ...>` block where it is, after the closing layout div. The modals are overlays and must not become grid children.

The panel markup:

```html
<aside class="agent-panel" id="agent-panel">
  <div class="ap-head">
    <h2>Chat with your agents</h2>
    <button class="btn" type="button" hx-post="/tasks/agents/chat/new"
            hx-target="#agent-thread" hx-swap="innerHTML">New chat</button>
  </div>
  <div class="achips" id="agent-room" hx-get="/tasks/agents/chat/room"
       hx-trigger="load" hx-swap="outerHTML"></div>
  <div class="ap-thread" id="agent-thread">
    <div class="aempty">Pick who is in the room, then ask.
      Each agent answers in its own message.</div>
  </div>
  <form class="ap-composer" hx-post="/tasks/agents/chat/send"
        hx-target="#agent-thread" hx-swap="beforeend"
        hx-on::after-request="this.reset()">
    <input type="text" name="message" autocomplete="off"
           placeholder="Ask the room something">
    <button class="btn primary" type="submit">Send</button>
  </form>
  <div class="ap-history">
    <h3>Earlier</h3>
    <p class="asidenote" id="agent-chatlist"
       hx-get="/tasks/agents/chat/chats"
       hx-trigger="load, agent-chats-changed from:body"
       hx-swap="outerHTML">Loading...</p>
  </div>
</aside>
```

Add the script tag before `</body>`:

```html
<script src="/tasks/static/agent-chat.js"></script>
```

- [ ] **Step 5: Add the styles**

Create `mcp-servers/tasks/static/agent-chat.css`. It uses the variables `agents.html` already defines (`--panel`, `--text-2` and friends), so it inherits the page's theme rather than restating it:

```css
/* The agent chat panel. Sits in the space the card grid already leaves: the
   page wrapper is 1640px while .grid caps at 792px. */
.agents-layout {
  display: grid; gap: 24px; align-items: start;
  grid-template-columns: minmax(0, 1fr) minmax(360px, 420px);
}
.agents-main { min-width: 0; }

.agent-panel {
  position: sticky; top: 16px;
  display: flex; flex-direction: column; gap: 12px;
  min-width: 0; max-height: calc(100vh - 32px);
  padding: 16px; border-radius: 14px;
  background: var(--panel); border: 1px solid rgba(255, 255, 255, .06);
}
.ap-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.ap-head h2 { margin: 0; font-size: 15px; }
.achips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip {
  padding: 4px 10px; border-radius: 999px; font-size: 12.5px; cursor: pointer;
  background: transparent; color: var(--text-2);
  border: 1px solid rgba(255, 255, 255, .14);
}
.chip.in { background: rgba(255, 255, 255, .10); color: inherit; }
.ap-thread { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 12px; }
.am { display: flex; gap: 10px; }
.am.user { justify-content: flex-end; }
.am.user .ab {
  max-width: 80%; padding: 8px 12px; border-radius: 14px;
  background: rgba(255, 255, 255, .10); white-space: pre-wrap;
}
.aav {
  flex: 0 0 26px; width: 26px; height: 26px; border-radius: 50%;
  display: grid; place-items: center; font-size: 12px;
  background: rgba(255, 255, 255, .10);
}
.abody { min-width: 0; }
.awho { font-size: 12px; color: var(--text-2); margin-bottom: 2px; }
.atext { white-space: pre-wrap; overflow-wrap: anywhere; }
.am.note { font-size: 12.5px; color: var(--text-2); font-style: italic; }
.aworking { font-size: 12.5px; color: var(--text-2); }
.acalls { margin: 6px 0; padding-left: 18px; font-size: 12.5px; }
.aargs { color: var(--text-2); overflow-wrap: anywhere; }
.aactions { display: flex; gap: 8px; margin-top: 6px; }
.ap-composer { display: flex; gap: 8px; }
.ap-composer input {
  flex: 1; min-width: 0; padding: 9px 12px; border-radius: 10px;
  background: rgba(255, 255, 255, .06); color: inherit;
  border: 1px solid rgba(255, 255, 255, .12);
}
.ap-history h3 { margin: 0 0 6px; font-size: 12px; color: var(--text-2); font-weight: 600; }
.achatrow { display: flex; align-items: center; gap: 4px; }
.achatopen {
  flex: 1; min-width: 0; text-align: left; padding: 5px 8px; border-radius: 8px;
  background: transparent; color: inherit; border: 0; cursor: pointer;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12.5px;
}
.achatrow.active .achatopen { background: rgba(255, 255, 255, .08); }
.achatdel { background: transparent; border: 0; color: var(--text-2); cursor: pointer; }
.asidenote { font-size: 12.5px; color: var(--text-2); }

/* Below this width the cards want the whole row, so the panel goes under. */
@media (max-width: 1180px) {
  .agents-layout { grid-template-columns: 1fr; }
  .agent-panel { position: static; max-height: none; }
}
```

- [ ] **Step 6: Add the client script**

Create `mcp-servers/tasks/static/agent-chat.js`:

```javascript
/* The small amount of client the panel needs.
   Everything else is server-rendered, on purpose: there is then no browser-side
   model of the conversation that can drift from the server's. */
(function () {
  "use strict";

  // Auth: HTMX requests carry the Open WebUI login token as a bearer header.
  // The SSE stream cannot, because EventSource cannot set headers, so that one
  // relies on the same-origin cookie instead.
  document.body.addEventListener("htmx:configRequest", function (e) {
    if (e.detail.path && e.detail.path.indexOf("/tasks/agents/chat") !== 0) return;
    var token = localStorage.getItem("token");
    if (token) { e.detail.headers["Authorization"] = "Bearer " + token; }
  });

  function thread() { return document.getElementById("agent-thread"); }

  function toBottom() {
    var el = thread();
    if (el) { el.scrollTop = el.scrollHeight; }
  }

  document.body.addEventListener("htmx:afterSwap", toBottom);
  document.body.addEventListener("htmx:sseMessage", toBottom);

  // When the round closes, stop the element listening. The SSE extension leaves
  // sse-connect in place after closing, and a live attribute is an invitation
  // for a later pass to reconnect and re-run a round we have already paid for.
  document.body.addEventListener("htmx:sseClose", function () {
    var open = document.querySelectorAll(".astream[sse-connect]");
    for (var i = 0; i < open.length; i++) {
      open[i].removeAttribute("sse-connect");
    }
    var work = document.querySelector(".awork");
    if (work) { work.innerHTML = ""; }
    toBottom();
  });
})();
```

- [ ] **Step 7: Run the tests to verify they pass**

```bash
python -m pytest tests/test_agent_chat_page.py tests/test_agents_page_access.py -q
```

Expected: 6 passed plus the existing page-access tests still passing.

- [ ] **Step 8: Run every test this feature touches**

```bash
python -m pytest tests/test_agent_chat_store.py tests/test_agent_chat_render.py \
  tests/test_agent_chat_round.py tests/test_agent_chat_approval.py \
  tests/test_agent_chat_rooms.py tests/test_agent_chat_page.py \
  tests/test_agent_turn_resume.py tests/test_agent_turn_endpoint.py \
  tests/test_agents_speak.py tests/test_agent_chat_endpoint.py -q
```

Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add mcp-servers/tasks/main.py \
        mcp-servers/tasks/static/agents.html \
        mcp-servers/tasks/static/agent-chat.css \
        mcp-servers/tasks/static/agent-chat.js \
        mcp-servers/tasks/tests/test_agent_chat_page.py
git commit -m "Show the agent chat panel on the AI Agents page"
```

---

### Task 7: Prove it on the real site

**STOP. Do not deploy without Ralph saying yes.** Deploying is his call every time. Present what would change and wait.

**Files:**
- Create: `mcp-servers/tasks/tests/browser/test_agent_panel_live.py`
- Modify: `.deploy-state` (written by the deploy script, not by hand)

**Interfaces:**
- Consumes: the deployed panel.
- Produces: evidence.

- [ ] **Step 1: Ask, and wait**

Tell Ralph exactly this: the deploy is the `tasks` service only, it needs a rebuild because static files are baked into the image rather than bind-mounted, migration 047 is additive and idempotent, and there is no gateway, Caddy or compose change. Then wait for a yes.

- [ ] **Step 2: Deploy**

```bash
ORCH_HOST=46.224.193.25 ./scripts/deploy_orchestrator.sh
```

If `rsync` is missing (it is absent from Git Bash on Windows), fall back to one `scp` per changed file, rebuild `tasks`, and update `.deploy-state`, which is JSON (`{"sha": ..., "deployed_at": ..., "deployed_by": ...}`) and breaks the next deploy if a bare SHA is written into it.

Never deploy the local `mcp-servers/tasks/templates.py`; the server's copy is ahead. Never touch `.env`.

- [ ] **Step 3: Confirm the service and the migration**

Run each as a direct ssh argument, not piped into `ssh bash -s`: a script piped on stdin is silently truncated when it runs `docker exec -i`, because docker eats the rest from the same stdin.

```bash
curl -fsS https://ai-ui.coolestdomain.win/tasks/healthz
ssh root@46.224.193.25 "docker exec tasks python -c \"import routes_agent_chat; print('ok')\""
ssh root@46.224.193.25 "docker exec openwebui-db psql -U postgres -d openwebui -c '\\d tasks.agent_chats'"
```

Expected: healthz OK, `ok`, and the table with its `pending` column.

- [ ] **Step 4: Write the live check**

Create `mcp-servers/tasks/tests/browser/test_agent_panel_live.py`. It drives Playwright (already installed in the `tasks` container, with Chromium) against the real site as a real signed-in person, and **asserts on the rendered DOM**. Reading stored rows instead of the screen is what let the previous attempt ship broken.

```python
"""The panel, on the real site, checked the way a person sees it.

Asserts on rendered text in the browser. The predecessor of this test asserted
on stored `content` while Open WebUI rendered `output`, so it passed on a
screen that was visibly wrong.
"""
import os

import pytest
from playwright.async_api import async_playwright

BASE = os.environ.get("AIUI_BASE", "https://ai-ui.coolestdomain.win")
TOKEN = os.environ.get("AIUI_TOKEN", "")


@pytest.mark.skipif(not TOKEN, reason="needs AIUI_TOKEN for a real sign-in")
async def test_two_agents_answer_in_two_separate_bubbles():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto(BASE)
        await page.evaluate("t => localStorage.setItem('token', t)", TOKEN)
        await page.goto(BASE + "/tasks/agents")
        await page.wait_for_selector("#agent-room .chip")

        chips = page.locator("#agent-room .chip")
        first = await chips.nth(0).inner_text()
        second = await chips.nth(1).inner_text()
        await chips.nth(0).click()
        await chips.nth(1).click()
        await page.wait_for_selector("#agent-room .chip.in >> nth=1")

        await page.fill(".ap-composer input", "say hello in one short line")
        await page.click(".ap-composer button")

        # Two agent rows, drawn by us, in the order they were seated.
        await page.wait_for_selector("#agent-thread .am.agent >> nth=1",
                                     timeout=180000)
        rows = page.locator("#agent-thread .am.agent")
        assert await rows.count() >= 2
        who = [await rows.nth(i).locator(".awho").inner_text()
               for i in range(2)]
        assert who == [first.strip(), second.strip()], who

        # Nothing from the old approach leaked into what a person can read.
        body = await page.locator("#agent-thread").inner_text()
        assert "aiui:turns" not in body
        assert "<!--" not in body
        assert not body.strip().startswith(first.strip() + ":")

        await page.screenshot(path="/tmp/agent-panel.png", full_page=True)
        await browser.close()
```

- [ ] **Step 5: Run it in the container**

```bash
ssh root@46.224.193.25 "docker exec -e AIUI_TOKEN=<token> tasks sh -lc 'cd /app && python -m pytest tests/browser/test_agent_panel_live.py -q'"
```

Expected: 1 passed.

- [ ] **Step 6: Look at the screenshot**

Copy `/tmp/agent-panel.png` off the container and **actually open it**. The test passing is not the check on its own; the previous attempt had a passing test and a broken screen. Confirm by eye: two separate rows, the right names, no stray label, no marker, no comment text.

```bash
ssh root@46.224.193.25 "docker cp tasks:/tmp/agent-panel.png /tmp/agent-panel.png"
scp root@46.224.193.25:/tmp/agent-panel.png ./agent-panel.png
```

- [ ] **Step 7: Send the screenshot to Ralph and wait for his word**

He has caught two of these with his own eyes. Do not call the feature verified before he has looked.

- [ ] **Step 8: Commit the live check**

```bash
git add mcp-servers/tasks/tests/browser/test_agent_panel_live.py
git commit -m "Check the panel on the real site, against the rendered page"
```

---

## Notes for whoever executes this

- `_turn_for` and `_agents_for` both live in `routes_agent_turn.py`. `routes_agents.py` imports them with `from routes_agent_turn import ...`, and its tests monkeypatch the name in the importing module. This plan follows that convention exactly, which is why the tests patch `routes_agent_chat._turn_for` and not `routes_agent_turn._turn_for`.
- The tests reload `agent_chat_store` and `routes_agent_chat` per test app, because `_SESSIONS` is module-level state and would otherwise leak between tests.
- If a step's expected output does not match, stop and say so rather than adjusting the test to fit. Every real defect in this feature's history was found by running code against reality, and every one that was missed was missed by reasoning about it.
