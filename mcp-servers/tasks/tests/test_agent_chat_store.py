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
    a.summary = "what we agreed"
    a.messages.append({"role": "user", "content": "hi"})
    assert b.summary == ""
    assert b.messages == []


def test_get_session_returns_the_same_object_for_one_person():
    store._SESSIONS.clear()
    first = store.get_session("same@example.com")
    first.summary = "kept"
    assert store.get_session("same@example.com").summary == "kept"


def test_sweep_drops_only_the_idle_session():
    store._SESSIONS.clear()
    store.get_session("fresh@example.com")
    stale = store.get_session("stale@example.com")
    stale.last_used = time.time() - store.SESSION_IDLE_SECONDS - 1
    store.sweep()
    # Keyed by the person and who they are talking to, so the room is
    # ("them", None) rather than the bare address.
    assert ("fresh@example.com", None) in store._SESSIONS
    assert ("stale@example.com", None) not in store._SESSIONS


def test_title_from_collapses_whitespace_and_shortens():
    assert store.title_from("  hello   team  ") == "hello team"
    assert store.title_from("") == "New chat"
    assert store.title_from("   ") == "New chat"
    long_title = store.title_from("x" * 100)
    assert len(long_title) == 48
    assert long_title.endswith("…")


# --- a private word with one agent ------------------------------------------
# Until now there was one conversation per person and every agent read all of
# it. Naming an agent routed the answer, but the question still sat in the
# shared room. "add that if he click that it will change the chat to name of
# the agent itl not be global."

def test_a_private_chat_is_a_different_session_from_the_room():
    store._SESSIONS.clear()
    room = store.get_session("me@example.com")
    private = store.get_session("me@example.com", "agent-ada-1")
    room.messages.append({"role": "user", "content": "everyone hear this"})
    assert private.messages == []


def test_each_agent_gets_its_own_private_chat():
    store._SESSIONS.clear()
    ada = store.get_session("me@example.com", "agent-ada-1")
    mia = store.get_session("me@example.com", "agent-mia-2")
    ada.messages.append({"role": "user", "content": "just between us"})
    assert mia.messages == []


def test_the_same_private_chat_comes_back():
    store._SESSIONS.clear()
    first = store.get_session("me@example.com", "agent-ada-1")
    first.summary = "kept"
    assert store.get_session("me@example.com", "agent-ada-1").summary == "kept"


def test_one_persons_private_chat_is_not_anothers():
    store._SESSIONS.clear()
    mine = store.get_session("me@example.com", "agent-ada-1")
    theirs = store.get_session("you@example.com", "agent-ada-1")
    mine.messages.append({"role": "user", "content": "mine"})
    assert theirs.messages == []


def test_the_room_is_still_what_you_get_by_default():
    """Every caller that does not name an agent keeps the one room it had."""
    store._SESSIONS.clear()
    a = store.get_session("me@example.com")
    b = store.get_session("me@example.com", None)
    assert a is b


def test_sweep_drops_an_idle_private_chat_too():
    store._SESSIONS.clear()
    store.get_session("me@example.com", "agent-fresh-1")
    stale = store.get_session("me@example.com", "agent-stale-2")
    stale.last_used = time.time() - store.SESSION_IDLE_SECONDS - 1
    store.sweep()
    assert store.get_session("me@example.com", "agent-stale-2").messages == []
    assert len(store._SESSIONS) == 2
