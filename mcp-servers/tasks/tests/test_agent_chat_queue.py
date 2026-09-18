"""Sending a second message while the agents are still answering.

Until now the panel refused it: "Still answering, one moment." Ralph hits that
every session, and a chat that turns your message away is not a chat. The
guard behind it is real, two rounds against one conversation would interleave
their replies and cost double, so the round stays single. What changes is that
a message arriving during one is kept and answered next, instead of thrown
back at the person who typed it.
"""
import pytest

import agent_chat_store as store
import routes_agent_chat as chat


class _User:
    email = "someone@example.com"


@pytest.fixture(autouse=True)
def clean():
    store._SESSIONS.clear()
    yield
    store._SESSIONS.clear()


async def _send(text):
    return await chat.agent_chat_send(message=text, user=_User())


async def test_a_message_sent_while_busy_is_kept_not_refused():
    s = store.get_session(_User.email)
    s.streaming = True
    out = await _send("and another thing")
    body = out.body.decode()
    assert "and another thing" in body, "their message did not appear"
    assert "Still answering" not in body
    assert "one moment" not in body
    assert s.queued == ["and another thing"]


async def test_the_queued_message_is_not_in_the_conversation_yet():
    """It has not been answered, and the round in flight is appending to
    s.messages as it goes. Putting it there now would interleave it into the
    middle of an answer that is still being written."""
    s = store.get_session(_User.email)
    s.streaming = True
    await _send("later please")
    assert not any("later please" in (m.get("content") or "")
                   for m in s.messages)


async def test_a_second_stream_is_not_opened_for_a_queued_message():
    """The open one drains the queue. A second EventSource would claim its
    own round and run two at once, which is the thing the guard exists to
    prevent."""
    s = store.get_session(_User.email)
    s.streaming = True
    out = await _send("queued")
    assert "sse" not in out.body.decode().lower()


async def test_the_first_message_still_opens_a_stream():
    s = store.get_session(_User.email)
    assert not s.streaming
    out = await _send("hello")
    assert "sse" in out.body.decode().lower()
    assert s.streaming is True
    assert s.queued == []


async def test_a_new_message_opens_a_turn():
    s = store.get_session(_User.email)
    out = await _send("what is in my inbox?")
    body = out.body.decode()
    assert "aturn" in body
    assert "what is in my inbox?" in body
    assert "sse" in body.lower(), "the stream block is still needed"


async def test_a_queued_message_opens_its_own_turn():
    """It is a separate question and gets its own block, or its answers land
    inside the previous turn and belong to the wrong message."""
    import re
    s = store.get_session(_User.email)
    s.streaming = True
    out = await _send("and my calendar?")
    body = out.body.decode()
    assert "aturn" in body
    assert "hx-swap-oob" in body, "it must not append after the open turn"
    # The id in the response is what the browser actually rendered. It has
    # to be the one the drain later pops and answers under (see
    # _take_queued_turn_id), or the round's answers name a turn nothing on
    # screen has. Parsed out rather than assumed, so this fails loudly if
    # the two diverge instead of passing on a fallback id neither side used.
    rendered_id = re.search(r'id="aturn-([^"]+)"', body).group(1)
    assert s.queued_turn_ids == [rendered_id]


async def test_several_queued_messages_keep_their_order():
    s = store.get_session(_User.email)
    s.streaming = True
    for text in ("one", "two", "three"):
        await _send(text)
    assert s.queued == ["one", "two", "three"]
    # Popped in lockstep with `queued` by _take_queued_turn_id: every send
    # while streaming pushes onto both, so a length mismatch here means a
    # later pop reads the wrong id for the wrong message and falls back to
    # a fresh, unrendered one instead of erroring, which is Critical 2
    # arriving again by a different route.
    assert len(s.queued_turn_ids) == len(s.queued)


async def test_an_empty_message_is_still_refused_while_busy():
    s = store.get_session(_User.email)
    s.streaming = True
    with pytest.raises(Exception):
        await _send("   ")
    assert s.queued == []


async def test_clearing_the_room_empties_the_queue():
    """Otherwise a message typed into the old conversation gets answered
    inside the new one. Same shape as the mid-round bleed this panel already
    had, so it gets its own test rather than a comment."""
    s = store.get_session(_User.email)
    s.streaming = True
    await _send("belongs to the old conversation")
    assert s.queued
    await chat.agent_chat_clear(user=_User())
    assert s.queued == []


