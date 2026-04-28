# App Builder Supabase Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users attach a Supabase project (URL + anon key) to any AIUI app — encrypted at rest, injected into the live app at runtime, and instructed to Claude on every build/enhance. Supabase is now the only first-class storage option (no localStorage prompts).

**Architecture:**
- New `tasks.project_supabase` table — one row per slug, anon key Fernet-encrypted.
- New endpoints `GET / POST / DELETE /api/projects/{slug}/supabase`, owner-only mutations via `_require_role(..., "owner", is_admin=...)`.
- Static-serve route inlines a `<script>` setting `window.SUPABASE_URL` / `window.SUPABASE_ANON_KEY` at the top of `<head>` for every published HTML response.
- BUILD/ENHANCE prompt templates gain a `{supabase_block}` placeholder filled when a config exists, with explicit instructions and a CDN import snippet.
- `projects.html` create-modal removes the localStorage option; the Supabase config UI lives inside the per-project Publish modal.

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy 2.x async / `cryptography` (Fernet) / pytest-asyncio / vanilla JS frontend.

---

## File Structure

**Will create:**
- `mcp-servers/tasks/migrations/007_project_supabase.sql` — table
- `mcp-servers/tasks/crypto_utils.py` — Fernet encrypt/decrypt with key from env
- `mcp-servers/tasks/routes_supabase.py` — `GET / POST / DELETE /api/projects/{slug}/supabase`
- `mcp-servers/tasks/tests/test_crypto_utils.py` — round-trip + missing-key behaviour
- `mcp-servers/tasks/tests/test_supabase_config.py` — endpoint coverage incl. role gating
- `mcp-servers/tasks/tests/test_supabase_inject.py` — verifies window vars get spliced into HTML at serve time
- `mcp-servers/tasks/tests/test_supabase_prompt.py` — verifies the build prompt includes the Supabase block when configured

**Will modify:**
- `mcp-servers/tasks/models.py` — add `ProjectSupabase` model
- `mcp-servers/tasks/main.py` — register router; inject `<script>` at `<head>` in `serve_published_app` for HTML responses
- `mcp-servers/tasks/claude_executor.py` — add `SUPABASE_BLOCK_TEMPLATE`, `_supabase_block(...)`, accept `supabase_url=` in `build_prompt` + `build_enhance_prompt`
- `mcp-servers/tasks/routes_execution.py` — fetch the project's Supabase URL when running a task and pass it to `build_prompt`
- `mcp-servers/tasks/routes_tasks.py` — same for `enhance` calling `build_enhance_prompt`
- `mcp-servers/tasks/static/projects.html` — drop the localStorage option from the New Project modal, keep "None" + "Supabase (configure after creating)"
- `mcp-servers/tasks/static/preview.html` — Supabase section in the Publish modal (URL + anon key + Save / Disconnect)
- `mcp-servers/tasks/requirements.txt` (or `pyproject.toml`) — add `cryptography>=42`
- `/root/proxy-server/.env` (host) — add `AIUI_FERNET_KEY=…`

---

### Task 1: Generate Fernet key + add to host .env

**Files:**
- Modify: `/root/proxy-server/.env` on the VPS

This is one-time setup before any code runs.

- [ ] **Step 1: Generate the key locally**

```bash
docker run --rm python:3.12-slim python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Save the printed string — it'll look like `<REDACTED-TEST-KEY-44CHARS>`.

- [ ] **Step 2: Append to host .env**

Replace `<KEY>` with the value from Step 1:

```bash
ssh -i ~/.ssh/aiui_safe root@46.224.193.25 "echo 'AIUI_FERNET_KEY=<KEY>' >> /root/proxy-server/.env && grep AIUI_FERNET_KEY /root/proxy-server/.env"
```

Expected output: `AIUI_FERNET_KEY=…` printed once. (If grep prints multiple lines, we have duplicates — keep only the last one.)

- [ ] **Step 3: Restart tasks container so env is picked up**

```bash
ssh -i ~/.ssh/aiui_safe root@46.224.193.25 "cd /root/proxy-server && docker compose up -d tasks && sleep 3 && docker exec tasks printenv AIUI_FERNET_KEY"
```

Expected: prints the key value (proves the env var is loaded inside the container).

- [ ] **Step 4: No commit — `.env` is git-ignored.** Just verify with:

```bash
git -C "C:/All/Work - Code/ai_ui" check-ignore -v .env
```

Expected output names a `.gitignore` rule covering `.env`.

---

### Task 2: `crypto_utils.py` Fernet helper

**Files:**
- Create: `mcp-servers/tasks/crypto_utils.py`
- Create: `mcp-servers/tasks/tests/test_crypto_utils.py`
- Modify: `mcp-servers/tasks/requirements.txt` (add `cryptography>=42`)

- [ ] **Step 1: Write the failing tests**

Create `mcp-servers/tasks/tests/test_crypto_utils.py`:

```python
"""Round-trip + key-handling tests for crypto_utils."""
import pytest


def test_encrypt_decrypt_round_trip(monkeypatch):
    monkeypatch.setenv("AIUI_FERNET_KEY", "<REDACTED-TEST-KEY-44CHARS>")
    from importlib import reload
    import crypto_utils
    reload(crypto_utils)

    plain = "eyJhbGciOiJIUzI1NiJ9.example.payload"
    enc = crypto_utils.encrypt(plain)
    assert enc != plain
    assert crypto_utils.decrypt(enc) == plain


def test_decrypt_with_wrong_key_raises(monkeypatch):
    """Tokens encrypted under a different key must fail to decrypt."""
    monkeypatch.setenv("AIUI_FERNET_KEY", "<REDACTED-TEST-KEY-44CHARS>")
    from importlib import reload
    import crypto_utils
    reload(crypto_utils)
    enc = crypto_utils.encrypt("hello")

    monkeypatch.setenv("AIUI_FERNET_KEY", "<REDACTED-TEST-KEY-44CHARS>")
    reload(crypto_utils)
    from cryptography.fernet import InvalidToken
    with pytest.raises(InvalidToken):
        crypto_utils.decrypt(enc)


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("AIUI_FERNET_KEY", raising=False)
    from importlib import reload
    import crypto_utils
    with pytest.raises(RuntimeError, match="AIUI_FERNET_KEY"):
        reload(crypto_utils)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
