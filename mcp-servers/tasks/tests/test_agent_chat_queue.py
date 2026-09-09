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
    async def fake_round(email, sess, agents, request=None):
        rounds_seen.append(chat.agent_routing.last_user_text(sess.messages))
        sess.messages.append({"role": "assistant", "agent_id": "a",
                              "agent_name": "Ada", "content": "ok"})
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

    async def clearing_round(email, sess, agents, request=None):
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