async def test_the_queue_survives_being_read_by_the_round():
    """take_queued is what the stream generator calls between rounds. It has
    to remove what it returns, or the same message is answered forever."""
    s = store.get_session(_User.email)
    s.queued = ["first", "second"]
    assert chat._take_queued(s) == "first"
    assert s.queued == ["second"]
    assert chat._take_queued(s) == "second"
    assert s.queued == []
    assert chat._take_queued(s) is None


# --- the round drains it ----------------------------------------------------

class _Req:
    async def is_disconnected(self):
        return False


async def _drain(monkeypatch, s, rounds_seen):
    """Run the stream generator with the round itself stubbed out."""
    async def fake_round(email, sess, agents, request=None, quote=False):
        rounds_seen.append(chat.agent_routing.last_user_text(sess.messages))
        sess.messages.append({
            "role": "assistant", "agent_id": "a", "agent_name": "Ada",
            "content": "ok",
            # What the real round stores, so the tests above it are testing
            # the shape the panel actually reads back.
            "replying_to": (chat.agent_routing.last_user_text(sess.messages)
                            if quote else None)})
        yield {"event": "message", "data": "x"}

    async def no_agents(email):
        return [{"id": "agent-a", "name": "Ada"}]

    monkeypatch.setattr(chat, "_run_round", fake_round)
    monkeypatch.setattr(chat, "_agents_for", no_agents)
    monkeypatch.setattr(chat, "_keep_within_budget",
                        lambda e, sess, a: _nothing())
    monkeypatch.setattr(store, "save_chat", lambda e, sess: _nothing())
    resp = await chat.agent_chat_stream(request=_Req(), user=_User())
    async for _event in resp.body_iterator:
        pass


async def _nothing():
    return None


async def test_the_running_round_answers_what_was_queued(monkeypatch):
    s = store.get_session(_User.email)
    await _send("first")
    s.queued = ["second", "third"]
    seen = []
    await _drain(monkeypatch, s, seen)
    assert seen == ["first", "second", "third"], seen
    assert s.queued == []


async def test_it_stops_when_there_is_nothing_queued(monkeypatch):
    s = store.get_session(_User.email)
    await _send("only one")
    seen = []
    await _drain(monkeypatch, s, seen)
    assert seen == ["only one"]


async def test_streaming_is_released_after_the_queue_drains(monkeypatch):
    """Held for the whole drain, not just the first round, or a second send
    would open its own stream and run beside this one."""
    s = store.get_session(_User.email)
    await _send("first")
    s.queued = ["second"]
    await _drain(monkeypatch, s, [])
    assert s.streaming is False


async def test_a_cleared_room_abandons_whatever_was_queued(monkeypatch):
    """New chat bumps the generation. A round still unwinding must not staple
    the old conversation's queued message onto the new one."""
    s = store.get_session(_User.email)
    await _send("first")
    s.queued = ["belongs to the old one"]
    seen = []

    async def clearing_round(email, sess, agents, request=None, quote=False):
        seen.append(chat.agent_routing.last_user_text(sess.messages))
        sess.generation += 1          # as New chat does, mid round
        yield {"event": "message", "data": "x"}

    monkeypatch.setattr(chat, "_run_round", clearing_round)
    monkeypatch.setattr(chat, "_agents_for",
                        lambda e: _agents_stub())
    monkeypatch.setattr(chat, "_keep_within_budget",
                        lambda e, sess, a: _nothing())
    monkeypatch.setattr(store, "save_chat", lambda e, sess: _nothing())
    resp = await chat.agent_chat_stream(request=_Req(), user=_User())
    async for _event in resp.body_iterator:
        pass
    assert seen == ["first"], "it answered a message from a cleared room"


