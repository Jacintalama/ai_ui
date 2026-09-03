"""A proposal is a promise that nothing has happened yet.

These use db_session_nondestructive, not db_session. db_session TRUNCATES
eight tables including tasks.items and tasks.published_apps, and on
2026-04-27 a careless run of it wiped 9 production projects and all chat
history. The clean_proposals fixture below deletes only the rows this file
creates, matched on the two email constants, so nothing else in the table
is touched, before and after every test.

Locally every db-backed test here errors at setup with no Postgres. That is
expected: see CLAUDE.md. Only test_the_ttl_is_thirty_minutes runs locally.
"""
import asyncio

import pytest
import pytest_asyncio
from sqlalchemy import text

from code_proposals import (
    MAX_DESCRIPTION_CHARS,
    PROPOSAL_TTL_SECONDS,
    ProposalError,
    consume_proposal,
    create_proposal,
)

# clean_proposals below matches on exactly these two strings. A different
# test file reusing OWNER or STRANGER would leave its own rows behind.
OWNER = "proposals-test-owner@example.com"
STRANGER = "proposals-test-stranger@example.com"


@pytest_asyncio.fixture
async def clean_proposals(db_session_nondestructive):
    """Deletes only rows this file created, matched on the test emails,
    before and after. Nothing else in the table is touched, which is what
    makes this safe to run against the real database."""
    async def _purge():
        await db_session_nondestructive.execute(text(
            "DELETE FROM tasks.agent_proposals WHERE user_email IN (:a, :b)"),
            {"a": OWNER, "b": STRANGER})
        await db_session_nondestructive.commit()
    await _purge()
    yield db_session_nondestructive
    await _purge()


def test_the_ttl_is_thirty_minutes():
    assert PROPOSAL_TTL_SECONDS == 1800


async def test_a_proposal_round_trips(clean_proposals):
    token = await create_proposal(OWNER, "shop", "make the button blue")
    got = await consume_proposal(OWNER, token)
    assert got["slug"] == "shop"
    assert got["description"] == "make the button blue"


async def test_a_token_is_single_use(clean_proposals):
    token = await create_proposal(OWNER, "shop", "make the button blue")
    await consume_proposal(OWNER, token)
    with pytest.raises(ProposalError):
        await consume_proposal(OWNER, token)


async def test_two_confirms_at_once_cannot_both_win(clean_proposals):
    """The sequential test above cannot see a race. Replacing the single
    UPDATE with a SELECT to check the row and then an UPDATE to claim it
    would still pass it, because the first call has already committed by
    the time the second one looks. Two calls genuinely in flight at once
    is the only shape that tells those two implementations apart."""
    token = await create_proposal(OWNER, "shop", "make the button blue")

    results = await asyncio.gather(
        consume_proposal(OWNER, token),
        consume_proposal(OWNER, token),
        return_exceptions=True,
    )

    winners = [r for r in results if isinstance(r, dict)]
    losers = [r for r in results if isinstance(r, ProposalError)]
    assert len(winners) == 1, results
    assert len(losers) == 1, results
    assert winners[0]["slug"] == "shop"


async def test_a_stranger_cannot_consume_it(clean_proposals):
    token = await create_proposal(OWNER, "shop", "make the button blue")
    with pytest.raises(ProposalError):
        await consume_proposal(STRANGER, token)
    # And it is still there for its owner, so a stranger's attempt cannot
    # be used to burn somebody else's token.
    assert (await consume_proposal(OWNER, token))["slug"] == "shop"


async def test_an_unknown_token_is_refused(clean_proposals):
    with pytest.raises(ProposalError):
        await consume_proposal(OWNER, "not-a-real-token")


async def test_an_empty_token_is_refused():
    """No database is touched: consume_proposal returns on this check
    before it ever opens a session. Taking a fixture that needs Postgres
    would gate the one property provable without one."""
    with pytest.raises(ProposalError):
        await consume_proposal(OWNER, "")


async def test_an_expired_token_is_refused(clean_proposals):
    token = await create_proposal(OWNER, "shop", "make the button blue")
    await clean_proposals.execute(text(
        "UPDATE tasks.agent_proposals"
        " SET created_at = now() - interval '31 minutes'"
        " WHERE token = :t"), {"t": token})
    await clean_proposals.commit()
    with pytest.raises(ProposalError):
        await consume_proposal(OWNER, token)


async def test_tokens_are_not_guessable(clean_proposals):
    tokens = {await create_proposal(OWNER, "shop", "x") for _ in range(5)}
    assert len(tokens) == 5
    assert all(len(t) >= 32 for t in tokens)


@pytest.mark.parametrize("slug,description", [
    ("", "make it blue"),
    ("   ", "make it blue"),
    ("shop", ""),
    ("shop", "   "),
])
async def test_an_empty_slug_or_description_is_refused(clean_proposals, slug, description):
    with pytest.raises(ProposalError):
        await create_proposal(OWNER, slug, description)


async def test_an_enormous_description_is_refused(clean_proposals):
    """This string becomes a build agent's instruction, so it is bounded
    where it enters rather than where it is used."""
    with pytest.raises(ProposalError):
        await create_proposal(OWNER, "shop", "x" * (MAX_DESCRIPTION_CHARS + 1))
