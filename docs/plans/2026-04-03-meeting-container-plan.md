# Meeting Container Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build an `mcp-meetings` container that stores Fathom meeting data in PostgreSQL and auto-pushes to OpenWebUI Knowledge Base.

**Architecture:** Standalone FastAPI container following the existing MCP server pattern (same as mcp-calendar, mcp-gdrive). Uses shared PostgreSQL with its own `meetings` schema. Auto-pushes meeting transcripts to OpenWebUI KB as background tasks.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy (asyncpg), httpx, uvicorn, Docker

---

### Task 1: Create the meetings container skeleton

**Files:**
- Create: `mcp-servers/meetings/Dockerfile`
- Create: `mcp-servers/meetings/requirements.txt`
- Create: `mcp-servers/meetings/main.py`

**Step 1: Create Dockerfile**

Create `mcp-servers/meetings/Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Step 2: Create requirements.txt**

Create `mcp-servers/meetings/requirements.txt`:

```
fastapi>=0.104.0
uvicorn>=0.24.0
httpx>=0.25.0
pydantic>=2.0.0
sqlalchemy[asyncio]>=2.0.0
asyncpg>=0.29.0
```

**Step 3: Create minimal main.py with health check**

Create `mcp-servers/meetings/main.py`:

```python
"""Meeting storage service — saves Fathom meeting data, auto-pushes to OpenWebUI KB."""
import os
import logging

from fastapi import FastAPI

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

DATABASE_URL = os.environ.get("DATABASE_URL", "")
OPENWEBUI_URL = os.environ.get("OPENWEBUI_URL", "http://open-webui:8080")
OPENWEBUI_API_KEY = os.environ.get("OPENWEBUI_API_KEY", "")

app = FastAPI(title="MCP Meetings")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "mcp-meetings"}
```

**Step 4: Commit**

```bash
git add mcp-servers/meetings/
git commit -m "feat: add mcp-meetings container skeleton"
```

---

### Task 2: Add database models and auto-create schema

**Files:**
- Create: `mcp-servers/meetings/models.py`
- Modify: `mcp-servers/meetings/main.py`

**Step 1: Create models.py**

Create `mcp-servers/meetings/models.py`:

```python
"""SQLAlchemy models for meeting records."""
import uuid
from datetime import datetime

from sqlalchemy import Column, String, Text, DateTime
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
    date = Column(DateTime, nullable=False)
    attendees = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    transcript = Column(Text, nullable=True)
    fathom_link = Column(String(1000), nullable=True)
    action_items = Column(Text, nullable=True)
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


# Need this import for sa_text
from sqlalchemy import text as sa_text
```

**Step 2: Update main.py to init DB on startup**

Replace the full content of `mcp-servers/meetings/main.py`:

```python
"""Meeting storage service — saves Fathom meeting data, auto-pushes to OpenWebUI KB."""
import os
import logging

from fastapi import FastAPI

from models import init_db, get_session_maker

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

DATABASE_URL = os.environ.get("DATABASE_URL", "")
OPENWEBUI_URL = os.environ.get("OPENWEBUI_URL", "http://open-webui:8080")
OPENWEBUI_API_KEY = os.environ.get("OPENWEBUI_API_KEY", "")

app = FastAPI(title="MCP Meetings")

_engine = None
_session_maker = None


@app.on_event("startup")
async def startup():
    global _engine, _session_maker
    if not DATABASE_URL:
        logger.error("DATABASE_URL not set")
        return
    _engine = await init_db(DATABASE_URL)
    _session_maker = get_session_maker(_engine)
    logger.info("Database initialized — meetings schema ready")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "mcp-meetings"}
```

**Step 3: Commit**

```bash
git add mcp-servers/meetings/models.py mcp-servers/meetings/main.py
git commit -m "feat: add meeting database models with auto-schema creation"
```

---

### Task 3: Add CRUD API endpoints

**Files:**
- Modify: `mcp-servers/meetings/main.py`

**Step 1: Add Pydantic schemas and CRUD endpoints to main.py**

Replace the full content of `mcp-servers/meetings/main.py`:

```python
"""Meeting storage service — saves Fathom meeting data, auto-pushes to OpenWebUI KB."""
import os
import logging
import uuid
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, delete

from models import init_db, get_session_maker, MeetingRecord

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

DATABASE_URL = os.environ.get("DATABASE_URL", "")
OPENWEBUI_URL = os.environ.get("OPENWEBUI_URL", "http://open-webui:8080")
OPENWEBUI_API_KEY = os.environ.get("OPENWEBUI_API_KEY", "")

app = FastAPI(title="MCP Meetings")

_engine = None
_session_maker = None


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class MeetingCreate(BaseModel):
    title: str
    date: datetime
    attendees: Optional[str] = None
    summary: Optional[str] = None
    transcript: Optional[str] = None
    fathom_link: Optional[str] = None
    action_items: Optional[str] = None