async def test_each_drained_round_answers_under_the_turn_it_was_given(
        monkeypatch):
    """_take_queued and _take_queued_turn_id both pop from index 0, kept in
    lockstep so the id a drained round wraps its answers in is the one the
    browser actually rendered for that message (see agent_chat_send). If the
    two ever pop out of order, a round answers under a turn nothing on
    screen has for that message: the original Critical, back by a third
    route, on exactly the state a later task is about to touch.

    _run_round is stubbed to record `sess.turn_id` from INSIDE each round,
    the same moment the real one reads it to wrap its fragments, rather than
    reading it after the drain: the drain's own final state can look correct
    even when an earlier round briefly answered under the wrong id.
    """
    s = store.get_session(_User.email)
    await _send("first")
    first_tid = s.turn_id
    s.queued = ["second", "third"]
    # Distinguishable, and distinguishable from first_tid, so a swapped or
    # off-by-one pop shows up as a wrong id rather than an accidental match.
    s.queued_turn_ids = ["tid-for-second", "tid-for-third"]

    seen = []

    async def recording_round(email, sess, agents, request=None,
                              quote=False):
        seen.append((chat.agent_routing.last_user_text(sess.messages),
                    sess.turn_id))
        sess.messages.append({"role": "assistant", "agent_id": "a",
                              "agent_name": "Ada", "content": "ok"})
        yield {"event": "message", "data": "x"}

    monkeypatch.setattr(chat, "_run_round", recording_round)
    monkeypatch.setattr(chat, "_agents_for", lambda e: _agents_stub())
    monkeypatch.setattr(chat, "_keep_within_budget",
                        lambda e, sess, a: _nothing())
    monkeypatch.setattr(store, "save_chat", lambda e, sess: _nothing())
    resp = await chat.agent_chat_stream(request=_Req(), user=_User())
    async for _event in resp.body_iterator:
        pass

    assert seen == [("first", first_tid),
                    ("second", "tid-for-second"),
                    ("third", "tid-for-third")], seen


async def _agents_stub():
    return [{"id": "agent-a", "name": "Ada"}]


# --- a round the browser walked away from ------------------------------------
#
# Production, 2026-09-16 13:39:23 UTC: the person opened App Builder mid round,
# which closes the EventSource. sse-starlette cancels the generator through an
# anyio task group, and anyio cancellation is level triggered: every await
# inside the cancelled scope is cancelled again, the save in the finally block
# included. CancelledError is not an Exception, so the finally aborted before
# it cleared s.streaming, and the five messages sent after that were all
# queued behind a round that no longer existed. Nothing answered them.
#
# These drive the real EventSourceResponse, the way production does, rather
# than cancelling a bare task once: a single task.cancel() is edge triggered
# and lets the await in the finally complete, which is exactly the case that
# does not happen on the server.

async def _walk_away_mid_round(monkeypatch, s, saved, during=None):
    """Run one stream whose agent never answers, and disconnect the client
    while it is thinking. Returns once the response has fully unwound.

    `during`, if given, runs while the agent is thinking: whatever else the
    person does while the round is still in flight."""
    import asyncio

    async def hangs(email, agent, history, names=(), **kw):
        if during is not None:
            await during()
        await asyncio.Event().wait()

    async def slow_save(email, sess):
        # A real UPDATE takes a round trip, which is the await that used to
        # be cancelled out from under the release.
        await asyncio.sleep(0.05)
        saved.append([dict(m) for m in sess.messages])

    monkeypatch.setattr(chat, "_turn_for", hangs)
    monkeypatch.setattr(chat, "_agents_for", lambda e: _agents_stub())
    monkeypatch.setattr(chat, "_keep_within_budget",
                        lambda e, sess, a: _nothing())
    monkeypatch.setattr(store, "save_chat", slow_save)

    resp = await chat.agent_chat_stream(request=_Req(), user=_User())
    sent = []

    async def send(message):
        sent.append(message)

    async def receive():
        # Long enough for the round to reach the agent, then the browser
        # navigates away.
        await asyncio.sleep(0.2)
        return {"type": "http.disconnect"}

    scope = {"type": "http", "asgi": {"spec_version": "2.3"}, "headers": []}
    try:
        await asyncio.wait_for(resp(scope, receive, send), timeout=10)
    except BaseException as exc:                     # noqa: BLE001
        if isinstance(exc, asyncio.TimeoutError):
            raise
    # The save is shielded from the cancel, so it may still be finishing.
    for _ in range(100):
        if saved:
            break
        await asyncio.sleep(0.01)


def _no_db(monkeypatch):
    async def created(email, title, sess):
        return "chat-1"

    async def newest(email):
        return None

    async def no_graph(email, question=""):
        return ""

    monkeypatch.setattr(store, "create_chat", created)
    monkeypatch.setattr(store, "newest_chat", newest)
    # The Brain reads the whole account over the database, and a round now
    # does that before the first agent speaks. Left real, it is the await the
    # disconnect lands in, so the round never reaches the agent and a test
    # about what happens DURING a turn never gets there.
    monkeypatch.setattr(chat.agent_graph, "graph_block", no_graph)


