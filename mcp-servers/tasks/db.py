"""Async SQLAlchemy engine + session factory."""
import os
import pathlib

import asyncpg
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

DATABASE_URL = os.environ.get("DATABASE_URL", "")

_engine = None
_session_maker: async_sessionmaker[AsyncSession] | None = None


async def _run_migrations() -> None:
    """Apply migration .sql files using a raw asyncpg connection.

    SQLAlchemy's text() forces prepared statements, which asyncpg refuses for
    multi-statement scripts. asyncpg's native execute() handles them fine.
    """
    migrations_dir = pathlib.Path(__file__).parent / "migrations"
    sql_files = sorted(migrations_dir.glob("*.sql"))
    if not sql_files:
        return
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        for sql_file in sql_files:
            await conn.execute(sql_file.read_text(encoding="utf-8"))
    finally:
        await conn.close()


async def init_db() -> None:
    """Run migrations, then build the SQLAlchemy session maker."""
    global _engine, _session_maker
    await _run_migrations()

    url = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")
    _engine = create_async_engine(url, pool_size=5, max_overflow=5)
    _session_maker = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)


def session() -> AsyncSession:
    global _engine, _session_maker
    if _session_maker is None:
        # Lazy-init without migrations — used by unit tests that set DATABASE_URL
        # but skip init_db().  In production init_db() is always called first so
        # this branch never executes in real traffic.
        url = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")
        _engine = create_async_engine(url, pool_size=5, max_overflow=5)
        _session_maker = async_sessionmaker(
            _engine, class_=AsyncSession, expire_on_commit=False
        )
    return _session_maker()
