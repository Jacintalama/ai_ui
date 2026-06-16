# Video Refine Chat + Studio UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a chat-driven "refine the generated video" loop (propose -> Apply -> re-render, with version history and the ability to upload more screenshots) and redesign the Video Generator page into a professional studio layout.

**Architecture:** A refine layer on top of the existing `mcp-servers/tasks` video pipeline. The chat sends the current plan + available screenshots + conversation to Claude (Opus, JSON-schema structured output), which returns a clarifying question or a validated revised plan. Applying a proposal writes `plan_json` and sets `status='queued'`; the existing worker re-renders (it already skips AI-scripting when a plan is present). Each successful render is snapshotted as a row in a new `video_job_versions` table so the user can revert instantly.

**Tech Stack:** Python 3.11, FastAPI, async SQLAlchemy + asyncpg, Postgres (`tasks` schema), Anthropic SDK (`claude-opus-4-8`), Pillow, ffmpeg + Piper on the build host, vanilla HTML/CSS/JS for the page. Tests: pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-06-16-video-refine-chat-design.md`

---

## Conventions for this codebase (read first)

- All commands run from `mcp-servers/tasks/` unless noted: `cd "mcp-servers/tasks"`.
- Run tests with `python -m pytest tests/<file>.py -v`. Tests are async via pytest-asyncio (auto mode); write `async def test_...` with no decorator.
- **DB tests** require a real Postgres. Mirror the existing pattern: guard them with `@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")` where:
  ```python
  import os
  _DB_URL = os.environ.get("DATABASE_URL", "")
  _HAVE_DB = bool(_DB_URL) and "nowhere" not in _DB_URL
  ```
  Offline (no DB) tests exercise pure logic and guards that fire before any DB call.
- **Auth in tests** is faked with gateway headers: `HEAD = {"X-User-Email": "ralph@aiui.com", "X-User-Admin": "true"}`. App + client:
  ```python
  from httpx import ASGITransport, AsyncClient
  from main import app
  async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
      r = await c.post("/api/video-jobs/...", headers=HEAD, ...)
  ```
- **Migrations** (`db.py::_run_migrations`) run EVERY `.sql` file in `migrations/` in sorted order on EVERY startup, with no tracking table. Migration 022 MUST be idempotent: use `CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`, and `ADD COLUMN IF NOT EXISTS`.
- Follow PEP 8 + type annotations. Use `logging`, never `print`. No em-dashes in code comments or docs.
- Commit after every green task. Author is the repo git user (no AI co-author trailers).

## File structure

**New files**
- `migrations/022_video_refine.sql` - versions table + `conversation`, `current_version_no`, `pending_summary` columns (idempotent).
- `video_refine.py` - `REFINE_SCHEMA`, prompt builders, conversation helpers (pure), and `refine_plan(...)` (async, wraps the Anthropic call).
- `video_versions.py` - DB helpers: `next_version_no`, `record_version`, `list_versions`, `find_version`.
- `tests/test_video_refine.py`, `tests/test_video_versions.py`, `tests/test_routes_video_refine.py`.

**Modified files**
- `video_models.py` - add `conversation`, `current_version_no`, `pending_summary` to `VideoJob`; add `VideoJobVersion` ORM.
- `routes_video.py` - new endpoints: `POST /{id}/refine`, `POST /{id}/apply`, `POST /{id}/screenshots`, `GET /{id}/versions`, `POST /{id}/revert`; extend `GET /{id}` and `GET /{id}/download`.
- `video_worker.py` - on render success, snapshot a version + set `output_path`/`current_version_no`.
- `video_cleanup.py` - stop pruning `screenshots`; cap version files.
- `static/video.html` - studio-split layout + refine chat pane + version bar + JS wiring.
- `tests/conftest.py` - add `tasks.video_job_versions` to the TRUNCATE list.
- `tests/test_video_cleanup.py`, `tests/test_video_worker.py` - extend.
- `api-gateway/main.py` - add a `/api/video-jobs` routing branch (parity).

---

## Phase 1: Data model + migration

### Task 1.1: Migration 022 (idempotent)

**Files:**
- Create: `mcp-servers/tasks/migrations/022_video_refine.sql`

- [ ] **Step 1: Write the migration**

```sql
-- 022_video_refine.sql
-- Refine-chat support: version history + per-job conversation. Idempotent:
-- db.py re-runs every migration file on every startup, so use IF NOT EXISTS.

ALTER TABLE tasks.video_jobs
  ADD COLUMN IF NOT EXISTS conversation       JSONB NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS current_version_no INT,
  ADD COLUMN IF NOT EXISTS pending_summary    TEXT;

CREATE TABLE IF NOT EXISTS tasks.video_job_versions (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id      UUID NOT NULL REFERENCES tasks.video_jobs(id) ON DELETE CASCADE,
  version_no  INT  NOT NULL,
  plan_json   JSONB NOT NULL,
  summary     TEXT,
  output_path TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (job_id, version_no)
);

CREATE INDEX IF NOT EXISTS video_job_versions_job_idx
  ON tasks.video_job_versions (job_id, version_no DESC);
```

- [ ] **Step 2: Sanity-check it parses** (offline, no DB): confirm the file is non-empty and contains the three `IF NOT EXISTS` guards.

Run: `grep -c "IF NOT EXISTS" migrations/022_video_refine.sql`
Expected: `5` (2 columns checked individually count as 2, table 1, index 1, plus the third column = 5 total `IF NOT EXISTS` occurrences).

- [ ] **Step 3: Commit**

