"""One permanent room: everyone listens, whoever has something to say answers.

Nobody seats an agent before asking a question, and there is no list of
conversations. Name an agent and only that agent answers, because you asked
it. Name nobody and every agent hears it and decides for itself.
"""
import importlib

from fastapi import FastAPI
from fastapi.testclient import TestClient

EMAIL = "room-owner@example.com"
ADA = {"id": "agent-research-assistant-0001", "name": "Ada"}
MIA = {"id": "agent-inbox-triage-0002", "name": "Mia"}


def _hdr(email=EMAIL):
    return {"X-User-Email": email}


def _fake_store(mod, monkeypatch):
    """The single conversation row, as a dict."""
    rows: dict[str, dict] = {}

    async def create(email, title, s):
        rows[email] = {"id": "chat-1", "user_email": email, "title": title,
                       "messages": list(s.messages), "summary": s.summary,
                       "pending": dict(s.pending)}
        return "chat-1"

    async def save(email, s):
        row = rows.get(email)
        if row and s.chat_id == row["id"]:
            row.update(messages=list(s.messages), summary=s.summary,
                       pending=dict(s.pending))

    async def newest(email):
        row = rows.get(email)
        return dict(row) if row else None

    monkeypatch.setattr(mod.store, "create_chat", create)
    monkeypatch.setattr(mod.store, "save_chat", save)
    monkeypatch.setattr(mod.store, "newest_chat", newest)
    return rows


def _app(monkeypatch, answers=None, agents=(ADA, MIA)):
    import agent_chat_store
    import routes_agent_chat
    importlib.reload(agent_chat_store)
    importlib.reload(routes_agent_chat)

    seen = []

    async def agents_for(email):
        return list(agents)

    async def turn(email, agent, messages, names=()):
        seen.append({"agent": agent["id"],
                     "may_pass": any(
                         "reply with exactly PASS" in (m.get("content") or "")
                         for m in messages)})
        reply = (answers or {}).get(agent["name"], f'{agent["name"]} here')
        return {"answer": reply, "notes": [],
                "agent": {"id": agent["id"], "name": agent["name"]}}

    monkeypatch.setattr(routes_agent_chat, "_agents_for", agents_for)
    monkeypatch.setattr(routes_agent_chat, "_turn_for", turn)
    rows = _fake_store(routes_agent_chat, monkeypatch)
    app = FastAPI()
    app.include_router(routes_agent_chat.router)
    return app, routes_agent_chat, seen, rows


def _ask(app, text):
    c = TestClient(app)
    c.post("/tasks/agents/chat/send", data={"message": text}, headers=_hdr())
    return c, c.get("/tasks/agents/chat/stream", headers=_hdr()).text


# ------------------------------------------------------------------ speakers

def test_naming_nobody_lets_every_agent_hear_it(monkeypatch):
    app, mod, seen, _ = _app(monkeypatch)
    _, body = _ask(app, "what should I do about the invoices")
    assert [t["agent"] for t in seen] == [ADA["id"], MIA["id"]]
    assert all(t["may_pass"] for t in seen), "an unaddressed agent may pass"
    assert body.count('class="am agent"') == 2


def test_naming_one_agent_means_only_that_agent_answers(monkeypatch):
    app, mod, seen, _ = _app(monkeypatch)
    _, body = _ask(app, "mia, anything urgent in my inbox?")
    assert [t["agent"] for t in seen] == [MIA["id"]]
    assert not seen[0]["may_pass"], "you asked it, so it does not get to pass"
    assert "Mia here" in body
    assert "Ada here" not in body


def test_a_collective_word_reaches_everyone(monkeypatch):
    app, mod, seen, _ = _app(monkeypatch)
    _ask(app, "hi team")
    assert [t["agent"] for t in seen] == [ADA["id"], MIA["id"]]
    assert not any(t["may_pass"] for t in seen), "the room was addressed"


def test_speakers_for_is_the_whole_rule():
    import routes_agent_chat as mod
    named, may_pass = mod._speakers_for("ada, look this up", [ADA, MIA])
    assert [a["id"] for a in named] == [ADA["id"]] and may_pass is False
    everyone, may_pass = mod._speakers_for("what do you think", [ADA, MIA])
    assert [a["id"] for a in everyone] == [ADA["id"], MIA["id"]]
    assert may_pass is True


# ---------------------------------------------------------------- passing

