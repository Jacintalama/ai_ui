# Admin Task Approval Panel — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a floating task-approval panel inside Open WebUI that surfaces meeting action items to the 4 admins, lets them approve AI execution (via Claude Code remote) or claim manual handling, and records history.

**Architecture:** New FastAPI service (`mcp-servers/tasks/`) on port 8210 backed by PostgreSQL. Receives action items from the existing `meetings` decision engine via webhook. Frontend is a JS file injected into Open WebUI through the existing custom-JS pattern. AI execution **spawns the `claude` CLI as a subprocess inside the tasks container** and streams its stdout — no separate gateway hop. The container mounts the host repo read-write so Claude can edit files.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.x async + asyncpg, Pydantic v2, Server-Sent Events (FastAPI `StreamingResponse`), httpx, vanilla JS for the frontend (no framework).

**Spec:** [`docs/superpowers/specs/2026-04-13-admin-task-panel-design.md`](../specs/2026-04-13-admin-task-panel-design.md)

**Spec deviation:** The spec uses `assignee_user_id` (UUID). The implementation uses `assignee_email` instead — the existing API gateway already forwards `X-User-Email` to backend services as a trusted header, and email is a stable identifier in Open WebUI. No UUID lookup is needed.

---

## File Structure

**New files (all under `mcp-servers/tasks/`):**
| File | Responsibility |
|------|---------------|
| `Dockerfile` | Container build |
| `requirements.txt` | Python deps |
| `main.py` | FastAPI app, lifespan, router mounting |
| `db.py` | Async SQLAlchemy engine + session factory |
| `models.py` | SQLAlchemy ORM models (`TaskItem`, `TaskExecution`) |
| `schemas.py` | Pydantic request/response schemas |
| `assignee_map.py` | Env-driven name → email resolver |
| `auth.py` | FastAPI dependency that reads `X-User-Email` / `X-User-Admin` headers |
| `routes_tasks.py` | CRUD endpoints (`GET`, `manual`, `complete`, `answer`, `history`) |
| `routes_webhook.py` | `/webhooks/meeting-action-items` ingestion |
| `routes_execution.py` | `/execute`, `/stream` (SSE), `/cancel` |
| `claude_executor.py` | subprocess spawn for `claude` CLI, sentinel parser, execution lifecycle |
| `migrations/001_init.sql` | Schema, tables, indexes, partial unique index |
| `static/task-panel.js` | Frontend overlay loaded by Open WebUI custom JS |
| `static/task-history.html` | Standalone history page |
| `tests/conftest.py` | Pytest fixtures (DB, FastAPI test client) |
| `tests/test_assignee_map.py` | |
| `tests/test_models.py` | |
| `tests/test_routes_tasks.py` | |
| `tests/test_routes_webhook.py` | |
| `tests/test_routes_execution.py` | |
| `tests/test_claude_executor.py` | |

**Modified files:**
| File | Why |
|------|-----|
| `mcp-servers/meetings/decision_engine.py` | Add webhook POST to tasks service |
| `mcp-servers/meetings/main.py` | Read `TASKS_WEBHOOK_URL` env var |
| `docker-compose.unified.yml` | Add `tasks` service entry |
| `Caddyfile` | Route `/tasks/*` and `/api/tasks/*` to tasks service |
| `.env.example` | New env vars |

---

## Task 0: Bootstrap container skeleton

**Files:**
- Create: `mcp-servers/tasks/Dockerfile`
- Create: `mcp-servers/tasks/requirements.txt`
- Create: `mcp-servers/tasks/main.py`
- Modify: `docker-compose.unified.yml` (add tasks service)
- Modify: `.env.example` (add `TASKS_WEBHOOK_URL`, `TASKS_ASSIGNEE_MAP`)

- [ ] **Step 1: Write `requirements.txt`**

```
fastapi>=0.104.0
uvicorn[standard]>=0.24.0
httpx>=0.25.0
pydantic>=2.0.0
sqlalchemy[asyncio]>=2.0.0
asyncpg>=0.29.0
sse-starlette>=2.0.0
pytest>=7.4.0
pytest-asyncio>=0.23.0
```

- [ ] **Step 2: Write `Dockerfile`** — base on `mcp-servers/meetings/Dockerfile` plus the `claude` CLI install:

```dockerfile
FROM python:3.11-slim

# Install Node.js (required by the @anthropic-ai/claude-code package) and git
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates git \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g @anthropic-ai/claude-code \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8210
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8210"]
```

- [ ] **Step 3: Write minimal `main.py` with `/health`**

```python
"""Tasks service — admin task approval and AI execution."""
import logging
from fastapi import FastAPI

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tasks")

app = FastAPI(title="Tasks Service", version="0.1.0")

@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "tasks"}
```

- [ ] **Step 4: Add `tasks` entry to `docker-compose.unified.yml`** (place near the `meetings` service)

```yaml
  tasks:
    build: ./mcp-servers/tasks
    container_name: tasks
    restart: unless-stopped
    environment:
      - DATABASE_URL=postgresql://openwebui:${POSTGRES_PASSWORD}@postgres:5432/openwebui
      - TASKS_ASSIGNEE_MAP=${TASKS_ASSIGNEE_MAP}
      - CLAUDE_WORKSPACE=/workspace/ai_ui
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
    volumes:
      # Mount the repo so Claude Code can read/edit it
      - ./:/workspace/ai_ui
    depends_on:
      postgres:
        condition: service_healthy
    networks:
      - backend
    deploy:
      resources:
        limits:
          memory: 256M
        reservations:
          memory: 128M
```

- [ ] **Step 5: Add env-var stubs to `.env.example`**

```
# Tasks service
TASKS_ASSIGNEE_MAP=ralph:ralph@aiui.com,clarenz:clarenz@aiui.com,lukas:lukas@aiui.com,jacint:jacint@aiui.com
TASKS_WEBHOOK_URL=http://tasks:8210/webhooks/meeting-action-items
```

- [ ] **Step 6: Build and verify**

Run: `docker compose -f docker-compose.unified.yml build tasks && docker compose -f docker-compose.unified.yml up -d tasks`
Then: `curl http://localhost:8210/health`
Expected: `{"status":"ok","service":"tasks"}`

- [ ] **Step 7: Commit**

```bash
git add mcp-servers/tasks/ docker-compose.unified.yml .env.example
git commit -m "feat(tasks): bootstrap tasks service container with /health endpoint"
```

---

## Task 1: Database schema + migration

**Files:**
- Create: `mcp-servers/tasks/migrations/001_init.sql`
- Create: `mcp-servers/tasks/db.py`
- Modify: `mcp-servers/tasks/main.py` (run migration on startup)

- [ ] **Step 1: Write `migrations/001_init.sql`**