async def test_a_round_the_browser_left_releases_the_room(monkeypatch):
    _no_db(monkeypatch)
    s = store.get_session(_User.email)
    await _send("build me a shoe shop")
    assert s.streaming is True
    saved = []
    await _walk_away_mid_round(monkeypatch, s, saved)

    assert s.streaming is False, (
        "a cancelled round kept the room, so every later message is queued "
        "behind nothing and never answered")
    out = await _send("are you still there?")
    body = out.body.decode()
    assert s.queued == [], "the next message was queued behind a dead round"
    assert "sse" in body.lower(), "the next message did not open its stream"


async def test_a_round_the_browser_left_still_saves_the_conversation(
        monkeypatch):
    """Releasing the room must not come at the cost of the save: the question
    was asked, and a reload should still show it."""
    _no_db(monkeypatch)
    s = store.get_session(_User.email)
    await _send("build me a shoe shop")
    saved = []
    await _walk_away_mid_round(monkeypatch, s, saved)
    assert saved, "the save never ran"
    assert any(m.get("content") == "build me a shoe shop"
               for m in saved[-1]), saved


async def test_messages_queued_behind_a_cancelled_round_are_kept(monkeypatch):
    """The drain that would have answered them died with the round. Left in
    s.queued they are invisible on reload, lost on restart, and answered out
    of order after whatever the person sends next, under turn ids from a page
    that is gone. So they move into the conversation as unanswered turns,
    under the ids the page already drew, and the next round's agents read
    them as history."""
    _no_db(monkeypatch)
    s = store.get_session(_User.email)
    await _send("build me a shoe shop")
    await _send("and make it blue")         # queued, the round is running
    assert s.queued == ["and make it blue"]
    queued_tid = s.queued_turn_ids[0]
    saved = []
    await _walk_away_mid_round(monkeypatch, s, saved)

    assert s.queued == [] and s.queued_turn_ids == []
    kept = [m for m in s.messages
            if m.get("role") == "user" and m.get("content") == "and make it blue"]
    assert len(kept) == 1, s.messages
    assert kept[0]["turn_id"] == queued_tid
    assert any(m.get("content") == "and make it blue" for m in saved[-1]), \
        "kept in memory but not in the row, so a restart still loses it"
    # Unanswered, but the tail must still not read as "user": a reconnecting
    # EventSource would take that as a round nobody has run and run one
    # without holding the room.
    assert s.messages[-1].get("role") != "user", s.messages
    assert "and make it blue" in chat.render.thread(s.messages)


async def test_a_cancelled_round_leaves_a_cleared_rooms_new_round_alone(
        monkeypatch):
    """The generation guard, on the cancel path. The person clears the room
    while the old round is thinking, sends again (a new round owns the room)
    and queues a message behind that one. When the old round is cancelled it
    must neither release the new round's claim nor take the new round's
    queue for itself."""
    _no_db(monkeypatch)
    s = store.get_session(_User.email)
    await _send("belongs to the old room")

    async def clear_and_carry_on():
        await chat.agent_chat_clear(user=_User())
        await _send("first in the new room")
        await _send("queued in the new room")

    await _walk_away_mid_round(monkeypatch, s, [], during=clear_and_carry_on)

    assert s.streaming is True, "the old round released the new round's claim"
    assert s.queued == ["queued in the new room"], s.queued
    assert len(s.queued_turn_ids) == 1
    assert not any(m.get("content") == "queued in the new room"
                   for m in s.messages), s.messages


async def test_a_reconnect_after_a_cancelled_round_does_not_run_one(
        monkeypatch):
    _no_db(monkeypatch)
    s = store.get_session(_User.email)
    await _send("build me a shoe shop")
    await _send("and make it blue")
    await _walk_away_mid_round(monkeypatch, s, [])

    ran = []

    async def must_not_run(email, sess, agents, request=None, quote=False):
        ran.append(1)
        yield {"event": "message", "data": "x"}

    monkeypatch.setattr(chat, "_run_round", must_not_run)
    resp = await chat.agent_chat_stream(request=_Req(), user=_User())
    async for _event in resp.body_iterator:
        pass
    assert ran == [], "a reconnect ran a round nobody asked for"


# --- a failed turn renders as a failure, not a bubble ------------------------
#
# _turn_for never raises: one agent blowing up must not cost the others their
# answer. So a failure comes back as an ordinary answer string, and the round
# is the only place that can tell one from a real answer.

