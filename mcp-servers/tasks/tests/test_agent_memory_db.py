"""The agent memory store against real Postgres.

Container only: `python -m pytest tests/test_agent_memory_db.py -q` inside
the tasks container with AIUI_TEST_DB=1 and a DATABASE_URL containing
"test". Locally every test here errors at setup, which is expected.
"""
import uuid

import pytest

import agent_memory as am

pytestmark = pytest.mark.asyncio


def _who():
    tag = uuid.uuid4().hex[:8]
    return "memtest-%s@example.com" % tag, "agent-memtest-%s" % tag


async def test_add_list_dedup_and_delete(db_session):
    email, agent = _who()
    added = await am.add_notes(email, agent, ["Sends the digest at 7am.",
                                              "sends the digest at 7am"])
    assert added == 1, "the same note in different case is one row"
    rows = await am.list_notes(email, agent)
    assert [r["content"] for r in rows] == ["Sends the digest at 7am."]
    assert await am.delete_note(email, agent, rows[0]["id"]) is True
    assert await am.list_notes(email, agent) == []


async def test_the_cap_prunes_the_oldest(db_session):
    email, agent = _who()
    for i in range(am.MAX_NOTES_PER_AGENT + 5):
        await am.add_notes(email, agent, ["note number %d for pruning" % i])
    rows = await am.list_notes(email, agent, limit=500)
    assert len(rows) == am.MAX_NOTES_PER_AGENT
    assert all("note number 0 " not in r["content"] for r in rows)
    await am.clear_notes(email, agent)


async def test_counts_are_per_agent_for_one_person(db_session):
    email, agent = _who()
    await am.add_notes(email, agent, ["one thing worth keeping"])
    await am.add_notes(email, agent + "-b", ["another thing worth keeping"])
    counts = await am.note_counts(email)
    assert counts[agent] == 1 and counts[agent + "-b"] == 1
    await am.clear_notes(email, agent)
    await am.clear_notes(email, agent + "-b")