```sql
CREATE SCHEMA IF NOT EXISTS tasks;

CREATE TABLE IF NOT EXISTS tasks.items (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    meeting_id      UUID NOT NULL,
    action_type     TEXT NOT NULL CHECK (action_type IN ('RESEARCH','BUILD','INTEGRATE','ASK_USER')),
    assignee_name   TEXT NOT NULL,
    assignee_email  TEXT NOT NULL,
    description     TEXT NOT NULL,
    query           TEXT,
    priority        TEXT NOT NULL CHECK (priority IN ('CRITICAL','IMPORTANT','NICE_TO_HAVE')),
    status          TEXT NOT NULL DEFAULT 'pending'
                      CHECK (status IN ('pending','claimed_manual','running','awaiting_input','completed','failed')),
    mode            TEXT CHECK (mode IN ('ai','manual')),
    result          TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS items_assignee_status_idx ON tasks.items (assignee_email, status);
CREATE INDEX IF NOT EXISTS items_assignee_completed_idx ON tasks.items (assignee_email, completed_at DESC);
CREATE INDEX IF NOT EXISTS items_meeting_idx ON tasks.items (meeting_id);

-- Idempotency on webhook ingestion
CREATE UNIQUE INDEX IF NOT EXISTS items_meeting_desc_uniq
    ON tasks.items (meeting_id, md5(description));

CREATE TABLE IF NOT EXISTS tasks.executions (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id      UUID NOT NULL REFERENCES tasks.items(id) ON DELETE CASCADE,
    started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at  TIMESTAMPTZ,
    status       TEXT NOT NULL DEFAULT 'running'
                   CHECK (status IN ('running','succeeded','failed','needs_input')),
    log          TEXT NOT NULL DEFAULT '',
    error        TEXT
);

-- Only one execution per task may be 'running' at a time
CREATE UNIQUE INDEX IF NOT EXISTS executions_one_running
    ON tasks.executions (task_id) WHERE status = 'running';

CREATE OR REPLACE FUNCTION tasks._touch_updated_at() RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS items_touch_updated_at ON tasks.items;
CREATE TRIGGER items_touch_updated_at BEFORE UPDATE ON tasks.items
    FOR EACH ROW EXECUTE FUNCTION tasks._touch_updated_at();
```

- [ ] **Step 2: Write `db.py`**

```python
"""Async SQLAlchemy engine + session factory."""
import os
import pathlib
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

DATABASE_URL = os.environ.get("DATABASE_URL", "")

_engine = None
_session_maker: async_sessionmaker[AsyncSession] | None = None


async def init_db() -> None:
    """Create engine, run migrations, build session maker."""
    global _engine, _session_maker
    url = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")
    _engine = create_async_engine(url, pool_size=5, max_overflow=5)

    migrations_dir = pathlib.Path(__file__).parent / "migrations"
    sql_files = sorted(migrations_dir.glob("*.sql"))
    async with _engine.begin() as conn:
        for sql_file in sql_files:
            sql = sql_file.read_text(encoding="utf-8")
            await conn.execute(text(sql))

    _session_maker = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)


def session() -> AsyncSession:
    if _session_maker is None:
        raise RuntimeError("DB not initialized")
    return _session_maker()
```

- [ ] **Step 3: Wire `init_db` into `main.py` startup**

Replace the contents of `main.py` with:

```python
"""Tasks service — admin task approval and AI execution."""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from db import init_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tasks")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    logger.info("DB initialized")
    yield


app = FastAPI(title="Tasks Service", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "tasks"}
```

- [ ] **Step 4: Rebuild and verify schema exists**

```bash
docker compose -f docker-compose.unified.yml up -d --build tasks
docker exec -i postgres psql -U openwebui -d openwebui -c "\dt tasks.*"
```

Expected: lists `tasks.items` and `tasks.executions`.

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/migrations/ mcp-servers/tasks/db.py mcp-servers/tasks/main.py
git commit -m "feat(tasks): add tasks schema and run migrations on startup"
```

---

## Task 2: SQLAlchemy models + tests

**Files:**
- Create: `mcp-servers/tasks/models.py`
- Create: `mcp-servers/tasks/tests/conftest.py`
- Create: `mcp-servers/tasks/tests/test_models.py`

- [ ] **Step 1: Write `models.py`**

```python
"""SQLAlchemy ORM models for tasks schema."""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
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
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    executions = relationship("TaskExecution", back_populates="task", cascade="all, delete-orphan")


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
```

- [ ] **Step 2: Write `tests/conftest.py`**

```python
"""Shared pytest fixtures."""
import os
import uuid
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine, AsyncSession
from sqlalchemy import text

# Use a separate test DB; falls back to default for CI.
TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://openwebui:openwebui@localhost:5432/openwebui",
)