async def test_a_failed_agent_renders_as_a_failure(monkeypatch):
    """_turn_for never raises; it returns the failure sentence as an answer,
    which is exactly how a failure became a bubble."""
    import routes_agent_turn as rt
    s = store.get_session(_User.email)
    await _send("hi")

    async def failing(email, agent, history, names=(), **kw):
        return {"answer": rt._turn_failed_sentence("Ada"), "notes": [],
                "agent": {"id": "agent-a", "name": "Ada"}}

    monkeypatch.setattr(chat, "_turn_for", failing)
    monkeypatch.setattr(chat, "_agents_for",
                        lambda e: _agents_stub())
    monkeypatch.setattr(chat, "_keep_within_budget",
                        lambda e, sess, a: _nothing())
    monkeypatch.setattr(store, "save_chat", lambda e, sess: _nothing())
    events = []
    resp = await chat.agent_chat_stream(request=_Req(), user=_User())
    async for event in resp.body_iterator:
        events.append(str(event))
    assert any("afail" in e for e in events), events
    # Not just "afail somewhere in the stream": the same answer must not ALSO
    # have gone out as a bubble, which is exactly the bug being fixed here.
    assert not any('class=\\"am agent\\"' in e or 'class="am agent"' in e
                  for e in events), events
    assert any(m.get("role") == "failure" for m in s.messages), s.messages
    assert not any(m.get("role") == "assistant" for m in s.messages), \
        "the failure was also stored as an answer"


async def test_the_free_router_giving_up_also_renders_as_a_failure(
        monkeypatch):
    """agent_runner.ROUTER_EXHAUSTED comes back as an ordinary answer string
    the same way _turn_failed_sentence does, and it is the case Ralph
    actually hits: an agent left on Auto (Free) when the shared pool runs
    out. Left unmatched it would still read as a real reply."""
    from agent_runner import ROUTER_EXHAUSTED
    s = store.get_session(_User.email)
    await _send("hi")

    async def exhausted(email, agent, history, names=(), **kw):
        return {"answer": ROUTER_EXHAUSTED, "notes": [],
                "agent": {"id": "agent-a", "name": "Ada"}}

    monkeypatch.setattr(chat, "_turn_for", exhausted)
    monkeypatch.setattr(chat, "_agents_for",
                        lambda e: _agents_stub())
    monkeypatch.setattr(chat, "_keep_within_budget",
                        lambda e, sess, a: _nothing())
    monkeypatch.setattr(store, "save_chat", lambda e, sess: _nothing())
    events = []
    resp = await chat.agent_chat_stream(request=_Req(), user=_User())
    async for event in resp.body_iterator:
        events.append(str(event))
    assert any("afail" in e for e in events), events
    assert any("Auto (Free)" in e for e in events), events
    assert not any('class=\\"am agent\\"' in e or 'class="am agent"' in e
                  for e in events), events
    failures = [m for m in s.messages if m.get("role") == "failure"]
    assert failures, s.messages
    assert failures[0]["reason"] == "The free models are all busy right now."
    assert "Auto (Free)" in failures[0]["fix"]


async def test_the_everybody_passed_fallback_call_can_also_fail(monkeypatch):
    """Every agent passes, so the round makes one more call, without the
    option to pass, rather than leave the room silent. That extra call is
    exactly as capable of failing as any other _turn_for call, and it is a
    second, separate call site from the per-agent loop above: recognising a
    failure there does nothing for this one unless the two share the same
    check."""
    import routes_agent_turn as rt
    s = store.get_session(_User.email)
    await _send("hi")

    calls = []

    async def pass_once_then_fail(email, agent, history, names=(), **kw):
        calls.append(1)
        if len(calls) == 1:
            # The one agent in the room, asked with the option to pass.
            return {"answer": "PASS", "notes": [],
                    "agent": {"id": "agent-a", "name": "Ada"}}
        # The fallback call, made without that option, and it blows up.
        return {"answer": rt._turn_failed_sentence("Ada"), "notes": [],
                "agent": {"id": "agent-a", "name": "Ada"}}

    monkeypatch.setattr(chat, "_turn_for", pass_once_then_fail)
    monkeypatch.setattr(chat, "_agents_for",
                        lambda e: _agents_stub())
    monkeypatch.setattr(chat, "_keep_within_budget",
                        lambda e, sess, a: _nothing())
    monkeypatch.setattr(store, "save_chat", lambda e, sess: _nothing())
    events = []
    resp = await chat.agent_chat_stream(request=_Req(), user=_User())
    async for event in resp.body_iterator:
        events.append(str(event))
    assert len(calls) == 2, "expected a pass, then the fallback's own call"
    assert any("afail" in e for e in events), events
    assert not any('class=\\"am agent\\"' in e or 'class="am agent"' in e
                  for e in events), events
    # The wrong old behaviour was not silence, it was a real-looking bubble
    # OR the "nobody had anything to add" note; a failure must not read as
    # either.
    assert not any("Nobody had anything to add" in e for e in events), events
    assert any(m.get("role") == "failure" for m in s.messages), s.messages
    assert not any(m.get("role") == "note" for m in s.messages), s.messages


