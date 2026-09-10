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


async def test_several_queued_messages_keep_their_order():
    s = store.get_session(_User.email)
    s.streaming = True
    for text in ("one", "two", "three"):
        await _send(text)
    assert s.queued == ["one", "two", "three"]


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


async def _agents_stub():
    return [{"id": "agent-a", "name": "Ada"}]


# --- where a queued message actually lands ----------------------------------

# Found by reading the DOM wiring rather than by a failing test, which is the
# wrong way round and worth writing down. The composer appends to
# #agent-thread with hx-swap="beforeend", and the open round's answers append
# INSIDE .astream .alive, which is itself a child of #agent-thread. So a
# queued bubble appended to the thread lands BELOW every answer, including the
# answer to itself. You would see your own question underneath its reply.

def test_a_queued_bubble_targets_the_live_area(monkeypatch):
    from agent_chat_render import queued_bubble
    html = queued_bubble("and another thing")
    assert "hx-swap-oob" in html
    assert ".alive" in html, "it does not aim at the live area"
    assert "and another thing" in html


def test_the_live_area_it_aims_at_is_the_one_the_stream_makes():
    """A cross-file check. The selector is a string in one file and the
    element is created in another, and nothing else would notice them
    drifting apart: the bubble would simply stop appearing."""
    from agent_chat_render import queued_bubble, stream_block
    import re
    target = re.search(r'hx-swap-oob="beforeend:([^"]+)"',
                       queued_bubble("x")).group(1)
    leaf = target.rsplit(" ", 1)[-1].lstrip(".")
    assert leaf in stream_block(), (target, "not a class the stream creates")


def test_the_thread_id_in_the_selector_is_the_one_on_the_page():
    import pathlib
    import re
    from agent_chat_render import queued_bubble
    page = (pathlib.Path(__file__).resolve().parents[1]
            / "static" / "agents.html").read_text(encoding="utf-8")
    target = re.search(r'hx-swap-oob="beforeend:([^"]+)"',
                       queued_bubble("x")).group(1)
    thread = target.split()[0].lstrip("#")
    assert 'id="%s"' % thread in page, thread


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
