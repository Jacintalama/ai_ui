"""SQLAlchemy models for meeting records."""
import uuid
from datetime import datetime

from sqlalchemy import Column, String, Text, DateTime, text as sa_text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class MeetingRecord(Base):
    __tablename__ = "records"
    __table_args__ = {"schema": "meetings"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(500), nullable=False)
    date = Column(Text, nullable=False)
    attendees = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    transcript = Column(Text, nullable=True)
    fathom_link = Column(String(1000), nullable=True)
    kb_file_id = Column(String(100), nullable=True)
    # A NULL kb_file_id meant both "never attempted" and "attempted and
    # failed"; 8 production rows are stuck in that ambiguity. These two say
    # which, and why. kb_error is cleared on a successful push.
    kb_error = Column(Text, nullable=True)
    kb_attempted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# Columns added after meetings.records shipped. create_all() creates missing
# TABLES but never alters an existing one, so these need saying explicitly.
# Idempotent — they re-run on every container boot, the same convention as
# mcp-servers/tasks/migrations/*.sql. They live here rather than in a
# migrations/ directory because this service's Dockerfile copies `*.py` only,
# so a .sql file would never reach the image.
COLUMN_MIGRATIONS = (
    "ALTER TABLE meetings.records ADD COLUMN IF NOT EXISTS kb_error TEXT",
    "ALTER TABLE meetings.records ADD COLUMN IF NOT EXISTS kb_attempted_at TIMESTAMP",
)


async def init_db(database_url: str):
    """Create the meetings schema and tables if they don't exist."""
    engine = create_async_engine(database_url.replace("postgresql://", "postgresql+asyncpg://"))

    async with engine.begin() as conn:
        await conn.execute(sa_text("CREATE SCHEMA IF NOT EXISTS meetings"))
        await conn.run_sync(Base.metadata.create_all)
        for statement in COLUMN_MIGRATIONS:
            await conn.execute(sa_text(statement))

    return engine


def get_session_maker(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
