"""Jev decisions against real Postgres.

DB tier: run inside a tasks container with AIUI_TEST_DB=1 and a
DATABASE_URL containing "test". Locally every test here errors at setup,
which is expected. Every person is a made-up jevtest-<hex>@example.com and
only their rows are deleted.
"""
import uuid

import pytest
from sqlalchemy import text as sql_text

import agent_decider as d
from db import session

pytestmark = pytest.mark.asyncio

PREFIX = "jevtest-"


async def _purge():
    async with session() as s:
        await s.execute(sql_text(
            "DELETE FROM tasks.agent_decision WHERE user_email LIKE :p"),
            {"p": PREFIX + "%@example.com"})
        await s.commit()


@pytest.fixture
async def clean(db_session_nondestructive):
    await _purge()
    yield
    await _purge()


async def test_a_recorded_decision_reads_back(clean):
    who = "%s%s@example.com" % (PREFIX, uuid.uuid4().hex[:8])
    decision = d.Decision(path=d.PATH_ONE_AGENT, kind="answer",
                          kind_confidence=0.96, agent_id="agent-dev",
                          agent_confidence=0.85, ms=281, model="jev-1.13.0",
                          input_tokens=436)
    await d.record(who, "chat-1", decision)
    rows = await d.recent(who)
    assert len(rows) == 1
    row = rows[0]
    assert row["provider"] == "jev" and row["path"] == "one_agent"
    assert row["agent_id"] == "agent-dev" and row["ms"] == 281
    assert row["kind_confidence"] == pytest.approx(0.96)
    assert float(row["cost_usd"]) == pytest.approx(436 * 0.042 / 1e6)
    assert row["reason"] is None


async def test_one_persons_decisions_are_not_anothers(clean):
    a = "%s%s@example.com" % (PREFIX, uuid.uuid4().hex[:8])
    b = "%s%s@example.com" % (PREFIX, uuid.uuid4().hex[:8])
    await d.record(a, None, d.Decision(path=d.PATH_FALLBACK,
                                       reason="timeout"))
    assert await d.recent(b) == []
    assert [r["reason"] for r in await d.recent(a)] == ["timeout"]


async def test_an_email_in_any_case_finds_its_decisions(clean):
    tag = uuid.uuid4().hex[:8]
    await d.record("%s%s@Example.com" % ("JEVTEST-", tag), None,
                   d.Decision(path=d.PATH_FALLBACK, reason="timeout"))
    try:
        rows = await d.recent("%s%s@example.com" % (PREFIX, tag))
        assert [r["reason"] for r in rows] == ["timeout"]
    finally:
        async with session() as s:
            await s.execute(sql_text(
                "DELETE FROM tasks.agent_decision WHERE user_email = :e"),
                {"e": "%s%s@Example.com" % ("JEVTEST-", tag)})
            await s.commit()
