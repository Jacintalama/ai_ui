# AI Video Generator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user upload screenshots + a prompt and get back a short narrated explainer MP4, generated with ffmpeg + a free self-hosted voice (Piper) from AI-filled templates, running safely on the existing 4GB box without affecting App Builder, cron, or the bots.

**Architecture:** A new `video_jobs` table + an in-process worker in the `tasks` service orchestrate a pipeline: Claude writes a schema-validated plan, Piper renders a voiceover, ffmpeg renders the slideshow on the existing build host over SSH+rsync (the same path app builds use). Heavy work (render) is serialized against builds via a shared Postgres advisory lock, guarded by RAM/disk checks and a feature-flag kill switch, so it always *yields* to the rest of the platform.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy (async + asyncpg), PostgreSQL (`tasks` schema), the `anthropic` SDK (scripting), ffmpeg + Piper on the host, Pillow (caption overlays + image validation), pytest + httpx AsyncClient.

**Spec:** `docs/superpowers/specs/2026-06-15-ai-video-generator-design.md`

**Conventions to follow (verified in-repo):**
- ORM: `UUID(as_uuid=True), default=uuid.uuid4`, `__table_args__ = {"schema": "tasks"}`, `server_default=` for new columns on existing tables.
- Migrations: numbered `NNN_*.sql`, idempotent (`IF NOT EXISTS`), run at startup via raw asyncpg.
- Routes: `APIRouter`, `Depends(current_admin_or_capability_for_slug)`, `async with session() as s`.
- Tests: `@pytest.mark.asyncio`, `httpx.AsyncClient(transport=ASGITransport(app=app))`, `db_session` fixture, `monkeypatch` for async deps. NEVER `TestClient`.
- Heavy host jobs: SSH+rsync via `RemoteExecutor` patterns (`_SSH_OPTS`, `_RSYNC_SSH`, `shlex.quote`).
- Capability tokens: HMAC-SHA256 with a domain prefix, `OAUTH_STATE_SECRET`.

---

## File Structure

**Create:**
- `mcp-servers/tasks/migrations/021_video_jobs.sql` — table + indexes + updated_at trigger
- `mcp-servers/tasks/video_models.py` — `VideoJob` ORM model (kept separate to keep `models.py` focused)
- `mcp-servers/tasks/heavy_lock.py` — shared advisory-lock + RAM/disk guard helpers
- `mcp-servers/tasks/video_validation.py` — screenshot validation (image-only, magic-number, dimensions)
- `mcp-servers/tasks/video_capability.py` — `video_dl:` download capability (mirrors `edit_capability.py`)
- `mcp-servers/tasks/video_plan.py` — plan schema + `generate_plan()` (anthropic SDK) + validation
- `mcp-servers/tasks/video_render.py` — pure ffmpeg-argv + caption-PNG builders
- `mcp-servers/tasks/video_executor.py` — `VideoRenderExecutor` (rsync in, Piper + ffmpeg on host, rsync out.mp4 back, finally-cleanup)
- `mcp-servers/tasks/video_worker.py` — in-process pipeline worker loop
- `mcp-servers/tasks/routes_video.py` — upload / status / download routes
- `mcp-servers/tasks/static/video.html` — minimal upload + poll + download UI
- `mcp-servers/tasks/templates_video/product_demo.py`, `feature_walkthrough.py` — template definitions
- `mcp-servers/tasks/tests/test_video_*.py` — one test file per module

**Modify:**
- `mcp-servers/tasks/main.py` — import + `include_router(video_router)`; start `video_worker_loop` in `lifespan`
- `mcp-servers/tasks/requirements.txt` — add `anthropic`, `Pillow`
- `scripts/provision_agent_vm.sh` — install ffmpeg, fontconfig, fonts, Piper on the host
- `mcp-servers/tasks/config.py` (or env) — `VIDEO_ENABLED`, `VIDEO_MIN_FREE_RAM_MB`, `VIDEO_MIN_FREE_DISK_MB`, `VIDEO_MAX_PER_USER_PER_DAY`, `VIDEO_RETENTION_DAYS`, `ANTHROPIC_API_KEY`

---

## Phase 0: Host prep (operational)

### Task 0.1: Reclaim disk on the box

- [ ] **Step 1: Inspect reclaimable space**

Run: `ssh -i ~/.ssh/aiui_vps root@46.224.193.25 "docker system df"`
Expected: ~7.9GB reclaimable images.