```bash
git add mcp-servers/tasks/migrations/022_video_refine.sql
git commit -m "feat(video): migration 022 - version table + conversation columns"
```

### Task 1.2: ORM model changes

**Files:**
- Modify: `mcp-servers/tasks/video_models.py`
- Test: `mcp-servers/tasks/tests/test_video_models.py`

- [ ] **Step 1: Write the failing test** (offline - ORM class shape, no DB)

```python
def test_video_job_version_model_columns():
    from video_models import VideoJobVersion
    cols = set(VideoJobVersion.__table__.columns.keys())
    assert cols == {"id", "job_id", "version_no", "plan_json", "summary",
                    "output_path", "created_at"}
    assert VideoJobVersion.__table__.schema == "tasks"

def test_video_job_has_refine_columns():
    from video_models import VideoJob
    cols = set(VideoJob.__table__.columns.keys())
    assert {"conversation", "current_version_no", "pending_summary"} <= cols
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_video_models.py -v -k "version_model_columns or refine_columns"`
Expected: FAIL (ImportError: cannot import name 'VideoJobVersion' / missing columns).

- [ ] **Step 3: Implement**

Add to `video_models.py` (mirror the existing `VideoJob` column styles; `JSONB` and `UUID` are already imported there):

```python
class VideoJob(Base):  # existing - add three columns alongside the others
    # ...existing columns...
    conversation = Column(JSONB, nullable=False, default=list)
    current_version_no = Column(Integer, nullable=True)
    pending_summary = Column(Text, nullable=True)


class VideoJobVersion(Base):
    __tablename__ = "video_job_versions"
    __table_args__ = {"schema": "tasks"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    version_no = Column(Integer, nullable=False)
    plan_json = Column(JSONB, nullable=False)
    summary = Column(Text, nullable=True)
    output_path = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
```

Ensure `Integer` is imported (add to the existing `from sqlalchemy import ...` line if absent).

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_video_models.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/video_models.py mcp-servers/tasks/tests/test_video_models.py
git commit -m "feat(video): VideoJobVersion ORM + refine columns on VideoJob"
```

### Task 1.3: Add the new table to the test TRUNCATE list

**Files:**
- Modify: `mcp-servers/tasks/tests/conftest.py:64-69`

- [ ] **Step 1: Edit the TRUNCATE statement** to include the child table first (CASCADE from `video_jobs` already covers it, but listing it is explicit and order-safe):

```python
        await conn.execute(text(
            "TRUNCATE tasks.items, tasks.executions, "
            "tasks.published_apps, tasks.project_members, "
            "tasks.project_supabase, tasks.chat_history, "
            "tasks.video_job_versions, tasks.video_jobs CASCADE"
        ))
```

- [ ] **Step 2: Commit**

```bash
git add mcp-servers/tasks/tests/conftest.py
git commit -m "test(video): truncate video_job_versions between tests"
```

---

## Phase 2: Version helpers (`video_versions.py`)

### Task 2.1: `next_version_no` + `record_version`

**Files:**
- Create: `mcp-servers/tasks/video_versions.py`
- Test: `mcp-servers/tasks/tests/test_video_versions.py`

- [ ] **Step 1: Write the failing test** (DB - skipif)

```python
import os, uuid
import pytest
from sqlalchemy import select
from video_models import VideoJob, VideoJobVersion
from video_versions import next_version_no, record_version, list_versions

_DB_URL = os.environ.get("DATABASE_URL", "")
_HAVE_DB = bool(_DB_URL) and "nowhere" not in _DB_URL
PLAN = {"template_id": "product_demo", "title": "t",
        "scenes": [{"screenshot": "screenshot-1.png", "caption": "c",
                    "duration_s": 3, "transition": "cut"}],
        "narration_script": "hello"}

@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_record_version_increments(db_session):
    job = VideoJob(id=uuid.uuid4(), slug="alpha", user_email="r@x.com",
                   prompt="p", status="done", plan_json=PLAN)
    db_session.add(job)
    await db_session.commit()
    n1 = await next_version_no(db_session, job.id)
    assert n1 == 1
    await record_version(db_session, job.id, n1, PLAN, None, "/x/out-v1.mp4")
    await db_session.commit()
    n2 = await next_version_no(db_session, job.id)
    assert n2 == 2
    vs = await list_versions(db_session, job.id)
    assert [v.version_no for v in vs] == [1]
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_video_versions.py -v` (offline: collected + skipped; with DB: fails on import).
Expected: FAIL/ERROR (module `video_versions` not found) when DB present; SKIPPED offline.

- [ ] **Step 3: Implement `video_versions.py`**

```python
"""DB helpers for video render versions (tasks.video_job_versions)."""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from video_models import VideoJobVersion


async def next_version_no(s: AsyncSession, job_id: uuid.UUID) -> int:
    current_max = (await s.execute(
        select(func.max(VideoJobVersion.version_no))
        .where(VideoJobVersion.job_id == job_id)
    )).scalar()
    return (current_max or 0) + 1


async def record_version(
    s: AsyncSession, job_id: uuid.UUID, version_no: int,
    plan_json: dict, summary: str | None, output_path: str | None,
) -> VideoJobVersion:
    v = VideoJobVersion(
        id=uuid.uuid4(), job_id=job_id, version_no=version_no,
        plan_json=plan_json, summary=summary, output_path=output_path,
    )
    s.add(v)
    return v


async def list_versions(s: AsyncSession, job_id: uuid.UUID) -> list[VideoJobVersion]:
    return list((await s.execute(
        select(VideoJobVersion).where(VideoJobVersion.job_id == job_id)
        .order_by(VideoJobVersion.version_no)
    )).scalars().all())


