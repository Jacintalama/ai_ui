"""Meeting storage service — saves Fathom meeting data, auto-pushes to OpenWebUI KB."""
import asyncio
import os
import logging
import uuid
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, delete

from models import init_db, get_session_maker, MeetingRecord
from kb_sync import format_meeting_markdown, push_to_kb
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
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


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
        )

    # Step 3: Push to KB (uses AI-processed summary if available)
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

    file_id = await push_to_kb(OPENWEBUI_URL, OPENWEBUI_API_KEY, filename, content)

    if file_id and _session_maker:
        async with _session_maker() as session:
            result = await session.execute(
                select(MeetingRecord).where(MeetingRecord.id == record.id)
            )
            rec = result.scalar_one_or_none()
            if rec:
                rec.kb_file_id = file_id
                await session.commit()


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
async def create_meeting(meeting: MeetingCreate):
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
    asyncio.create_task(_process_and_push(record))
    return _to_response(record)


@app.get("/", response_model=list[MeetingResponse])
async def list_meetings(
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
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
async def get_meeting(meeting_id: str):
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
async def update_meeting(meeting_id: str, update: MeetingUpdate):
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
    asyncio.create_task(_process_and_push(record))
    return _to_response(record)


@app.delete("/{meeting_id}", status_code=204)
async def delete_meeting(meeting_id: str):
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
