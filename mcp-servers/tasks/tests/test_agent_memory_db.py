"""The agent memory store against real Postgres.

Container only: `python -m pytest tests/test_agent_memory_db.py -q` inside
the tasks container with AIUI_TEST_DB=1 and a DATABASE_URL containing
"test". Locally every test here errors at setup, which is expected.

These use db_session_nondestructive, not db_session: they create rows under
a name nobody else uses and delete exactly those rows, which is that
fixture's contract. db_session truncates eight tables this module never
touches, and a test that truncates can only ever run against a database
nobody minds losing.
"""
import os
import time
import uuid

import pytest
from sqlalchemy import text as sql_text

import agent_memory as am
from db import session

pytestmark = pytest.mark.asyncio


def _who():
    tag = uuid.uuid4().hex[:8]
    return "memtest-%s@example.com" % tag, "agent-memtest-%s" % tag


async def test_add_list_dedup_and_delete(db_session_nondestructive):
    email, agent = _who()
    try:
        added = await am.add_notes(email, agent, ["Sends the digest at 7am.",
                                                  "sends the digest at 7am"])
        assert added == 1, "the same note in different case is one row"
        rows = await am.list_notes(email, agent)
        assert [r["content"] for r in rows] == ["Sends the digest at 7am."]
        assert await am.delete_note(email, agent, rows[0]["id"]) is True
        assert await am.list_notes(email, agent) == []
    finally:
        await am.clear_notes(email, agent)


async def test_the_cap_prunes_the_oldest(db_session_nondestructive):
    email, agent = _who()
    try:
        for i in range(am.MAX_NOTES_PER_AGENT + 5):
            await am.add_notes(email, agent, ["note number %d for pruning" % i])
        rows = await am.list_notes(email, agent, limit=500)
        assert len(rows) == am.MAX_NOTES_PER_AGENT
        assert all("note number 0 " not in r["content"] for r in rows)
    finally:
        await am.clear_notes(email, agent)


async def test_counts_are_per_agent_for_one_person(db_session_nondestructive):
    email, agent = _who()
    try:
        await am.add_notes(email, agent, ["one thing worth keeping"])
        await am.add_notes(email, agent + "-b", ["another thing worth keeping"])
        counts = await am.note_counts(email)
        assert counts[agent] == 1 and counts[agent + "-b"] == 1
    finally:
        await am.clear_notes(email, agent)
        await am.clear_notes(email, agent + "-b")


async def test_the_prune_leaves_another_agent_and_another_person_alone(db_session_nondestructive):
    email, agent = _who()
    other_email, other_agent = _who()
    await am.add_notes(other_email, other_agent, ["another person's note here"])
    await am.add_notes(email, other_agent, ["same person, a different agent"])
    try:
        for i in range(am.MAX_NOTES_PER_AGENT + 5):
            await am.add_notes(email, agent, ["note number %d for pruning" % i])
        assert len(await am.list_notes(other_email, other_agent)) == 1
        assert len(await am.list_notes(email, other_agent)) == 1
    finally:
        await am.clear_notes(email, agent)
        await am.clear_notes(email, other_agent)
        await am.clear_notes(other_email, other_agent)


@pytest.mark.skipif(
    not os.environ.get("AIUI_MEMORY_TEST_EMAIL"),
    reason="set AIUI_MEMORY_TEST_EMAIL to a real Open WebUI user to run this")
async def test_facts_round_trip_for_a_real_person(db_session_nondestructive):
    """Facts go to Open WebUI's own table, so this one needs a real user.

    There is no way to invent a person here: the insert is keyed on a row in
    public."user", and creating one would leave a fake account behind. So it
    runs only when somebody names an account it may write to, and it deletes
    exactly the row it wrote.
    """
    email = os.environ["AIUI_MEMORY_TEST_EMAIL"]
    fact = "Memory test fact %s, safe to delete." % uuid.uuid4().hex[:8]
    try:
        # Seeded so the write has something to invalidate. recall_block
        # serves facts from a short lived cache, and a write that left it
        # standing would tell the next turn what was true before it. The
        # key is folded because the cache folds it: this address comes
        # from an environment variable and may be typed any way.
        cache_key = email.lower()
        am._facts_cache[cache_key] = (time.monotonic(), ["a stale fact"])
        assert await am.add_facts(email, [fact]) == 1
        assert cache_key not in am._facts_cache
        assert fact in await am.list_facts(email)
        assert await am.add_facts(email, [fact]) == 0, "the same fact twice is one row"
    finally:
        am._facts_cache.pop(email.lower(), None)
        async with session() as s:
            await s.execute(sql_text(
                'DELETE FROM public."memory" WHERE content = :c'), {"c": fact})
            await s.commit()
