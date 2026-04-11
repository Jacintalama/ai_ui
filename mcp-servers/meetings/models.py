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
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


async def init_db(database_url: str):
    """Create the meetings schema and tables if they don't exist."""
    engine = create_async_engine(database_url.replace("postgresql://", "postgresql+asyncpg://"))

    async with engine.begin() as conn:
        await conn.execute(sa_text("CREATE SCHEMA IF NOT EXISTS meetings"))
        await conn.run_sync(Base.metadata.create_all)

    return engine


def get_session_maker(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