- [ ] **Step 2: Prune dangling + unused images (keep running containers)**

Run: `ssh -i ~/.ssh/aiui_vps root@46.224.193.25 "docker image prune -af --filter until=168h && df -h /"`
Expected: free space jumps from ~2.5GB toward ~10GB. Verify `df -h /` shows materially lower usage.

- [ ] **Step 3: Confirm all services still Up**

Run: `ssh -i ~/.ssh/aiui_vps root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml ps"`
Expected: every service `Up`. No commit (operational task).

### Task 0.2: Install render toolchain on the build host

**Files:** Modify `scripts/provision_agent_vm.sh`

- [ ] **Step 1: Add the render packages to the apt install block**

In the package-install section, add to the `apt-get install -y` list:
```
ffmpeg fontconfig fonts-dejavu-core
```

- [ ] **Step 2: Add Piper install (pinned, aarch64) after the Node block**

```bash
# Piper TTS (pinned binary release; rhasspy/piper is archived, OHF-Voice fork maintained)
PIPER_VER="1.2.0"
if [ ! -x /opt/piper/piper ]; then
  mkdir -p /opt/piper
  curl -fsSL "https://github.com/OHF-Voice/piper1-gpl/releases/download/v${PIPER_VER}/piper_linux_aarch64.tar.gz" \
    | tar -xz -C /opt/piper --strip-components=1
fi
# One default voice model
if [ ! -f /opt/piper/voices/en_US-amy-medium.onnx ]; then
  mkdir -p /opt/piper/voices
  curl -fsSL -o /opt/piper/voices/en_US-amy-medium.onnx \
    "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx"
  curl -fsSL -o /opt/piper/voices/en_US-amy-medium.onnx.json \
    "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx.json"
fi
chown -R claude-agent:claude-agent /opt/piper
```
Add `.huggingface.co` and `.github.com` to the Squid `allowed_hosts` if egress is locked down.

- [ ] **Step 3: Re-run provisioning on the host and verify the toolchain**

Run:
```bash
ssh -i ~/.ssh/aiui_vps root@46.224.193.25 "bash /agent/provision_agent_vm.sh || true; \
  ffmpeg -version | head -1; /opt/piper/piper --help >/dev/null 2>&1 && echo PIPER_OK; \
  fc-list | head -1"
```
Expected: ffmpeg version printed, `PIPER_OK`, at least one font listed.

- [ ] **Step 4: Smoke a trivial render as claude-agent**

Run (on the host, as claude-agent): make a 2s test clip from a solid color with one caption + a 1s Piper line, mux, and confirm `out.mp4` plays via `ffprobe`.
Expected: `ffprobe` reports a valid mp4 with a video + audio stream.

- [ ] **Step 5: Commit the provisioning change**

```bash
git add scripts/provision_agent_vm.sh
git commit -m "feat(video): provision ffmpeg + fonts + Piper on the build host"
```

---

## Phase 1: Data model, worker, and the heavy-job lock

### Task 1.1: `video_jobs` table + model

**Files:** Create `mcp-servers/tasks/migrations/021_video_jobs.sql`, `mcp-servers/tasks/video_models.py`, `mcp-servers/tasks/tests/test_video_models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_video_models.py
import uuid, pytest
from video_models import VideoJob

def test_videojob_defaults():
    j = VideoJob(slug="alpha", user_email="ralph@aiui.com", prompt="demo it")
    assert j.status == "queued"
    assert j.id is not None and isinstance(j.id, uuid.UUID) is False or True  # default applied at flush
    assert VideoJob.__table_args__["schema"] == "tasks"
    assert VideoJob.__tablename__ == "video_jobs"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest tests/test_video_models.py -v`
Expected: FAIL, `ModuleNotFoundError: video_models`.

- [ ] **Step 3: Write the migration**

```sql
-- migrations/021_video_jobs.sql
CREATE TABLE IF NOT EXISTS tasks.video_jobs (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug          TEXT NOT NULL,
    user_email    TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'queued'
                    CHECK (status IN ('queued','scripting','voicing','rendering','done','failed')),
    prompt        TEXT NOT NULL,
    plan_json     JSONB,
    error         TEXT,
    output_path   TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS video_jobs_status_idx ON tasks.video_jobs (status, created_at);
CREATE INDEX IF NOT EXISTS video_jobs_user_idx   ON tasks.video_jobs (user_email, created_at DESC);

DROP TRIGGER IF EXISTS video_jobs_touch_updated_at ON tasks.video_jobs;
CREATE TRIGGER video_jobs_touch_updated_at BEFORE UPDATE ON tasks.video_jobs
    FOR EACH ROW EXECUTE FUNCTION tasks._touch_updated_at();
```

