"""Shared pytest fixtures."""
import base64
import os
import pathlib
import sys
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Make app modules importable from tests/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# And make THIS file importable by name, so the handful of tests that need a
# shared helper can say `from conftest import ...` rather than each carrying
# its own copy. pytest loads conftest as a plugin, which shares fixtures but
# not plain functions.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Ensure tests that don't touch the DB can be collected without DATABASE_URL set.
# Must happen BEFORE importing db — db.py captures DATABASE_URL at import time,
# and an empty URL makes session() raise (every session-touching route 500s).
# The db_session fixture still needs a real DATABASE_URL in env (CI sets it)
# because that's when a connection is opened.
os.environ.setdefault("DATABASE_URL", "postgresql://nobody@nowhere/nobody")

# Same reasoning for the fernet key: crypto_utils raises at IMPORT time when
# AIUI_FERNET_KEY is unset, and routes_projects imports it (export feature,
# b627b88be), so any test transitively importing routes_projects needed the key
# just to be COLLECTED. Eight files carried their own setdefault; in a full run
# the alphabetically-first one set it and every later file passed BY ACCIDENT,
# while running a single file failed. setdefault, so the container's real key
# always wins — this only ever supplies a dummy for local collection.
os.environ.setdefault(
    "AIUI_FERNET_KEY",
    base64.urlsafe_b64encode(b"aiui-test-key-not-a-real-secret!").decode(),
)

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
    # The app's lazy db.session() maker binds its engine to the first event
    # loop that used it. pytest-asyncio gives every test a fresh loop, so a
    # maker left over from a previous test poisons this one with cross-loop
    # RuntimeErrors. Abandon it (closing would touch the dead loop) and let
    # init_db() rebuild it on this test's loop.
    import db as _db
    _db._engine = None
    _db._session_maker = None
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


@pytest_asyncio.fixture
async def db_session_nondestructive():
    """A real session that TRUNCATES nothing.

    `db_session` above wipes eight tables to give a test a blank database. That
    is the right tool for a test that needs to count every row, and it is why
    the safety guard exists, but it also means such a test can only ever run
    against a database nobody minds losing.

    Most tests do not need a blank database. They need a session, and they
    create rows they can identify and delete themselves. Those tests were
    borrowing `db_session` purely for the session, inheriting a TRUNCATE they
    never wanted, and were therefore refused on any real database. Fifteen of
    them had consequently never executed anywhere.

    This fixture has no guard because it destroys nothing. A test using it must
    delete exactly the rows it created, matched on a value it chose, which is
    the same rule the repository already applies to anything touching the live
    database.
    """
    # Same loop-binding dance as db_session: the app's lazy maker binds its
    # engine to the first event loop that touches it, and pytest-asyncio hands
    # every test a fresh loop, so a maker left from a previous test poisons
    # this one with cross-loop errors.
    import db as _db
    _db._engine = None
    _db._session_maker = None
    await init_db()
    engine = create_async_engine(SQLA_DB_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


@pytest.fixture
def fake_meeting_id() -> uuid.UUID:
    return uuid.uuid4()


def repo_root_or_skip():
    """The checkout root, or skip the module when there isn't one.

    Six test files read files that live outside this service: the compose file,
    the Open WebUI pipes, the terminal client's mirror. They found them with
    `parents[3]`, which is the repo root in a checkout and does not exist inside
    the container, where /app IS this service.

    An IndexError at import time is a COLLECTION error, and pytest aborts the
    whole run on those. So `pytest tests/` has never been runnable in the
    container, which is the only place the database tier can run at all. These
    files have nothing to say about a deployed container, so they skip there
    instead of taking every other test down with them.
    """
    import pytest
    here = pathlib.Path(__file__).resolve()
    for candidate in here.parents:
        if (candidate / "docker-compose.unified.yml").exists():
            return candidate
    pytest.skip("not a checkout: these files read the repository, not the app",
                allow_module_level=True)
