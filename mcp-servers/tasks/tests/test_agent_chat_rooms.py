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


def test_deleting_the_open_conversation_clears_streaming(monkeypatch):
    """Regression test for a defect a prior review caught: new and open both
    clear streaming when they bump generation, but delete did not. Left
    uncleared, deleting the conversation you are in while a round is still
    marked as running locks the session out of every send for two hours,
    until the idle sweep. TestClient drains the SSE stream to completion
    before returning, so streaming is already False by then; set it back to
    True here to stand in for a round that is still (or still marked as)
    running at the moment of delete.
    """
    app, mod, rows = _app(monkeypatch)
    c = TestClient(app)
    c.post("/tasks/agents/chat/room/add", data={"agent_id": "agent-a"},
           headers=_hdr())
    c.post("/tasks/agents/chat/send", data={"message": "bye"}, headers=_hdr())
    c.get("/tasks/agents/chat/stream", headers=_hdr())
    s = mod.store.get_session(EMAIL)
    s.streaming = True
    c.delete("/tasks/agents/chat/chat/chat-1", headers=_hdr())
    assert mod.store.get_session(EMAIL).streaming is False