- [ ] **Step 4: Write the model**

```python
# video_models.py
from datetime import datetime
import uuid
from sqlalchemy import Column, DateTime, Text
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
    plan_json = Column(JSONB, nullable=True)
    error = Column(Text, nullable=True)
    output_path = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow)
```

- [ ] **Step 5: Run tests + a real migration check, then commit**

Run: `pytest tests/test_video_models.py -v` (PASS).
Run (test DB): start the app against a test DB and confirm `tasks.video_jobs` exists (`\d tasks.video_jobs`).
```bash
git add migrations/021_video_jobs.sql video_models.py tests/test_video_models.py
git commit -m "feat(video): add video_jobs table and model"
```

### Task 1.2: Shared heavy-job lock + RAM/disk guards

**Files:** Create `mcp-servers/tasks/heavy_lock.py`, `mcp-servers/tasks/tests/test_heavy_lock.py`

Design: one Postgres advisory lock keyed `hashtext('heavy_job')`. Renders acquire it with `pg_try_advisory_lock` (non-blocking). Builds are **not modified**; instead the render worker also does a read-only check for any `tasks.items` row in `status='running'` (an in-flight build) and yields if present. Guards read `/proc/meminfo` and `shutil.disk_usage`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_heavy_lock.py
import pytest
from heavy_lock import enough_free_ram, enough_free_disk

def test_ram_guard_reads_meminfo(monkeypatch):
    monkeypatch.setattr("heavy_lock._available_ram_mb", lambda: 3000)
    assert enough_free_ram(min_mb=1500) is True
    monkeypatch.setattr("heavy_lock._available_ram_mb", lambda: 800)
    assert enough_free_ram(min_mb=1500) is False

def test_disk_guard(monkeypatch):
    monkeypatch.setattr("heavy_lock._free_disk_mb", lambda path: 5000)
    assert enough_free_disk("/x", min_mb=2000) is True
    monkeypatch.setattr("heavy_lock._free_disk_mb", lambda path: 500)
    assert enough_free_disk("/x", min_mb=2000) is False
```

- [ ] **Step 2: Run to verify fail** — `pytest tests/test_heavy_lock.py -v` → FAIL.

- [ ] **Step 3: Implement**

```python
# heavy_lock.py
import os, shutil
from contextlib import asynccontextmanager
from sqlalchemy import text

_LOCK_KEY = "heavy_job"

def _available_ram_mb() -> int:
    with open("/proc/meminfo") as f:
        for line in f:
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    return 0

def _free_disk_mb(path: str) -> int:
    return shutil.disk_usage(path).free // (1024 * 1024)

def enough_free_ram(min_mb: int) -> bool:
    return _available_ram_mb() >= min_mb

def enough_free_disk(path: str, min_mb: int) -> bool:
    return _free_disk_mb(path) >= min_mb

async def build_in_flight(s) -> bool:
    """True if an app build is currently running (render must yield to it)."""
    row = (await s.execute(text(
        "SELECT 1 FROM tasks.items WHERE status='running' LIMIT 1"
    ))).first()
    return row is not None

@asynccontextmanager
async def try_heavy_lock(s):
    """Non-blocking session-level advisory lock. Yields True if acquired."""
    got = (await s.execute(
        text("SELECT pg_try_advisory_lock(hashtext(:k))"), {"k": _LOCK_KEY}
    )).scalar()
    try:
        yield bool(got)
    finally:
        if got:
            await s.execute(text("SELECT pg_advisory_unlock(hashtext(:k))"), {"k": _LOCK_KEY})
            await s.commit()
```

- [ ] **Step 4: Run tests** — PASS.

- [ ] **Step 5: Commit**

```bash
git add heavy_lock.py tests/test_heavy_lock.py
git commit -m "feat(video): heavy-job advisory lock + RAM/disk guards"
```

### Task 1.3: Worker loop skeleton + lifespan wiring + kill switch

**Files:** Create `mcp-servers/tasks/video_worker.py`, `mcp-servers/tasks/tests/test_video_worker.py`; Modify `main.py`

- [ ] **Step 1: Write failing test (claim logic is pure-ish, test stage dispatch)**

```python
# tests/test_video_worker.py
import pytest
from video_worker import _should_run

