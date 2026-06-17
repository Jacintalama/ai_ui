"""SQLAlchemy ORM model for the video generator (tasks schema)."""
import uuid
from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
)
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
    title = Column(Text, nullable=True)
    plan_json = Column(JSONB, nullable=True)
    error = Column(Text, nullable=True)
    output_path = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    conversation = Column(JSONB, nullable=False, default=list)
    current_version_no = Column(Integer, nullable=True)
    pending_summary = Column(Text, nullable=True)
    style = Column(Text, nullable=False, default="clean_product_demo")
    voice = Column(Text, nullable=True)


class VideoJobVersion(Base):
    """A saved version of a video job's plan + rendered output."""

    __tablename__ = "video_job_versions"
    __table_args__ = (
        UniqueConstraint("job_id", "version_no"),
        Index("video_job_versions_job_idx", "job_id", "version_no"),
        {"schema": "tasks"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tasks.video_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_no = Column(Integer, nullable=False)
    plan_json = Column(JSONB, nullable=False)
    summary = Column(Text, nullable=True)
    output_path = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
