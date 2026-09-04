"""The table that decides who runs an agent's turn.

Structural, against the SQL and the statement that uses it, because the DB
tier is not run locally: this repo's AIUI_TEST_DB=1 once wiped nine production
projects, so the real INSERT is verified on the server instead.

What is checked here is the part that carries the whole argument. The
duplicate-run protection is not application logic that could be reviewed for
correctness; it is a primary key, resolved by Postgres under a unique index.
If the key is not those four columns, or the INSERT is not ON CONFLICT DO
NOTHING, there is no protection at all, however right the surrounding code
looks.
"""
import pathlib
import re

import db
import routes_agents

MIGRATIONS = pathlib.Path(db.__file__).parent / "migrations"
SQL = (MIGRATIONS / "046_agent_turn_claim.sql").read_text(encoding="utf-8")


def test_the_migration_is_in_the_set_that_runs_on_startup():
    assert "046_agent_turn_claim.sql" in [f.name for f in db.migration_files()]


def test_the_number_is_not_already_taken():
    """The runner applies every file in sorted order, so two files sharing a
    number would be ambiguous forever. 045 was the number in the review
    dispatch and 045_agent_proposals.sql already had it."""
    numbers = [f.name.split("_")[0] for f in db.migration_files()]
    assert len(numbers) == len(set(numbers)), "two migrations share a number"


def test_the_primary_key_is_the_whole_argument():
    """Four columns, in this order. Drop user_email and one person's claim
    collides with another's; drop after_id and an agent could speak only once
    per conversation for ever."""
    m = re.search(r"PRIMARY KEY\s*\(([^)]*)\)", SQL)
    assert m, "no primary key declared"
    cols = [c.strip() for c in m.group(1).split(",")]
    assert cols == ["user_email", "chat_id", "agent_id", "after_id"], cols


def test_it_is_idempotent_because_every_migration_reruns_on_every_startup():
    assert "CREATE TABLE IF NOT EXISTS tasks.agent_turn_claim" in SQL
    assert "CREATE INDEX IF NOT EXISTS" in SQL


def test_the_claim_is_decided_by_the_key_not_by_a_read_then_write():
    """A SELECT followed by an INSERT would have the same race the page has.
    The whole point is that Postgres decides it."""
    src = pathlib.Path(routes_agents.__file__).read_text(encoding="utf-8")
    claim = src[src.index("async def _claim_turn"):src.index("def _pending_for_page")]
    assert "ON CONFLICT DO NOTHING" in claim
    assert "RETURNING 1" in claim
    assert "SELECT" not in claim.upper().replace("SELECT PG_", ""), (
        "the claim reads before it writes, which is the race it exists to fix")


def test_the_table_cannot_grow_without_bound():
    """Swept on the same statement path that writes, so it cannot be
    forgotten, and indexed so the sweep is not a table scan."""
    src = pathlib.Path(routes_agents.__file__).read_text(encoding="utf-8")
    claim = src[src.index("async def _claim_turn"):src.index("def _pending_for_page")]
    assert "DELETE FROM tasks.agent_turn_claim" in claim
    assert "24 hours" in claim
    assert "claimed_at" in SQL.split("CREATE INDEX")[1]


def test_a_claim_is_never_released():
    """Releasing one is exactly how the duplicate comes back: a turn that
    failed after its tool already sent something is the turn that must not be
    retried. The migration has to say so, because a later reader will
    otherwise 'fix' the missing cleanup."""
    src = pathlib.Path(routes_agents.__file__).read_text(encoding="utf-8")
    claim = src[src.index("async def _claim_turn"):src.index("def _pending_for_page")]
    # Adjacent string literals are one SQL statement, so flatten the
    # source before looking for statements in it.
    flat = claim.replace(chr(34), '').replace(chr(10), ' ')
    parts = flat.split('DELETE FROM tasks.agent_turn_claim')[1:]
    assert len(parts) == 1, parts
    assert parts[0].lstrip().startswith('WHERE claimed_at <'), (
        'the only delete must be the age sweep')
    assert "never released" in SQL.lower() or "never be released" in SQL.lower()


def test_no_foreign_keys_to_tables_this_service_does_not_own():
    """chat_id and agent_id belong to Open WebUI. A cascade would delete the
    claim and re-enable the duplicate."""
    assert "REFERENCES" not in SQL.upper()
