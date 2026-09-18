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

    async def turn(email, agent, messages, names=(), **kw):
        seen.append({"agent": agent["id"],
                     # What the round handed this agent besides the
                     # conversation: the roster with everybody's job, and the
                     # block describing what this person actually has.
                     "roster": kw.get("roster"),
                     "graph": kw.get("graph"),
                     "may_pass": any(
                         "reply with exactly PASS" in (m.get("content") or "")
                         for m in messages)})
        reply = (answers or {}).get(agent["name"], f'{agent["name"]} here')
        return {"answer": reply, "notes": [],
                "agent": {"id": agent["id"], "name": agent["name"]}}

    async def no_graph(email, question=""):
        return ""

    monkeypatch.setattr(routes_agent_chat, "_agents_for", agents_for)
    monkeypatch.setattr(routes_agent_chat, "_turn_for", turn)
    # Real I/O, like the store above: a round reads the person's whole
    # account before the first agent speaks. The tests that are about the
    # graph patch this again with something that answers.
    monkeypatch.setattr(routes_agent_chat.agent_graph, "graph_block", no_graph)
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


def test_a_collective_word_reaches_everyone_without_compelling_them(monkeypatch):
    """A reversal, and the reasoning it overturns is worth keeping.

    This used to assert the opposite: "the room was addressed", so nobody
    could pass. That reads correctly and produces something nobody wants.
    Reported with a screenshot 2026-09-14: seven agents, "hey everyone", and
    seven replies of "I'm here, what do you need?".

    Addressing a room is not the same as putting a question to every person
    in it. Say "hey everyone" to seven people and one or two answer. Naming
    an agent is still a question put to that agent, which the test below
    still pins.
    """
    app, mod, seen, _ = _app(monkeypatch)
    _ask(app, "hi team")
    assert [t["agent"] for t in seen] == [ADA["id"], MIA["id"]], (
        "a collective word must still reach everybody")
    assert all(t["may_pass"] for t in seen), (
        "the room was addressed, not interrogated one by one")


def test_a_follow_on_goes_back_to_whoever_is_mid_job(monkeypatch):
    """"go ahead" is not a question for the room. Ralph, 2026-09-18: Rex was
    part way through building a page and every short reply after it went to
    all seven agents, who each had to decide whether it was theirs."""
    app, mod, seen, _ = _app(monkeypatch, answers={"Ada": "PASS",
                                                   "Mia": "On it."})
    c = TestClient(app)
    c.post("/tasks/agents/chat/send", data={"message": "mia start the draft"},
           headers=_hdr())
    c.get("/tasks/agents/chat/stream", headers=_hdr())
    seen.clear()
    c.post("/tasks/agents/chat/send", data={"message": "go ahead"},
           headers=_hdr())
    c.get("/tasks/agents/chat/stream", headers=_hdr())
    assert [t["agent"] for t in seen] == [MIA["id"]], (
        "the follow on went to the room instead of to Mia")
    assert not seen[0]["may_pass"], "it was asked, so it cannot pass"


def test_a_new_subject_still_reaches_the_room(monkeypatch):
    """The other half of the rule above: a message that carries its own
    subject is not a follow on, however recently somebody spoke."""
    app, mod, seen, _ = _app(monkeypatch)
    c = TestClient(app)
    c.post("/tasks/agents/chat/send", data={"message": "mia start the draft"},
           headers=_hdr())
    c.get("/tasks/agents/chat/stream", headers=_hdr())
    seen.clear()
    c.post("/tasks/agents/chat/send",
           data={"message": "what does everybody think we should charge for "
                            "the new plan, and why that number"},
           headers=_hdr())
    c.get("/tasks/agents/chat/stream", headers=_hdr())
    assert sorted(t["agent"] for t in seen) == sorted([ADA["id"], MIA["id"]])


def test_the_room_reads_the_account_once_and_gives_it_to_everybody(monkeypatch):
    """Ralph, 2026-09-18: "make sure the graph connected to the agents so
    agents use the graph". It was wired to every ordinary model through an
    Open WebUI inlet filter and to none of the agents, because an agent turn
    is a direct API call that never passes through that filter.

    Once per question, not once per agent: _assemble_live reads the whole
    account, and a room of seven answering one question would read it seven
    times for an answer that cannot have changed in between."""
    app, mod, seen, _ = _app(monkeypatch)
    asked = []

    async def fake_block(user_email, question=""):
        asked.append((user_email, question))
        return "WHAT THEY HAVE"

    monkeypatch.setattr(mod.agent_graph, "graph_block", fake_block)
    _ask(app, "what am I working on")

    assert asked == [(EMAIL, "what am I working on")], asked
    assert [t["graph"] for t in seen] == ["WHAT THEY HAVE"] * len(seen)


