"""SQLAlchemy ORM model for the video generator (tasks schema)."""
import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from models import Base  # reuse the shared DeclarativeBase


class VideoJob(Base):
    """One image+prompt -> video render job."""

    __tablename__ = "video_jobs"
    __table_args__ = {"schema": "tasks"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug = Column(Text, nullable=False)
    user_email = Column(Text, nullable=False)
    status = Column(Text, nullable=False, default="queued")
    prompt = Column(Text, nullable=False)
    plan_json = Column(JSONB, nullable=True)
    error = Column(Text, nullable=True)
    output_path = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow)
