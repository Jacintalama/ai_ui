"""SQLAlchemy ORM models for the tasks schema."""
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Integer, Text, func
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
    # Structured pre-build clarifying questions (Task 4). Populated only by the
    # one-shot question pass ahead of a NON-template build; the separate
    # mid-build free-text NEEDS_INPUT flow never touches these columns (its
    # question lives in `result`, and questions_json stays NULL for it).
    questions_json = Column(JSONB, nullable=True)
    questions_asked_at = Column(DateTime(timezone=True), nullable=True)
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
    # One-time schedules fire once on the matching minute, then the scheduler
    # flips enabled=False. Repeating rows leave this False.
    run_once = Column(Boolean, nullable=False, server_default="false", default=False)
    # The AI Agent this schedule runs as, or NULL for the CLI executor that
    # schedules have always used. Not a foreign key: Open WebUI owns the model
    # table and an agent can be deleted from the web at any time, so the
    # scheduler checks at run time and falls back rather than letting a delete
    # cascade into somebody's schedule.
    agent_id = Column(Text, nullable=True)
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    last_run_status = Column(Text, nullable=True)
    # What the run actually produced. Kept regardless of whether there is
    # anywhere to deliver it: a schedule with no destination used to compute an
    # answer and throw it away while reporting "Completed".
    last_result = Column(Text, nullable=True)
    last_result_at = Column(DateTime(timezone=True), nullable=True)
    # Discord channel/thread id to post each run's result into (set when the
    # schedule is created from Discord). NULL = no delivery (CLI/operator runs).
    delivery_channel_id = Column(Text, nullable=True)
    # Which platform the run result is delivered to (discord|slack).
    # Defaults to 'discord' so existing rows preserve current behavior.
    delivery_platform = Column(Text, nullable=False, server_default="discord")
    # 'agent' (default) = prompt via the remote executor; 'video' = direct
    # video render of video_config (no LLM). See scheduler._run_video_schedule.
    kind = Column(Text, nullable=False, server_default="agent", default="agent")
    # For kind='video': {url, template, prompt, voice, title}. NULL otherwise.
    video_config = Column(JSONB, nullable=True)
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
    # The user's private Discord thread for the video studio (created/reused by the bot).
    video_thread_id = Column(Text, nullable=True)


class BotState(Base):
    """Generic per-key state for the chat bots (webhook-handler): pending intents,
    clarify replies, and each user's current app slug. Persisted here so a
    webhook-handler redeploy doesn't wipe in-flight conversations. Written/read via
    the system /state endpoints (X-Internal-Secret)."""
    __tablename__ = "bot_state"
    __table_args__ = {"schema": "tasks"}

    state_key = Column(Text, primary_key=True)
    value = Column(JSONB, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    expires_at = Column(DateTime(timezone=True), nullable=True)


class GatewayLink(Base):
    """A platform account (Telegram, CLI) paired to an IO account.

    `owui_user_id` is the Open WebUI user id, which is what a minted token
    carries; `email` is stored alongside it for logging and for the tasks
    endpoints that key on email like every other route here."""
    __tablename__ = "gateway_links"
    __table_args__ = {"schema": "tasks"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    platform = Column(Text, nullable=False)
    platform_user_id = Column(Text, nullable=False)
    owui_user_id = Column(Text, nullable=False)
    email = Column(Text, nullable=False)
    # Carried over from the pairing code so the UI can show WHICH account is
    # linked, not just that one is. Added in migration 035.
    platform_user_name = Column(Text, nullable=True)
    linked_at = Column(DateTime(timezone=True), server_default=func.now())


class GatewayBot(Base):
    """A bot a user brought themselves, rather than the one IO operates.

    `token_encrypted` is Fernet ciphertext, never plaintext. `bot_key` is the
    opaque segment in /webhook/telegram/{bot_key} and is deliberately not a
    secret: authentication is `webhook_secret`, which Telegram echoes back in a
    header."""
    __tablename__ = "gateway_bots"
    __table_args__ = {"schema": "tasks"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    bot_key = Column(Text, nullable=False, unique=True)
    email = Column(Text, nullable=False)
    platform = Column(Text, nullable=False)
    token_encrypted = Column(Text, nullable=False)
    webhook_secret = Column(Text, nullable=False)
    bot_username = Column(Text)
    #: Where this connection goes, for a platform we reach out to rather than
    #: one that calls us. Buzz's relay URL lives here; Telegram leaves it empty
    #: because Telegram's address is Telegram's, not the user's. Not a secret,
    #: so it comes back to the browser and prefills on edit.
    endpoint = Column(Text, nullable=False, default="")
    allowed_ids = Column(Text, nullable=False, default="")
    owner_platform_user_id = Column(Text)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False,
                        server_default=func.now())
    last_error = Column(Text)
    #: When a held-open connection last reported itself up. NULL for Telegram,
    #: which holds nothing open and reports failure by not calling us. Written
    #: only by webhook-handler, through the internal state endpoint.
    connected_at = Column(DateTime(timezone=True))
    #: A second Fernet-encrypted credential, for a channel that needs two.
    #: Slack Socket Mode is the only one: xoxb- sends messages and xapp- opens
    #: the websocket, issued separately and failing separately. NULL everywhere
    #: else. See migrations/037_gateway_bot_app_token.sql.
    app_token_encrypted = Column(Text)


class GatewayPairingCode(Base):
    """A short-lived, single-use code that turns into a GatewayLink.

    `code_hash` is a sha256, never the code itself."""
    __tablename__ = "gateway_pairing_codes"
    __table_args__ = {"schema": "tasks"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    code_hash = Column(Text, nullable=False)
    platform = Column(Text, nullable=False)
    platform_user_id = Column(Text, nullable=False)
    platform_user_name = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)
    redeemed_at = Column(DateTime(timezone=True), nullable=True)


class GatewayRedeemBudget(Base):
    """Failed pairing-code redemptions, counted against the account that made
    them rather than against the code.

    A wrong code matches no row, so counting on the code was only possible by
    incrementing every live code, which let one guesser lock out every pending
    pairing. The guesser is always a signed-in user, so they are the right thing
    to charge."""
    __tablename__ = "gateway_redeem_budget"
    __table_args__ = {"schema": "tasks"}

    email = Column(Text, primary_key=True)
    failures = Column(Integer, nullable=False, default=0)
    window_started_at = Column(DateTime(timezone=True), server_default=func.now())
    locked_until = Column(DateTime(timezone=True), nullable=True)


class GatewaySession(Base):
    """One platform conversation mapped to one real Open WebUI chat.

    Because the target is a real chat, the conversation shows up in the user's
    sidebar, is searchable, and feeds the Brain, with no sync mechanism of our
    own to maintain."""
    __tablename__ = "gateway_sessions"
    __table_args__ = {"schema": "tasks"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    platform = Column(Text, nullable=False)
    chat_id = Column(Text, nullable=False)
    owui_chat_id = Column(Text, nullable=False)
    owui_user_id = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(),
                        onupdate=func.now())