class MeetingUpdate(BaseModel):
    title: Optional[str] = None
    date: Optional[datetime] = None
    attendees: Optional[str] = None
    summary: Optional[str] = None
    transcript: Optional[str] = None
    fathom_link: Optional[str] = None
    action_items: Optional[str] = None


class MeetingResponse(BaseModel):
    id: str
    title: str
    date: datetime
    attendees: Optional[str] = None
    summary: Optional[str] = None
    transcript: Optional[str] = None
    fathom_link: Optional[str] = None
    action_items: Optional[str] = None
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
        action_items=record.action_items,
        kb_file_id=record.kb_file_id,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


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


@app.post("/meetings", response_model=MeetingResponse, status_code=201)
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
        action_items=meeting.action_items,
    )

    async with _session_maker() as session:
        session.add(record)
        await session.commit()
        await session.refresh(record)

    logger.info(f"Meeting saved: {record.title} ({record.id})")
    return _to_response(record)


@app.get("/meetings", response_model=list[MeetingResponse])
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


@app.get("/meetings/{meeting_id}", response_model=MeetingResponse)
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


@app.put("/meetings/{meeting_id}", response_model=MeetingResponse)
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
    return _to_response(record)


@app.delete("/meetings/{meeting_id}", status_code=204)
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
```

**Step 2: Commit**

```bash
git add mcp-servers/meetings/main.py
git commit -m "feat: add meeting CRUD API endpoints"
```

---

### Task 4: Add OpenWebUI KB auto-push

**Files:**
- Create: `mcp-servers/meetings/kb_sync.py`
- Modify: `mcp-servers/meetings/main.py`

**Step 1: Create kb_sync.py**

Create `mcp-servers/meetings/kb_sync.py`:

```python
"""Auto-push meeting records to OpenWebUI Knowledge Base."""
import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)

KB_NAME = "Meeting Transcripts"
KB_DESCRIPTION = "Fathom meeting summaries with recording links. Auto-populated from team meetings."


def _kb_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def format_meeting_markdown(
    title: str,
    date: str,
    attendees: str | None,
    summary: str | None,
    action_items: str | None,
    transcript: str | None,
    fathom_link: str | None,
) -> str:
    """Format a meeting record as markdown for KB upload."""
    parts = [f"# {title}"]
    parts.append(f"Date: {date} | Attendees: {attendees or 'N/A'}")
    parts.append("")

    if summary:
        parts.append("## Summary")
        parts.append(summary)
        parts.append("")

    if action_items:
        parts.append("## Action Items")
        parts.append(action_items)
        parts.append("")

    if transcript:
        parts.append("## Transcript")
        parts.append(transcript)
        parts.append("")

    parts.append("## Recording")
    parts.append(fathom_link if fathom_link else "No recording link available")

    return "\n".join(parts)


async def _get_or_create_kb(client: httpx.AsyncClient, api_key: str, openwebui_url: str) -> str:
    """Find or create the Meeting Transcripts KB. Returns KB id."""
    resp = await client.get(
        f"{openwebui_url}/api/v1/knowledge/",
        headers=_kb_headers(api_key),
    )
    resp.raise_for_status()

    data = resp.json()
    kbs = data.get("items", data) if isinstance(data, dict) else data
    for kb in kbs:
        if isinstance(kb, dict) and kb.get("name") == KB_NAME:
            return kb["id"]

    # Create new KB
    resp = await client.post(
        f"{openwebui_url}/api/v1/knowledge/create",
        headers={**_kb_headers(api_key), "Content-Type": "application/json"},
        json={"name": KB_NAME, "description": KB_DESCRIPTION},
    )
    resp.raise_for_status()
    kb_id = resp.json()["id"]
    logger.info(f"Created KB '{KB_NAME}' with id {kb_id}")
    return kb_id


async def push_to_kb(
    openwebui_url: str,
    api_key: str,
    filename: str,
    content: str,
) -> str | None:
    """Upload a meeting markdown file to OpenWebUI KB. Returns file_id or None on failure."""
    if not api_key:
        logger.warning("OPENWEBUI_API_KEY not set — skipping KB push")
        return None

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            # Get or create KB
            kb_id = await _get_or_create_kb(client, api_key, openwebui_url)

            # Upload file
            resp = await client.post(
                f"{openwebui_url}/api/v1/files/",
                headers={"Authorization": f"Bearer {api_key}"},
                files={"file": (filename, content.encode("utf-8"), "text/markdown")},
            )
            resp.raise_for_status()
            file_id = resp.json()["id"]

            # Poll for processing completion
            for _ in range(30):
                status_resp = await client.get(
                    f"{openwebui_url}/api/v1/files/{file_id}/process/status",
                    headers=_kb_headers(api_key),
                )
                if status_resp.is_success:
                    status = status_resp.json().get("status", "")
                    if status == "completed":
                        break
                await asyncio.sleep(2)

            # Add to KB
            resp = await client.post(
                f"{openwebui_url}/api/v1/knowledge/{kb_id}/file/add",
                headers={**_kb_headers(api_key), "Content-Type": "application/json"},
                json={"file_id": file_id},
            )
            resp.raise_for_status()

            logger.info(f"Pushed to KB: {filename} (file_id={file_id})")
            return file_id

    except Exception as exc:
        logger.error(f"KB push failed for {filename}: {exc}")
        return None