def test_an_agent_with_nothing_to_add_says_nothing(monkeypatch):
    app, mod, seen, _ = _app(monkeypatch, answers={"Mia": "PASS"})
    _, body = _ask(app, "what is a good name for a cat")
    assert len(seen) == 2, "both still heard it"
    assert "Ada here" in body
    assert "PASS" not in body
    assert body.count('class="am agent"') == 1
    stored = mod.store.get_session(EMAIL).messages
    assert not any(m.get("agent_name") == "Mia" for m in stored), \
        "a pass should leave no trace in the conversation"


def test_a_pass_is_recognised_however_it_is_punctuated():
    import routes_agent_chat as mod
    for said in ("PASS", "pass", " Pass. ", '"PASS"', "pass."):
        assert mod._is_pass(said), said
    for said in ("PASS the salt", "I will pass on that", "passport"):
        assert not mod._is_pass(said), said


def test_if_everybody_passes_one_of_them_still_answers(monkeypatch):
    app, mod, seen, _ = _app(monkeypatch, answers={"Ada": "PASS", "Mia": "PASS"})
    _, body = _ask(app, "just thinking out loud")
    # Two heard it and passed, then one was asked again without the option.
    assert len(seen) == 3
    assert seen[-1]["may_pass"] is False
    # This stub passes even when not offered the option, which is the worst
    # case: the room must still say something rather than go silent.
    assert "Nobody had anything to add" in body


def test_the_fallback_prefers_whoever_spoke_last(monkeypatch):
    app, mod, seen, _ = _app(monkeypatch)
    _ask(app, "mia, hello")            # Mia answers, so Mia spoke last
    seen.clear()
    # Now everybody passes on the next message.
    async def all_pass(email, agent, messages, names=()):
        seen.append({"agent": agent["id"],
                     "may_pass": any("reply with exactly PASS" in (m.get("content") or "")
                                     for m in messages)})
        return {"answer": "PASS" if len(seen) <= 2 else "Mia here", "notes": [],
                "agent": {"id": agent["id"], "name": agent["name"]}}
    monkeypatch.setattr(mod, "_turn_for", all_pass)
    c = TestClient(app)
    c.post("/tasks/agents/chat/send", data={"message": "hmm"}, headers=_hdr())
    c.get("/tasks/agents/chat/stream", headers=_hdr())
    assert seen[-1]["agent"] == MIA["id"], "Mia spoke last, so Mia is asked"


# -------------------------------------------------------------- permanence

def test_the_conversation_is_still_there_after_a_restart(monkeypatch):
    app, mod, _, rows = _app(monkeypatch)
    _ask(app, "remember this")
    assert rows[EMAIL]["messages"], "the row holds the conversation"

    # A restart: the in-memory session is gone, the row is not.
    mod.store._SESSIONS.clear()
    c = TestClient(app)
    thread = c.get("/tasks/agents/chat/thread", headers=_hdr()).text
    assert "remember this" in thread
    assert mod.store.get_session(EMAIL).chat_id == "chat-1"


def test_a_second_person_gets_their_own_room(monkeypatch):
    app, mod, _, rows = _app(monkeypatch)
    _ask(app, "mine")
    other = TestClient(app).get("/tasks/agents/chat/thread",
                                headers=_hdr("someone@example.com")).text
    assert "mine" not in other


def test_clearing_empties_the_room_and_keeps_one_row(monkeypatch):
    app, mod, _, rows = _app(monkeypatch)
    c, _ = _ask(app, "forget this")
    mod.store.get_session(EMAIL).summary = "old notes"
    r = c.post("/tasks/agents/chat/clear", headers=_hdr())
    assert r.status_code == 200
    s = mod.store.get_session(EMAIL)
    assert s.messages == [] and s.pending == {} and s.summary == ""
    assert s.chat_id == "chat-1", "the row is emptied, not orphaned"
    assert rows[EMAIL]["messages"] == []
    assert "Every agent hears it" in r.text


def test_clearing_hands_over_a_fresh_buffer(monkeypatch):
    """A round still running holds the old lists and must keep writing into
    them, not into the conversation that replaced them."""
    app, mod, _, _ = _app(monkeypatch)
    c, _ = _ask(app, "first")
    s = mod.store.get_session(EMAIL)
    was = s.messages
    c.post("/tasks/agents/chat/clear", headers=_hdr())
    assert s.messages is not was
    assert was, "the detached buffer still holds the old round"
