"""SQLAlchemy ORM models for the tasks schema."""
import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class TaskItem(Base):
    __tablename__ = "items"
    __table_args__ = {"schema": "tasks"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    meeting_id = Column(UUID(as_uuid=True), nullable=False)
    action_type = Column(Text, nullable=False)
    assignee_name = Column(Text, nullable=False)
    assignee_email = Column(Text, nullable=False)
    description = Column(Text, nullable=False)
    query = Column(Text, nullable=True)
    priority = Column(Text, nullable=False)
    status = Column(Text, nullable=False, default="pending")
    mode = Column(Text, nullable=True)
    result = Column(Text, nullable=True)
    max_attempts = Column(Integer, nullable=False, default=1)
    attempt_count = Column(Integer, nullable=False, default=0)
    conversation_history = Column(JSONB, nullable=False, default=list)
    plan = Column(Text, nullable=True)
    plan_status = Column(Text, nullable=True)
    built_app_slug = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    executions = relationship(
        "TaskExecution", back_populates="task", cascade="all, delete-orphan"
    )


class TaskExecution(Base):
    __tablename__ = "executions"
    __table_args__ = {"schema": "tasks"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(UUID(as_uuid=True), ForeignKey("tasks.items.id"), nullable=False)
    started_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(Text, nullable=False, default="running")
    log = Column(Text, nullable=False, default="")
    error = Column(Text, nullable=True)

    task = relationship("TaskItem", back_populates="executions")


class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = {"schema": "tasks"}

    slug = Column(Text, primary_key=True)
    user_email = Column(Text, primary_key=True)
    role = Column(Text, nullable=False, default="editor")
    added_by = Column(Text, nullable=False)
    added_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class PublishedApp(Base):
    __tablename__ = "published_apps"
    __table_args__ = {"schema": "tasks"}

    slug = Column(Text, primary_key=True)
    published_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    published_by = Column(Text, nullable=False)
    public_host = Column(Text, nullable=False)
    custom_domain = Column(Text, nullable=True)
    custom_domain_verified_at = Column(DateTime(timezone=True), nullable=True)


class ProjectSupabase(Base):
    __tablename__ = "project_supabase"
    __table_args__ = {"schema": "tasks"}

    slug = Column(Text, primary_key=True)
    supabase_url = Column(Text, nullable=False)
    anon_key_encrypted = Column(Text, nullable=False)
    db_uri_encrypted = Column(Text, nullable=True)
    configured_by = Column(Text, nullable=False)
    configured_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class ChatMessage(Base):
    __tablename__ = "chat_history"
    __table_args__ = {"schema": "tasks"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug = Column(Text, nullable=False)
    user_email = Column(Text, nullable=False)
    role = Column(Text, nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
