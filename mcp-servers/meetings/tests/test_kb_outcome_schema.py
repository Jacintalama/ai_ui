"""The record has to be able to say "this failed, here is why, at this time".

A NULL `kb_file_id` currently means two different things — "never attempted"
and "attempted and failed" — and production has 8 rows where nobody can tell
which. Two columns split them apart.

`meetings.records` already exists in production, and `Base.metadata.create_all`
creates missing TABLES but never alters an existing one, so new columns need an
explicit statement at boot. Idempotent, re-run every start, the same convention
as mcp-servers/tasks/migrations/*.sql. It lives in models.py rather than a
migrations/ directory because this service's Dockerfile copies `*.py` only — a
.sql file would never reach the image.
"""
import sys
import pathlib

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import models  # noqa: E402


class _RecordingConn:
    def __init__(self):
        self.statements = []
        self.synced = []

    async def execute(self, stmt):
        self.statements.append(str(stmt))

    async def run_sync(self, fn):
        self.synced.append(fn)


class _FakeEngine:
    """Stands in for the asyncpg engine — this box has no Postgres."""

    def __init__(self):
        self.conn = _RecordingConn()

    def begin(self):
        conn = self.conn

        class _Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *_exc):
                return False

        return _Ctx()


@pytest.fixture
def booted(monkeypatch):
    engine = _FakeEngine()
    monkeypatch.setattr(models, "create_async_engine", lambda *_a, **_kw: engine)
    return engine


def test_record_can_hold_the_failure_reason():
    assert "kb_error" in models.MeetingRecord.__table__.columns


def test_record_can_hold_when_the_attempt_happened():
    assert "kb_attempted_at" in models.MeetingRecord.__table__.columns


@pytest.mark.asyncio
async def test_boot_adds_the_columns_to_the_existing_table(booted):
    """create_all() will not touch meetings.records because it already exists.
    Without this the new columns are only ever in the model, and every write
    to them fails against production."""
    await models.init_db("postgresql://u:p@postgres:5432/openwebui")

    ddl = " ".join(booted.conn.statements)
    assert "kb_error" in ddl, f"no statement adds kb_error: {ddl}"
    assert "kb_attempted_at" in ddl, f"no statement adds kb_attempted_at: {ddl}"


@pytest.mark.asyncio
async def test_boot_still_creates_schema_and_tables(booted):
    await models.init_db("postgresql://u:p@postgres:5432/openwebui")

    assert any("CREATE SCHEMA IF NOT EXISTS meetings" in s for s in booted.conn.statements)
    assert booted.conn.synced, "Base.metadata.create_all no longer runs"


def test_every_column_migration_is_idempotent():
    """It re-runs on every container boot; a second boot must not error."""
    assert models.COLUMN_MIGRATIONS, "no column migrations declared"
    for stmt in models.COLUMN_MIGRATIONS:
        assert "IF NOT EXISTS" in stmt.upper(), f"not re-runnable: {stmt}"


def test_migrated_columns_match_the_model():
    """A column added to the model but not to the migration works locally
    (create_all builds a fresh table) and fails only in production."""
    declared = " ".join(models.COLUMN_MIGRATIONS)
    for name in ("kb_error", "kb_attempted_at"):
        assert name in declared
        assert name in models.MeetingRecord.__table__.columns
