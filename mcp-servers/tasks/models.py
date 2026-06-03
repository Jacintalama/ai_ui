"""SQLAlchemy ORM models for the tasks schema."""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, Text
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
    agent_host = Column(Text, nullable=True)

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
    supabase_url = Column(Text, nullable=True)
    anon_key_encrypted = Column(Text, nullable=True)
    db_uri_encrypted = Column(Text, nullable=True)
    configured_by = Column(Text, nullable=False)
    configured_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    oauth_access_token_encrypted = Column(Text, nullable=True)
    oauth_refresh_token_encrypted = Column(Text, nullable=True)
    oauth_expires_at = Column(DateTime(timezone=True), nullable=True)
    linked_project_ref = Column(Text, nullable=True)
    oauth_org_slug = Column(Text, nullable=True)


class ChatMessage(Base):
    __tablename__ = "chat_history"
    __table_args__ = {"schema": "tasks"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug = Column(Text, nullable=False)
    user_email = Column(Text, nullable=False)
    role = Column(Text, nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class Schedule(Base):
    """Heartbeat scheduler: cron-triggered agent runs with per-schedule memory.

    The tasks service polls this table once per minute. Rows whose cron_expr
    matches the current minute (in their tz) get dispatched through the
    remote_executor pipeline; MEMORY.md persists between runs at
    /agent/memory/<id>.md on the agent VM.
    """
    __tablename__ = "schedules"
    __table_args__ = {"schema": "tasks"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_email = Column(Text, nullable=False)
    name = Column(Text, nullable=False)
    cron_expr = Column(Text, nullable=False)
    tz = Column(Text, nullable=False, default="Asia/Manila")
    persona = Column(Text, nullable=False, default="")
    prompt = Column(Text, nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    last_run_status = Column(Text, nullable=True)
    # Discord channel/thread id to post each run's result into (set when the
    # schedule is created from Discord). NULL = no delivery (CLI/operator runs).
    delivery_channel_id = Column(Text, nullable=True)
    # Which platform the run result is delivered to (discord|slack).
    # Defaults to 'discord' so existing rows preserve current behavior.
    delivery_platform = Column(Text, nullable=False, server_default="discord")
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class DiscordLink(Base):
    """Self-service Discord↔email links (admin-approved). One row per Discord
    user; the webhook-handler resolves an approved row to act as that email."""
    __tablename__ = "discord_links"
    __table_args__ = {"schema": "tasks"}

    discord_id = Column(Text, primary_key=True)
    discord_username = Column(Text, nullable=True)
    email = Column(Text, nullable=False)
    status = Column(Text, nullable=False, default="pending")  # pending|approved|rejected
    requested_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    decided_at = Column(DateTime(timezone=True), nullable=True)
    decided_by = Column(Text, nullable=True)
    # The user's private Discord thread for schedules (created/reused by the bot).
    schedules_thread_id = Column(Text, nullable=True)
    # The user's private Discord thread for the App Builder (created/reused by the bot).
    builder_thread_id = Column(Text, nullable=True)
