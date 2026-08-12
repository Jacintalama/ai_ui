"""Meeting storage service — saves Fathom meeting data, auto-pushes to OpenWebUI KB."""
import asyncio
import os
import logging
import secrets
import uuid
from datetime import datetime
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, delete

from models import init_db, get_session_maker, MeetingRecord
from kb_sync import format_meeting_markdown, push_to_kb, KbPushError
from ai_processor import process_transcript
from decision_engine import process_action_items

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

DATABASE_URL = os.environ.get("DATABASE_URL", "")
OPENWEBUI_URL = os.environ.get("OPENWEBUI_URL", "http://open-webui:8080")
OPENWEBUI_API_KEY = os.environ.get("OPENWEBUI_API_KEY", "")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

app = FastAPI(title="MCP Meetings")

_engine = None
_session_maker = None

# asyncio holds only a weak reference to a task, so a fire-and-forget task can
# be garbage collected mid-flight. Keep a strong reference until it finishes.
_BACKGROUND_TASKS: set = set()

# kb_error is TEXT, but it is read by a human and OpenWebUI can answer with a
# whole HTML page.
MAX_KB_ERROR_CHARS = 1000


# ---------------------------------------------------------------------------
# Auth
#
# Every endpoint here was unauthenticated until 2026-08-03, when a plain
# `curl https://ai-ui.coolestdomain.win/meetings/` returned 21 records — full
# transcripts, summaries, attendee names and Fathom share links — and PUT and
# DELETE were reachable the same way.
#
# The gateway strips `x-user-email` from the incoming request and re-sets it
# only after validating the JWT (api-gateway/main.py:298-309), so a non-empty
# X-User-Email arriving here is trustworthy. Same trust model as
# tasks/routes_schedules.py::_resolve_caller.
#
# Transcript ingestion is an external n8n workflow with no user session, so
# writes additionally accept a shared secret. An UNSET secret closes that path
# rather than opening it.
# ---------------------------------------------------------------------------

def _ingest_secret() -> str:
    """Read at call time, not import time, so rotation takes effect on the
    next request instead of the next container restart."""
    return os.environ.get("MEETINGS_INGEST_SECRET", "")


def _caller_email(x_user_email: str) -> Optional[str]:
    """The gateway sends X-User-Email: "" for anonymous traffic, so an empty
    or whitespace-only value is the absence of a credential, not a user."""
    return (x_user_email or "").strip() or None


def _is_ingester(presented: str) -> bool:
    expected = _ingest_secret()
    if not expected:
        return False
    return secrets.compare_digest((presented or "").strip(), expected)


def _denied() -> HTTPException:
    return HTTPException(
        status_code=403,
        detail="Authentication required: sign in, or present the ingest secret",
    )


async def require_user(x_user_email: str = Header(default="")) -> str:
    """Reading and deleting meetings is for signed-in platform users only."""
    email = _caller_email(x_user_email)
    if not email:
        raise _denied()
    return email


async def require_user_or_ingest(
    x_user_email: str = Header(default=""),
    x_meetings_ingest_secret: str = Header(default=""),
) -> str:
    """Creating and updating additionally allows the transcript ingester."""
    email = _caller_email(x_user_email)
    if email:
        return email
    if _is_ingester(x_meetings_ingest_secret):
        return "machine:ingest"
    raise _denied()


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class MeetingCreate(BaseModel):
    title: str
    date: str
    attendees: Optional[str] = None
    summary: Optional[str] = None
    transcript: Optional[str] = None
    fathom_link: Optional[str] = None


class MeetingUpdate(BaseModel):
    title: Optional[str] = None
    date: Optional[str] = None
    attendees: Optional[str] = None
    summary: Optional[str] = None
    transcript: Optional[str] = None
    fathom_link: Optional[str] = None


class MeetingResponse(BaseModel):
    id: str
    title: str
    date: str
    attendees: Optional[str] = None
    summary: Optional[str] = None
    transcript: Optional[str] = None
    fathom_link: Optional[str] = None
    kb_file_id: Optional[str] = None
    # An operator reads the API, not the database. A NULL kb_file_id with no
    # reason next to it is what let 8 records stay broken for two months.
    kb_error: Optional[str] = None
    kb_attempted_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