async def find_version(
    s: AsyncSession, job_id: uuid.UUID, version_no: int,
) -> VideoJobVersion | None:
    return (await s.execute(
        select(VideoJobVersion)
        .where(VideoJobVersion.job_id == job_id,
               VideoJobVersion.version_no == version_no)
    )).scalar_one_or_none()
```

- [ ] **Step 4: Run to verify it passes** (at deploy/CI with DB; offline it stays skipped)

Run: `python -m pytest tests/test_video_versions.py -v`
Expected: PASS (or SKIPPED offline).

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/video_versions.py mcp-servers/tasks/tests/test_video_versions.py
git commit -m "feat(video): version DB helpers (next/record/list/find)"
```

---

## Phase 3: Refiner (`video_refine.py`)

### Task 3.1: Schema + prompt builders + conversation helpers (pure, offline)

**Files:**
- Create: `mcp-servers/tasks/video_refine.py`
- Test: `mcp-servers/tasks/tests/test_video_refine.py`

- [ ] **Step 1: Write the failing test** (offline - pure functions)

```python
import pytest
from video_refine import (
    REFINE_SCHEMA, build_system_prompt, build_messages,
    append_turn, keep_only_latest_proposal_plan, latest_pending_proposal,
    mark_proposal_applied,
)

PLAN = {"template_id": "product_demo", "title": "t",
        "scenes": [{"screenshot": "screenshot-1.png", "caption": "c",
                    "duration_s": 3, "transition": "cut"}],
        "narration_script": "hi"}

def test_schema_allows_ask_and_propose():
    assert REFINE_SCHEMA["properties"]["action"]["enum"] == ["ask", "propose"]
    assert "plan" in REFINE_SCHEMA["properties"]

def test_system_prompt_lists_screenshots_and_plan():
    sp = build_system_prompt(PLAN, ["screenshot-1.png", "screenshot-2.png"])
    assert "screenshot-2.png" in sp and "narration_script" in sp

def test_build_messages_caps_to_40_turns():
    convo = [{"role": "user", "kind": "message", "content": str(i)} for i in range(60)]
    msgs = build_messages(convo, "newest")
    assert len(msgs) <= 41  # 40 history + the new user turn
    assert msgs[-1]["content"].endswith("newest") or msgs[-1]["content"] == "newest"

def test_keep_only_latest_proposal_plan_strips_old_plans():
    convo = [
        {"role": "assistant", "kind": "proposal", "content": "v1", "plan": PLAN, "applied": True},
        {"role": "assistant", "kind": "proposal", "content": "v2", "plan": PLAN, "applied": False},
    ]
    out = keep_only_latest_proposal_plan(convo)
    assert "plan" not in out[0]            # older proposal stripped
    assert out[1]["plan"] == PLAN          # latest keeps its plan

def test_latest_pending_proposal_and_mark_applied():
    convo = [
        {"role": "assistant", "kind": "proposal", "content": "old", "plan": PLAN, "applied": True},
        {"role": "assistant", "kind": "proposal", "content": "new", "plan": PLAN, "applied": False},
    ]
    p = latest_pending_proposal(convo)
    assert p["content"] == "new"
    out = mark_proposal_applied(convo, p)
    assert latest_pending_proposal(out) is None  # nothing pending after applying
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_video_refine.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement the pure parts of `video_refine.py`**

```python
"""Chat-driven refinement of a video plan (structured plan-regeneration).

refine_plan() asks Claude for either a clarifying question or a complete,
schema-valid revised plan; the validated plan is what the worker re-renders.
"""
from __future__ import annotations

import asyncio
import json
import os

import anthropic

from video_plan import PLAN_SCHEMA, validate_plan

REFINE_MODEL = "claude-opus-4-8"
MAX_HISTORY_TURNS = 40

REFINE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["action", "message"],
    "properties": {
        "action": {"enum": ["ask", "propose"]},
        "message": {"type": "string"},
        "plan": PLAN_SCHEMA,
    },
}


class RefineUnavailable(RuntimeError):
    """Raised when ANTHROPIC_API_KEY is not configured."""


def build_system_prompt(current_plan: dict, screenshots: list[str]) -> str:
    return (
        "You are editing an existing narrated screenshot-slideshow video. "
        "You will receive the current render plan (JSON) and the list of "
        "available screenshot filenames. The user describes a change in plain "
        "language (reorder, delete, re-caption, retime scenes, rewrite the "
        "narration, or add scenes that use available screenshots).\n\n"
        "Rules:\n"
        "- Only reference screenshots from the provided list.\n"
        "- Keep total scene duration <= 60 seconds; each scene 0.5-15s.\n"
        "- Change ONLY what the user asked; keep everything else identical.\n"
        "- If the request is genuinely ambiguous, set action='ask' with a "
        "brief clarifying question and omit 'plan'.\n"
        "- Otherwise set action='propose', put a one-line summary of the "
        "change in 'message', and return a COMPLETE revised 'plan' that "
        "conforms to the schema.\n\n"
        f"Available screenshots: {json.dumps(screenshots)}\n"
        f"Current plan: {json.dumps(current_plan)}"
    )


def build_messages(conversation: list[dict], message: str) -> list[dict]:
    """Map the stored conversation (last MAX_HISTORY_TURNS turns) plus the new
    user message into Anthropic message dicts. 'user' turns map to user; every
    assistant turn (question/proposal/note) maps to assistant text."""
    msgs: list[dict] = []
    for turn in conversation[-MAX_HISTORY_TURNS:]:
        role = "user" if turn.get("role") == "user" else "assistant"
        msgs.append({"role": role, "content": str(turn.get("content", ""))})
    if not msgs or msgs[-1]["content"] != message:
        msgs.append({"role": "user", "content": message})
    return msgs