# --- where a queued message actually lands ----------------------------------

# Found by reading the DOM wiring rather than by a failing test, which is the
# wrong way round and worth writing down. The composer appends to
# #agent-thread with hx-swap="beforeend", and the open round's answers used
# to append INSIDE .astream .alive, itself a child of #agent-thread. So a
# queued bubble appended to the thread ordinarily would have landed BELOW
# every answer, including the answer to itself: you would see your own
# question underneath its reply.
#
# That first fix was a bubble named `queued_bubble`, targeted out of band
# straight at `.alive` (`QUEUED_TARGET`). It is gone now, not merely unused:
# a queued message needs a whole turn, not one bubble, and a round's answers
# no longer land in `.alive` either (they are addressed by turn id, out of
# band, wherever they land in the DOM; see into_turn/turn_status in
# agent_chat_render.py). Keeping queued_bubble around after nothing called
# it would have meant a function whose docstring described a placement that
# stopped happening. See test_a_new_message_opens_a_turn and
# test_a_queued_message_opens_its_own_turn above for what replaced it.

async def test_sending_while_busy_returns_the_out_of_band_bubble():
    s = store.get_session(_User.email)
    s.streaming = True
    out = await _send("second")
    body = out.body.decode()
    assert "hx-swap-oob" in body
    assert "second" in body


async def test_the_first_message_uses_the_ordinary_bubble():
    """Nothing is out of band when there is no live area to aim at."""
    s = store.get_session(_User.email)
    out = await _send("first")
    body = out.body.decode()
    assert "hx-swap-oob" not in body
    assert "first" in body


# --- the reply says what it is answering ------------------------------------

# Ralph: "in human chat you long press the message to reply. What I need is
# the agent will reply on the message so it is not confusing." Nothing to
# press: when more than one of your messages is on screen unanswered, the
# answer carries the one it belongs to.

def test_an_answer_can_carry_the_question_it_answers():
    from agent_chat_render import agent_bubble
    html = agent_bubble("Mia", "Here are your emails",
                        replying_to="what is in my inbox?")
    assert "what is in my inbox?" in html
    assert "aquote" in html


def test_an_ordinary_answer_carries_no_quote():
    """One question, one answer, nothing above it to confuse it with. A quote
    there just repeats the line directly above."""
    from agent_chat_render import agent_bubble
    assert "aquote" not in agent_bubble("Mia", "Here are your emails")


def test_the_quoted_question_is_escaped_like_any_other_user_text():
    from agent_chat_render import agent_bubble
    html = agent_bubble("Mia", "ok",
                        replying_to='<img src=x onerror="alert(1)">')
    assert "<img" not in html
    assert "&lt;img" in html


def test_a_long_question_is_trimmed_not_reprinted():
    """Otherwise a paragraph you typed reappears above every answer to it,
    and with two agents answering you would read it twice."""
    from agent_chat_render import agent_bubble
    long = "tell me about " + ("everything " * 60)
    html = agent_bubble("Mia", "ok", replying_to=long)
    assert len(html) < len(long)
    assert "\u2026" in html or "..." in html


def test_a_replayed_conversation_shows_the_same_quotes():
    """What you saw before a reload is what you see after it. The decision is
    stored rather than recomputed, because after a reload the messages are in
    order and nothing looks ambiguous any more."""
    from agent_chat_render import thread
    html = thread([
        {"role": "user", "content": "what is in my inbox?"},
        {"role": "user", "content": "and my calendar?"},
        {"role": "assistant", "agent_name": "Mia", "content": "Your emails",
         "replying_to": "what is in my inbox?"},
        {"role": "assistant", "agent_name": "Ada", "content": "Your day",
         "replying_to": "and my calendar?"},
    ])
    assert html.count("aquote") == 2
    assert "what is in my inbox?" in html
    assert "and my calendar?" in html


def test_a_replayed_answer_without_one_shows_no_quote():
    from agent_chat_render import thread
    html = thread([
        {"role": "user", "content": "hi"},
        {"role": "assistant", "agent_name": "Mia", "content": "hello"},
    ])
    assert "aquote" not in html