ssh -i ~/.ssh/aiui_safe root@46.224.193.25 "docker exec tasks pytest tests/test_crypto_utils.py -v"
```

Expected: ImportError or ModuleNotFoundError on `import crypto_utils` — module doesn't exist yet.

- [ ] **Step 3: Add `cryptography>=42` to `requirements.txt`**

Open `mcp-servers/tasks/requirements.txt`, append:

```
cryptography>=42
```

If `cryptography` is already listed (could come transitively), pin it to `>=42` explicitly so we know the version.

- [ ] **Step 4: Implement `crypto_utils.py`**

```python
"""Fernet symmetric encryption for sensitive config (Supabase anon keys, etc.).

The key is loaded from the AIUI_FERNET_KEY env var. Generate one with:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
import os

from cryptography.fernet import Fernet

_KEY = os.environ.get("AIUI_FERNET_KEY")
if not _KEY:
    raise RuntimeError(
        "AIUI_FERNET_KEY is not set. Generate one with "
        "`python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'` "
        "and add it to the host .env."
    )

_FERNET = Fernet(_KEY.encode() if isinstance(_KEY, str) else _KEY)


def encrypt(plaintext: str) -> str:
    """Encrypt a string. Returns URL-safe base64."""
    return _FERNET.encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(ciphertext: str) -> str:
    """Decrypt a Fernet token. Raises InvalidToken if tampered or wrong key."""
    return _FERNET.decrypt(ciphertext.encode("ascii")).decode("utf-8")
```

- [ ] **Step 5: Rebuild image so `cryptography` is installed**

```bash
scp -i ~/.ssh/aiui_safe "C:/All/Work - Code/ai_ui/mcp-servers/tasks/crypto_utils.py" "C:/All/Work - Code/ai_ui/mcp-servers/tasks/requirements.txt" "C:/All/Work - Code/ai_ui/mcp-servers/tasks/tests/test_crypto_utils.py" root@46.224.193.25:/tmp/
ssh -i ~/.ssh/aiui_safe root@46.224.193.25 "cp /tmp/crypto_utils.py /root/proxy-server/mcp-servers/tasks/ && cp /tmp/requirements.txt /root/proxy-server/mcp-servers/tasks/ && cp /tmp/test_crypto_utils.py /root/proxy-server/mcp-servers/tasks/tests/"
ssh -i ~/.ssh/aiui_safe root@46.224.193.25 "cd /root/proxy-server && docker compose build tasks && docker compose up -d tasks && sleep 5"
```

Expected: docker build prints `Successfully tagged proxy-server-tasks:latest` (or similar). Container restarts cleanly.

- [ ] **Step 6: Run tests, expect all 3 PASS**

```bash
ssh -i ~/.ssh/aiui_safe root@46.224.193.25 "docker exec tasks pytest tests/test_crypto_utils.py -v"
```

- [ ] **Step 7: Commit**

```bash
git -C "C:/All/Work - Code/ai_ui" add mcp-servers/tasks/crypto_utils.py mcp-servers/tasks/tests/test_crypto_utils.py mcp-servers/tasks/requirements.txt
git -C "C:/All/Work - Code/ai_ui" commit -m "feat(tasks): Fernet helper + cryptography dep for at-rest encryption"
```

(No co-author trailer.)

---

### Task 3: `tasks.project_supabase` migration + ORM model

**Files:**
- Create: `mcp-servers/tasks/migrations/007_project_supabase.sql`
- Modify: `mcp-servers/tasks/models.py`

- [ ] **Step 1: Write the migration**

```sql
-- Per-project Supabase config. anon_key_encrypted holds a Fernet ciphertext;
-- decrypt only at request time. We never accept service-role keys — clients
-- should configure their app with anon + Row Level Security policies.

CREATE TABLE IF NOT EXISTS tasks.project_supabase (
    slug                TEXT PRIMARY KEY,
    supabase_url        TEXT NOT NULL,
    anon_key_encrypted  TEXT NOT NULL,
    configured_by       TEXT NOT NULL,
    configured_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

- [ ] **Step 2: Add the ORM model**

Append to `mcp-servers/tasks/models.py` (just below `PublishedApp`):

```python
class ProjectSupabase(Base):
    __tablename__ = "project_supabase"
    __table_args__ = {"schema": "tasks"}

    slug = Column(Text, primary_key=True)
    supabase_url = Column(Text, nullable=False)
    anon_key_encrypted = Column(Text, nullable=False)
    configured_by = Column(Text, nullable=False)
    configured_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow)
```

- [ ] **Step 3: Update conftest to truncate the new table between tests**

In `mcp-servers/tasks/tests/conftest.py`, find the existing TRUNCATE call and extend:

```python
        await conn.execute(text(
            "TRUNCATE tasks.items, tasks.executions, "
            "tasks.published_apps, tasks.project_members, "
            "tasks.project_supabase CASCADE"
        ))
```

- [ ] **Step 4: Apply on the server (init_db runs migrations on startup)**

```bash
scp -i ~/.ssh/aiui_safe "C:/All/Work - Code/ai_ui/mcp-servers/tasks/migrations/007_project_supabase.sql" "C:/All/Work - Code/ai_ui/mcp-servers/tasks/models.py" "C:/All/Work - Code/ai_ui/mcp-servers/tasks/tests/conftest.py" root@46.224.193.25:/tmp/
ssh -i ~/.ssh/aiui_safe root@46.224.193.25 "cp /tmp/007_project_supabase.sql /root/proxy-server/mcp-servers/tasks/migrations/ && cp /tmp/models.py /root/proxy-server/mcp-servers/tasks/ && cp /tmp/conftest.py /root/proxy-server/mcp-servers/tasks/tests/ && docker cp /tmp/007_project_supabase.sql tasks:/app/migrations/ && docker cp /tmp/models.py tasks:/app/ && docker cp /tmp/conftest.py tasks:/app/tests/ && docker restart tasks && sleep 5 && docker exec postgres psql \$(docker exec tasks printenv DATABASE_URL | sed 's|postgresql+asyncpg://|postgresql://|') -c '\\d tasks.project_supabase'"
```

Expected: prints the table schema with 6 columns.

- [ ] **Step 5: Commit**

```bash
git -C "C:/All/Work - Code/ai_ui" add mcp-servers/tasks/migrations/007_project_supabase.sql mcp-servers/tasks/models.py mcp-servers/tasks/tests/conftest.py
git -C "C:/All/Work - Code/ai_ui" commit -m "feat(supabase): project_supabase table + model + truncate in tests"
```

---

### Task 4: `routes_supabase.py` endpoints

**Files:**
- Create: `mcp-servers/tasks/routes_supabase.py`
- Create: `mcp-servers/tasks/tests/test_supabase_config.py`
- Modify: `mcp-servers/tasks/main.py` — register router

- [ ] **Step 1: Write the failing tests**

Create `mcp-servers/tasks/tests/test_supabase_config.py`:

```python
"""Tests for Supabase config endpoints (GET / POST / DELETE)."""
import os
import uuid

# Set the Fernet key BEFORE importing app so crypto_utils initializes cleanly.
os.environ.setdefault("AIUI_FERNET_KEY", "<REDACTED-TEST-KEY-44CHARS>")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from main import app
from models import ProjectMember, ProjectSupabase, TaskItem

OWNER_HDR = {"X-User-Email": "ralph@aiui.com", "X-User-Admin": "true"}
ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.example.signature"


@pytest.fixture
def transport():
    return ASGITransport(app=app)


def _setup_owner(db_session, slug="alpha"):
    db_session.add(TaskItem(
        meeting_id=uuid.uuid4(), action_type="BUILD",
        assignee_name="Ralph", assignee_email="ralph@aiui.com",
        description="x", priority="IMPORTANT", status="completed",
        built_app_slug=slug,
    ))
    db_session.add(ProjectMember(
        slug=slug, user_email="ralph@aiui.com",
        role="owner", added_by="ralph@aiui.com",
    ))


async def test_get_returns_unconfigured_state(db_session, transport):
    _setup_owner(db_session)
    await db_session.commit()
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/projects/alpha/supabase", headers=OWNER_HDR)
    assert r.status_code == 200
    assert r.json()["configured"] is False


async def test_set_then_get_returns_configured_state(db_session, transport):
    _setup_owner(db_session)
    await db_session.commit()

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/projects/alpha/supabase", headers=OWNER_HDR, json={
            "supabase_url": "https://xyz.supabase.co",
            "anon_key": ANON_KEY,
        })
        assert r.status_code == 200
        body = r.json()
        assert body["configured"] is True
        assert body["supabase_url"] == "https://xyz.supabase.co"
        # Anon key MUST NOT be returned in any field.
        assert "anon_key" not in body
        assert "anon_key_encrypted" not in body

        r = await c.get("/api/projects/alpha/supabase", headers=OWNER_HDR)
        assert r.status_code == 200
        assert r.json()["configured"] is True
        assert r.json()["supabase_url"] == "https://xyz.supabase.co"

    # DB row holds ENCRYPTED key (not the plaintext).
    row = (await db_session.execute(
        select(ProjectSupabase).where(ProjectSupabase.slug == "alpha")
    )).scalar_one()
    assert row.anon_key_encrypted != ANON_KEY


async def test_set_rejects_invalid_url(db_session, transport):
    _setup_owner(db_session)
    await db_session.commit()
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/projects/alpha/supabase", headers=OWNER_HDR,
                         json={"supabase_url": "ftp://nope", "anon_key": ANON_KEY})
    assert r.status_code == 400


async def test_set_rejects_non_owner(db_session, transport):
    _setup_owner(db_session)
    await db_session.commit()
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/projects/alpha/supabase",
                         headers={"X-User-Email": "stranger@aiui.com",
                                  "X-User-Admin": "true"},
                         json={"supabase_url": "https://xyz.supabase.co",
                               "anon_key": ANON_KEY})
    assert r.status_code == 403


async def test_delete_removes_config(db_session, transport):
    _setup_owner(db_session)
    db_session.add(ProjectSupabase(
        slug="alpha", supabase_url="https://xyz.supabase.co",
        anon_key_encrypted="enc", configured_by="ralph@aiui.com",
    ))
    await db_session.commit()
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.delete("/api/projects/alpha/supabase", headers=OWNER_HDR)
        assert r.status_code == 204
        r = await c.get("/api/projects/alpha/supabase", headers=OWNER_HDR)
        assert r.json()["configured"] is False
```

- [ ] **Step 2: Run, expect failures (router not registered)**

```bash
scp -i ~/.ssh/aiui_safe "C:/All/Work - Code/ai_ui/mcp-servers/tasks/tests/test_supabase_config.py" root@46.224.193.25:/tmp/ && ssh -i ~/.ssh/aiui_safe root@46.224.193.25 "cp /tmp/test_supabase_config.py /root/proxy-server/mcp-servers/tasks/tests/ && docker cp /tmp/test_supabase_config.py tasks:/app/tests/ && docker exec tasks pytest tests/test_supabase_config.py -v"
```

Expected: 4 FAILS (404 instead of 200/403), 1 PASS coincidentally (the GET-unconfigured one returns 404 from the missing route, not the 200 we want — make sure the test asserts 200 explicitly so it fails correctly here).

- [ ] **Step 3: Implement `routes_supabase.py`**

```python
"""Supabase configuration per project.