def append_turn(conversation: list[dict], role: str, kind: str,
                content: str, **extra) -> list[dict]:
    turn = {"role": role, "kind": kind, "content": content}
    turn.update(extra)
    return [*conversation, turn]


def keep_only_latest_proposal_plan(conversation: list[dict]) -> list[dict]:
    """Strip the heavy 'plan' field from every proposal turn except the most
    recent one, to bound the JSONB column size."""
    last_idx = max(
        (i for i, t in enumerate(conversation) if t.get("kind") == "proposal"),
        default=-1,
    )
    out = []
    for i, t in enumerate(conversation):
        if t.get("kind") == "proposal" and i != last_idx and "plan" in t:
            t = {k: v for k, v in t.items() if k != "plan"}
        out.append(t)
    return out


def latest_pending_proposal(conversation: list[dict]) -> dict | None:
    for t in reversed(conversation):
        if t.get("kind") == "proposal" and not t.get("applied") and t.get("plan"):
            return t
    return None


def mark_proposal_applied(conversation: list[dict], proposal: dict) -> list[dict]:
    out = []
    for t in conversation:
        if t is proposal or (t.get("kind") == "proposal"
                             and t.get("content") == proposal.get("content")
                             and not t.get("applied")):
            t = {**t, "applied": True}
        out.append(t)
    return out
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_video_refine.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/video_refine.py mcp-servers/tasks/tests/test_video_refine.py
git commit -m "feat(video): refine schema + prompt + conversation helpers"
```

### Task 3.2: `refine_plan` (ask vs propose, invalid-plan downgrade)

**Files:**
- Modify: `mcp-servers/tasks/video_refine.py`
- Test: `mcp-servers/tasks/tests/test_video_refine.py`

- [ ] **Step 1: Write the failing test** (offline - monkeypatch the model call)

```python
import video_refine