async def test_answers_quote_the_question_when_more_are_waiting(monkeypatch):
    """The case Ralph described: several messages on screen, and no way to
    tell which one an answer belongs to."""
    s = store.get_session(_User.email)
    await _send("what is in my inbox?")
    s.queued = ["and my calendar?"]
    seen = []
    await _drain(monkeypatch, s, seen)
    answers = [m for m in s.messages if m.get("role") == "assistant"]
    assert len(answers) == 2, s.messages
    assert answers[0]["replying_to"] == "what is in my inbox?"
    assert answers[1]["replying_to"] == "and my calendar?"


async def test_an_ordinary_exchange_quotes_nothing(monkeypatch):
    """One question, one answer. The quote would repeat the line above it."""
    s = store.get_session(_User.email)
    await _send("hi")
    await _drain(monkeypatch, s, [])
    answers = [m for m in s.messages if m.get("role") == "assistant"]
    assert answers
    assert not any(a.get("replying_to") for a in answers)


# ---------------------------------------------------------------------------
# An agent may not run on a pipe that calls back into this service. Measured
# 2026-09-10: two agents set to Auto (Free) opened dozens of chats a second
# and restarted Open WebUI twice, because the pipe asks /agents/chat who
# should answer, that matches the agent, and the agent runs again. The pipe's
# own route_only guard does not help: it only short-circuits when NO agent
# matches, and an agent running itself always matches.
# ---------------------------------------------------------------------------


def test_the_callback_models_are_named_not_guessed():
    """Named rather than pattern-matched on "auto" or "pipe", because the
    property that matters is calling back into this service, and no naming
    convention carries that. Regenerate with:
      select id from public.function
       where type='pipe' and content like '%/agents/chat%';
    """
    import routes_agent_turn as rt
    assert "auto_router.auto" in rt.CALLBACK_MODEL_IDS
    assert "io.io" in rt.CALLBACK_MODEL_IDS
    # Auto (Smart) does NOT call back, and must stay usable by an agent.
    assert "auto_smart.auto-smart" not in rt.CALLBACK_MODEL_IDS


async def test_an_agent_on_a_callback_model_never_runs(monkeypatch):
    """The loop must be refused before the turn costs anything, and the
    refusal must name the fix rather than read as a mystery."""
    import routes_agent_turn as rt

    async def listed(token):
        return ([{"id": "agent-a", "name": "Ada",
                  "base_model_id": "auto_router.auto", "meta": {}}], False)

    async def owner(email):
        return "user-1"

    ran = []

    async def must_not_run(**kw):
        ran.append(kw)
        return ("should never happen", [])

    monkeypatch.setattr(rt, "_list_agents", listed)
    monkeypatch.setattr(rt, "_owui_user_id_for", owner)
    monkeypatch.setattr(rt, "mint_owui_token", lambda *a, **k: "tok")
    monkeypatch.setattr(rt, "_chat", must_not_run)

    out = await rt._turn_for("me@example.com",
                             {"id": "agent-a", "name": "Ada"},
                             [{"role": "user", "content": "hi"}])
    assert out["answer"] == rt.AGENT_ON_CALLBACK_MODEL, out
    assert ran == [], "it ran the turn anyway, which is the loop"


async def test_a_normal_model_still_runs(monkeypatch):
    """The guard must not refuse everything: that would be a worse bug than
    the one it fixes, and it would look identical from the outside."""
    import routes_agent_turn as rt

    async def listed(token):
        return ([{"id": "agent-a", "name": "Ada",
                  "base_model_id": "openai/gpt-5-mini", "meta": {}}], False)

    async def owner(email):
        return "user-1"

    async def answers(**kw):
        return ("PONG", [])

    monkeypatch.setattr(rt, "_list_agents", listed)
    monkeypatch.setattr(rt, "_owui_user_id_for", owner)
    monkeypatch.setattr(rt, "mint_owui_token", lambda *a, **k: "tok")
    monkeypatch.setattr(rt, "_chat", answers)
    monkeypatch.setattr(rt.agent_activity, "start_run",
                        lambda *a, **k: _nothing())
    monkeypatch.setattr(rt.agent_activity, "finish_run",
                        lambda *a, **k: _nothing())

    out = await rt._turn_for("me@example.com",
                             {"id": "agent-a", "name": "Ada"},
                             [{"role": "user", "content": "hi"}])
    assert out["answer"] == "PONG", out