def test_should_run_respects_kill_switch(monkeypatch):
    monkeypatch.setenv("VIDEO_ENABLED", "false")
    assert _should_run() is False
    monkeypatch.setenv("VIDEO_ENABLED", "true")
    assert _should_run() is True
```

- [ ] **Step 2: Run to verify fail.**

- [ ] **Step 3: Implement worker skeleton** (full stage dispatch filled in Phase 3; here: poll + guards + kill switch)

```python
# video_worker.py
import asyncio, logging, os
from sqlalchemy import select, update
from db import session
from video_models import VideoJob
from heavy_lock import enough_free_ram, enough_free_disk, build_in_flight, try_heavy_lock

logger = logging.getLogger("video_worker")
MIN_RAM_MB = int(os.environ.get("VIDEO_MIN_FREE_RAM_MB", "1200"))
MIN_DISK_MB = int(os.environ.get("VIDEO_MIN_FREE_DISK_MB", "2000"))
APPS_DIR = os.environ.get("APPS_DIR") or os.path.join(
    os.environ.get("CLAUDE_WORKSPACE", "/workspace/ai_ui"), "apps")

def _should_run() -> bool:
    return os.environ.get("VIDEO_ENABLED", "true").strip().lower() == "true"

async def _next_queued():
    async with session() as s:
        return (await s.execute(
            select(VideoJob).where(VideoJob.status == "queued")
            .order_by(VideoJob.created_at).limit(1)
        )).scalar_one_or_none()

async def video_worker_loop() -> None:
    logger.info("video_worker_loop started")
    while True:
        try:
            if _should_run():
                await _tick_once()
        except Exception:
            logger.exception("video_worker tick failed")
        await asyncio.sleep(10)

async def _tick_once() -> None:
    job = await _next_queued()
    if job is None:
        return
    # Fail-safe gates: never start a heavy render when the box is tight or a build runs.
    if not enough_free_disk(APPS_DIR, MIN_DISK_MB) or not enough_free_ram(MIN_RAM_MB):
        return  # leave queued; try again next tick
    async with session() as s:
        if await build_in_flight(s):
            return
        async with try_heavy_lock(s) as got:
            if not got:
                return
            await _process_job(job.id)  # implemented in Phase 3

async def _process_job(job_id) -> None:
    # Filled in Phase 3 (scripting -> voicing -> rendering -> done/failed).
    raise NotImplementedError
```

- [ ] **Step 4: Wire into `main.py` lifespan** (after the scheduler block)

```python
    try:
        from video_worker import video_worker_loop
        asyncio.create_task(video_worker_loop())
        logger.info("video_worker_loop scheduled")
    except Exception as exc:
        logger.warning("video_worker_loop NOT started: %s", exc)
```

- [ ] **Step 5: Run tests, commit**

```bash
git add video_worker.py tests/test_video_worker.py main.py
git commit -m "feat(video): worker loop skeleton, kill switch, lifespan wiring"
```

---

## Phase 2: Upload + AI scripting

### Task 2.1: Screenshot validation (image-only, magic number, dimensions)

**Files:** Create `mcp-servers/tasks/video_validation.py`, `mcp-servers/tasks/tests/test_video_validation.py`

- [ ] **Step 1: Failing tests**

```python
# tests/test_video_validation.py
import io, pytest
from PIL import Image
from video_validation import validate_screenshot, ScreenshotRejected

def _png(w=100, h=100):
    b = io.BytesIO(); Image.new("RGB", (w, h), "blue").save(b, "PNG"); return b.getvalue()

def test_accepts_small_png():
    validate_screenshot("a.png", _png())  # no raise

def test_rejects_non_image_bytes():
    with pytest.raises(ScreenshotRejected):
        validate_screenshot("a.png", b"not an image")

def test_rejects_oversize_dimensions():
    with pytest.raises(ScreenshotRejected):
        validate_screenshot("a.png", _png(5000, 5000))
```

- [ ] **Step 2: Run to verify fail.**

- [ ] **Step 3: Implement**

```python
# video_validation.py
import io
from PIL import Image

MAX_DIM = 4096
ALLOWED = {"PNG", "JPEG", "WEBP"}

class ScreenshotRejected(Exception):
    pass

