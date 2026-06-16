"""Shared pytest fixtures."""
import os
import sys
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Make app modules importable from tests/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import init_db  # noqa: E402

# Ensure tests that don't touch the DB can be collected without DATABASE_URL set.
# The dummy DSN is only read at import time; the db_session fixture still needs
# a real DATABASE_URL in env (CI sets it) because that's when a connection is opened.
os.environ.setdefault("DATABASE_URL", "postgresql://nobody@nowhere/nobody")

# Use the same DB as the running app — DATABASE_URL is set in the container env.
RAW_DB_URL = os.environ["DATABASE_URL"]
SQLA_DB_URL = RAW_DB_URL.replace("postgresql://", "postgresql+asyncpg://")


@pytest_asyncio.fixture
async def db_session():
    """Initialize the global session maker on the current event loop, then
    yield a clean session with truncated tables.

    Initializing per-test (rather than once per session) avoids asyncpg's
    "future attached to different loop" errors when pytest-asyncio creates
    a fresh event loop per test function.
    """
    await init_db()
    engine = create_async_engine(SQLA_DB_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    # SAFETY: refuse to TRUNCATE on a database that holds real user data.
    # On 2026-04-27 a careless `pytest` against the live tasks container with
    # AIUI_TEST_DB=1 wiped 9 production projects, all chat history, and all
    # Supabase OAuth tokens — recoverable from disk for items, gone for the
    # rest. The override flag now requires BOTH:
    #   1. AIUI_TEST_DB=1 explicitly set, AND
    #   2. The database name contains "test" (e.g. openwebui_test, test_aiui).
    # The "real project rows" count check still gates non-override runs.
    async with engine.begin() as conn:
        existing = (await conn.execute(text(
            "SELECT COUNT(*) FROM tasks.items "
            "WHERE built_app_slug IS NOT NULL AND built_app_slug NOT IN ('alpha','beta')"
        ))).scalar() or 0
        if os.environ.get("AIUI_TEST_DB") == "1":
            db_url_lower = (os.environ.get("DATABASE_URL") or "").lower()
            if "test" not in db_url_lower:
                raise RuntimeError(
                    "Refusing to TRUNCATE — AIUI_TEST_DB=1 is set but DATABASE_URL "
                    f"({db_url_lower!r}) doesn't look like a test database "
                    "(name must contain 'test'). Use a dedicated test DB."
                )
        elif existing > 0:
            raise RuntimeError(
                f"Refusing to TRUNCATE — database has {existing} real project rows. "
                "Set AIUI_TEST_DB=1 AND point DATABASE_URL at a test DB."
            )
        await conn.execute(text(
            "TRUNCATE tasks.items, tasks.executions, "
            "tasks.published_apps, tasks.project_members, "
            "tasks.project_supabase, tasks.chat_history, "
            "tasks.video_job_versions, tasks.video_jobs CASCADE"
        ))
    async with maker() as s:
        yield s
    await engine.dispose()


@pytest.fixture
def fake_meeting_id() -> uuid.UUID:
    return uuid.uuid4()