def test_the_refusal_renders_as_a_failure_with_the_fix():
    """It must not arrive as an ordinary bubble. The whole point of naming
    this failure is that the person can act on it."""
    import routes_agent_turn as rt
    pair = chat._failure_reason("Ada", rt.AGENT_ON_CALLBACK_MODEL)
    assert pair is not None, "it would render as something the agent said"
    reason, fix = pair
    assert "cannot run an agent" in reason
    assert "Pick a specific model" in fix, fix


# ---------------------------------------------------------------------------
# The same agent must reach the same tools whichever surface woke it.
# Measured on production 2026-09-10: Ada had 12 tools in chat and 1 on a
# schedule, and that 1 was the connected-apps umbrella with nothing behind
# it. So a scheduled run could read nothing, wrote from nothing, and the card
# still said "Every tool you have". Nothing in either file said they differed.
# ---------------------------------------------------------------------------


async def test_an_unnarrowed_agent_gets_everything_the_owner_can_reach(monkeypatch):
    import routes_agent_turn as rt

    async def every(email):
        return ["gmail", "calendar", "remember", "skills"]

    monkeypatch.setattr(rt, "_every_tool_for", every)
    tools = await rt.tools_for_agent("me@example.com",
                                     {"toolIds": ["server:mcp-proxy"]})
    assert "skills" in tools and "gmail" in tools, tools
    # Its own list stays in front, so an explicit grant is never lost to a
    # short read from the wider lookup.
    assert tools[0] == "server:mcp-proxy", tools


async def test_a_narrowed_agent_keeps_only_what_was_picked(monkeypatch):
    """The narrowing must survive the extraction, or picking a few tools
    would silently become picking all of them."""
    import routes_agent_turn as rt

    async def every(email):
        return ["gmail", "calendar", "remember", "skills"]

    monkeypatch.setattr(rt, "_every_tool_for", every)
    tools = await rt.tools_for_agent(
        "me@example.com", {"toolIds": ["gmail"], "toolScope": "picked"})
    assert tools == ["gmail"], tools


async def test_narrowed_to_nothing_still_gets_everything(monkeypatch):
    """Picking nothing is not a request for nothing: an agent with no tools
    at all just looks broken. Pre-existing behaviour, pinned here because the
    extraction moved the branch that implements it."""
    import routes_agent_turn as rt

    async def every(email):
        return ["gmail", "skills"]

    monkeypatch.setattr(rt, "_every_tool_for", every)
    tools = await rt.tools_for_agent(
        "me@example.com", {"toolIds": [], "toolScope": "picked"})
    assert "gmail" in tools and "skills" in tools, tools


async def test_a_scheduled_run_resolves_tools_like_the_chat_path(monkeypatch):
    """The defect itself. run_agent used to read meta["toolIds"] verbatim, so
    the two surfaces disagreed about the same agent."""
    import agent_runner as ar
    import routes_agent_turn as rt

    async def every(email):
        return ["gmail", "calendar", "remember", "skills"]

    monkeypatch.setattr(rt, "_every_tool_for", every)
    meta = {"toolIds": ["server:mcp-proxy"]}

    seen = {}

    async def fake_chat(**kw):
        seen.update(kw)
        return ("done", [])

    async def fake_list(token):
        return ([{"id": "agent-a", "name": "Ada", "meta": meta,
                  "base_model_id": "openai/gpt-5-mini"}], False)

    async def fake_owner(email):
        return "user-1"

    monkeypatch.setattr(ar, "_chat", fake_chat)
    monkeypatch.setattr(ar, "_list_agents", fake_list)
    monkeypatch.setattr(ar, "_owui_user_id_for", fake_owner)
    monkeypatch.setattr(ar, "mint_owui_token", lambda *a, **k: "tok")
    monkeypatch.setattr(ar.agent_activity, "start_run",
                        lambda *a, **k: _nothing())
    monkeypatch.setattr(ar.agent_activity, "finish_run",
                        lambda *a, **k: _nothing())

    class Sched:
        id = "s1"
        user_email = "me@example.com"
        agent_id = "agent-a"
        tool_mode = "read_only"
        prompt = "write the weekly review"
        last_run_status = None
        last_result = None

    await ar.run_agent(Sched())
    got = seen.get("tool_ids") or []
    assert "skills" in got, (
        "a scheduled agent could not reach the skills tool, so use_skill "
        "could never fire: %r" % (got,))
    assert len(got) > 1, (
        "the schedule got only its raw toolIds, which is the defect: %r" % (got,))