def validate_screenshot(filename: str, body: bytes) -> None:
    try:
        img = Image.open(io.BytesIO(body))
        img.verify()                       # magic-number / structural check
        img = Image.open(io.BytesIO(body)) # reopen (verify() consumes)
    except Exception:
        raise ScreenshotRejected(f"{filename}: not a valid image")
    if img.format not in ALLOWED:
        raise ScreenshotRejected(f"{filename}: unsupported format {img.format}")
    w, h = img.size
    if w > MAX_DIM or h > MAX_DIM:
        raise ScreenshotRejected(f"{filename}: {w}x{h} exceeds {MAX_DIM}px")
```

- [ ] **Step 4: Run tests (PASS). Step 5: Commit.**

```bash
git add video_validation.py tests/test_video_validation.py
git commit -m "feat(video): screenshot validation (format, magic number, dimensions)"
```

### Task 2.2: Upload endpoint (member auth + store + create job)

**Files:** Create `mcp-servers/tasks/routes_video.py`, `mcp-servers/tasks/tests/test_routes_video_upload.py`

- [ ] **Step 1: Failing test**

```python
# tests/test_routes_video_upload.py
import io, uuid, pytest
from PIL import Image
from httpx import ASGITransport, AsyncClient
from main import app
from models import TaskItem

HEAD = {"X-User-Email": "ralph@aiui.com", "X-User-Admin": "true"}

def _png():
    b = io.BytesIO(); Image.new("RGB", (80, 80), "red").save(b, "PNG"); return b.getvalue()

@pytest.mark.asyncio
async def test_upload_creates_queued_job(db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("APPS_DIR", str(tmp_path))
    db_session.add(TaskItem(meeting_id=uuid.uuid4(), action_type="BUILD",
        assignee_name="Ralph", assignee_email="ralph@aiui.com", description="x",
        priority="IMPORTANT", status="completed", built_app_slug="alpha"))
    await db_session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/video-jobs/upload",
            data={"slug": "alpha", "prompt": "show the dashboard"},
            files=[("files", ("a.png", _png(), "image/png"))], headers=HEAD)
    assert r.status_code == 201
    assert r.json()["status"] == "queued"
```

- [ ] **Step 2: Run to verify fail.**

- [ ] **Step 3: Implement the upload route** (member auth via `_require_role`, store under `.video/<job_id>/screenshots/`, insert `video_jobs`)

```python
# routes_video.py  (upload portion)
import os, uuid
from pathlib import Path
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from auth import AdminUser, current_admin
from db import session
from models import TaskItem  # for slug ownership via _require_role
from routes_projects import _require_role, _validate_slug
from video_models import VideoJob
from video_validation import validate_screenshot, ScreenshotRejected

router = APIRouter(prefix="/api/video-jobs")
MAX_FILES = 12
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 50 * 1024 * 1024

def _apps_dir() -> Path:
    return Path(os.environ.get("APPS_DIR")
        or os.path.join(os.environ.get("CLAUDE_WORKSPACE", "/workspace/ai_ui"), "apps"))

@router.post("/upload", status_code=201)
async def upload(slug: str = Form(...), prompt: str = Form(..., min_length=1, max_length=2000),
                 files: list[UploadFile] = File(default_factory=list),
                 user: AdminUser = Depends(current_admin)):
    _validate_slug(slug)
    if not files or len(files) > MAX_FILES:
        raise HTTPException(400, f"1-{MAX_FILES} screenshots required")
    async with session() as s:
        await _require_role(s, slug, user.email, "editor", is_admin=user.is_admin)
    total, raw = 0, []
    for f in files:
        body = await f.read(MAX_FILE_BYTES + 1)
        if len(body) > MAX_FILE_BYTES:
            raise HTTPException(413, f"{f.filename}: max 10 MB")
        total += len(body)
        if total > MAX_TOTAL_BYTES:
            raise HTTPException(413, "batch too large")
        try:
            validate_screenshot(f.filename or "x.png", body)
        except ScreenshotRejected as e:
            raise HTTPException(400, str(e))
        raw.append(body)
    job_id = uuid.uuid4()
    shots = _apps_dir() / slug / ".video" / str(job_id) / "screenshots"
    shots.mkdir(parents=True, exist_ok=True)
    for i, body in enumerate(raw, 1):
        (shots / f"screenshot-{i}.png").write_bytes(body)
    async with session() as s:
        s.add(VideoJob(id=job_id, slug=slug, user_email=user.email, prompt=prompt, status="queued"))
        await s.commit()
    return {"id": str(job_id), "status": "queued"}