```

**Step 2: Wire KB push into create and update endpoints in main.py**

Add this import at the top of `main.py` (after existing imports):

```python
from kb_sync import format_meeting_markdown, push_to_kb
```

Add this helper function after `_to_response`:

```python
async def _push_meeting_to_kb(record: MeetingRecord):
    """Background task: push meeting to OpenWebUI KB."""
    content = format_meeting_markdown(
        title=record.title,
        date=str(record.date),
        attendees=record.attendees,
        summary=record.summary,
        action_items=record.action_items,
        transcript=record.transcript,
        fathom_link=record.fathom_link,
    )
    slug = record.title.lower().replace(" ", "-")[:50]
    filename = f"meeting-{record.date.strftime('%Y-%m-%d')}-{slug}.md"

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
```

Add `import asyncio` to the top imports, then update `create_meeting` — add this line after `logger.info(...)` and before `return`:

```python
    asyncio.create_task(_push_meeting_to_kb(record))
```

Update `update_meeting` — add this line after `logger.info(...)` and before `return`:

```python
    asyncio.create_task(_push_meeting_to_kb(record))
```

**Step 3: Commit**

```bash
git add mcp-servers/meetings/kb_sync.py mcp-servers/meetings/main.py
git commit -m "feat: add OpenWebUI KB auto-push on meeting save/update"
```

---

### Task 5: Add to docker-compose.unified.yml

**Files:**
- Modify: `docker-compose.unified.yml`

**Step 1: Add mcp-meetings service**

Add the following service block after the `mcp-calendar` service (after line ~205 in docker-compose.unified.yml):

```yaml
  # ===========================================================================
  # MCP MEETINGS - Meeting Transcript Storage & KB Integration
  # ===========================================================================
  mcp-meetings:
    build: ./mcp-servers/meetings
    container_name: mcp-meetings
    restart: unless-stopped
    environment:
      - DATABASE_URL=postgresql://openwebui:${POSTGRES_PASSWORD:-openwebui-secret}@postgres:5432/openwebui
      - OPENWEBUI_URL=http://open-webui:8080
      - OPENWEBUI_API_KEY=${OPENWEBUI_API_KEY}
    networks:
      - backend
    depends_on:
      postgres:
        condition: service_healthy
    deploy:
      resources:
        limits:
          memory: 128M
```

**Step 2: Commit**

```bash
git add docker-compose.unified.yml
git commit -m "feat: add mcp-meetings service to docker-compose"
```

---

### Task 6: Add Caddy route

**Files:**
- Modify: `Caddyfile`

**Step 1: Add meetings route**

Add the following block after the Google Calendar MCP section in the Caddyfile (after the `handle /calendar/*` block):

```caddyfile
	# ---------------------------------------------------------------------------
	# Meetings MCP — meeting transcript storage
	# ---------------------------------------------------------------------------
	handle /meetings/* {
		uri strip_prefix /meetings
		reverse_proxy mcp-meetings:8000
	}
```

**Step 2: Commit**

```bash
git add Caddyfile
git commit -m "feat: add Caddy route for mcp-meetings"
```

---

### Task 7: Deploy and verify

**Step 1: SCP files to server**

```bash
scp -r mcp-servers/meetings root@46.224.193.25:/root/proxy-server/mcp-servers/meetings
scp docker-compose.unified.yml root@46.224.193.25:/root/proxy-server/docker-compose.unified.yml
scp Caddyfile root@46.224.193.25:/root/proxy-server/Caddyfile
```

**Step 2: Build and start on server**

```bash
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --build mcp-meetings && docker compose -f docker-compose.unified.yml restart caddy"
```

**Step 3: Verify health check**

```bash
ssh root@46.224.193.25 "docker compose -f /root/proxy-server/docker-compose.unified.yml logs --tail=10 mcp-meetings"
```

Expected: `Database initialized — meetings schema ready`

**Step 4: Test the API**

```bash
curl -X POST https://ai-ui.coolestdomain.win/meetings/meetings \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Test Meeting",
    "date": "2026-04-03T10:00:00",
    "attendees": "Lukas, Ralph, Clarence",
    "summary": "Test meeting to verify the container works",
    "fathom_link": null
  }'
```

Expected: `201` response with meeting record including `id` and `kb_file_id` (null initially, populated async).

**Step 5: Verify KB push**

Wait 30 seconds, then:

```bash
curl -X GET https://ai-ui.coolestdomain.win/meetings/meetings
```

Expected: Meeting record with `kb_file_id` populated (not null).

**Step 6: Commit any fixes**

```bash
git add -A
git commit -m "fix: deployment adjustments for mcp-meetings"
```
