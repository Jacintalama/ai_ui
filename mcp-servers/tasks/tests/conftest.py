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

from db import _run_migrations  # noqa: E402

# Use the same DB as the running app — DATABASE_URL is set in the container env.
RAW_DB_URL = os.environ["DATABASE_URL"]
SQLA_DB_URL = RAW_DB_URL.replace("postgresql://", "postgresql+asyncpg://")


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _ensure_schema():
    """Make sure tasks schema exists before tests run."""
    await _run_migrations()


@pytest_asyncio.fixture
async def db_session():
    """Provide a clean session, truncating tables between tests."""
    engine = create_async_engine(SQLA_DB_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE tasks.items, tasks.executions CASCADE"))
    async with maker() as s:
        yield s
    await engine.dispose()


@pytest.fixture
def fake_meeting_id() -> uuid.UUID:
    return uuid.uuid4()