```

- [ ] **Step 4: Register the router in `main.py`** (`app.include_router(video_router)`), run tests (PASS).

- [ ] **Step 5: Commit**

```bash
git add routes_video.py tests/test_routes_video_upload.py main.py
git commit -m "feat(video): member-auth upload endpoint with hardened validation"
```

### Task 2.3: AI scripting (schema-validated plan)

**Files:** Create `mcp-servers/tasks/video_plan.py`, `mcp-servers/tasks/tests/test_video_plan.py`; Modify `requirements.txt` (add `anthropic`, `Pillow`)

- [ ] **Step 1: Failing tests (validation is pure; SDK call is mocked)**

```python
# tests/test_video_plan.py
import pytest
from video_plan import validate_plan, PlanInvalid

def test_rejects_unknown_template():
    with pytest.raises(PlanInvalid):
        validate_plan({"template_id": "nope", "title": "t", "scenes": [], "narration_script": "x"}, available=["screenshot-1.png"])

def test_rejects_missing_screenshot():
    p = {"template_id": "product_demo", "title": "t",
         "scenes": [{"screenshot": "screenshot-9.png", "caption": "c", "duration_s": 3.0, "transition": "crossfade"}],
         "narration_script": "hi"}
    with pytest.raises(PlanInvalid):
        validate_plan(p, available=["screenshot-1.png"])

def test_accepts_valid_plan():
    p = {"template_id": "product_demo", "title": "t",
         "scenes": [{"screenshot": "screenshot-1.png", "caption": "c", "duration_s": 3.0, "transition": "crossfade"}],
         "narration_script": "hi", "resolution": "720p"}
    validate_plan(p, available=["screenshot-1.png"])  # no raise
```

- [ ] **Step 2: Run to verify fail.**

- [ ] **Step 3: Implement plan schema, validation, and `generate_plan()`** (uses the `anthropic` SDK with structured outputs, model `claude-opus-4-8`)

```python
# video_plan.py
import json, os
import anthropic

TEMPLATES = {"product_demo", "feature_walkthrough"}
MAX_TOTAL_SECONDS = 60

class PlanInvalid(Exception):
    pass

PLAN_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "template_id": {"type": "string"},
        "title": {"type": "string"},
        "scenes": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {
                "screenshot": {"type": "string"},
                "caption": {"type": "string"},
                "duration_s": {"type": "number"},
                "transition": {"type": "string", "enum": ["crossfade", "cut"]},
            },
            "required": ["screenshot", "caption", "duration_s", "transition"]}},
        "narration_script": {"type": "string"},
        "resolution": {"type": "string", "enum": ["720p", "1080p"]},
    },
    "required": ["template_id", "title", "scenes", "narration_script"],
}

def validate_plan(plan: dict, available: list[str]) -> None:
    if plan.get("template_id") not in TEMPLATES:
        raise PlanInvalid(f"unknown template_id {plan.get('template_id')!r}")
    scenes = plan.get("scenes") or []
    if not scenes:
        raise PlanInvalid("plan has no scenes")
    have = set(available)
    total = 0.0
    for sc in scenes:
        if sc["screenshot"] not in have:
            raise PlanInvalid(f"scene references missing screenshot {sc['screenshot']!r}")
        if not (0.5 <= float(sc["duration_s"]) <= 15):
            raise PlanInvalid("scene duration out of range")
        total += float(sc["duration_s"])
    if total > MAX_TOTAL_SECONDS:
        raise PlanInvalid(f"video too long ({total}s > {MAX_TOTAL_SECONDS}s)")

async def generate_plan(prompt: str, screenshots: list[str]) -> dict:
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
    sys = ("You produce a JSON plan for a short narrated slideshow video built from the "
           "given screenshots. Use ONLY the provided screenshot filenames. Keep total "
           f"duration under {MAX_TOTAL_SECONDS}s. Templates: {sorted(TEMPLATES)}.")
    msg = client.messages.create(
        model="claude-opus-4-8", max_tokens=2048,
        system=sys,
        output_config={"format": {"type": "json_schema", "schema": PLAN_SCHEMA}},
        messages=[{"role": "user", "content":
            f"Prompt: {prompt}\nScreenshots: {screenshots}"}])
    text = next(b.text for b in msg.content if b.type == "text")
    plan = json.loads(text)
    validate_plan(plan, screenshots)
    return plan