GET    — anyone with viewer+ on the project (so members can confirm one is set)
POST   — owner-only (or platform admin via _require_role's is_admin bypass)
DELETE — owner-only

The anon key is Fernet-encrypted at rest and never returned from the API.
"""
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

import crypto_utils
from auth import AdminUser, current_admin
from db import session
from models import ProjectSupabase
from routes_projects import _require_role, _validate_slug

router = APIRouter(prefix="/api/projects")

# Supabase URLs are like https://abcdefgh.supabase.co. Allow any https host
# with at least one dot — keep the regex liberal so self-hosted Supabase works.
_URL_RE = re.compile(r"^https://[a-z0-9][a-z0-9.-]+\.[a-z]{2,}(:\d+)?(/.*)?$")


class SupabaseConfigRequest(BaseModel):
    supabase_url: str = Field(min_length=10, max_length=300)
    anon_key: str = Field(min_length=20, max_length=2000)


class SupabaseConfigStatus(BaseModel):
    configured: bool
    supabase_url: str | None = None
    configured_by: str | None = None
    configured_at: str | None = None


@router.get("/{slug}/supabase", response_model=SupabaseConfigStatus)
async def get_supabase(slug: str, user: AdminUser = Depends(current_admin)):
    _validate_slug(slug)
    async with session() as s:
        await _require_role(s, slug, user.email, "viewer", is_admin=user.is_admin)
        row = (await s.execute(
            select(ProjectSupabase).where(ProjectSupabase.slug == slug)
        )).scalar_one_or_none()
    if row is None:
        return SupabaseConfigStatus(configured=False)
    return SupabaseConfigStatus(
        configured=True,
        supabase_url=row.supabase_url,
        configured_by=row.configured_by,
        configured_at=row.configured_at.isoformat() if row.configured_at else None,
    )


@router.post("/{slug}/supabase", response_model=SupabaseConfigStatus)
async def set_supabase(
    slug: str,
    body: SupabaseConfigRequest,
    user: AdminUser = Depends(current_admin),
):
    _validate_slug(slug)
    url = body.supabase_url.strip()
    if not _URL_RE.match(url):
        raise HTTPException(status_code=400, detail="supabase_url must be an https://… URL")
    enc_key = crypto_utils.encrypt(body.anon_key.strip())

    async with session() as s:
        await _require_role(s, slug, user.email, "owner", is_admin=user.is_admin)
        existing = (await s.execute(
            select(ProjectSupabase).where(ProjectSupabase.slug == slug)
        )).scalar_one_or_none()
        if existing:
            existing.supabase_url = url
            existing.anon_key_encrypted = enc_key
            existing.configured_by = user.email
            existing.updated_at = datetime.utcnow()
            row = existing
        else:
            row = ProjectSupabase(
                slug=slug, supabase_url=url, anon_key_encrypted=enc_key,
                configured_by=user.email,
            )
            s.add(row)
        await s.commit()
        await s.refresh(row)
    return SupabaseConfigStatus(
        configured=True,
        supabase_url=row.supabase_url,
        configured_by=row.configured_by,
        configured_at=row.configured_at.isoformat() if row.configured_at else None,
    )


@router.delete("/{slug}/supabase", status_code=204)
async def delete_supabase(slug: str, user: AdminUser = Depends(current_admin)):
    _validate_slug(slug)
    async with session() as s:
        await _require_role(s, slug, user.email, "owner", is_admin=user.is_admin)
        row = (await s.execute(
            select(ProjectSupabase).where(ProjectSupabase.slug == slug)
        )).scalar_one_or_none()
        if row is not None:
            await s.delete(row)
            await s.commit()
    return None
```

- [ ] **Step 4: Register the router in main.py**

In `mcp-servers/tasks/main.py`, add the import alongside existing routers:

```python
from routes_supabase import router as supabase_router
```

And include:

```python
app.include_router(supabase_router)
```

(Order doesn't matter for FastAPI route resolution; place near `app.include_router(projects_router)`.)

- [ ] **Step 5: Deploy**

```bash
scp -i ~/.ssh/aiui_safe "C:/All/Work - Code/ai_ui/mcp-servers/tasks/routes_supabase.py" "C:/All/Work - Code/ai_ui/mcp-servers/tasks/main.py" root@46.224.193.25:/tmp/
ssh -i ~/.ssh/aiui_safe root@46.224.193.25 "cp /tmp/routes_supabase.py /root/proxy-server/mcp-servers/tasks/ && cp /tmp/main.py /root/proxy-server/mcp-servers/tasks/ && docker cp /tmp/routes_supabase.py tasks:/app/ && docker cp /tmp/main.py tasks:/app/ && docker restart tasks && sleep 4"
```

- [ ] **Step 6: Run tests, expect all 5 PASS**

```bash
ssh -i ~/.ssh/aiui_safe root@46.224.193.25 "docker exec tasks pytest tests/test_supabase_config.py -v"
```

- [ ] **Step 7: Commit**

```bash
git -C "C:/All/Work - Code/ai_ui" add mcp-servers/tasks/tests/test_supabase_config.py
git -C "C:/All/Work - Code/ai_ui" commit -m "test(supabase): cover GET/POST/DELETE config endpoints + role gating"
git -C "C:/All/Work - Code/ai_ui" add mcp-servers/tasks/routes_supabase.py mcp-servers/tasks/main.py
git -C "C:/All/Work - Code/ai_ui" commit -m "feat(supabase): GET/POST/DELETE /api/projects/{slug}/supabase endpoints"
```

---

### Task 5: Inject `window.SUPABASE_URL` / `window.SUPABASE_ANON_KEY` at serve time

**Files:**
- Modify: `mcp-servers/tasks/main.py` — `serve_published_app` function
- Create: `mcp-servers/tasks/tests/test_supabase_inject.py`

When serving a published app's HTML, look up the slug's Supabase config and prepend a `<script>` setting the window vars at the top of `<head>`. Files of any other type pass through unchanged.

- [ ] **Step 1: Write the failing test**

Create `mcp-servers/tasks/tests/test_supabase_inject.py`:

```python
"""Tests for the runtime window-var injection in serve_published_app."""
import os
import uuid
from datetime import datetime

os.environ.setdefault("AIUI_FERNET_KEY", "<REDACTED-TEST-KEY-44CHARS>")

import pytest
from httpx import ASGITransport, AsyncClient

import crypto_utils
from main import app
from models import ProjectSupabase, PublishedApp


@pytest.fixture
def transport():
    return ASGITransport(app=app)


def _make_published(db_session, slug, html, supabase_url=None, anon_key=None, tmp_path=None):
    """Set up apps/<slug>/index.html on disk and matching DB rows."""
    apps_dir = tmp_path / "apps" / slug
    apps_dir.mkdir(parents=True)
    (apps_dir / "index.html").write_text(html)
    db_session.add(PublishedApp(
        slug=slug, published_by="ralph@aiui.com",
        public_host=f"{slug}.example.com",
    ))
    if supabase_url:
        db_session.add(ProjectSupabase(
            slug=slug, supabase_url=supabase_url,
            anon_key_encrypted=crypto_utils.encrypt(anon_key),
            configured_by="ralph@aiui.com",
        ))


async def test_html_no_supabase_passes_through(db_session, transport, tmp_path, monkeypatch):
    monkeypatch.setattr("main._APP_ROOT_FS", str(tmp_path / "apps"))
    _make_published(db_session, "alpha",
                    "<html><head><title>x</title></head><body>hi</body></html>",
                    tmp_path=tmp_path)
    await db_session.commit()
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/__public/alpha/")
    assert r.status_code == 200
    assert "window.SUPABASE_URL" not in r.text
    assert "<title>x</title>" in r.text


async def test_html_with_supabase_injects_after_head(db_session, transport, tmp_path, monkeypatch):
    monkeypatch.setattr("main._APP_ROOT_FS", str(tmp_path / "apps"))
    _make_published(db_session, "alpha",
                    "<html><head><title>x</title></head><body>hi</body></html>",
                    supabase_url="https://demo.supabase.co",
                    anon_key="eyJtest.anon.key",
                    tmp_path=tmp_path)
    await db_session.commit()
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/__public/alpha/")
    assert r.status_code == 200
    body = r.text
    assert 'window.SUPABASE_URL="https://demo.supabase.co"' in body
    assert 'window.SUPABASE_ANON_KEY="eyJtest.anon.key"' in body
    # Script must come AFTER <head> opening tag, BEFORE <title>.
    head_idx = body.lower().find("<head>")
    title_idx = body.lower().find("<title>")
    script_idx = body.find("window.SUPABASE_URL")
    assert head_idx < script_idx < title_idx


async def test_non_html_files_not_modified(db_session, transport, tmp_path, monkeypatch):
    monkeypatch.setattr("main._APP_ROOT_FS", str(tmp_path / "apps"))
    apps_dir = tmp_path / "apps" / "alpha"
    apps_dir.mkdir(parents=True)
    (apps_dir / "index.html").write_text("<html></html>")
    (apps_dir / "app.js").write_text("console.log('hi');")
    db_session.add(PublishedApp(slug="alpha", published_by="ralph@aiui.com",
                                public_host="alpha.example.com"))
    db_session.add(ProjectSupabase(
        slug="alpha", supabase_url="https://x.supabase.co",
        anon_key_encrypted=crypto_utils.encrypt("k"),
        configured_by="ralph@aiui.com",
    ))
    await db_session.commit()

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/__public/alpha/app.js")
    assert r.status_code == 200
    assert r.text == "console.log('hi');"  # untouched
```

- [ ] **Step 2: Run, expect failures (no injection logic yet)**

```bash
scp -i ~/.ssh/aiui_safe "C:/All/Work - Code/ai_ui/mcp-servers/tasks/tests/test_supabase_inject.py" root@46.224.193.25:/tmp/
ssh -i ~/.ssh/aiui_safe root@46.224.193.25 "cp /tmp/test_supabase_inject.py /root/proxy-server/mcp-servers/tasks/tests/ && docker cp /tmp/test_supabase_inject.py tasks:/app/tests/ && docker exec tasks pytest tests/test_supabase_inject.py -v"
```

Expected: `test_html_with_supabase_injects_after_head` fails (no injection); the other two might pass coincidentally.

- [ ] **Step 3: Add the injection helper + use it in `serve_published_app`**

Open `mcp-servers/tasks/main.py`. Just above `serve_published_app`, add:

```python
async def _supabase_inject_for(slug: str) -> str:
    """Return the <script> snippet to inject for this slug, or '' if no config."""
    from models import ProjectSupabase as _ProjSb
    import crypto_utils as _crypto
    import json
    async with _db_session() as s:
        row = (await s.execute(
            _select(_ProjSb).where(_ProjSb.slug == slug)
        )).scalar_one_or_none()
    if row is None:
        return ""
    try:
        anon = _crypto.decrypt(row.anon_key_encrypted)
    except Exception:
        return ""  # corrupt token / wrong key — fail silently rather than 500
    url_js = json.dumps(row.supabase_url)
    key_js = json.dumps(anon)
    return (
        "<script>"
        f"window.SUPABASE_URL={url_js};"
        f"window.SUPABASE_ANON_KEY={key_js};"
        "</script>"
    )
```

Then change the end of `serve_published_app`. Find:

```python
    ext = _os.path.splitext(target)[1].lower()
    media = _MIME_BY_EXT.get(ext, "application/octet-stream")
    return FileResponse(
        target, media_type=media,
        headers={"Cache-Control": "public, max-age=120"},
    )
```

Replace with:

```python
    ext = _os.path.splitext(target)[1].lower()
    media = _MIME_BY_EXT.get(ext, "application/octet-stream")

    if ext in (".html", ".htm"):
        with open(target, "rb") as f:
            body = f.read().decode("utf-8", errors="replace")
        snippet = await _supabase_inject_for(slug)
        if snippet:
            lower = body.lower()
            head_idx = lower.find("<head>")
            if head_idx >= 0:
                body = body[: head_idx + 6] + snippet + body[head_idx + 6 :]
            else:
                body = snippet + body
        return Response(content=body, media_type=media,
                        headers={"Cache-Control": "public, max-age=120"})

    return FileResponse(
        target, media_type=media,
        headers={"Cache-Control": "public, max-age=120"},
    )
```

Add `Response` to FastAPI imports near the top of the file:

```python
from fastapi import HTTPException, Request, Response
```

- [ ] **Step 4: Deploy**

```bash
scp -i ~/.ssh/aiui_safe "C:/All/Work - Code/ai_ui/mcp-servers/tasks/main.py" root@46.224.193.25:/tmp/
ssh -i ~/.ssh/aiui_safe root@46.224.193.25 "cp /tmp/main.py /root/proxy-server/mcp-servers/tasks/ && docker cp /tmp/main.py tasks:/app/ && docker restart tasks && sleep 4"
```

- [ ] **Step 5: Run all 3 tests, expect PASS**

```bash
ssh -i ~/.ssh/aiui_safe root@46.224.193.25 "docker exec tasks pytest tests/test_supabase_inject.py -v"
```

- [ ] **Step 6: Commit**

```bash
git -C "C:/All/Work - Code/ai_ui" add mcp-servers/tasks/tests/test_supabase_inject.py
git -C "C:/All/Work - Code/ai_ui" commit -m "test(supabase): cover window-var injection in served HTML"
git -C "C:/All/Work - Code/ai_ui" add mcp-servers/tasks/main.py
git -C "C:/All/Work - Code/ai_ui" commit -m "feat(supabase): inject window.SUPABASE_URL/KEY into served index.html"
```

---

### Task 6: BUILD/ENHANCE prompt templates know about Supabase

**Files:**
- Modify: `mcp-servers/tasks/claude_executor.py` — `PROMPT_TEMPLATE`, `ENHANCE_PROMPT_TEMPLATE`, `build_prompt`, `build_enhance_prompt`
- Modify: `mcp-servers/tasks/routes_execution.py` — pass `supabase_url=` when calling `build_prompt`
- Modify: `mcp-servers/tasks/routes_tasks.py` — pass `supabase_url=` when calling `build_enhance_prompt`
- Create: `mcp-servers/tasks/tests/test_supabase_prompt.py`

- [ ] **Step 1: Write the failing test**

Create `mcp-servers/tasks/tests/test_supabase_prompt.py`:

```python
"""The build/enhance prompt templates must include Supabase context when configured."""
from claude_executor import build_prompt, build_enhance_prompt


def test_build_prompt_omits_block_when_no_supabase():
    text = build_prompt(
        description="x", action_type="BUILD", priority="IMPORTANT",
        meeting_title="m", meeting_date="2026-04-25",
        supabase_url=None,
    )
    assert "Supabase" not in text


def test_build_prompt_includes_block_when_supabase_configured():
    text = build_prompt(
        description="x", action_type="BUILD", priority="IMPORTANT",
        meeting_title="m", meeting_date="2026-04-25",
        supabase_url="https://demo.supabase.co",
    )
    assert "Supabase integration available" in text
    assert "window.SUPABASE_URL" in text
    assert "window.SUPABASE_ANON_KEY" in text
    assert "https://demo.supabase.co" in text
    assert "Row Level Security" in text or "RLS" in text


def test_enhance_prompt_includes_block_when_supabase_configured():
    text = build_enhance_prompt(
        slug="alpha", description="x", priority="IMPORTANT",
        existing_files_listing="index.html",
        supabase_url="https://demo.supabase.co",
    )
    assert "Supabase integration available" in text
    assert "https://demo.supabase.co" in text
```

- [ ] **Step 2: Run, expect failures (function signatures don't accept the kwarg yet)**

```bash
scp -i ~/.ssh/aiui_safe "C:/All/Work - Code/ai_ui/mcp-servers/tasks/tests/test_supabase_prompt.py" root@46.224.193.25:/tmp/
ssh -i ~/.ssh/aiui_safe root@46.224.193.25 "cp /tmp/test_supabase_prompt.py /root/proxy-server/mcp-servers/tasks/tests/ && docker cp /tmp/test_supabase_prompt.py tasks:/app/tests/ && docker exec tasks pytest tests/test_supabase_prompt.py -v"
```

Expected: TypeErrors — `build_prompt() got an unexpected keyword argument 'supabase_url'`.

- [ ] **Step 3: Add the block template + helper to claude_executor.py**

Insert near the top of `mcp-servers/tasks/claude_executor.py` (just below the existing `PROMPT_TEMPLATE` definition):

```python
SUPABASE_BLOCK_TEMPLATE = """## Supabase integration available

A Supabase project is attached to this app. Use it for any data persistence,
auth, or file storage needs. Do NOT roll your own backend.

- Read URL/key from `window.SUPABASE_URL` and `window.SUPABASE_ANON_KEY`.
  These are injected by the host on every request — never hardcode them.
- Import the SDK in your HTML:
  `<script type="module">import {{ createClient }} from "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/+esm"; window.supabase = createClient(window.SUPABASE_URL, window.SUPABASE_ANON_KEY);</script>`
- Auth: `supabase.auth.signUp` / `signInWithPassword` / `signOut` / `onAuthStateChange`.
- Tables: enable Row Level Security (RLS) on every table; document the schema
  the app expects in `schema.sql` at the app root so the user can apply it.

URL: {url}
"""


def _supabase_block(supabase_url: str | None) -> str:
    """Return the Supabase prompt block, or '' if no config."""
    if not supabase_url:
        return ""
    return SUPABASE_BLOCK_TEMPLATE.format(url=supabase_url)
```

- [ ] **Step 4: Add `{supabase_block}` placeholder to both templates**

In `PROMPT_TEMPLATE`, find a spot just before the implementation/rules section (look for "## Implementation rules" or similar). Insert:

```
{supabase_block}
```

Same insertion in `ENHANCE_PROMPT_TEMPLATE`.

- [ ] **Step 5: Update `build_prompt` and `build_enhance_prompt` signatures**

Change `build_prompt` to:

```python
def build_prompt(
    *,
    description: str,
    action_type: str,
    priority: str,
    meeting_title: str,
    meeting_date: str,
    supabase_url: str | None = None,
) -> str:
    return PROMPT_TEMPLATE.format(
        description=description,
        action_type=action_type,
        priority=priority,
        meeting_title=meeting_title,
        meeting_date=meeting_date,
        supabase_block=_supabase_block(supabase_url),
    )
```

Change `build_enhance_prompt` similarly — add `supabase_url: str | None = None` to its kwargs and pass `supabase_block=_supabase_block(supabase_url)` to `.format()`.

(If `build_clarify_prompt` and `build_plan_prompt` use the same templates, they need the same treatment — read the file and update each.)

- [ ] **Step 6: Update callers to fetch + pass the URL**

In `mcp-servers/tasks/routes_execution.py`, find where `build_prompt(...)` is called inside `_run_execution`. Just before the call, add:

```python
        supabase_url = None
        if item.built_app_slug:
            from models import ProjectSupabase
            sb_row = (await s.execute(
                select(ProjectSupabase).where(ProjectSupabase.slug == item.built_app_slug)
            )).scalar_one_or_none()
            if sb_row:
                supabase_url = sb_row.supabase_url
```

And add `supabase_url=supabase_url` to the `build_prompt(...)` call's kwargs.

In `mcp-servers/tasks/routes_tasks.py`, do the equivalent for `build_enhance_prompt` inside `enhance` (the slug is `source.built_app_slug`).

- [ ] **Step 7: Deploy + run tests**

```bash
scp -i ~/.ssh/aiui_safe "C:/All/Work - Code/ai_ui/mcp-servers/tasks/claude_executor.py" "C:/All/Work - Code/ai_ui/mcp-servers/tasks/routes_execution.py" "C:/All/Work - Code/ai_ui/mcp-servers/tasks/routes_tasks.py" root@46.224.193.25:/tmp/
ssh -i ~/.ssh/aiui_safe root@46.224.193.25 "cp /tmp/claude_executor.py /tmp/routes_execution.py /tmp/routes_tasks.py /root/proxy-server/mcp-servers/tasks/ && docker cp /tmp/claude_executor.py tasks:/app/ && docker cp /tmp/routes_execution.py tasks:/app/ && docker cp /tmp/routes_tasks.py tasks:/app/ && docker restart tasks && sleep 4 && docker exec tasks pytest tests/test_supabase_prompt.py tests/test_enhance_prompt.py tests/test_claude_executor.py -v"
```

Expected: 3 new tests PASS, existing prompt tests still PASS. (If existing prompt tests break because they call `build_prompt(...)` positionally, fix them by adding the explicit keyword.)

- [ ] **Step 8: Commit**

```bash
git -C "C:/All/Work - Code/ai_ui" add mcp-servers/tasks/tests/test_supabase_prompt.py
git -C "C:/All/Work - Code/ai_ui" commit -m "test(supabase): build/enhance prompts include Supabase block when configured"
git -C "C:/All/Work - Code/ai_ui" add mcp-servers/tasks/claude_executor.py mcp-servers/tasks/routes_execution.py mcp-servers/tasks/routes_tasks.py
git -C "C:/All/Work - Code/ai_ui" commit -m "feat(supabase): include Supabase context in BUILD + ENHANCE prompts"
```

---

### Task 7: Drop localStorage from the New Project create modal

**Files:**
- Modify: `mcp-servers/tasks/static/projects.html`

The current modal has a "Storage (data persistence)" picker with `none` and `localstorage`. We're switching to `none` (in-memory only) + `supabase` (configure after publishing).

- [ ] **Step 1: Update the `<select>` markup**

Find the existing block at `mcp-servers/tasks/static/projects.html:627-630`:

```html
          <label class="form-label" for="np-storage">Storage (data persistence)</label>
          <select id="np-storage" class="form-select">
            <option value="none" selected>None — no backend</option>
            <option value="localstorage">Browser localStorage — saves data in the browser</option>
          </select>
```

Replace with:

```html
          <label class="form-label" for="np-storage">Backend</label>
          <select id="np-storage" class="form-select">
            <option value="none" selected>None — UI only, no data</option>
            <option value="supabase">Supabase — connect after creating</option>
          </select>
          <div class="form-hint" style="font-size:11px; margin-top:4px; color:var(--muted);">
            Supabase gives you auth, database, and file storage. After creating the project, open
            the Publish modal to paste your Supabase URL and anon key.
          </div>
```

- [ ] **Step 2: Update `STORAGE_INSTRUCTIONS` in the same file**

Find around `mcp-servers/tasks/static/projects.html:820`:

```javascript
    const STORAGE_INSTRUCTIONS = {
      none: "• Storage: NO persistence. App is stateless in-memory only.",
      localstorage: "• Storage: use window.localStorage under a clear namespace key (e.g. 'myapp:v1:items'). Handle JSON parse failures. Don't store sensitive data.",
    };
```

Replace with:

```javascript
    const STORAGE_INSTRUCTIONS = {
      none: "• Storage: NO persistence. The app is stateless / UI-only.",
      supabase: "• Storage: a Supabase project will be attached after creation. Read URL/key from `window.SUPABASE_URL` / `window.SUPABASE_ANON_KEY` (injected by the host). Use `supabase-js` v2 from jsDelivr. Enable RLS on any table you create. Document your schema in `schema.sql` at the app root.",
    };
```

- [ ] **Step 3: Manual UI test**

```bash
scp -i ~/.ssh/aiui_safe "C:/All/Work - Code/ai_ui/mcp-servers/tasks/static/projects.html" root@46.224.193.25:/tmp/
ssh -i ~/.ssh/aiui_safe root@46.224.193.25 "cp /tmp/projects.html /root/proxy-server/mcp-servers/tasks/static/ && docker cp /tmp/projects.html tasks:/app/static/projects.html"
```

Open `https://ai-ui.coolestdomain.win/tasks/app-builder` in a browser, click "+ New Project". The Backend select should show "None" + "Supabase — connect after creating" only. The hint paragraph appears below.

- [ ] **Step 4: Commit**

```bash
git -C "C:/All/Work - Code/ai_ui" add mcp-servers/tasks/static/projects.html
git -C "C:/All/Work - Code/ai_ui" commit -m "feat(projects): drop localStorage from create modal — Supabase is the persistence option"
```

---

### Task 8: Supabase config UI in the Publish modal (preview.html)

**Files:**
- Modify: `mcp-servers/tasks/static/preview.html`

A new "🗄 Supabase backend" section inside the existing Publish modal, with URL + anon key fields and Save / Disconnect.

- [ ] **Step 1: Add markup just below the Custom Domain section in the Publish modal**

Find the closing `</div>` of the `pub-cd-attached` block (search for `id="pub-cd-attached"`). After that block, before the Publish modal's footer button row, insert:

```html
    <!-- ─── Supabase backend section ─── -->
    <div class="pub-section-divider"></div>
    <div class="pub-section-title">
      <span>🗄 Supabase backend</span>
      <span class="badge-soft" id="pub-sb-badge">Optional</span>
    </div>
    <div class="body" id="pub-sb-body">
      Connect a Supabase project for auth, database, and file storage.
      Your anon key is encrypted at rest and injected into the live app
      at runtime (<code style="font-family:var(--font-mono);font-size:11px;">window.SUPABASE_URL</code> /
      <code style="font-family:var(--font-mono);font-size:11px;">window.SUPABASE_ANON_KEY</code>).
      Claude is told how to use it on every build.
    </div>
    <div class="pub-domain-input-row">
      <input type="url" class="pub-domain-input" id="pub-sb-url"
             placeholder="https://xxxxx.supabase.co" autocomplete="off" spellcheck="false">
      <button type="button" class="btn btn-primary" id="pub-sb-save">Save</button>
    </div>
    <input type="text" class="pub-domain-input" id="pub-sb-anon"
           placeholder="anon public key (eyJ…)" autocomplete="off" spellcheck="false"
           style="margin-top:6px;">
    <div id="pub-sb-attached" hidden>
      <div class="pub-url-pill">
        <span style="flex:1;" id="pub-sb-current"></span>
        <button type="button" class="copy" id="pub-sb-clear">Disconnect</button>
      </div>
    </div>
```

- [ ] **Step 2: Add the JS just before the existing `// ── Rename project ──` block**

Search for `// ── Rename project ──` in `preview.html`. Insert above it:

```javascript
  // ── Supabase config ──
  const $sbUrl      = document.getElementById("pub-sb-url");
  const $sbAnon     = document.getElementById("pub-sb-anon");
  const $sbSave     = document.getElementById("pub-sb-save");
  const $sbClear    = document.getElementById("pub-sb-clear");
  const $sbAttached = document.getElementById("pub-sb-attached");
  const $sbCurrent  = document.getElementById("pub-sb-current");
  const $sbBadge    = document.getElementById("pub-sb-badge");

  let _sbState = null;

  async function refreshSupabase() {
    if (!slug) return;
    try {
      const token = localStorage.getItem("token");
      const r = await fetch(`/api/projects/${encodeURIComponent(slug)}/supabase`, {
        headers: token ? { Authorization: "Bearer " + token } : {},
        credentials: "include",
      });
      if (r.ok) _sbState = await r.json();
    } catch (_) {}
    _renderSupabase();
  }

  function _renderSupabase() {
    const cfg = _sbState || {};
    if (cfg.configured) {
      $sbBadge.textContent = "Connected";
      $sbBadge.classList.add("verified");
      $sbAttached.hidden = false;
      $sbCurrent.textContent = cfg.supabase_url || "";
      $sbUrl.value = cfg.supabase_url || "";
      $sbAnon.value = "";
      $sbAnon.placeholder = "(saved — paste again only to change)";
    } else {
      $sbBadge.textContent = "Optional";
      $sbBadge.classList.remove("verified");
      $sbAttached.hidden = true;
      $sbAnon.placeholder = "anon public key (eyJ…)";
    }
  }

  $sbSave.addEventListener("click", async () => {
    const url = ($sbUrl.value || "").trim();
    const key = ($sbAnon.value || "").trim();
    if (!url) { $sbUrl.focus(); return; }
    if (!key) {
      // If a config already exists, refuse silent re-save (user must paste key).
      if (!(_sbState && _sbState.configured)) {
        $sbAnon.focus();
        toast("Paste your anon public key.", "error", 4000);
        return;
      }
      toast("Paste your anon key again to change the config (we don't store it in plaintext).", "error", 5000);
      return;
    }
    $sbSave.disabled = true;
    $sbSave.textContent = "Saving…";
    try {
      const token = localStorage.getItem("token");
      const r = await fetch(`/api/projects/${encodeURIComponent(slug)}/supabase`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(token ? { Authorization: "Bearer " + token } : {}) },
        credentials: "include",
        body: JSON.stringify({ supabase_url: url, anon_key: key }),
      });
      if (!r.ok) {
        const txt = await r.text();
        toast("Save failed: " + txt.slice(0, 240), "error", 6000);
        return;
      }
      _sbState = await r.json();
      _renderSupabase();
      toast("Supabase saved. Future builds + the live app will use it.", "success", 4000);
    } catch (err) {
      toast("Network error: " + err.message, "error", 6000);
    } finally {
      $sbSave.disabled = false;
      $sbSave.textContent = "Save";
    }
  });

  $sbClear.addEventListener("click", async () => {
    if (!confirm("Disconnect Supabase from this project? The live app will lose access immediately.")) return;
    try {
      const token = localStorage.getItem("token");
      const r = await fetch(`/api/projects/${encodeURIComponent(slug)}/supabase`, {
        method: "DELETE",
        headers: token ? { Authorization: "Bearer " + token } : {},
        credentials: "include",
      });
      if (!r.ok && r.status !== 204) {
        const txt = await r.text();
        toast("Disconnect failed: " + txt.slice(0, 240), "error", 6000);
        return;
      }
      _sbState = { configured: false };
      _renderSupabase();
      toast("Supabase disconnected.", "success", 3000);
    } catch (err) { toast("Network error: " + err.message, "error", 6000); }
  });

  // Refresh Supabase config every time the publish modal opens.
  $btnPub.addEventListener("click", () => {
    setTimeout(refreshSupabase, 100);
  });
```

- [ ] **Step 3: Manual UI test**

```bash
scp -i ~/.ssh/aiui_safe "C:/All/Work - Code/ai_ui/mcp-servers/tasks/static/preview.html" root@46.224.193.25:/tmp/
ssh -i ~/.ssh/aiui_safe root@46.224.193.25 "cp /tmp/preview.html /root/proxy-server/mcp-servers/tasks/static/ && docker cp /tmp/preview.html tasks:/app/static/preview.html"
```

Open the preview page for any project, click 🌐 Publish/Live in the topbar. Scroll to "🗄 Supabase backend":
- Paste a real Supabase URL + anon key → click Save → badge flips to "Connected", URL pill appears.
- Reload the page. The URL persists; key field is blank.
- Click Disconnect → confirms → badge returns to "Optional", URL pill hides.

- [ ] **Step 4: Commit**

```bash
git -C "C:/All/Work - Code/ai_ui" add mcp-servers/tasks/static/preview.html
git -C "C:/All/Work - Code/ai_ui" commit -m "feat(supabase): UI to attach + disconnect Supabase per project"
```

---

### Task 9: End-to-end smoke test with a real Supabase project

**Files:** none — verification only.

- [ ] **Step 1: Create a free Supabase project**

Go to <https://supabase.com>, sign up (free tier), create a new project. Wait ~2 min for it to provision. Copy the **Project URL** and the **anon public key** from Project Settings → API.

- [ ] **Step 2: Attach to a published AIUI app**

In the AIUI App Builder, pick (or create) a published project. Open its Publish modal → 🗄 Supabase backend → paste URL + anon key → Save.

Verify:
- The Connected badge lights up.
- DB row exists:
  ```bash
  ssh -i ~/.ssh/aiui_safe root@46.224.193.25 "docker exec postgres psql \$(docker exec tasks printenv DATABASE_URL | sed 's|postgresql+asyncpg://|postgresql://|') -c 'SELECT slug, supabase_url FROM tasks.project_supabase'"
  ```

- [ ] **Step 3: Visit the live app's URL and verify window vars**

In the browser DevTools console on the published app's URL:

```javascript
console.log(window.SUPABASE_URL, window.SUPABASE_ANON_KEY);
```

Expected: prints both values.

- [ ] **Step 4: Verify SDK works against your Supabase project**

In the same console:

```javascript
const { createClient } = await import("https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/+esm");
const sb = createClient(window.SUPABASE_URL, window.SUPABASE_ANON_KEY);
const { data, error } = await sb.from("nonexistent").select("*");
console.log("status:", error?.message || "ok");
```

Expected: a Supabase-side error like `relation "public.nonexistent" does not exist` or `permission denied for table nonexistent` — NOT a network/auth error. That confirms the URL + key pair is valid and the request reached Supabase.

- [ ] **Step 5: Trigger a build that uses Supabase, confirm Claude reads the prompt block**

In the preview's Build sidebar, send: *"Add a sign-up form that creates a row in a Supabase `signups` table."* Watch the live execution log; the Claude prompt should contain the "Supabase integration available" block. The resulting code should `import {createClient}` from jsDelivr and call `supabase.auth.signUp` (or the table insert).

- [ ] **Step 6: Final commit if any nits surfaced**

```bash
git -C "C:/All/Work - Code/ai_ui" add -A
git -C "C:/All/Work - Code/ai_ui" commit -m "chore(supabase): e2e pass" || true
```

---

## Self-Review

**Spec coverage**
- "Users can integrate their Supabase" → Tasks 4, 7, 8.
- "Encrypted at rest" → Task 2 (Fernet helper) + Task 4 (uses it on POST).
- "Injected into live app" → Task 5.
- "Claude is instructed" → Task 6.
- "No localStorage" → Task 7 (drops the option from the create modal and from STORAGE_INSTRUCTIONS).

**Placeholder scan** — none. All steps have explicit code blocks and exact commands.

**Type consistency**
- `SupabaseConfigStatus` shape (configured / supabase_url / configured_by / configured_at) is identical between routes_supabase.py (Task 4), test_supabase_config.py (Task 4), and the UI's `_renderSupabase()` (Task 8).
- `_supabase_block(supabase_url: str | None)` signature matches all 3 callers (`build_prompt`, `build_enhance_prompt`, future `build_clarify_prompt` if applicable).
- The window-var injection script string in Task 5 (`window.SUPABASE_URL=…;window.SUPABASE_ANON_KEY=…;`) matches the assertions in test_supabase_inject.py.
- Endpoint paths `/api/projects/{slug}/supabase` are consistent backend (Task 4) ↔ frontend fetch (Task 8).

---

Plan complete and saved to `docs/superpowers/plans/2026-04-25-app-builder-supabase.md`.

Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**

Heads-up before either:
- **Task 1 needs the host `.env` updated** with `AIUI_FERNET_KEY=…`. I can do that automatically on the VPS, but I want explicit OK first since it touches the global env file that other services read.
- **Task 2 rebuilds the tasks Docker image** to install `cryptography`. Brief downtime (~30s) on the tasks service.
- **Task 9 is manual** (creating a real Supabase project) — say the word when you've got URL + anon key in hand and I'll walk through the smoke test.