def _to_response(record: MeetingRecord) -> MeetingResponse:
    return MeetingResponse(
        id=str(record.id),
        title=record.title,
        date=record.date,
        attendees=record.attendees,
        summary=record.summary,
        transcript=record.transcript,
        fathom_link=record.fathom_link,
        kb_file_id=record.kb_file_id,
        kb_error=record.kb_error,
        kb_attempted_at=record.kb_attempted_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


async def _record_kb_outcome(
    meeting_id,
    *,
    file_id: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    """Write the outcome of a KB push attempt onto the meeting.

    Never raises. This is the thing that records failures, so it must not be
    able to become one — if the database is what is broken, the log line is
    all that is left, but the caller still returns normally.
    """
    try:
        if not _session_maker:
            logger.error("No database — KB outcome for %s not recorded: %s", meeting_id, error)
            return

        async with _session_maker() as session:
            result = await session.execute(
                select(MeetingRecord).where(MeetingRecord.id == meeting_id)
            )
            rec = result.scalar_one_or_none()
            if not rec:
                logger.warning("Meeting %s vanished before its KB outcome was recorded", meeting_id)
                return

            rec.kb_attempted_at = datetime.utcnow()
            if file_id:
                rec.kb_file_id = file_id
                rec.kb_error = None
            else:
                rec.kb_error = (error or "KB push failed for an unrecorded reason")[
                    :MAX_KB_ERROR_CHARS
                ]
            await session.commit()

    except Exception as exc:
        logger.error("Could not record the KB outcome for %s: %s", meeting_id, exc)


async def _push_record_to_kb(record: MeetingRecord) -> str:
    """Render the meeting and push it. Returns the file_id or raises."""
    content = format_meeting_markdown(
        title=record.title,
        date=str(record.date),
        attendees=record.attendees,
        summary=record.summary,
        transcript=record.transcript,
        fathom_link=record.fathom_link,
    )
    slug = record.title.lower().replace(" ", "-")[:50]
    date_slug = record.date[:10] if len(record.date) >= 10 else record.date
    filename = f"meeting-{date_slug}-{slug}.md"

    return await push_to_kb(OPENWEBUI_URL, OPENWEBUI_API_KEY, filename, content)


async def _guarded_process_and_push(record: MeetingRecord):
    """Run the pipeline and make sure the outcome outlives it.

    `_process_and_push` was fired as a bare `asyncio.create_task`. Nothing
    awaited it, so anything raised inside — a dead OpenWebUI key, a NameError
    in this file — was handed to the event loop and lost. The meeting was then
    indistinguishable from one that had never been pushed.
    """
    try:
        await _process_and_push(record)
    except Exception as exc:
        reason = str(exc) if isinstance(exc, KbPushError) else f"{type(exc).__name__}: {exc}"
        logger.error("KB pipeline failed for '%s': %s", record.title, reason)
        await _record_kb_outcome(record.id, error=reason)


def _dispatch_kb_pipeline(record: MeetingRecord) -> None:
    """The only way this pipeline is ever scheduled — always guarded."""
    task = asyncio.create_task(_guarded_process_and_push(record))
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


async def _process_and_push(record: MeetingRecord):
    """Background task: AI process transcript, update DB, then push to KB."""
    # Step 1: AI process transcript if it exists and summary is empty
    if record.transcript and len(record.transcript.strip()) > 50 and not record.summary:
        logger.info(f"AI processing transcript for '{record.title}'...")
        result = await process_transcript(
            openwebui_url=OPENWEBUI_URL,
            api_key=OPENWEBUI_API_KEY,
            transcript=record.transcript,
            title=record.title,
        )

        if result and _session_maker:
            async with _session_maker() as session:
                db_record = await session.execute(
                    select(MeetingRecord).where(MeetingRecord.id == record.id)
                )
                rec = db_record.scalar_one_or_none()
                if rec:
                    rec.summary = result["summary"]
                    await session.commit()
                    await session.refresh(rec)
                    record = rec
                    logger.info(f"AI output saved for '{record.title}'")

    # Step 2: Decision Engine — classify and route action items
    if record.summary:
        logger.info(f"Running decision engine for '{record.title}'...")
        await process_action_items(
            openwebui_url=OPENWEBUI_URL,
            api_key=OPENWEBUI_API_KEY,
            discord_webhook_url=DISCORD_WEBHOOK_URL,
            summary=record.summary,
            title=record.title,
            meeting_id=str(record.id),
        )

    # Step 3: Push to KB (uses AI-processed summary if available).
    # A failure raises out of here into _guarded_process_and_push, which
    # records the reason on the meeting.
    file_id = await _push_record_to_kb(record)
    await _record_kb_outcome(record.id, file_id=file_id)


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def startup():
    global _engine, _session_maker
    if not DATABASE_URL:
        logger.error("DATABASE_URL not set")
        return
    _engine = await init_db(DATABASE_URL)
    _session_maker = get_session_maker(_engine)
    logger.info("Database initialized — meetings schema ready")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "service": "mcp-meetings"}


@app.post("/", response_model=MeetingResponse, status_code=201)
async def create_meeting(
    meeting: MeetingCreate,
    caller: str = Depends(require_user_or_ingest),
):
    if not _session_maker:
        raise HTTPException(status_code=503, detail="Database not initialized")

    record = MeetingRecord(
        title=meeting.title,
        date=meeting.date,
        attendees=meeting.attendees,
        summary=meeting.summary,
        transcript=meeting.transcript,
        fathom_link=meeting.fathom_link,
    )

    async with _session_maker() as session:
        session.add(record)
        await session.commit()
        await session.refresh(record)

    logger.info(f"Meeting saved: {record.title} ({record.id})")
    _dispatch_kb_pipeline(record)
    return _to_response(record)


@app.get("/", response_model=list[MeetingResponse])
async def list_meetings(
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    caller: str = Depends(require_user),
):
    if not _session_maker:
        raise HTTPException(status_code=503, detail="Database not initialized")

    async with _session_maker() as session:
        query = select(MeetingRecord).order_by(MeetingRecord.date.desc())

        if search:
            query = query.where(
                MeetingRecord.title.ilike(f"%{search}%")
                | MeetingRecord.summary.ilike(f"%{search}%")
                | MeetingRecord.attendees.ilike(f"%{search}%")
            )

        query = query.limit(limit).offset(offset)
        result = await session.execute(query)
        records = result.scalars().all()

    return [_to_response(r) for r in records]


@app.get("/{meeting_id}", response_model=MeetingResponse)
async def get_meeting(meeting_id: str, caller: str = Depends(require_user)):
    if not _session_maker:
        raise HTTPException(status_code=503, detail="Database not initialized")

    try:
        uid = uuid.UUID(meeting_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid meeting ID")

    async with _session_maker() as session:
        result = await session.execute(
            select(MeetingRecord).where(MeetingRecord.id == uid)
        )
        record = result.scalar_one_or_none()

    if not record:
        raise HTTPException(status_code=404, detail="Meeting not found")

    return _to_response(record)


@app.put("/{meeting_id}", response_model=MeetingResponse)
async def update_meeting(
    meeting_id: str,
    update: MeetingUpdate,
    caller: str = Depends(require_user_or_ingest),
):
    if not _session_maker:
        raise HTTPException(status_code=503, detail="Database not initialized")

    try:
        uid = uuid.UUID(meeting_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid meeting ID")

    async with _session_maker() as session:
        result = await session.execute(
            select(MeetingRecord).where(MeetingRecord.id == uid)
        )
        record = result.scalar_one_or_none()
        if not record:
            raise HTTPException(status_code=404, detail="Meeting not found")

        update_data = update.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(record, key, value)
        record.updated_at = datetime.utcnow()

        await session.commit()
        await session.refresh(record)

    logger.info(f"Meeting updated: {record.title} ({record.id})")
    _dispatch_kb_pipeline(record)
    return _to_response(record)


@app.delete("/{meeting_id}", status_code=204)
async def delete_meeting(meeting_id: str, caller: str = Depends(require_user)):
    if not _session_maker:
        raise HTTPException(status_code=503, detail="Database not initialized")

    try:
        uid = uuid.UUID(meeting_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid meeting ID")

    async with _session_maker() as session:
        result = await session.execute(
            delete(MeetingRecord).where(MeetingRecord.id == uid)
        )
        await session.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Meeting not found")

    logger.info(f"Meeting deleted: {meeting_id}")