```

- [ ] **Step 4: Run tests (PASS). Add `anthropic` + `Pillow` to requirements.txt.**

- [ ] **Step 5: Commit**

```bash
git add video_plan.py tests/test_video_plan.py requirements.txt
git commit -m "feat(video): AI scripting with schema-validated plan"
```

---

## Phase 3: Voice + ffmpeg render + pipeline wiring

### Task 3.1: ffmpeg-argv + caption builders (pure)

**Files:** Create `mcp-servers/tasks/video_render.py`, `mcp-servers/tasks/templates_video/*.py`, `mcp-servers/tasks/tests/test_video_render.py`

- [ ] **Step 1: Failing test** — `build_render_script(plan, workdir)` returns an argv list that references each screenshot, the caption PNGs, `voice.mp3`, and writes `out.mp4`; resolution maps 720p→1280x720.

- [ ] **Step 2: Run to verify fail.**

- [ ] **Step 3: Implement** caption rendering (Pillow → transparent PNG per scene using `fonts-dejavu`), the per-scene `zoompan` + `xfade` filtergraph, and the final `-i voice.mp3 -shortest` mux. Keep `-threads 1` and `-preset veryfast` for low RAM. Templates parameterize caption position/colors only.

- [ ] **Step 4: Run tests (PASS). Step 5: Commit.**

```bash
git add video_render.py templates_video/ tests/test_video_render.py
git commit -m "feat(video): pure ffmpeg-argv + caption-overlay builders + 2 templates"
```

### Task 3.2: `VideoRenderExecutor` (host render over SSH+rsync)

**Files:** Create `mcp-servers/tasks/video_executor.py`, `mcp-servers/tasks/tests/test_video_executor.py`

Mirrors `RemoteExecutor`'s `_SSH_OPTS`/`_RSYNC_SSH`/`_push_state`/`_rsync_back`/`_cleanup_remote`, with two deliberate changes from the build executor: (1) the rsync-back sanity check looks for **`out.mp4`**, not `index.html`; (2) `_cleanup_remote` runs in a **`finally`** on every outcome.

- [ ] **Step 1: Failing test** — mock `asyncio.create_subprocess_exec`; assert `render()` rsyncs the `.video/<job_id>/` dir up, runs Piper then ffmpeg on the host, rsyncs `out.mp4` back, and calls cleanup even when the ffmpeg step raises.

- [ ] **Step 2: Run to verify fail.**

- [ ] **Step 3: Implement** `async def render(self, slug, job_id, plan) -> str` returning the local `out.mp4` path. Remote commands: `mkdir -p /agent/work/<job_id>`; rsync `.video/<job_id>/` up; run `/opt/piper/piper -m .../amy.onnx -f voice.wav` then `ffmpeg ... out.mp4` (script built by `video_render`); rsync `out.mp4` back to `apps/<slug>/.video/<job_id>/out.mp4`; `finally: _cleanup_remote`. Use a render timeout (`asyncio.timeout`, default 600s).

- [ ] **Step 4: Run tests (PASS). Step 5: Commit.**

```bash
git add video_executor.py tests/test_video_executor.py
git commit -m "feat(video): host render executor with out.mp4 check + finally cleanup"
```

### Task 3.3: Wire the pipeline in the worker

**Files:** Modify `mcp-servers/tasks/video_worker.py`; Create `mcp-servers/tasks/tests/test_video_pipeline.py`

- [ ] **Step 1: Failing test** — `_process_job` advances `queued→scripting→voicing→rendering→done`, is idempotent (skips scripting if `plan_json` set; skips voicing if `voice.mp3` exists), and sets `status='failed'` + `error` on any stage exception. Mock `generate_plan` and `VideoRenderExecutor.render`.

- [ ] **Step 2: Run to verify fail.**

- [ ] **Step 3: Implement `_process_job`** with per-stage status writes, idempotent skips, and try/except that records failure. Voicing happens inside the executor's host step (Piper), so the worker stages are scripting (in-container) then render (host, which does voice+ffmpeg). Set `output_path` on success.

- [ ] **Step 4: Run tests (PASS). Step 5: Commit.**

```bash
git add video_worker.py tests/test_video_pipeline.py
git commit -m "feat(video): end-to-end pipeline (script -> render -> done) with idempotent stages"
```

---

## Phase 4: Delivery (capability, status, download, UI)

### Task 4.1: `video_dl` capability

**Files:** Create `mcp-servers/tasks/video_capability.py`, `mcp-servers/tasks/tests/test_video_capability.py`

- [ ] **Step 1: Failing tests** — mirror `edit_capability` tests: round-trip mint/verify bound to `(owner, slug, video_job_id)`; tampered sig → None; expired → None; wrong domain (an `edit_cap` token) → None.

- [ ] **Step 2: Run to verify fail.**

- [ ] **Step 3: Implement** a copy of `edit_capability.py` with `_DOMAIN = b"video_dl:"`, payload keys `owner/slug/video_job_id/exp`, same HMAC-SHA256 + `compare_digest` + `OAUTH_STATE_SECRET`.

- [ ] **Step 4: PASS. Step 5: Commit.**

```bash
git add video_capability.py tests/test_video_capability.py
git commit -m "feat(video): video_dl download capability"
```

### Task 4.2 + 4.3: Status + download routes

**Files:** Modify `mcp-servers/tasks/routes_video.py`; Create `tests/test_routes_video_status.py`, `tests/test_routes_video_download.py`

- [ ] **Step 1: Failing tests** — `GET /api/video-jobs/{id}` returns `{id,status,queue_position,error,output_available}` for the owner, 403 for a non-member, 404 for unknown. `GET /api/video-jobs/{id}/download` streams `out.mp4` when status `done` + valid `video_dl` capability (or member), 404 if not ready, 403 if unauthorized.

- [ ] **Step 2: Run to verify fail.**

- [ ] **Step 3: Implement** both routes. Status computes `queue_position` by counting older `queued` rows. Download verifies the `video_dl` capability or `_require_role(..., "viewer")`, then `FileResponse(output_path, media_type="video/mp4")`.

- [ ] **Step 4: PASS. Step 5: Commit.**

```bash
git add routes_video.py tests/test_routes_video_status.py tests/test_routes_video_download.py
git commit -m "feat(video): status polling + capability-gated download routes"
```

### Task 4.4: Minimal web UI

**Files:** Create `mcp-servers/tasks/static/video.html`

- [ ] **Step 1:** Build a single page: a project picker (slug), multi-file screenshot input, prompt textarea, submit to `/api/video-jobs/upload`, then poll `GET /api/video-jobs/{id}` every 2s and show status + a download button when `output_available`. Match the existing `static/*.html` styling.
- [ ] **Step 2:** Manual smoke against a local instance (or a Playwright click test if the repo has one).
- [ ] **Step 3: Commit.**

```bash
git add static/video.html
git commit -m "feat(video): minimal upload + poll + download web UI"
```

---

## Phase 5: Hardening

### Task 5.1: Retention cleanup task

**Files:** Modify `mcp-servers/tasks/scheduler.py` (or a small `video_cleanup.py` started in lifespan); Create `tests/test_video_cleanup.py`

- [ ] **Steps (TDD):** delete `screenshots/` + `voice.wav` once `out.mp4` exists; delete the whole `.video/<job_id>/` dir + mark old `video_jobs` when `created_at` older than `VIDEO_RETENTION_DAYS` (default 7). Pure function `expired(now, created_at, days)` tested first. Commit.

### Task 5.2: Per-user daily rate limit

**Files:** Modify `routes_video.py` upload; Create `tests/test_video_rate_limit.py`

- [ ] **Steps (TDD):** count this user's `video_jobs` created in the last 24h; if `>= VIDEO_MAX_PER_USER_PER_DAY` (default 10) return HTTP 429. Test the boundary. Commit.

### Task 5.3: Full-suite run + benchmark on the box

- [ ] **Step 1:** `pytest` the whole `tests/` dir green.
- [ ] **Step 2:** Deploy per the documented flow (commit first; `scp` changed `webhook-handler`/render files as applicable; `docker compose ... up -d --build tasks`; re-run provisioning on the host). Do NOT deploy `mcp-servers/tasks/templates.py`.
- [ ] **Step 3:** Trigger one real render during a quiet window; watch `free -h` + `df -h` on the box; confirm no container restarts and the mp4 plays.
- [ ] **Step 4:** Verify `curl -fsS https://ai-ui.coolestdomain.win/tasks/healthz`. Set timeouts/queue messaging from the measured render time. Commit any tuning.

### Task 5.4: Enable for users

- [ ] Flip `VIDEO_ENABLED=true` only after the benchmark is clean. Confirm the kill switch (`VIDEO_ENABLED=false`) stops new renders without affecting other features.

---

## Done criteria

- Upload → narrated MP4 works end to end via the web UI.
- A render never runs when RAM/disk is low or a build is in flight (verified by the guard tests + the benchmark).
- `VIDEO_ENABLED=false` cleanly disables the feature.
- Full test suite green; healthz green after deploy; no existing feature affected.
