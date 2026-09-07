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
