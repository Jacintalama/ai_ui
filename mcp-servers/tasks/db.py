"""Async SQLAlchemy engine + session factory."""
import os
import pathlib

import asyncpg
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

DATABASE_URL = os.environ.get("DATABASE_URL", "")

_engine = None
_session_maker: async_sessionmaker[AsyncSession] | None = None


def migration_files() -> list[pathlib.Path]:
    """Exactly the files startup will execute, in order.

    A function rather than an expression inside the runner so a test can assert
    on the real selection. The first version of that test re-implemented the
    filter and therefore passed while the bug below was present.

    NOT rglob, and *.down.sql is excluded: a rollback script here runs on every
    startup like anything else, and sorting puts "012_x.down.sql" BEFORE
    "012_x.sql" because "." sorts before "s". So each start dropped agent_host
    and re-added it, and Postgres never reclaims a dropped column's slot. After
    roughly 1593 restarts tasks.executions hit the hard 1600-column ceiling and
    the service stopped booting at all, in a way no image rollback could fix:
    every version runs this before serving anything. Rollbacks live in
    migrations/rollbacks/ and are applied by hand.
    """
    migrations_dir = pathlib.Path(__file__).parent / "migrations"
    return sorted(f for f in migrations_dir.glob("*.sql")
                  if not f.name.endswith(".down.sql"))


async def _run_migrations() -> None:
    """Apply migration .sql files using a raw asyncpg connection.

    SQLAlchemy's text() forces prepared statements, which asyncpg refuses for
    multi-statement scripts. asyncpg's native execute() handles them fine.
    """
    sql_files = migration_files()
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