def test_every_agent_is_told_who_the_others_are_and_what_they_do(monkeypatch):
    """The roster travels with the turn, so the brief can say "Rex
    (programmer)" rather than listing bare names and letting each agent guess
    at the others' jobs."""
    app, mod, seen, _ = _app(monkeypatch)
    _ask(app, "what should we do about the invoices")
    for turn in seen:
        assert [a["id"] for a in turn["roster"]] == [ADA["id"], MIA["id"]]


def test_a_graph_that_fails_does_not_stop_the_round(monkeypatch):
    """It is an improvement to an answer the person is getting either way."""
    app, mod, seen, _ = _app(monkeypatch)

    async def broken(user_email, question=""):
        raise RuntimeError("no database")

    monkeypatch.setattr(mod.agent_graph, "graph_block", broken)
    _, body = _ask(app, "what am I working on")
    assert "Ada here" in body


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


# Copied from tasks.agent_chats on production, 2026-09-17, not written by
# hand. An agent on Auto (Smart) passes, and the pipe appends its route
# footer (open-webui-functions/auto_smart_pipe.py _footer), so the reply was
# drawn as a bubble reading PASS, and it counted as an answer, which kept
# the everybody-passed fallback from ever running.
STORED_SMART_PASS = ("PASS\n\n*Auto (Smart): routed to the paid general "
                     "model `gpt-5.5`.*")
# Also stored, from Kai. It starts with PASS and then says what the agent
# did, so it is an answer, and it stays one.
STORED_PASS_THEN_ANSWER = (
    "PASS\n\n(create-me-a-shoe-website-fe02: I inspected the files. I read "
    "public/index.html and the root index.html, but both read results were "
    "shortened by the tool.)")


def test_a_pass_with_a_router_footer_is_still_a_pass():
    import routes_agent_chat as mod
    assert mod._is_pass(STORED_SMART_PASS)
    # The same shape with punctuation, and the Auto (Free) router's footer
    # (auto_router_pipe.py _footer), which has the same form.
    assert mod._is_pass("PASS.\n\n*Auto (Smart): routed to the free code "
                        "model `qwen/qwen3-coder:free`.*")
    assert mod._is_pass("PASS\n\n*Auto-routed to the free general model "
                        "`meta-llama/llama-3.3-70b-instruct:free`.*")


def test_a_footer_does_not_turn_an_answer_into_a_pass():
    import routes_agent_chat as mod
    assert not mod._is_pass(STORED_PASS_THEN_ANSWER)
    assert not mod._is_pass("Here is the plan.\n\n*Auto (Smart): routed to "
                            "the paid general model `gpt-5.5`.*")
    assert not mod._is_pass("PASS on the blue one, take the red.\n\n*Auto "
                            "(Smart): routed to the paid general model "
                            "`gpt-5.5`.*")
    # A footer alone is not a pass either: there is nothing it is declining.
    assert not mod._is_pass("\n\n*Auto (Smart): routed to the paid general "
                            "model `gpt-5.5`.*")


def test_a_pass_under_a_name_label_is_a_pass_and_an_answer_under_one_is_not():
    """Any one word name, not only this room's: the paid move reads a PASS
    with this same function, and it does not know the room's names."""
    import routes_agent_chat as mod
    for said in ("Ada:\n\nPASS", "**Ada**\n\nPASS", "**Nova:**\nPASS.",
                 "Ada:\n\n" + STORED_SMART_PASS):
        assert mod._is_pass(said), said
    for said in ("Ada:\n\n" + STORED_PASS_THEN_ANSWER, "Ada:", "Ada: PASS"):
        assert not mod._is_pass(said), said


def test_a_footered_pass_draws_nothing_and_lets_the_fallback_run(monkeypatch):
    app, mod, seen, _ = _app(monkeypatch, answers={
        "Ada": STORED_SMART_PASS, "Mia": STORED_SMART_PASS})
    _, body = _ask(app, "just thinking out loud")
    assert "PASS" not in body, "a pass was drawn as a message"
    assert len(seen) == 3, "the everybody-passed fallback never ran"
    assert seen[-1]["may_pass"] is False


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
    async def all_pass(email, agent, messages, names=(), **kw):
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
