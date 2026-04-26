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
    # SAFETY: refuse to TRUNCATE in production. Tests may only run when
    # AIUI_TEST_DB=1 is set explicitly, OR when the DB has zero user data.
    # Without this guard, running pytest against the live DATABASE_URL wipes
    # users' projects (which is exactly what happened — never again).
    async with engine.begin() as conn:
        if os.environ.get("AIUI_TEST_DB") != "1":
            existing = (await conn.execute(text(
                "SELECT COUNT(*) FROM tasks.items "
                "WHERE built_app_slug IS NOT NULL AND built_app_slug NOT IN ('alpha','beta')"
            ))).scalar() or 0
            if existing > 0:
                raise RuntimeError(
                    f"Refusing to TRUNCATE — database has {existing} real project rows. "
                    "Set AIUI_TEST_DB=1 to override (only on a dedicated test DB)."
                )
        await conn.execute(text(
            "TRUNCATE tasks.items, tasks.executions, "
            "tasks.published_apps, tasks.project_members, "
            "tasks.project_supabase, tasks.chat_history CASCADE"
        ))
    async with maker() as s:
        yield s
    await engine.dispose()


@pytest.fixture
def fake_meeting_id() -> uuid.UUID:
    return uuid.uuid4()