async def test_refine_returns_question(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setattr(video_refine, "_call_model",
                        lambda system, messages: {"action": "ask", "message": "Which scene?"})
    out = await video_refine.refine_plan(PLAN, ["screenshot-1.png"], [], "make it better")
    assert out == {"action": "ask", "message": "Which scene?"}

async def test_refine_returns_validated_proposal(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    good = {"action": "propose", "message": "shorter scene 1", "plan": PLAN}
    monkeypatch.setattr(video_refine, "_call_model", lambda s, m: good)
    out = await video_refine.refine_plan(PLAN, ["screenshot-1.png"], [], "shorten")
    assert out["action"] == "propose" and out["plan"] == PLAN

async def test_refine_downgrades_invalid_plan_to_ask(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    bad = {"action": "propose", "message": "x",
           "plan": {"template_id": "product_demo", "title": "t",
                    "scenes": [{"screenshot": "MISSING.png", "caption": "c",
                                "duration_s": 3, "transition": "cut"}],
                    "narration_script": "n"}}
    monkeypatch.setattr(video_refine, "_call_model", lambda s, m: bad)
    out = await video_refine.refine_plan(PLAN, ["screenshot-1.png"], [], "add missing")
    assert out["action"] == "ask"  # screenshot not available -> validate_plan raises -> downgrade

async def test_refine_requires_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(video_refine.RefineUnavailable):
        await video_refine.refine_plan(PLAN, ["screenshot-1.png"], [], "hi")
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_video_refine.py -v -k refine_`
Expected: FAIL (`_call_model` / `refine_plan` not defined).

- [ ] **Step 3: Implement** (append to `video_refine.py`)

```python
def _call_model(system: str, messages: list[dict]) -> dict:
    """Blocking Anthropic structured-output call. Mirrors video_plan.generate_plan.
    Isolated so tests can monkeypatch it. Returns the parsed JSON object."""
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
    resp = client.messages.create(
        model=REFINE_MODEL,
        max_tokens=2048,
        system=system,
        output_config={"format": {"type": "json_schema", "schema": REFINE_SCHEMA}},
        messages=messages,
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    return json.loads(text)


async def refine_plan(current_plan: dict, screenshots: list[str],
                      conversation: list[dict], message: str) -> dict:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RefineUnavailable("ANTHROPIC_API_KEY not configured")
    system = build_system_prompt(current_plan, screenshots)
    messages = build_messages(conversation, message)
    raw = await asyncio.to_thread(_call_model, system, messages)

    if raw.get("action") == "propose":
        plan = raw.get("plan")
        try:
            validate_plan(plan, screenshots)  # raises on any invalid/missing plan
        except Exception as exc:  # noqa: BLE001 - any failure downgrades to a re-ask
            return {"action": "ask",
                    "message": f"I could not build a valid change ({exc}). "
                               "Can you rephrase?"}
        return {"action": "propose",
                "message": raw.get("message") or "Here is the change.",
                "plan": plan}
    return {"action": "ask",
            "message": raw.get("message") or "Could you clarify what to change?"}
```

(If `validate_plan`'s exception type is `PlanInvalid`, the broad `except Exception` still covers it plus `AttributeError` from a `None` plan, per the spec.)

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_video_refine.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/video_refine.py mcp-servers/tasks/tests/test_video_refine.py
git commit -m "feat(video): refine_plan (ask/propose with validated downgrade)"
```

---

## Phase 4: Routes (`routes_video.py`)

> Read `routes_video.py` first to reuse its exact imports and helpers: `current_admin`/`AdminUser` (from `auth`), `_require_role` + `_validate_slug` (from `routes_projects`), `_coerce_job_id`, `session`, `VideoJob`, the `MAX_FILES`/`MAX_FILE_BYTES`/`MAX_TOTAL_BYTES` constants, `enough_free_disk`, `validate_screenshot`/`ScreenshotRejected`, and `_screenshots_dir`-style path building. Define a module helper `_video_enabled()` mirroring the upload kill-switch (503 when `VIDEO_ENABLED != 'true'`). Add Pydantic request models `RefineRequest{message: str}` (1..2000) and `RevertRequest{version_no: int}`.

### Task 4.1: `POST /{job_id}/refine`

**Files:**
- Modify: `mcp-servers/tasks/routes_video.py`
- Test: `mcp-servers/tasks/tests/test_routes_video_refine.py`

- [ ] **Step 1: Write the failing tests** (offline guards + DB happy path)

```python
import os, uuid, pytest
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient
os.environ.setdefault("AIUI_FERNET_KEY", Fernet.generate_key().decode())
from main import app
from models import TaskItem
from video_models import VideoJob

HEAD = {"X-User-Email": "ralph@aiui.com", "X-User-Admin": "true"}
_DB_URL = os.environ.get("DATABASE_URL", "")
_HAVE_DB = bool(_DB_URL) and "nowhere" not in _DB_URL
PLAN = {"template_id": "product_demo", "title": "t",
        "scenes": [{"screenshot": "screenshot-1.png", "caption": "c",
                    "duration_s": 3, "transition": "cut"}],
        "narration_script": "hi"}

async def test_refine_no_auth_401():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(f"/api/video-jobs/{uuid.uuid4()}/refine", json={"message": "x"})
    assert r.status_code == 401

@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_refine_proposal_persists_conversation(db_session, tmp_path, monkeypatch):
    import video_refine
    monkeypatch.setenv("APPS_DIR", str(tmp_path))
    # screenshots on disk for validate_plan
    job_id = uuid.uuid4()
    shots = tmp_path / "alpha" / ".video" / str(job_id) / "screenshots"
    shots.mkdir(parents=True)
    (shots / "screenshot-1.png").write_bytes(b"x")
    db_session.add(TaskItem(meeting_id=uuid.uuid4(), action_type="BUILD",
                            assignee_name="R", assignee_email="ralph@aiui.com",
                            description="x", priority="IMPORTANT", status="completed",
                            built_app_slug="alpha"))
    db_session.add(VideoJob(id=job_id, slug="alpha", user_email="ralph@aiui.com",
                            prompt="p", status="done", plan_json=PLAN, output_path="x"))
    await db_session.commit()
    monkeypatch.setattr(video_refine, "_call_model",
                        lambda s, m: {"action": "propose", "message": "shorter", "plan": PLAN})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(f"/api/video-jobs/{job_id}/refine", json={"message": "shorten"}, headers=HEAD)
    assert r.status_code == 200
    assert r.json() == {"action": "propose", "message": "shorter", "can_apply": True}
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_routes_video_refine.py -v -k "no_auth or proposal_persists"`
Expected: FAIL (404 route missing / 405).

- [ ] **Step 3: Implement** the `refine` endpoint in `routes_video.py`:

```python
@router.post("/{job_id}/refine")
async def refine(job_id: str, body: RefineRequest, user: AdminUser = Depends(current_admin)):
    if not _video_enabled():
        raise HTTPException(503, "Video generation is disabled")
    jid = _coerce_job_id(job_id)
    async with session() as s:
        job = (await s.execute(select(VideoJob).where(VideoJob.id == jid))).scalar_one_or_none()
        if job is None:
            raise HTTPException(404, "Video job not found")
        await _require_role(s, job.slug, user.email, "editor", is_admin=user.is_admin)
        shots = _list_screenshots(job.slug, str(jid))  # sorted filenames on disk
        convo = list(job.conversation or [])
        convo = append_turn(convo, "user", "message", body.message)
        try:
            result = await refine_plan(job.plan_json or {}, shots, convo, body.message)
        except RefineUnavailable:
            raise HTTPException(503, "Refinement is unavailable (no API key)")
        if result["action"] == "propose":
            convo = append_turn(convo, "assistant", "proposal", result["message"],
                                plan=result["plan"], applied=False)
            convo = keep_only_latest_proposal_plan(convo)
        else:
            convo = append_turn(convo, "assistant", "question", result["message"])
        await s.execute(update(VideoJob).where(VideoJob.id == jid)
                        .values(conversation=convo))
        await s.commit()
    return {"action": result["action"], "message": result["message"],
            "can_apply": result["action"] == "propose"}
```

Add `_list_screenshots(slug, job_id)` (sorted `os.listdir` of the screenshots dir, `[]` if absent) and the imports (`from video_refine import refine_plan, RefineUnavailable, append_turn, keep_only_latest_proposal_plan, latest_pending_proposal, mark_proposal_applied`).

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_routes_video_refine.py -v`
Expected: PASS (DB test skipped offline).

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/routes_video.py mcp-servers/tasks/tests/test_routes_video_refine.py
git commit -m "feat(video): POST /{id}/refine endpoint"
```

### Task 4.2: `POST /{job_id}/apply`

**Files:** Modify `routes_video.py`; Test `tests/test_routes_video_refine.py`

- [ ] **Step 1: Write the failing tests**: (a) `apply` with no pending proposal returns 409 (DB test: create a job with empty conversation); (b) `apply` after a proposal sets `status='queued'`, `plan_json`=proposal plan, `pending_summary`=summary, and marks the proposal applied (DB test).

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Implement**:

```python
@router.post("/{job_id}/apply")
async def apply(job_id: str, user: AdminUser = Depends(current_admin)):
    if not _video_enabled():
        raise HTTPException(503, "Video generation is disabled")
    jid = _coerce_job_id(job_id)
    async with session() as s:
        job = (await s.execute(select(VideoJob).where(VideoJob.id == jid))).scalar_one_or_none()
        if job is None:
            raise HTTPException(404, "Video job not found")
        await _require_role(s, job.slug, user.email, "editor", is_admin=user.is_admin)
        prop = latest_pending_proposal(job.conversation or [])
        if prop is None:
            raise HTTPException(409, "No pending change to apply")
        shots = _list_screenshots(job.slug, str(jid))
        try:
            validate_plan(prop["plan"], shots)  # defense in depth
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(422, f"Proposed change is no longer valid: {exc}")
        convo = mark_proposal_applied(job.conversation or [], prop)
        convo = append_turn(convo, "assistant", "note", "Applying. Re-rendering your video.")
        await s.execute(update(VideoJob).where(VideoJob.id == jid).values(
            plan_json=prop["plan"], status="queued", conversation=convo,
            pending_summary=prop["content"]))
        await s.commit()
    return {"status": "queued"}
```

- [ ] **Step 4: Run to verify it passes.**
- [ ] **Step 5: Commit** `feat(video): POST /{id}/apply (queue re-render of proposed plan)`.

### Task 4.3: `POST /{job_id}/screenshots`

**Files:** Modify `routes_video.py`; Test `tests/test_routes_video_refine.py`

- [ ] **Step 1: Write the failing tests**: (a) no-auth 401 (offline); (b) too-many/oversized files -> 413 (reuse upload's guards); (c) DB happy path: posting one PNG to an existing job appends `screenshot-{n+1}.png` and returns the full sorted list.

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Implement** mirroring `upload`'s validation order (kill switch 503, count cap counting existing+new vs `MAX_FILES`, `enough_free_disk` 507, per-file `MAX_FILE_BYTES` 413, cumulative `MAX_TOTAL_BYTES` 413, `validate_screenshot` 400). Save new files as `screenshot-{existing_count + i}.png` in the screenshots dir; return `{"screenshots": sorted(os.listdir(shots_dir))}`. Require `editor` role.

- [ ] **Step 4: Run to verify it passes.**
- [ ] **Step 5: Commit** `feat(video): POST /{id}/screenshots (add images mid-chat)`.

### Task 4.4: `GET /{job_id}/versions` + `POST /{job_id}/revert`

**Files:** Modify `routes_video.py`; Test `tests/test_routes_video_refine.py`

- [ ] **Step 1: Write the failing tests** (DB): seed a job with two version rows; `GET /versions` returns both with `current`/`available` flags; `POST /revert {version_no: 1}` re-points `plan_json`/`output_path`/`current_version_no` to v1 without changing `status` when the file exists (use a real temp file); reverting to a `version_no` with no file sets `status='queued'`; unknown version -> 404.

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Implement**:

```python
@router.get("/{job_id}/versions")
async def versions(job_id: str, user: AdminUser = Depends(current_admin)):
    jid = _coerce_job_id(job_id)
    async with session() as s:
        job = (await s.execute(select(VideoJob).where(VideoJob.id == jid))).scalar_one_or_none()
        if job is None:
            raise HTTPException(404, "Video job not found")
        if not user.is_admin:
            await _require_role(s, job.slug, user.email, "viewer")
        vs = await list_versions(s, jid)
        return {"versions": [{
            "version_no": v.version_no, "summary": v.summary,
            "created_at": v.created_at.isoformat() if v.created_at else None,
            "current": v.version_no == job.current_version_no,
            "available": bool(v.output_path and os.path.exists(v.output_path)),
        } for v in vs]}


@router.post("/{job_id}/revert")
async def revert(job_id: str, body: RevertRequest, user: AdminUser = Depends(current_admin)):
    if not _video_enabled():
        raise HTTPException(503, "Video generation is disabled")
    jid = _coerce_job_id(job_id)
    async with session() as s:
        job = (await s.execute(select(VideoJob).where(VideoJob.id == jid))).scalar_one_or_none()
        if job is None:
            raise HTTPException(404, "Video job not found")
        await _require_role(s, job.slug, user.email, "editor", is_admin=user.is_admin)
        v = await find_version(s, jid, body.version_no)
        if v is None:
            raise HTTPException(404, "Version not found")
        convo = append_turn(job.conversation or [], "assistant", "note",
                            f"Reverted to v{v.version_no}.")
        if v.output_path and os.path.exists(v.output_path):
            await s.execute(update(VideoJob).where(VideoJob.id == jid).values(
                plan_json=v.plan_json, output_path=v.output_path,
                current_version_no=v.version_no, conversation=convo))
            await s.commit()
            return {"status": "reverted", "output_available": True}
        await s.execute(update(VideoJob).where(VideoJob.id == jid).values(
            plan_json=v.plan_json, status="queued", conversation=convo,
            pending_summary=f"Revert to v{v.version_no}"))
        await s.commit()
        return {"status": "queued", "output_available": False}
```

Add imports `from video_versions import list_versions, find_version`.

- [ ] **Step 4: Run to verify it passes.**
- [ ] **Step 5: Commit** `feat(video): versions list + revert endpoints`.

### Task 4.5: Extend `GET /{job_id}` and `GET /{job_id}/download`

**Files:** Modify `routes_video.py`; Test `tests/test_routes_video_status.py`, `tests/test_routes_video_download.py`

- [ ] **Step 1: Write failing tests**: `GET /{id}` response now includes `conversation` (list), `current_version_no`, and `pending` (bool, true when a pending proposal exists); `GET /{id}/download?version=N` serves that version's file (DB + temp file), defaults to current when omitted, 404 on unknown version.

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Implement**: add the three fields to the status response dict; in `download`, accept `version: int | None = None`, and when provided resolve `find_version(...).output_path` (404 if missing) instead of `job.output_path`, keeping the existing capability/member auth untouched.

- [ ] **Step 4: Run to verify it passes.**
- [ ] **Step 5: Commit** `feat(video): expose conversation/versions on status + versioned download`.

---

## Phase 5: Worker + cleanup

### Task 5.1: Worker snapshots a version on render success

**Files:**
- Modify: `mcp-servers/tasks/video_worker.py:75-132`
- Test: `mcp-servers/tasks/tests/test_video_worker.py`

- [ ] **Step 1: Write the failing test** (DB): seed a `queued` job with a `plan_json`, monkeypatch `VideoRenderExecutor.render` to write a fake `out.mp4` under the job dir and return its path; run `_process_job(job.id)`; assert `status='done'`, a `video_job_versions` row `version_no=1` exists, `out-v1.mp4` exists, `job.output_path` ends with `out-v1.mp4`, `current_version_no=1`, and `pending_summary` is cleared (None).

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Implement.** In `_process_job`, read `pending_summary` in the initial fetch (line ~97): `slug, prompt, plan, pending_summary = job.slug, job.prompt, job.plan_json, job.pending_summary`. Replace Stage 3 (lines ~126-132) with:

```python
        # Stage 3: snapshot a version, then mark done.
        import shutil
        from video_versions import next_version_no, record_version
        async with session() as s:
            version_no = await next_version_no(s, job_id)
            job_dir = os.path.join(APPS_DIR, slug, ".video", str(job_id))
            versioned = os.path.join(job_dir, f"out-v{version_no}.mp4")
            try:
                shutil.copy2(out, versioned)
            except OSError:
                versioned = out  # fall back to the single out.mp4 if copy fails
            await record_version(s, job_id, version_no, plan, pending_summary, versioned)
            await s.execute(update(VideoJob).where(VideoJob.id == job_id).values(
                status="done", output_path=versioned,
                current_version_no=version_no, pending_summary=None))
            await s.commit()
```

(`version_no=1` gets `summary=pending_summary` which is `None` for the initial render and the proposal/revert summary for re-renders.)

- [ ] **Step 4: Run to verify it passes.**
- [ ] **Step 5: Commit** `feat(video): worker snapshots each render as a version`.

### Task 5.2: Cleanup keeps screenshots

**Files:**
- Modify: `mcp-servers/tasks/video_cleanup.py:38`
- Test: `mcp-servers/tasks/tests/test_video_cleanup.py`

- [ ] **Step 1: Write the failing test** (offline, pure): create a temp job dir with `screenshots/`, `captions/`, `narration.txt`, `voice.mp3`, `out.mp4`; call `prune_inputs(job_dir)`; assert `screenshots/` and `out.mp4` SURVIVE and `captions/`, `narration.txt`, `voice.mp3` are gone.

- [ ] **Step 2: Run to verify it fails** (current code deletes `screenshots`).

- [ ] **Step 3: Implement**: change line 38 to

```python
_PRUNE_ENTRIES = ("voice.wav", "voice.mp3", "captions", "narration.txt")
```

- [ ] **Step 4: Run to verify it passes.**
- [ ] **Step 5: Commit** `fix(video): stop pruning screenshots so re-render/add-scene works`.

### Task 5.3: Cap version files on disk

**Files:**
- Modify: `mcp-servers/tasks/video_cleanup.py` (add `cap_version_files` + call it in `_sweep_once` (a))
- Test: `mcp-servers/tasks/tests/test_video_cleanup.py`

- [ ] **Step 1: Write the failing test** (offline, pure): create `out-v1.mp4 .. out-v7.mp4`; call `cap_version_files(job_dir, max_versions=5, keep={"out-v2.mp4"})`; assert the 5 newest by version number plus the protected `out-v2.mp4` remain, older ones deleted.

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Implement**:

```python
import re
MAX_VERSIONS = int(os.environ.get("VIDEO_MAX_VERSIONS", "5"))
_VER_RE = re.compile(r"^out-v(\d+)\.mp4$")

def cap_version_files(job_dir: str, max_versions: int, keep: set[str]) -> None:
    """Keep the newest `max_versions` out-v*.mp4 files plus any in `keep`.
    PURE filesystem op; best-effort (errors logged, never raised)."""
    try:
        files = [(int(m.group(1)), name)
                 for name in os.listdir(job_dir)
                 if (m := _VER_RE.match(name))]
    except OSError:
        return
    files.sort(reverse=True)  # newest version_no first
    survivors = {name for _, name in files[:max_versions]} | set(keep)
    for _, name in files:
        if name not in survivors:
            try:
                os.remove(os.path.join(job_dir, name))
            except OSError:
                logger.exception("cap_version_files: could not remove %s", name)
```

Then in `_sweep_once` (a), after `prune_inputs(job_dir)`:

```python
            keep = {os.path.basename(job.output_path)} if job.output_path else set()
            cap_version_files(job_dir, MAX_VERSIONS, keep)
```

- [ ] **Step 4: Run to verify it passes.**
- [ ] **Step 5: Commit** `feat(video): cap kept version files (default 5) on the tight disk`.

---

## Phase 6: Studio UI (`static/video.html`)

> This is one HTML file (inline CSS + vanilla JS). Reuse its existing design tokens and `.card`/`.btn`/`.badge`/`.field`/spinner classes. Clone the chat-pane behavior from `static/preview.html` (`renderChatBubble`, `submitChat`, `authHeaders` + `credentials:'include'`). Keep `MAX_FILES`/poll constants. After each change, verify with a Playwright screenshot against the live page (manual smoke). UI logic is exercised by hand + the screenshot smoke, not pytest.

### Task 6.1: Studio-split layout + version bar + chat markup

**Files:** Modify `mcp-servers/tasks/static/video.html`

- [ ] **Step 1:** Replace the `.layout` block so the LEFT column is the primary studio area (large `<video>` + a `#scene-strip` + a `#version-bar`) and the RIGHT column (`.col-right`) holds the refine chat (`#chat-log`, a paperclip `#add-shots` file input, a `#chat-input` textarea + send button). Keep the create form (`#form-card`) in the left area, shown only in the create state (`body[data-state="create"]`); the studio elements show in `data-state="studio"`. Add CSS for `.chat-bubble.user/.ai/.proposal`, `.scene-strip`, `.version-bar .chip`, and matching cache-bust on poster + video. Remove the asymmetric empty-void styling and the inline styles flagged in the spec. Add a real empty/placeholder state for the player.

- [ ] **Step 2:** Open the live page in Playwright and screenshot the create state and (with a seeded done job) the studio state; confirm no empty void and the chat rail renders. Commit.

### Task 6.2: JS wiring (refine / apply / poll / revert / add-screenshots)

**Files:** Modify `mcp-servers/tasks/static/video.html`

- [ ] **Step 1:** Implement: `sendRefine()` -> `POST /{id}/refine` -> render an AI question bubble, or a proposal bubble with an **Apply** button; `applyChange()` -> `POST /{id}/apply` -> reuse `pollJob()` until `done` -> swap `<video src>` with a fresh cache-bust + reload the version bar; `loadVersions()` -> `GET /{id}/versions` -> render the bar; `revertTo(n)` -> `POST /{id}/revert` -> swap video (or poll if it re-rendered); `addShots()` -> `POST /{id}/screenshots` -> toast + hint to mention them. On load, `GET /{id}` rebuilds the conversation, version bar, and pending state. Reuse `authHeaders`/`multipartAuthHeaders` + `credentials:'include'`.

- [ ] **Step 2:** Playwright smoke: drive a refine -> proposal -> Apply -> video swap against the live job; screenshot each state. Commit.

---

## Phase 7: Gateway parity + deploy

### Task 7.1: api-gateway routes `/api/video-jobs`

**Files:**
- Modify: `api-gateway/main.py` (the routing elif-chain)
- Test: `mcp-servers/tasks/tests/test_main_jwt_forwarding.py` or an api-gateway test if one exists

- [ ] **Step 1:** Read the elif-chain (it has branches for `/api/tasks`, `/api/projects`, etc., but not `/api/video-jobs`). Add a branch that forwards `/api/video-jobs` to the tasks service exactly like `/api/tasks` (same `gateway_headers` injection so `X-User-Email` reaches the new endpoints).

- [ ] **Step 2:** Add/adjust a test asserting a `/api/video-jobs/...` request is routed to the tasks upstream with the gateway identity headers (mirror the existing `/api/tasks` forwarding test). Run it.

- [ ] **Step 3:** Commit `feat(gateway): route /api/video-jobs to the tasks service`.

### Task 7.2: Full test pass + deploy runbook (manual, not TDD)

- [ ] **Step 1:** Run the whole tasks suite with a real DB at CI/deploy: `cd mcp-servers/tasks && AIUI_TEST_DB=1 DATABASE_URL=<test-db> python -m pytest -q`. Expected: all green (existing 50+ video tests plus the new ones). Never run with `AIUI_TEST_DB=1` against a non-`test` database (conftest guard will refuse; respect it).
- [ ] **Step 2:** On the VPS, verify `/api/video-jobs/*` reaches the tasks service through the live host Caddy (the repo gateway/Caddyfile do not route it): `curl -fsS https://ai-ui.coolestdomain.win/tasks/healthz` and a `GET /api/video-jobs/<known-id>` with a valid session. If the host Caddy lacks the route, add it (host `/etc/caddy/Caddyfile`, not the dead compose caddy) per the deploy memory.
- [ ] **Step 3:** Deploy via targeted rebuild (NOT the orchestrator-all path): `git archive HEAD <changed files under mcp-servers/tasks> | ssh ... tar -x` into `/root/proxy-server`, then `docker compose -f docker-compose.unified.yml up -d --build tasks`. Migration 022 applies on startup (idempotent). Confirm the worker/cleanup loops log "started".
- [ ] **Step 4:** Smoke on prod: create a job, refine -> Apply -> confirm a v2 renders and the player swaps; revert to v1; verify `screenshots/` survive past the hourly sweep. `VIDEO_ENABLED` continues to gate the feature.
- [ ] **Step 5:** Bump the demo/page cache-bust if `video.html` changed, and confirm `/video-generator` serves the new studio page.

---

## Definition of done

- All new + existing tasks-service tests pass with a real DB.
- The page is a studio-split layout with a working refine chat: type a change -> proposal -> Apply -> re-render as a new version; version bar with revert; add-screenshots mid-chat.
- Screenshots survive the retention sweep; version files capped at `MAX_VERSIONS`.
- `/api/video-jobs/*` is routed by the api-gateway (parity) and verified on the VPS.
- No regressions to the existing create/upload/download flow.