@pytest_asyncio.fixture
async def db_session():
    """Provide a clean session, truncating tables between tests."""
    engine = create_async_engine(TEST_DB_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE tasks.items, tasks.executions CASCADE"))
    async with maker() as s:
        yield s
    await engine.dispose()


@pytest.fixture
def fake_meeting_id() -> uuid.UUID:
    return uuid.uuid4()
```

- [ ] **Step 3: Write `tests/test_models.py`**

```python
"""Smoke tests for ORM persistence."""
import uuid
import pytest
from models import TaskItem, TaskExecution


@pytest.mark.asyncio
async def test_can_persist_and_query_task(db_session, fake_meeting_id):
    item = TaskItem(
        meeting_id=fake_meeting_id,
        action_type="BUILD",
        assignee_name="Ralph Benitez",
        assignee_email="ralph@aiui.com",
        description="Fix Caddy routing",
        priority="CRITICAL",
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)
    assert item.id is not None
    assert item.status == "pending"


@pytest.mark.asyncio
async def test_partial_unique_index_blocks_two_running_executions(db_session, fake_meeting_id):
    """Inserting two 'running' rows for the same task must fail."""
    from sqlalchemy.exc import IntegrityError
    item = TaskItem(
        meeting_id=fake_meeting_id, action_type="BUILD",
        assignee_name="x", assignee_email="x@y", description="d", priority="IMPORTANT",
    )
    db_session.add(item)
    await db_session.commit()

    db_session.add(TaskExecution(task_id=item.id, status="running"))
    await db_session.commit()
    db_session.add(TaskExecution(task_id=item.id, status="running"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
```

- [ ] **Step 4: Run tests**

Inside the running container:
```bash
docker compose -f docker-compose.unified.yml exec tasks pytest tests/test_models.py -v
```
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/models.py mcp-servers/tasks/tests/
git commit -m "feat(tasks): add ORM models with persistence and uniqueness tests"
```

---

## Task 3: Pydantic schemas

**Files:**
- Create: `mcp-servers/tasks/schemas.py`

- [ ] **Step 1: Write `schemas.py`**

```python
"""Request/response schemas."""
from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field

ActionType = Literal["RESEARCH", "BUILD", "INTEGRATE", "ASK_USER"]
Priority = Literal["CRITICAL", "IMPORTANT", "NICE_TO_HAVE"]
Status = Literal["pending", "claimed_manual", "running", "awaiting_input", "completed", "failed"]
Mode = Literal["ai", "manual"]


class TaskOut(BaseModel):
    id: UUID
    meeting_id: UUID
    action_type: ActionType
    assignee_name: str
    assignee_email: str
    description: str
    query: str | None = None
    priority: Priority
    status: Status
    mode: Mode | None = None
    result: str | None = None
    created_at: datetime
    completed_at: datetime | None = None

    class Config:
        from_attributes = True


class IngestActionItem(BaseModel):
    """One item posted by the meetings decision engine."""
    action_type: ActionType
    assignee: str = Field(description="Raw assignee name from decision engine")
    description: str
    query: str | None = None
    priority: Priority


class IngestRequest(BaseModel):
    meeting_id: UUID
    items: list[IngestActionItem]


class CompleteRequest(BaseModel):
    result: str = ""


class AnswerRequest(BaseModel):
    answer: str
```

- [ ] **Step 2: Quick smoke test (no separate file needed)**

Inside the container:
```bash
docker compose exec tasks python -c "from schemas import IngestRequest; print(IngestRequest.model_validate({'meeting_id': '00000000-0000-0000-0000-000000000000', 'items': []}))"
```
Expected: prints `meeting_id=UUID('00000000-...') items=[]`.

- [ ] **Step 3: Commit**

```bash
git add mcp-servers/tasks/schemas.py
git commit -m "feat(tasks): add pydantic schemas for tasks API"
```

---

## Task 4: Assignee map

**Files:**
- Create: `mcp-servers/tasks/assignee_map.py`
- Create: `mcp-servers/tasks/tests/test_assignee_map.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_assignee_map.py
import pytest
from assignee_map import AssigneeMap, TEAM_EMAIL


def test_resolves_known_prefix_case_insensitive():
    m = AssigneeMap.from_env_string("ralph:ralph@x,lukas:lukas@x")
    assert m.resolve("Ralph Benitez") == "ralph@x"
    assert m.resolve("LUKAS HERAJT") == "lukas@x"


def test_unknown_assignee_returns_team_sentinel():
    m = AssigneeMap.from_env_string("ralph:ralph@x")
    assert m.resolve("Some Other Person") == TEAM_EMAIL


def test_team_keyword_returns_team_sentinel():
    m = AssigneeMap.from_env_string("ralph:ralph@x")
    assert m.resolve("team") == TEAM_EMAIL


def test_empty_string_returns_team_sentinel():
    m = AssigneeMap.from_env_string("ralph:ralph@x")
    assert m.resolve("") == TEAM_EMAIL


def test_admin_emails_lists_all_known():
    m = AssigneeMap.from_env_string("ralph:ralph@x,lukas:lukas@x")
    assert set(m.admin_emails()) == {"ralph@x", "lukas@x"}
```

- [ ] **Step 2: Run tests, verify failure** — `pytest tests/test_assignee_map.py -v` → ImportError.

- [ ] **Step 3: Implement `assignee_map.py`**

```python
"""Resolve raw assignee names from the decision engine to admin emails."""
from __future__ import annotations
import os
from dataclasses import dataclass

TEAM_EMAIL = "team@aiui.local"


@dataclass(frozen=True)
class AssigneeMap:
    """Map of lowercase prefix → email."""
    entries: tuple[tuple[str, str], ...]

    @classmethod
    def from_env_string(cls, raw: str) -> "AssigneeMap":
        pairs: list[tuple[str, str]] = []
        for chunk in (raw or "").split(","):
            chunk = chunk.strip()
            if not chunk or ":" not in chunk:
                continue
            key, email = chunk.split(":", 1)
            pairs.append((key.strip().lower(), email.strip()))
        return cls(entries=tuple(pairs))

    @classmethod
    def from_env(cls) -> "AssigneeMap":
        return cls.from_env_string(os.environ.get("TASKS_ASSIGNEE_MAP", ""))

    def resolve(self, assignee_name: str) -> str:
        if not assignee_name:
            return TEAM_EMAIL
        lower = assignee_name.strip().lower()
        if lower == "team":
            return TEAM_EMAIL
        for key, email in self.entries:
            if lower.startswith(key):
                return email
        return TEAM_EMAIL

    def admin_emails(self) -> list[str]:
        return [email for _, email in self.entries]
```

- [ ] **Step 4: Run tests, verify pass** — Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/assignee_map.py mcp-servers/tasks/tests/test_assignee_map.py
git commit -m "feat(tasks): add assignee map with prefix matching and team fallback"
```

---

## Task 5: Auth dependency (trusted gateway headers)

**Files:**
- Create: `mcp-servers/tasks/auth.py`
- Create: `mcp-servers/tasks/tests/test_auth.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_auth.py
import pytest
from fastapi import FastAPI, Depends, HTTPException
from fastapi.testclient import TestClient
from auth import current_admin, AdminUser


def _make_app():
    app = FastAPI()
    @app.get("/whoami")
    def whoami(user: AdminUser = Depends(current_admin)):
        return {"email": user.email, "is_admin": user.is_admin}
    return app


def test_returns_admin_when_headers_present():
    client = TestClient(_make_app())
    r = client.get("/whoami", headers={"X-User-Email": "ralph@aiui.com", "X-User-Admin": "true"})
    assert r.status_code == 200
    assert r.json() == {"email": "ralph@aiui.com", "is_admin": True}


def test_rejects_when_missing_email():
    client = TestClient(_make_app())
    r = client.get("/whoami")
    assert r.status_code == 401


def test_rejects_when_not_admin():
    client = TestClient(_make_app())
    r = client.get("/whoami", headers={"X-User-Email": "guest@aiui.com", "X-User-Admin": "false"})
    assert r.status_code == 403
```

- [ ] **Step 2: Run tests, verify failure** — ImportError.

- [ ] **Step 3: Implement `auth.py`**

```python
"""Read the trusted gateway headers and expose the current admin user."""
from dataclasses import dataclass
from fastapi import HTTPException, Request


@dataclass(frozen=True)
class AdminUser:
    email: str
    is_admin: bool


def current_admin(request: Request) -> AdminUser:
    """FastAPI dependency. Returns the current admin or raises 401/403."""
    email = request.headers.get("x-user-email", "").strip()
    is_admin = request.headers.get("x-user-admin", "").strip().lower() == "true"
    if not email:
        raise HTTPException(status_code=401, detail="Missing X-User-Email")
    if not is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return AdminUser(email=email, is_admin=True)
```

- [ ] **Step 4: Run tests** — Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/auth.py mcp-servers/tasks/tests/test_auth.py
git commit -m "feat(tasks): add auth dependency reading trusted gateway headers"
```

---

## Task 6: Webhook ingestion

**Files:**
- Create: `mcp-servers/tasks/routes_webhook.py`
- Create: `mcp-servers/tasks/tests/test_routes_webhook.py`
- Modify: `mcp-servers/tasks/main.py` (mount router)

- [ ] **Step 1: Write failing tests**

```python
# tests/test_routes_webhook.py
import uuid
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from main import app
from models import TaskItem


@pytest.mark.asyncio
async def test_webhook_creates_task_per_item(db_session, monkeypatch):
    monkeypatch.setenv("TASKS_ASSIGNEE_MAP", "ralph:ralph@x,lukas:lukas@x")
    mid = str(uuid.uuid4())
    payload = {
        "meeting_id": mid,
        "items": [
            {"action_type": "BUILD", "assignee": "Ralph Benitez", "description": "Fix routing", "priority": "CRITICAL"},
            {"action_type": "RESEARCH", "assignee": "Lukas", "description": "Compare X vs Y", "priority": "IMPORTANT"},
        ],
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/webhooks/meeting-action-items", json=payload)
        assert r.status_code == 201
        assert r.json()["created"] == 2

    rows = (await db_session.execute(select(TaskItem))).scalars().all()
    by_email = {r.assignee_email for r in rows}
    assert by_email == {"ralph@x", "lukas@x"}


@pytest.mark.asyncio
async def test_webhook_idempotent_on_duplicate_post(db_session):
    mid = str(uuid.uuid4())
    payload = {"meeting_id": mid, "items": [
        {"action_type": "BUILD", "assignee": "team", "description": "Same task", "priority": "IMPORTANT"},
    ]}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r1 = await c.post("/webhooks/meeting-action-items", json=payload)
        r2 = await c.post("/webhooks/meeting-action-items", json=payload)
    assert r1.json()["created"] == 1
    assert r2.json()["created"] == 0
    rows = (await db_session.execute(select(TaskItem))).scalars().all()
    assert len(rows) == 1
```

- [ ] **Step 2: Run tests, verify failure** — Module/route not found.

- [ ] **Step 3: Implement `routes_webhook.py`**

```python
"""Webhook ingestion from the meetings decision engine."""
from fastapi import APIRouter, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from assignee_map import AssigneeMap
from db import session
from models import TaskItem
from schemas import IngestRequest

router = APIRouter()


@router.post("/webhooks/meeting-action-items", status_code=status.HTTP_201_CREATED)
async def ingest(payload: IngestRequest) -> dict[str, int]:
    """Idempotent insert of action items for a meeting."""
    amap = AssigneeMap.from_env()
    created = 0
    async with session() as s:
        for item in payload.items:
            email = amap.resolve(item.assignee)
            stmt = pg_insert(TaskItem.__table__).values(
                meeting_id=payload.meeting_id,
                action_type=item.action_type,
                assignee_name=item.assignee,
                assignee_email=email,
                description=item.description,
                query=item.query,
                priority=item.priority,
            ).on_conflict_do_nothing()
            result = await s.execute(stmt)
            if result.rowcount:
                created += 1
        await s.commit()
    return {"created": created}
```

> **Note for implementer:** `on_conflict_do_nothing()` with no args lets Postgres detect any unique conflict — including the expression-based `items_meeting_desc_uniq UNIQUE (meeting_id, md5(description))` from the migration. If SQLAlchemy still complains, fall back to a raw `INSERT ... ON CONFLICT DO NOTHING` via `text()`.

- [ ] **Step 4: Mount the router in `main.py`**

```python
from routes_webhook import router as webhook_router
app.include_router(webhook_router)
```

- [ ] **Step 5: Run tests, verify pass** — Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add mcp-servers/tasks/routes_webhook.py mcp-servers/tasks/tests/test_routes_webhook.py mcp-servers/tasks/main.py
git commit -m "feat(tasks): add idempotent webhook ingestion of meeting action items"
```

---

## Task 7: Task list + status transitions (manual flow)

**Files:**
- Create: `mcp-servers/tasks/routes_tasks.py`
- Create: `mcp-servers/tasks/tests/test_routes_tasks.py`
- Modify: `mcp-servers/tasks/main.py` (mount router)

- [ ] **Step 1: Write failing tests** for these endpoints:
  - `GET /api/tasks?status=pending` — returns only current admin's pending items
  - `POST /api/tasks/{id}/manual` — pending → claimed_manual, mode='manual'
  - `POST /api/tasks/{id}/complete` — claimed_manual → completed, fills result + completed_at
  - `POST /api/tasks/{id}/answer` — pending(ASK_USER) → completed; or awaiting_input → running (resume) — see Task 9 for the resume path; for now just assert completion of ASK_USER tasks
  - `GET /api/tasks/history?limit=10` — returns paginated completed/failed items

```python
# tests/test_routes_tasks.py — abridged, write all 5 tests
import uuid
import pytest
from httpx import AsyncClient, ASGITransport
from main import app
from models import TaskItem

ADMIN_HEADERS = {"X-User-Email": "ralph@aiui.com", "X-User-Admin": "true"}


@pytest.mark.asyncio
async def test_list_returns_only_pending_for_current_admin(db_session):
    db_session.add(TaskItem(
        meeting_id=uuid.uuid4(), action_type="BUILD",
        assignee_name="Ralph", assignee_email="ralph@aiui.com",
        description="mine", priority="CRITICAL",
    ))
    db_session.add(TaskItem(
        meeting_id=uuid.uuid4(), action_type="BUILD",
        assignee_name="Lukas", assignee_email="lukas@aiui.com",
        description="not mine", priority="CRITICAL",
    ))
    await db_session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/tasks?status=pending", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    descs = [t["description"] for t in r.json()]
    assert descs == ["mine"]


@pytest.mark.asyncio
async def test_manual_transition(db_session):
    item = TaskItem(meeting_id=uuid.uuid4(), action_type="BUILD",
                    assignee_name="Ralph", assignee_email="ralph@aiui.com",
                    description="d", priority="IMPORTANT")
    db_session.add(item); await db_session.commit(); await db_session.refresh(item)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(f"/api/tasks/{item.id}/manual", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    assert r.json()["status"] == "claimed_manual"
    assert r.json()["mode"] == "manual"


@pytest.mark.asyncio
async def test_complete_sets_result_and_timestamp(db_session):
    item = TaskItem(meeting_id=uuid.uuid4(), action_type="BUILD",
                    assignee_name="Ralph", assignee_email="ralph@aiui.com",
                    description="d", priority="IMPORTANT", status="claimed_manual", mode="manual")
    db_session.add(item); await db_session.commit(); await db_session.refresh(item)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(f"/api/tasks/{item.id}/complete",
                         json={"result": "Done it"}, headers=ADMIN_HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "completed"
    assert body["result"] == "Done it"
    assert body["completed_at"] is not None


@pytest.mark.asyncio
async def test_history_returns_completed_and_failed_paginated(db_session):
    for i in range(3):
        db_session.add(TaskItem(
            meeting_id=uuid.uuid4(), action_type="BUILD",
            assignee_name="Ralph", assignee_email="ralph@aiui.com",
            description=f"item-{i}", priority="IMPORTANT",
            status="completed", mode="ai",
        ))
    await db_session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/tasks/history?limit=2", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    assert len(r.json()) == 2
```

- [ ] **Step 2: Run tests** — verify failures.

- [ ] **Step 3: Implement `routes_tasks.py`**

```python
"""Task CRUD + state transitions (manual mode)."""
from datetime import datetime
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from auth import AdminUser, current_admin
from db import session
from models import TaskItem
from schemas import AnswerRequest, CompleteRequest, TaskOut

router = APIRouter(prefix="/api/tasks")


async def _get_owned_task(s, task_id: UUID, email: str) -> TaskItem:
    res = await s.execute(select(TaskItem).where(TaskItem.id == task_id))
    item = res.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Task not found")
    # Email match OR team-pool sentinel
    if item.assignee_email != email and item.assignee_email != "team@aiui.local":
        raise HTTPException(status_code=403, detail="Not your task")
    return item


@router.get("", response_model=list[TaskOut])
async def list_tasks(status: str = "pending", limit: int = 50, user: AdminUser = Depends(current_admin)):
    statuses_by_tab = {
        "pending": ["pending", "awaiting_input"],
        "progress": ["running", "claimed_manual"],
        "done": ["completed", "failed"],
    }
    if status not in statuses_by_tab:
        raise HTTPException(status_code=400, detail="Invalid status filter")

    async with session() as s:
        q = (
            select(TaskItem)
            .where(
                TaskItem.assignee_email.in_([user.email, "team@aiui.local"]),
                TaskItem.status.in_(statuses_by_tab[status]),
            )
            .order_by(TaskItem.created_at.desc())
            .limit(limit)
        )
        rows = (await s.execute(q)).scalars().all()
    return rows


@router.get("/history", response_model=list[TaskOut])
async def history(limit: int = 50, offset: int = 0, user: AdminUser = Depends(current_admin)):
    async with session() as s:
        q = (
            select(TaskItem)
            .where(
                TaskItem.assignee_email.in_([user.email, "team@aiui.local"]),
                TaskItem.status.in_(["completed", "failed"]),
            )
            .order_by(TaskItem.completed_at.desc().nullslast())
            .limit(limit).offset(offset)
        )
        rows = (await s.execute(q)).scalars().all()
    return rows


@router.post("/{task_id}/manual", response_model=TaskOut)
async def claim_manual(task_id: UUID, user: AdminUser = Depends(current_admin)):
    async with session() as s:
        item = await _get_owned_task(s, task_id, user.email)
        if item.status != "pending":
            raise HTTPException(status_code=409, detail=f"Task is {item.status}")
        item.status = "claimed_manual"
        item.mode = "manual"
        await s.commit(); await s.refresh(item)
    return item


@router.post("/{task_id}/complete", response_model=TaskOut)
async def complete(task_id: UUID, body: CompleteRequest, user: AdminUser = Depends(current_admin)):
    async with session() as s:
        item = await _get_owned_task(s, task_id, user.email)
        if item.status not in ("claimed_manual", "awaiting_input"):
            raise HTTPException(status_code=409, detail=f"Cannot complete from {item.status}")
        item.status = "completed"
        item.result = body.result
        item.completed_at = datetime.utcnow()
        await s.commit(); await s.refresh(item)
    return item


@router.post("/{task_id}/answer", response_model=TaskOut)
async def answer(task_id: UUID, body: AnswerRequest, user: AdminUser = Depends(current_admin)):
    """For ASK_USER tasks, completes immediately. For awaiting_input AI tasks, see Task 9."""
    async with session() as s:
        item = await _get_owned_task(s, task_id, user.email)
        if item.action_type == "ASK_USER" and item.status == "pending":
            item.status = "completed"
            item.mode = "manual"
            item.result = body.answer
            item.completed_at = datetime.utcnow()
            await s.commit(); await s.refresh(item)
            return item
        # AI resume path is implemented in Task 9
        raise HTTPException(status_code=409, detail="Answer not applicable in current state")
```

- [ ] **Step 4: Mount router in `main.py`** and run tests. Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/routes_tasks.py mcp-servers/tasks/tests/test_routes_tasks.py mcp-servers/tasks/main.py
git commit -m "feat(tasks): add task list, manual claim, complete, answer, history endpoints"
```

---

## Task 8: Claude executor module (sentinel parser)

**Files:**
- Create: `mcp-servers/tasks/claude_executor.py`
- Create: `mcp-servers/tasks/tests/test_claude_executor.py`

This task does NOT spawn the subprocess yet — it isolates the sentinel parser and prompt builder so they're testable in isolation.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_claude_executor.py
from claude_executor import build_prompt, parse_outcome, Outcome


def test_build_prompt_includes_task_fields():
    p = build_prompt(description="Fix routing", action_type="BUILD",
                     priority="CRITICAL", meeting_title="Standup", meeting_date="Apr 8")
    assert "Fix routing" in p and "BUILD" in p and "CRITICAL" in p and "Standup" in p


def test_parse_completed():
    o = parse_outcome("Did the work.\nCOMPLETED: Updated Caddyfile and reloaded.")
    assert o.kind == "completed"
    assert o.payload == "Updated Caddyfile and reloaded."


def test_parse_needs_input():
    o = parse_outcome("Looked at it.\nNEEDS_INPUT: What's the Trello API token?")
    assert o.kind == "needs_input"
    assert "Trello API token" in o.payload


def test_parse_needs_steps():
    o = parse_outcome("NEEDS_STEPS: 1. Open Caddyfile\n2. Edit\n3. Reload")
    assert o.kind == "needs_steps"
    assert o.payload.startswith("1. Open Caddyfile")


def test_parse_no_sentinel_treated_as_failed():
    o = parse_outcome("I tried but I'm confused.")
    assert o.kind == "failed"
```

- [ ] **Step 2: Run tests** — ImportError.

- [ ] **Step 3: Implement `claude_executor.py`** (parser + prompt only for now)

```python
"""Build prompts and parse Claude Code outcomes for task execution."""
import re
from dataclasses import dataclass
from typing import Literal

PROMPT_TEMPLATE = """You are executing a task from the AIUI meeting decision engine.

TASK: {description}
TYPE: {action_type}
PRIORITY: {priority}
SOURCE: {meeting_title} on {meeting_date}

Repository: /workspace/ai_ui (you have full read/write access in this container)

Complete the task autonomously. If you cannot proceed because of:
  - Missing credentials → respond ending with: NEEDS_INPUT: <what you need>
  - Unclear requirement → respond ending with: NEEDS_INPUT: <clarifying question>
  - Hard blocker → respond ending with: NEEDS_STEPS: <numbered manual steps>

When done successfully, respond ending with: COMPLETED: <summary of what you did>"""


def build_prompt(*, description: str, action_type: str, priority: str,
                 meeting_title: str, meeting_date: str) -> str:
    return PROMPT_TEMPLATE.format(
        description=description, action_type=action_type, priority=priority,
        meeting_title=meeting_title, meeting_date=meeting_date,
    )


@dataclass(frozen=True)
class Outcome:
    kind: Literal["completed", "needs_input", "needs_steps", "failed"]
    payload: str


_SENTINEL_RE = re.compile(
    r"^(?P<kind>COMPLETED|NEEDS_INPUT|NEEDS_STEPS):\s*(?P<rest>.*)",
    re.MULTILINE | re.DOTALL,
)


def parse_outcome(claude_response: str) -> Outcome:
    """Find the LAST sentinel line and treat its payload as the result."""
    matches = list(_SENTINEL_RE.finditer(claude_response))
    if not matches:
        return Outcome(kind="failed", payload=claude_response.strip()[:500])
    last = matches[-1]
    kind_map = {"COMPLETED": "completed", "NEEDS_INPUT": "needs_input", "NEEDS_STEPS": "needs_steps"}
    return Outcome(kind=kind_map[last.group("kind")], payload=last.group("rest").strip())
```

- [ ] **Step 4: Run tests** — Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/claude_executor.py mcp-servers/tasks/tests/test_claude_executor.py
git commit -m "feat(tasks): add claude prompt builder and outcome sentinel parser"
```

---

## Task 9: Execute + SSE stream + cancel

**Files:**
- Modify: `mcp-servers/tasks/claude_executor.py` (add `run_claude_subprocess`)
- Create: `mcp-servers/tasks/routes_execution.py`
- Create: `mcp-servers/tasks/tests/test_routes_execution.py`
- Modify: `mcp-servers/tasks/main.py` (mount router)
- Modify: `mcp-servers/tasks/routes_tasks.py` (resume path in `/answer` for awaiting_input)

- [ ] **Step 1: Add `run_claude_subprocess` to `claude_executor.py`** — spawn the `claude` CLI in the mounted workspace, stream stdout chunks. The CLI is installed in the Dockerfile (Task 0).

```python
import asyncio
import os
from typing import AsyncIterator

CLAUDE_WORKSPACE = os.environ.get("CLAUDE_WORKSPACE", "/workspace/ai_ui")
EXECUTION_TIMEOUT_SECONDS = 300


async def run_claude_subprocess(prompt: str) -> AsyncIterator[str]:
    """Spawn the claude CLI with --print and stream its stdout.

    --print runs Claude non-interactively and writes the full response to stdout.
    --dangerously-skip-permissions is required so file edits don't prompt; this
    runs inside an isolated container with the repo mount as its only filesystem.
    """
    proc = await asyncio.create_subprocess_exec(
        "claude", "--print", "--dangerously-skip-permissions", prompt,
        cwd=CLAUDE_WORKSPACE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env={**os.environ},  # passes ANTHROPIC_API_KEY from container env
    )
    assert proc.stdout is not None
    try:
        async with asyncio.timeout(EXECUTION_TIMEOUT_SECONDS):
            while True:
                chunk = await proc.stdout.read(4096)
                if not chunk:
                    break
                yield chunk.decode("utf-8", errors="replace")
            await proc.wait()
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        yield "\n[TIMEOUT after 300s — process killed]\n"
```

> **Validation:** The plan assumes the official `@anthropic-ai/claude-code` npm package, invoked as `claude --print "<prompt>"`. Verify the exact flag names with `claude --help` after building the container. If `--dangerously-skip-permissions` is named differently in the installed version, update accordingly.

- [ ] **Step 2: Implement `routes_execution.py`**

```python
"""AI execution: spawns the claude CLI subprocess, streams progress via SSE."""
import asyncio
import logging
from datetime import datetime
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, update
from sse_starlette.sse import EventSourceResponse

from auth import AdminUser, current_admin
from claude_executor import build_prompt, parse_outcome, run_claude_subprocess
from db import session
from models import TaskExecution, TaskItem
from schemas import TaskOut

logger = logging.getLogger("tasks")
router = APIRouter(prefix="/api/tasks")

# In-process registry of running execution tasks for cancellation
_RUNNING: dict[UUID, asyncio.Task] = {}


async def _run_execution(task_id: UUID, execution_id: UUID, prompt: str):
    """Background coroutine: stream Claude output, parse outcome, persist."""
    full_log: list[str] = []
    try:
        async for chunk in run_claude_subprocess(prompt):
            full_log.append(chunk)
            async with session() as s:
                await s.execute(
                    update(TaskExecution).where(TaskExecution.id == execution_id)
                    .values(log=TaskExecution.log + chunk)
                )
                await s.commit()

        outcome = parse_outcome("".join(full_log))
        new_task_status = {
            "completed": "completed", "needs_input": "awaiting_input",
            "needs_steps": "claimed_manual", "failed": "failed",
        }[outcome.kind]
        new_exec_status = {
            "completed": "succeeded", "needs_input": "needs_input",
            "needs_steps": "succeeded", "failed": "failed",
        }[outcome.kind]

        async with session() as s:
            await s.execute(
                update(TaskExecution).where(TaskExecution.id == execution_id)
                .values(status=new_exec_status, finished_at=datetime.utcnow())
            )
            await s.execute(
                update(TaskItem).where(TaskItem.id == task_id).values(
                    status=new_task_status,
                    mode="ai" if outcome.kind != "needs_steps" else "manual",
                    result=outcome.payload,
                    completed_at=datetime.utcnow() if outcome.kind == "completed" else None,
                )
            )
            await s.commit()
    except Exception as exc:
        logger.exception("Execution failed: %s", exc)
        async with session() as s:
            await s.execute(
                update(TaskExecution).where(TaskExecution.id == execution_id)
                .values(status="failed", error=str(exc), finished_at=datetime.utcnow())
            )
            await s.execute(
                update(TaskItem).where(TaskItem.id == task_id).values(status="failed")
            )
            await s.commit()
    finally:
        _RUNNING.pop(task_id, None)


@router.post("/{task_id}/execute", response_model=TaskOut)
async def execute(task_id: UUID, user: AdminUser = Depends(current_admin)):
    async with session() as s:
        item = (await s.execute(select(TaskItem).where(TaskItem.id == task_id))).scalar_one_or_none()
        if item is None: raise HTTPException(404, "Task not found")
        if item.assignee_email not in (user.email, "team@aiui.local"):
            raise HTTPException(403, "Not your task")
        if item.action_type not in ("BUILD", "INTEGRATE"):
            raise HTTPException(400, "AI execution not allowed for this task type")
        if item.status not in ("pending", "awaiting_input"):
            raise HTTPException(409, f"Task is {item.status}")
        item.status = "running"; item.mode = "ai"
        execution = TaskExecution(task_id=item.id, status="running", log="")
        s.add(execution)
        await s.commit(); await s.refresh(item); await s.refresh(execution)

    prompt = build_prompt(
        description=item.description, action_type=item.action_type,
        priority=item.priority, meeting_title=str(item.meeting_id), meeting_date="",
    )
    bg = asyncio.create_task(_run_execution(item.id, execution.id, prompt))
    _RUNNING[item.id] = bg
    return item


@router.get("/{task_id}/stream")
async def stream(task_id: UUID, request: Request, from_: int = 0,
                 user: AdminUser = Depends(current_admin)):
    """SSE stream of execution log. Pass `?from_=<line_no>` to resume after disconnect."""
    async def event_generator():
        last_len = from_
        while True:
            if await request.is_disconnected():
                break
            async with session() as s:
                row = (await s.execute(
                    select(TaskExecution).where(TaskExecution.task_id == task_id)
                    .order_by(TaskExecution.started_at.desc()).limit(1)
                )).scalar_one_or_none()
                item = (await s.execute(
                    select(TaskItem).where(TaskItem.id == task_id)
                )).scalar_one_or_none()
            if row is None or item is None:
                yield {"event": "error", "data": "no execution"}; break
            if len(row.log) > last_len:
                yield {"event": "log", "data": row.log[last_len:]}
                last_len = len(row.log)
            if item.status not in ("running",):
                yield {"event": "done", "data": item.status}
                break
            await asyncio.sleep(1.0)
    return EventSourceResponse(event_generator())


@router.post("/{task_id}/cancel", response_model=TaskOut)
async def cancel(task_id: UUID, user: AdminUser = Depends(current_admin)):
    bg = _RUNNING.pop(task_id, None)
    if bg: bg.cancel()
    async with session() as s:
        await s.execute(update(TaskItem).where(TaskItem.id == task_id).values(status="failed"))
        await s.execute(
            update(TaskExecution).where(TaskExecution.task_id == task_id, TaskExecution.status == "running")
            .values(status="failed", error="cancelled by user", finished_at=datetime.utcnow())
        )
        await s.commit()
        item = (await s.execute(select(TaskItem).where(TaskItem.id == task_id))).scalar_one()
    return item
```

- [ ] **Step 3: Update `routes_tasks.py /answer` to handle the resume path**

In the `answer` function, before the final `raise HTTPException`, add:

```python
if item.status == "awaiting_input":
    # Append the answer to the prompt context and re-execute
    from routes_execution import _run_execution
    from claude_executor import build_prompt
    item.status = "running"
    new_exec = TaskExecution(task_id=item.id, status="running", log="")
    s.add(new_exec)
    await s.commit(); await s.refresh(item); await s.refresh(new_exec)

    prompt = build_prompt(
        description=item.description, action_type=item.action_type,
        priority=item.priority, meeting_title=str(item.meeting_id), meeting_date="",
    ) + f"\n\nADMIN PROVIDED THIS ANSWER: {body.answer}"
    import asyncio
    asyncio.create_task(_run_execution(item.id, new_exec.id, prompt))
    return item
```

- [ ] **Step 4: Write tests** with `run_claude_subprocess` monkeypatched

```python
# tests/test_routes_execution.py
import asyncio, uuid, pytest
from httpx import AsyncClient, ASGITransport
from main import app
from models import TaskItem
from sqlalchemy import select

ADMIN = {"X-User-Email": "ralph@aiui.com", "X-User-Admin": "true"}


async def _fake_completed(prompt):
    yield "Read Caddyfile\n"; yield "COMPLETED: Updated and reloaded.\n"


async def _fake_needs_input(prompt):
    yield "NEEDS_INPUT: What is the API key?\n"


@pytest.mark.asyncio
async def test_execute_completed_path(db_session, monkeypatch):
    import claude_executor
    monkeypatch.setattr(claude_executor, "run_claude_subprocess", _fake_completed)
    item = TaskItem(meeting_id=uuid.uuid4(), action_type="BUILD",
                    assignee_name="Ralph", assignee_email="ralph@aiui.com",
                    description="d", priority="CRITICAL")
    db_session.add(item); await db_session.commit(); await db_session.refresh(item)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(f"/api/tasks/{item.id}/execute", headers=ADMIN)
    assert r.status_code == 200
    # Poll until background task finishes
    for _ in range(30):
        await db_session.refresh(item)
        if item.status == "completed": break
        await asyncio.sleep(0.1)
    assert item.status == "completed"
    assert "Updated and reloaded" in item.result


@pytest.mark.asyncio
async def test_execute_needs_input_path(db_session, monkeypatch):
    import claude_executor
    monkeypatch.setattr(claude_executor, "run_claude_subprocess", _fake_needs_input)
    item = TaskItem(meeting_id=uuid.uuid4(), action_type="INTEGRATE",
                    assignee_name="Ralph", assignee_email="ralph@aiui.com",
                    description="d", priority="IMPORTANT")
    db_session.add(item); await db_session.commit(); await db_session.refresh(item)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        await c.post(f"/api/tasks/{item.id}/execute", headers=ADMIN)
    for _ in range(30):
        await db_session.refresh(item)
        if item.status == "awaiting_input": break
        await asyncio.sleep(0.1)
    assert item.status == "awaiting_input"
    assert "API key" in item.result
```

- [ ] **Step 5: Mount router in `main.py`, run tests** — Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add mcp-servers/tasks/claude_executor.py mcp-servers/tasks/routes_execution.py mcp-servers/tasks/routes_tasks.py mcp-servers/tasks/tests/test_routes_execution.py mcp-servers/tasks/main.py
git commit -m "feat(tasks): add AI execution via claude subprocess with SSE stream and cancel"
```

---

## Task 10: Wire decision engine to webhook

**Files:**
- Modify: `mcp-servers/meetings/decision_engine.py` (call tasks webhook in addition to Discord)
- Modify: `mcp-servers/meetings/main.py` (read `TASKS_WEBHOOK_URL`)
- Modify: `docker-compose.unified.yml` (add `TASKS_WEBHOOK_URL` to meetings env)

- [ ] **Step 1: Add helper to `decision_engine.py`**

```python
TASKS_WEBHOOK_URL = os.environ.get("TASKS_WEBHOOK_URL", "")

async def post_to_tasks_service(meeting_id: str, items: list[dict]) -> bool:
    if not TASKS_WEBHOOK_URL:
        logger.info("TASKS_WEBHOOK_URL not set — skipping tasks webhook")
        return False
    payload = {"meeting_id": meeting_id, "items": [
        {
            "action_type": it.get("type", "BUILD"),
            "assignee": it.get("assignee", "team"),
            "description": it.get("description", ""),
            "query": it.get("query"),
            "priority": it.get("priority", "IMPORTANT"),
        } for it in items
    ]}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(TASKS_WEBHOOK_URL, json=payload)
            return resp.is_success
    except Exception as exc:
        logger.error(f"Tasks webhook failed: {exc}")
        return False
```

- [ ] **Step 2: Update `process_action_items` signature** to accept `meeting_id` and call `post_to_tasks_service` after classification

```python
async def process_action_items(
    openwebui_url: str, api_key: str, discord_webhook_url: str,
    summary: str, title: str = "", meeting_id: str = "",
) -> dict:
    items = await classify_action_items(openwebui_url, api_key, summary, title)
    if not items:
        return {"processed": 0, "results": []}

    if meeting_id:
        await post_to_tasks_service(meeting_id, items)
    # ... existing Discord routing unchanged
```

- [ ] **Step 3: Update caller in `meetings/main.py`** (in `_process_and_push`) to pass `meeting_id=str(record.id)` to `process_action_items`.

- [ ] **Step 4: Add `TASKS_WEBHOOK_URL=${TASKS_WEBHOOK_URL}` to the `meetings` service env block in `docker-compose.unified.yml`.**

- [ ] **Step 5: Manual integration test** — POST a meeting with a synthetic summary containing action items; check that rows appear in `tasks.items`:

```bash
curl -X POST http://localhost:8000/ -H 'Content-Type: application/json' -d '{
  "title": "Test Meeting",
  "date": "2026-04-13",
  "summary": "## Action Items\n- 🔴 **Ralph Benitez**: Test webhook"
}'

sleep 5
docker exec -i postgres psql -U openwebui -d openwebui -c "SELECT description, assignee_email FROM tasks.items;"
```

- [ ] **Step 6: Commit**

```bash
git add mcp-servers/meetings/decision_engine.py mcp-servers/meetings/main.py docker-compose.unified.yml
git commit -m "feat(meetings): forward classified action items to tasks service webhook"
```

---

## Task 11: Caddy routing

**Files:**
- Modify: `Caddyfile`

- [ ] **Step 1: Add a route block for the tasks service.** Place near the meetings/n8n routes, sending both the API and the static frontend through the API gateway (so JWT validation + `X-User-Email` header injection still happens):

```caddyfile
        # Tasks service — admin task panel API + static assets
        handle /api/tasks/* {
            reverse_proxy api-gateway:8080
        }
        handle /webhooks/meeting-action-items {
            reverse_proxy tasks:8210
        }
        handle /tasks/static/* {
            reverse_proxy tasks:8210
        }
```

> Note: `/webhooks/*` skips the gateway — it's an internal endpoint called from the meetings container directly. If exposed externally, restrict it (Caddy `@internal` matcher on source IP, or a shared secret header).

- [ ] **Step 2: Update API gateway routing** in `api-gateway/main.py`. The router is an `if/elif` chain inside `proxy_handler()` (around lines 376–417). Follow the same pattern used for `/mcp/meeting-kb/api/*` (line 401). Add a new branch **before** the final `else`:

```python
# /api/tasks/* → Tasks service (bypass MCP Proxy)
elif full_path.startswith("/api/tasks"):
    backend_url = os.getenv("TASKS_URL", "http://tasks:8210")
    backend_path = full_path
```

Also add `TASKS_URL` to the env block of the `api-gateway` service in `docker-compose.unified.yml`:

```yaml
      - TASKS_URL=http://tasks:8210
```

- [ ] **Step 3: Reload Caddy and gateway**

```bash
docker compose -f docker-compose.unified.yml restart caddy api-gateway
```

- [ ] **Step 4: Smoke test** — `curl https://ai-ui.coolestdomain.win/api/tasks?status=pending -H 'Cookie: token=<your-jwt>'` should return `[]` for a logged-in admin (or 403 for non-admin).

- [ ] **Step 5: Commit**

```bash
git add Caddyfile api-gateway/main.py
git commit -m "feat(tasks): wire tasks service routes through caddy and api-gateway"
```

---

## Task 12: Frontend `task-panel.js` (production)

**Files:**
- Create: `mcp-servers/tasks/static/task-panel.js`
- Modify: `mcp-servers/tasks/main.py` (mount static files)

The production JS is derived from `prototypes/task-panel.html` but:
- Hits the real `/api/tasks` endpoints (no sample data)
- Uses fetch with `credentials: "include"` (browser session cookie carries the JWT)
- Wires `⚡ AI` → `POST /api/tasks/{id}/execute` then opens an SSE stream
- Wires `✋ Manual` → `POST /api/tasks/{id}/manual`
- Wires `💬 Answer` → opens a textarea, then `POST /api/tasks/{id}/answer`
- Auto-popup on page load if pending count > 0 AND `localStorage.aiui-tasks-dismissed-at` is older than 4h
- "See full history →" link goes to `/tasks/static/task-history.html`

- [ ] **Step 1: Create `static/task-panel.js`** — port the prototype, replacing sample data with real fetch calls. Reuse the CSS-in-JS structure from the prototype.

- [ ] **Step 2: Add SSE handler**

```javascript
function startStreaming(taskId, cardEl) {
  const lastLineEl = cardEl.querySelector(".live-status");
  const ev = new EventSource(`/api/tasks/${taskId}/stream`, { withCredentials: true });
  ev.addEventListener("log", (e) => { lastLineEl.textContent = e.data.split("\n").filter(Boolean).slice(-1)[0] || ""; });
  ev.addEventListener("done", (e) => { ev.close(); refreshTasks(); });
  ev.onerror = () => { ev.close(); };
}
```

- [ ] **Step 3: Mount static files in `main.py`**

```python
from fastapi.staticfiles import StaticFiles
app.mount("/tasks/static", StaticFiles(directory="static"), name="static")
```

- [ ] **Step 4: Manual smoke test in browser**

1. Add to Open WebUI's admin → Settings → Interface → Custom JS:
   ```html
   <script src="/tasks/static/task-panel.js"></script>
   ```
2. Reload Open WebUI as admin → panel appears top-right with real tasks.
3. Click `⚡ AI` on a BUILD task → SSE updates show in the card.

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/static/ mcp-servers/tasks/main.py
git commit -m "feat(tasks): add production task-panel.js loaded via openwebui custom js"
```

---

## Task 13: History page

**Files:**
- Create: `mcp-servers/tasks/static/task-history.html`

- [ ] **Step 1: Create a single-file HTML page** at `static/task-history.html` that:
  - Calls `GET /api/tasks/history?limit=50&offset=N`
  - Renders a table: Date · Type · Description · Mode · Result
  - Has prev/next pagination buttons (drives `offset`)
  - Reuses the panel's color palette so it feels native
  - Links back to Open WebUI top-left

- [ ] **Step 2: Smoke test** — open `https://ai-ui.coolestdomain.win/tasks/static/task-history.html` while logged in.

- [ ] **Step 3: Commit**

```bash
git add mcp-servers/tasks/static/task-history.html
git commit -m "feat(tasks): add full history page with pagination"
```

---

## Task 14: End-to-end smoke test on staging

- [ ] **Step 1: Deploy** the merged branch to the staging VPS.

- [ ] **Step 2: Trigger a real meeting ingest** via the existing meetings endpoint. Wait ~30s for AI processing.

- [ ] **Step 3: Log in as Ralph** in Open WebUI, verify the panel auto-pops with the new pending action items assigned to "Ralph".

- [ ] **Step 4: Click `✋ Manual`** on one task, then `Complete` with a note. Verify it appears in the Done tab and on the history page.

- [ ] **Step 5: Click `⚡ AI`** on a BUILD task. Verify SSE log streams and the task ends in `completed` (or `awaiting_input`/`failed` depending on what Claude does).

- [ ] **Step 6: Log in as a non-admin user.** Verify the panel does NOT load (auth dependency rejects).

- [ ] **Step 7: Capture screenshots** for the PR description.

- [ ] **Step 8: Commit any tweaks discovered during smoke test, then open PR.**

```bash
git push -u origin feat/gdrive-gmail-connectors
gh pr create --title "feat: admin task approval panel" --body "..."
```

---

## Notes for the implementer

- **Skill:** Use `superpowers:test-driven-development` mindset throughout — write the failing test before each implementation step.
- **DRY:** The status-transition guards repeat across endpoints. If they grow beyond 3-4 occurrences, extract a `transition(item, from_states, to_state)` helper.
- **YAGNI:** Do not add task editing, task deletion, or task reassignment endpoints in v1. They are explicitly out of scope.
- **Frequent commits:** One commit per task. If a task feels too big, split it.
- **Containers, not local dev:** All Python runs inside the `tasks` container. Tests use `docker compose exec tasks pytest`.
- **No mocking the database:** Tests use a real Postgres `tasks` schema. Truncate between tests via the `db_session` fixture.
