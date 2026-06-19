# Discord Video Generation Channel — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `#video-generation` Discord channel that drives the existing `tasks`-service video pipeline at full parity with the web Video Studio (generate, refine, versions/revert, list), using interactions only (no Gateway/voice dependency).

**Architecture:** A thin URL-based screenshot intake + a `collecting` draft state on the `tasks` backend; everything else (render worker, styles, voices, capability, cleanup) is reused unchanged. The bot creates a per-user private thread ("the studio"), drives a details-first wizard (modal → selects → `/video add` → Generate), and a `_watch_video` poller delivers the finished MP4 (attach, or capability link if too large).

**Tech Stack:** Python 3.11, FastAPI + SQLAlchemy (async) + asyncpg (tasks); httpx + Discord HTTP interactions (webhook-handler); pytest.

**Spec:** `docs/superpowers/specs/2026-06-19-discord-video-channel-design.md`
**Branch:** `feat/discord-video-channel` (off `fork/main`)

**Conventions for every task:** run backend tests from `mcp-servers/tasks/` with `AIUI_TEST_DB=1` and a `DATABASE_URL` containing `test` (see `mcp-servers/tasks/tests/conftest.py`); run bot tests from `webhook-handler/`. Commit after each task. Never touch `.env` or `mcp-servers/tasks/templates.py`.

---

## Phase A — Backend (`mcp-servers/tasks`)

### Task A1: Migration 025 — add the `collecting` draft status

**Files:**
- Create: `mcp-servers/tasks/migrations/025_video_collecting_status.sql`
- Test: `mcp-servers/tasks/tests/test_migration_025_collecting.py`

The `video_jobs.status` CHECK is an unnamed inline constraint from migration 021 (Postgres auto-names it `video_jobs_status_check`). Migrations re-run on every startup (`db.py` `_run_migrations`), so the file must be idempotent. We drop the existing status CHECK by looking it up dynamically (robust to the auto name) and re-add a named one that includes `collecting`.

- [ ] **Step 1: Write the migration**

```sql
-- 025_video_collecting_status.sql
-- Add a 'collecting' draft status to tasks.video_jobs so the Discord video
-- wizard can accumulate title/prompt/style/voice/screenshots before the render
-- worker (which only picks 'queued') sees the job.
-- Idempotent: db.py re-runs every migration on each startup. We drop whatever
-- CHECK currently governs `status` (the unnamed 021 one OR our re-added named
-- one) and re-add the named superset, so repeated runs converge.
DO $$
DECLARE cname text;
BEGIN
    SELECT conname INTO cname
      FROM pg_constraint
     WHERE conrelid = 'tasks.video_jobs'::regclass
       AND contype = 'c'
       AND pg_get_constraintdef(oid) LIKE '%status%';
    IF cname IS NOT NULL THEN
        EXECUTE format('ALTER TABLE tasks.video_jobs DROP CONSTRAINT %I', cname);
    END IF;
    ALTER TABLE tasks.video_jobs
        ADD CONSTRAINT video_jobs_status_check
        CHECK (status IN ('queued','collecting','scripting','voicing','rendering','done','failed'));
END $$;
```

- [ ] **Step 2: Write the failing test**

```python
# mcp-servers/tasks/tests/test_migration_025_collecting.py
"""025 lets a video_jobs row hold status='collecting' (draft) and the file exists."""
import pathlib
import uuid

import pytest
from sqlalchemy import select

from db import session
from video_models import VideoJob

MIG = pathlib.Path(__file__).resolve().parents[1] / "migrations" / "025_video_collecting_status.sql"


def test_migration_file_includes_collecting():
    text = MIG.read_text(encoding="utf-8")
    assert "collecting" in text
    assert "video_jobs_status_check" in text


@pytest.mark.asyncio
async def test_can_insert_collecting_row():
    jid = uuid.uuid4()
    async with session() as s:
        s.add(VideoJob(id=jid, slug=f"vid-{jid.hex[:8]}", user_email="a@b.co",
                       prompt="p", title="t", style="clean_product_demo",
                       voice="amy", status="collecting"))
        await s.commit()
    async with session() as s:
        row = await s.get(VideoJob, jid)
        assert row is not None and row.status == "collecting"
```

- [ ] **Step 3: Run it to verify it passes** (migrations auto-apply when the test DB session initializes)

Run: `AIUI_TEST_DB=1 DATABASE_URL="postgresql+asyncpg://.../aiui_test" python -m pytest tests/test_migration_025_collecting.py -v`
Expected: PASS. If the insert raises a CheckViolation, the migration didn't apply — confirm `025_*.sql` sorts after `024` and the DO block ran.

- [ ] **Step 4: Commit**

```bash
git add mcp-servers/tasks/migrations/025_video_collecting_status.sql mcp-servers/tasks/tests/test_migration_025_collecting.py
git commit -m "feat(video): migration 025 — add 'collecting' draft status"
```

---

### Task A2: `POST /api/video-jobs/draft` + `GET /api/video-jobs/current-draft`

**Files:**
- Modify: `mcp-servers/tasks/routes_video.py` (add imports + two handlers; place the literal-path routes BEFORE the `/{job_id}` route at line ~247)
- Test: `mcp-servers/tasks/tests/test_routes_video_draft.py`

- [ ] **Step 1: Add imports** at the top of `routes_video.py` (extend existing import lines)

```python
# add to the existing "from video_capability import ..." line:
from video_capability import mint_video_capability, verify_video_capability
```

- [ ] **Step 2: Add the request model + handlers** (insert just after the `RevertRequest` model at line ~113, and register the GET route near `/voices` so it is matched before `/{job_id}`)

```python
class DraftRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    prompt: str = Field(..., min_length=1, max_length=2000)
    style: str = Field("clean_product_demo", max_length=50)
    voice: str = Field(DEFAULT_VOICE_ID, max_length=50)


@router.post("/draft", status_code=201)
async def create_draft(
    body: DraftRequest, user: CurrentUser = Depends(current_user)
) -> dict:
    """Create a 'collecting' draft video job (no screenshots yet) for the Discord
    wizard. The render worker only picks 'queued' jobs, so a draft is inert until
    POST /{job_id}/queue flips it. Daily limit is NOT charged here (only at queue)
    so abandoned drafts don't count."""
    if not _video_enabled():
        raise HTTPException(503, "Video generation is disabled")
    if body.style not in STYLE_CONFIGS:
        raise HTTPException(400, f"Unknown style: {body.style}")
    if not is_valid_voice(body.voice):
        raise HTTPException(400, f"Unknown voice: {body.voice}")
    job_id = uuid.uuid4()
    slug = f"vid-{job_id.hex[:8]}"
    async with session() as s:
        s.add(
            VideoJob(
                id=job_id, slug=slug, user_email=user.email,
                prompt=body.prompt, title=body.title, style=body.style,
                voice=body.voice, status="collecting",
            )
        )
        await s.commit()
    return {"id": str(job_id), "slug": slug, "status": "collecting"}
```

```python
# Registered BEFORE "/{job_id}" so the literal "current-draft" path is not
# captured as a job id (same rule as /voices).
@router.get("/current-draft")
async def current_draft(user: CurrentUser = Depends(current_user)) -> dict:
    """The caller's newest in-progress draft ('collecting'), with how many
    screenshots it has so far. 404 when there is no draft. Used by `/video add`
    to find which draft to attach screenshots to."""
    async with session() as s:
        job = (await s.execute(
            select(VideoJob)
            .where(and_(VideoJob.user_email == user.email,
                        VideoJob.status == "collecting"))
            .order_by(VideoJob.created_at.desc())
        )).scalars().first()
    if job is None:
        raise HTTPException(404, "No draft in progress")
    return {
        "id": str(job.id), "slug": job.slug, "title": job.title,
        "style": job.style, "voice": job.voice,
        "screenshot_count": len(_list_screenshots(job.slug, str(job.id))),
    }
```

- [ ] **Step 3: Write the failing tests**

```python
# mcp-servers/tasks/tests/test_routes_video_draft.py
import pytest
from httpx import ASGITransport, AsyncClient

from main import app

H = {"X-User-Email": "drafter@aiui.test"}


@pytest.mark.asyncio
async def test_create_draft_then_current_draft():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post("/api/video-jobs/draft", headers=H, json={
            "title": "Dashboard tour", "prompt": "walk the dashboard",
            "style": "clean_product_demo", "voice": "amy"})
        assert r.status_code == 201, r.text
        jid = r.json()["id"]
        assert r.json()["status"] == "collecting"

        r2 = await c.get("/api/video-jobs/current-draft", headers=H)
        assert r2.status_code == 200
        assert r2.json()["id"] == jid
        assert r2.json()["screenshot_count"] == 0


@pytest.mark.asyncio
async def test_create_draft_rejects_unknown_style_voice():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post("/api/video-jobs/draft", headers=H, json={
            "title": "x", "prompt": "y", "style": "bogus", "voice": "amy"})
        assert r.status_code == 400
        r = await c.post("/api/video-jobs/draft", headers=H, json={
            "title": "x", "prompt": "y", "style": "clean_product_demo", "voice": "bogus"})
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_current_draft_404_when_none():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/api/video-jobs/current-draft",
                        headers={"X-User-Email": "nobody@aiui.test"})
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_draft_requires_auth():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post("/api/video-jobs/draft", json={
            "title": "x", "prompt": "y"})
        assert r.status_code == 401
```

- [ ] **Step 4: Run** `AIUI_TEST_DB=1 DATABASE_URL=... python -m pytest tests/test_routes_video_draft.py -v` → all PASS.

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/routes_video.py mcp-servers/tasks/tests/test_routes_video_draft.py
git commit -m "feat(video): draft + current-draft endpoints for the Discord wizard"
```

---

### Task A3: `POST /api/video-jobs/{job_id}/screenshots-by-url` (URL intake + SSRF allow-list)

**Files:**
- Modify: `mcp-servers/tasks/routes_video.py` (module-level allow-list + handler)
- Test: `mcp-servers/tasks/tests/test_routes_video_screenshots_by_url.py`

- [ ] **Step 1: Add `httpx` + urlparse imports and the allow-list constant** near the other constants (line ~50)

```python
# add near the top imports:
import httpx
from urllib.parse import urlparse

# add near MAX_TOTAL_BYTES:
ALLOWED_URL_HOSTS = {
    h.strip().lower()
    for h in os.environ.get(
        "VIDEO_URL_INTAKE_ALLOWED_HOSTS",
        "cdn.discordapp.com,media.discordapp.net",
    ).split(",")
    if h.strip()
}
```

- [ ] **Step 2: Add the handler** (place beside `/screenshots`, after the `add_screenshots` handler at line ~546)

```python
class ScreenshotUrlsRequest(BaseModel):
    urls: list[str] = Field(..., min_length=1, max_length=MAX_FILES)


def _check_intake_url(u: str) -> None:
    """SSRF guard: only https URLs on the Discord CDN allow-list may be fetched.
    Fails closed (400) for any other scheme or host."""
    p = urlparse(u)
    if p.scheme != "https" or (p.hostname or "").lower() not in ALLOWED_URL_HOSTS:
        raise HTTPException(400, "screenshot URL host not allowed")


@router.post("/{job_id}/screenshots-by-url")
async def add_screenshots_by_url(
    job_id: str,
    body: ScreenshotUrlsRequest,
    user: CurrentUser = Depends(current_user),
) -> dict:
    """Add screenshots to a job by fetching image URLs server-side (the bot can't
    relay multipart bytes; it has Discord CDN URLs). Mirrors /screenshots: same
    count/size/validation/disk guards, same screenshot-N numbering. SSRF guard
    restricts fetches to the Discord CDN allow-list."""
    if not _video_enabled():
        raise HTTPException(503, "Video generation is disabled")
    jid = _coerce_job_id(job_id)
    async with session() as s:
        job = (await s.execute(
            select(VideoJob).where(VideoJob.id == jid)
        )).scalar_one_or_none()
        if job is None:
            raise HTTPException(404, "Video job not found")
        if not user.is_admin and job.user_email != user.email:
            raise HTTPException(403, "Not authorized for this video")
        slug = job.slug
    if not enough_free_disk(
        str(_apps_dir()), int(os.environ.get("VIDEO_MIN_FREE_DISK_MB", "2000"))
    ):
        raise HTTPException(507, "Insufficient storage; try again later")
    shots_dir = _apps_dir() / slug / ".video" / str(jid) / "screenshots"
    existing = _list_screenshots(slug, str(jid))
    start = _next_screenshot_index(existing)
    if len(existing) + len(body.urls) > MAX_FILES:
        raise HTTPException(400, f"max {MAX_FILES} screenshots per job")
    total = sum(
        (shots_dir / name).stat().st_size
        for name in existing
        if (shots_dir / name).is_file()
    )
    raw: list[bytes] = []
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
        for url in body.urls:
            _check_intake_url(url)
            try:
                resp = await client.get(url)
                resp.raise_for_status()
            except httpx.HTTPError:
                raise HTTPException(400, "could not fetch screenshot URL")
            data = resp.content
            if len(data) > MAX_FILE_BYTES:
                raise HTTPException(413, "screenshot too large (max 10 MB)")
            total += len(data)
            if total > MAX_TOTAL_BYTES:
                raise HTTPException(413, "batch too large")
            try:
                validate_screenshot(url.rsplit("/", 1)[-1] or "x.png", data)
            except ScreenshotRejected as e:
                raise HTTPException(400, str(e))
            raw.append(data)
    shots_dir.mkdir(parents=True, exist_ok=True)
    for i, data in enumerate(raw):
        (shots_dir / f"screenshot-{start + i}.png").write_bytes(data)
    shots = _list_screenshots(slug, str(jid))
    return {"screenshots": shots, "count": len(shots)}
```

- [ ] **Step 3: Write the failing tests** (mock the network with `monkeypatch` on `httpx.AsyncClient.get`; a 1×1 PNG is the fixture)

```python
# mcp-servers/tasks/tests/test_routes_video_screenshots_by_url.py
import io
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image

import routes_video
from db import session
from main import app
from video_models import VideoJob

H = {"X-User-Email": "shots@aiui.test"}


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(buf, format="PNG")
    return buf.getvalue()


async def _make_draft() -> str:
    jid = uuid.uuid4()
    async with session() as s:
        s.add(VideoJob(id=jid, slug=f"vid-{jid.hex[:8]}", user_email=H["X-User-Email"],
                       prompt="p", title="t", style="clean_product_demo",
                       voice="amy", status="collecting"))
        await s.commit()
    return str(jid)


class _FakeResp:
    def __init__(self, content): self.content = content
    def raise_for_status(self): pass


@pytest.mark.asyncio
async def test_adds_screenshots_from_discord_cdn(monkeypatch):
    jid = await _make_draft()
    png = _png_bytes()

    async def fake_get(self, url, *a, **k):
        return _FakeResp(png)
    monkeypatch.setattr("httpx.AsyncClient.get", fake_get)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post(f"/api/video-jobs/{jid}/screenshots-by-url", headers=H, json={
            "urls": ["https://cdn.discordapp.com/a/1.png",
                     "https://media.discordapp.net/a/2.png"]})
        assert r.status_code == 200, r.text
        assert r.json()["count"] == 2


@pytest.mark.asyncio
async def test_rejects_non_allowlisted_host(monkeypatch):
    jid = await _make_draft()

    async def fake_get(self, url, *a, **k):  # must never be called
        raise AssertionError("SSRF guard should reject before fetch")
    monkeypatch.setattr("httpx.AsyncClient.get", fake_get)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post(f"/api/video-jobs/{jid}/screenshots-by-url", headers=H,
                         json={"urls": ["https://evil.example.com/x.png"]})
        assert r.status_code == 400
        r = await c.post(f"/api/video-jobs/{jid}/screenshots-by-url", headers=H,
                         json={"urls": ["http://cdn.discordapp.com/x.png"]})  # not https
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_count_cap(monkeypatch):
    jid = await _make_draft()
    monkeypatch.setattr("httpx.AsyncClient.get",
                        lambda self, url, *a, **k: _FakeResp(_png_bytes()))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post(f"/api/video-jobs/{jid}/screenshots-by-url", headers=H,
                         json={"urls": [f"https://cdn.discordapp.com/{i}.png"
                                        for i in range(routes_video.MAX_FILES + 1)]})
        assert r.status_code == 400
```

Note: `httpx.AsyncClient.get` is async; in `test_count_cap` use an async lambda — replace with:
```python
        async def _g(self, url, *a, **k): return _FakeResp(_png_bytes())
        monkeypatch.setattr("httpx.AsyncClient.get", _g)
```

- [ ] **Step 4: Run** `... python -m pytest tests/test_routes_video_screenshots_by_url.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/routes_video.py mcp-servers/tasks/tests/test_routes_video_screenshots_by_url.py
git commit -m "feat(video): URL-based screenshot intake with SSRF allow-list"
```

---

### Task A4: `POST /api/video-jobs/{job_id}/queue`

**Files:**
- Modify: `mcp-servers/tasks/routes_video.py`
- Test: `mcp-servers/tasks/tests/test_routes_video_queue.py`

- [ ] **Step 1: Add the handler** (after `add_screenshots_by_url`)

```python
@router.post("/{job_id}/queue")
async def queue_job(
    job_id: str, user: CurrentUser = Depends(current_user)
) -> dict:
    """Commit a draft to rendering: 'collecting' -> 'queued'. Validates the draft
    has >=1 screenshot and enforces the per-user daily limit HERE (counting only
    jobs that actually rendered/queued, so abandoned drafts are free)."""
    if not _video_enabled():
        raise HTTPException(503, "Video generation is disabled")
    jid = _coerce_job_id(job_id)
    async with session() as s:
        job = (await s.execute(
            select(VideoJob).where(VideoJob.id == jid)
        )).scalar_one_or_none()
        if job is None:
            raise HTTPException(404, "Video job not found")
        if not user.is_admin and job.user_email != user.email:
            raise HTTPException(403, "Not authorized for this video")
        if job.status != "collecting":
            raise HTTPException(409, "Video is not a draft")
        if not _list_screenshots(job.slug, str(jid)):
            raise HTTPException(400, "Add at least one screenshot first")
        cutoff = datetime.utcnow() - timedelta(hours=24)
        used = (await s.execute(
            select(func.count()).select_from(VideoJob).where(and_(
                VideoJob.user_email == job.user_email,
                VideoJob.created_at >= cutoff,
                VideoJob.status.in_(["queued", "scripting", "rendering", "done"]),
            ))
        )).scalar() or 0
        if used >= int(os.environ.get("VIDEO_MAX_PER_USER_PER_DAY", "10")):
            raise HTTPException(429, "Daily video limit reached")
        await s.execute(
            update(VideoJob).where(VideoJob.id == jid).values(status="queued")
        )
        await s.commit()
        queue_position = (await s.execute(
            select(func.count()).select_from(VideoJob).where(and_(
                VideoJob.status == "queued",
                VideoJob.created_at < job.created_at,
            ))
        )).scalar() or 0
    return {"status": "queued", "queue_position": queue_position}
```

- [ ] **Step 2: Write the failing tests**

```python
# mcp-servers/tasks/tests/test_routes_video_queue.py
import io
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image

import routes_video
from db import session
from main import app
from video_models import VideoJob

H = {"X-User-Email": "queuer@aiui.test"}


def _png():
    buf = io.BytesIO(); Image.new("RGB", (8, 8), "white").save(buf, "PNG"); return buf.getvalue()


async def _draft_with_shots(n: int) -> str:
    jid = uuid.uuid4(); slug = f"vid-{jid.hex[:8]}"
    async with session() as s:
        s.add(VideoJob(id=jid, slug=slug, user_email=H["X-User-Email"], prompt="p",
                       title="t", style="clean_product_demo", voice="amy",
                       status="collecting"))
        await s.commit()
    shots = routes_video._apps_dir() / slug / ".video" / str(jid) / "screenshots"
    shots.mkdir(parents=True, exist_ok=True)
    for i in range(1, n + 1):
        (shots / f"screenshot-{i}.png").write_bytes(_png())
    return str(jid)


@pytest.mark.asyncio
async def test_queue_flips_collecting_to_queued():
    jid = await _draft_with_shots(2)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post(f"/api/video-jobs/{jid}/queue", headers=H)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "queued"
    async with session() as s:
        assert (await s.get(VideoJob, uuid.UUID(jid))).status == "queued"


@pytest.mark.asyncio
async def test_queue_rejects_zero_screenshots():
    jid = await _draft_with_shots(0)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post(f"/api/video-jobs/{jid}/queue", headers=H)
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_queue_rejects_non_draft():
    jid = await _draft_with_shots(1)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        await c.post(f"/api/video-jobs/{jid}/queue", headers=H)
        r = await c.post(f"/api/video-jobs/{jid}/queue", headers=H)  # already queued
        assert r.status_code == 409
```

- [ ] **Step 3: Run** → PASS. **Step 4: Commit**

```bash
git add mcp-servers/tasks/routes_video.py mcp-servers/tasks/tests/test_routes_video_queue.py
git commit -m "feat(video): queue endpoint (collecting -> queued) with daily limit"
```

---

### Task A5: `share_url` on `GET /api/video-jobs/{job_id}` when done

**Files:**
- Modify: `mcp-servers/tasks/routes_video.py` (`job_status` handler, line ~247-296)
- Test: `mcp-servers/tasks/tests/test_routes_video_share_url.py`

- [ ] **Step 1: Add the share_url block** inside `job_status`, right before the `return {...}` (line ~360), and add `"share_url": share_url` to the returned dict.

```python
        share_url = None
        if output_available:
            base = os.environ.get("VIDEO_PUBLIC_BASE", "").rstrip("/")
            if base:
                try:
                    tok = mint_video_capability(job.user_email, job.slug, str(job.id))
                    share_url = f"{base}/api/video-jobs/{job.id}/download?cap={tok}"
                except RuntimeError:
                    share_url = None  # OAUTH_STATE_SECRET unset -> no link
        return {
            "id": str(job.id),
            "slug": job.slug,
            "title": job.title,
            "status": job.status,
            "queue_position": queue_position,
            "error": job.error,
            "output_available": output_available,
            "share_url": share_url,
            "conversation": job.conversation or [],
            "current_version_no": job.current_version_no,
            "pending": latest_pending_proposal(job.conversation or []) is not None,
            "plan": job.plan_json,
        }
```

- [ ] **Step 2: Write the failing test**

```python
# mcp-servers/tasks/tests/test_routes_video_share_url.py
import os
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from db import session
from main import app
from video_models import VideoJob

H = {"X-User-Email": "sharer@aiui.test"}


@pytest.mark.asyncio
async def test_share_url_present_when_done(monkeypatch, tmp_path):
    monkeypatch.setenv("VIDEO_PUBLIC_BASE", "https://ai-ui.coolestdomain.win/tasks")
    monkeypatch.setenv("OAUTH_STATE_SECRET", "test-secret")
    out = tmp_path / "out.mp4"; out.write_bytes(b"x")
    jid = uuid.uuid4()
    async with session() as s:
        s.add(VideoJob(id=jid, slug=f"vid-{jid.hex[:8]}", user_email=H["X-User-Email"],
                       prompt="p", title="t", style="clean_product_demo", voice="amy",
                       status="done", output_path=str(out)))
        await s.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get(f"/api/video-jobs/{jid}", headers=H)
        assert r.status_code == 200
        url = r.json()["share_url"]
        assert url and url.startswith("https://ai-ui.coolestdomain.win/tasks/api/video-jobs/")
        assert "cap=" in url


@pytest.mark.asyncio
async def test_no_share_url_when_not_done():
    jid = uuid.uuid4()
    async with session() as s:
        s.add(VideoJob(id=jid, slug=f"vid-{jid.hex[:8]}", user_email=H["X-User-Email"],
                       prompt="p", title="t", style="clean_product_demo", voice="amy",
                       status="queued"))
        await s.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get(f"/api/video-jobs/{jid}", headers=H)
        assert r.json()["share_url"] is None
```

- [ ] **Step 3: Run** → PASS. **Step 4: Commit**

```bash
git add mcp-servers/tasks/routes_video.py mcp-servers/tasks/tests/test_routes_video_share_url.py
git commit -m "feat(video): expose capability share_url on done video status"
```

---

### Task A6: `video_thread_id` slot in the discord-links store

**Files:**
- Create: `mcp-servers/tasks/migrations/026_discord_link_video_thread.sql`
- Modify: `mcp-servers/tasks/models.py` (`DiscordLink`, after line 163)
- Modify: `mcp-servers/tasks/routes_discord_links.py` (add get/set video-thread, mirroring builder-thread)
- Test: `mcp-servers/tasks/tests/test_routes_discord_video_thread.py`

- [ ] **Step 1: Migration**

```sql
-- 026_discord_link_video_thread.sql
-- Per-user private Discord thread for the video studio (created/reused by the
-- bot), separate from schedules_thread_id and builder_thread_id.
-- Idempotent: re-applied on every startup.
ALTER TABLE tasks.discord_links
    ADD COLUMN IF NOT EXISTS video_thread_id text;
```

- [ ] **Step 2: Model column** — add to `DiscordLink` after `builder_thread_id` (models.py:163)

```python
    # The user's private Discord thread for the video studio (created/reused by the bot).
    video_thread_id = Column(Text, nullable=True)
```

- [ ] **Step 3: Routes** — add after `set_builder_thread` (routes_discord_links.py:183)

```python
@router.get("/{discord_id}/video-thread")
async def get_video_thread(discord_id: str, x_internal_secret: str = Header(default="")) -> dict[str, Any]:
    _require_internal(x_internal_secret)
    async with session() as s:
        link = (await s.execute(
            select(DiscordLink).where(DiscordLink.discord_id == discord_id)
        )).scalar_one_or_none()
    return {"thread_id": link.video_thread_id if link else None}


@router.post("/{discord_id}/video-thread")
async def set_video_thread(
    discord_id: str, body: ThreadIn, x_internal_secret: str = Header(default=""),
) -> dict[str, str]:
    _require_internal(x_internal_secret)
    async with session() as s:
        link = (await s.execute(
            select(DiscordLink).where(DiscordLink.discord_id == discord_id)
        )).scalar_one_or_none()
        if link:
            link.video_thread_id = body.thread_id
        else:
            # Same placeholder rationale as set_builder_thread (unlinked users).
            s.add(DiscordLink(
                discord_id=discord_id,
                email=f"discord-{discord_id}@aiui.local",
                status="pending",
                video_thread_id=body.thread_id,
            ))
        await s.commit()
    return {"status": "ok"}
```

- [ ] **Step 4: Write the failing test**

```python
# mcp-servers/tasks/tests/test_routes_discord_video_thread.py
import os
import pytest
from httpx import ASGITransport, AsyncClient

from main import app

SECRET = "vid-thread-secret"
IH = {"X-Internal-Secret": SECRET}


@pytest.mark.asyncio
async def test_get_set_video_thread(monkeypatch):
    monkeypatch.setenv("INTERNAL_CALLBACK_SECRET", SECRET)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/discord-links/55501/video-thread", headers=IH)
        assert r.status_code == 200 and r.json()["thread_id"] is None
        r = await c.post("/discord-links/55501/video-thread", headers=IH,
                         json={"thread_id": "tid-1"})
        assert r.status_code == 200
        r = await c.get("/discord-links/55501/video-thread", headers=IH)
        assert r.json()["thread_id"] == "tid-1"


@pytest.mark.asyncio
async def test_video_thread_requires_secret(monkeypatch):
    monkeypatch.setenv("INTERNAL_CALLBACK_SECRET", SECRET)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/discord-links/55501/video-thread",
                        headers={"X-Internal-Secret": "wrong"})
        assert r.status_code == 403
```

- [ ] **Step 5: Run** → PASS. **Step 6: Commit**

```bash
git add mcp-servers/tasks/migrations/026_discord_link_video_thread.sql mcp-servers/tasks/models.py mcp-servers/tasks/routes_discord_links.py mcp-servers/tasks/tests/test_routes_discord_video_thread.py
git commit -m "feat(video): video-thread slot in the discord-links store"
```

---

## Phase B — Bot (`webhook-handler`)

### Task B1: `TasksClient` video methods

**Files:**
- Modify: `webhook-handler/clients/tasks.py` (add methods near `start_build`; add thread methods near `set_user_builder_thread`)
- Test: `webhook-handler/tests/test_tasks_client_video.py`

- [ ] **Step 1: Add the video methods** (after `get_build_status`, ~line 235)

```python
    # --- Video generation (user-scoped, X-User-Email) ---
    async def get_video_voices(self) -> dict[str, Any]:
        # /voices is unauthenticated server-side; reuse _request (header is harmless).
        resp = await self._request("GET", "/api/video-jobs/voices", "system@aiui.local")
        return resp.json()

    async def create_video_draft(
        self, user_email: str, title: str, prompt: str, style: str, voice: str,
    ) -> dict[str, Any]:
        resp = await self._request(
            "POST", "/api/video-jobs/draft", user_email,
            json={"title": title, "prompt": prompt, "style": style, "voice": voice},
        )
        return resp.json()

    async def get_current_video_draft(self, user_email: str) -> dict[str, Any] | None:
        try:
            resp = await self._request("GET", "/api/video-jobs/current-draft", user_email)
        except TasksAPIError as e:
            if e.status == 404:
                return None
            raise
        return resp.json()

    async def update_video_draft_field(
        self, user_email: str, job_id: str, *, style: str | None = None,
        voice: str | None = None,
    ) -> dict[str, Any]:
        # Style/voice changes on a draft re-create via draft is overkill; instead
        # we PATCH-by-recreate is avoided — selects update via a dedicated endpoint.
        # (Implemented as create-draft semantics is not needed; see note in B5.)
        raise NotImplementedError  # replaced in B5 wiring; kept for signature clarity

    async def add_video_screenshots_urls(
        self, user_email: str, job_id: str, urls: list[str],
    ) -> dict[str, Any]:
        resp = await self._request(
            "POST", f"/api/video-jobs/{job_id}/screenshots-by-url", user_email,
            json={"urls": urls},
        )
        return resp.json()

    async def queue_video(self, user_email: str, job_id: str) -> dict[str, Any]:
        resp = await self._request("POST", f"/api/video-jobs/{job_id}/queue", user_email)
        return resp.json()

    async def get_video(self, user_email: str, job_id: str) -> dict[str, Any]:
        resp = await self._request("GET", f"/api/video-jobs/{job_id}", user_email)
        return resp.json()

    async def list_videos(self, user_email: str) -> dict[str, Any]:
        resp = await self._request("GET", "/api/video-jobs", user_email)
        return resp.json()

    async def refine_video(self, user_email: str, job_id: str, message: str) -> dict[str, Any]:
        resp = await self._request(
            "POST", f"/api/video-jobs/{job_id}/refine", user_email,
            json={"message": message})
        return resp.json()

    async def apply_video(self, user_email: str, job_id: str) -> dict[str, Any]:
        resp = await self._request("POST", f"/api/video-jobs/{job_id}/apply", user_email)
        return resp.json()

    async def video_versions(self, user_email: str, job_id: str) -> dict[str, Any]:
        resp = await self._request("GET", f"/api/video-jobs/{job_id}/versions", user_email)
        return resp.json()

    async def revert_video(self, user_email: str, job_id: str, version_no: int) -> dict[str, Any]:
        resp = await self._request(
            "POST", f"/api/video-jobs/{job_id}/revert", user_email,
            json={"version_no": version_no})
        return resp.json()

    async def download_video_bytes(self, user_email: str, job_id: str) -> bytes:
        """Fetch the rendered MP4 (member-auth via X-User-Email). Returns raw bytes."""
        resp = await self._request("GET", f"/api/video-jobs/{job_id}/download", user_email)
        return resp.content

    async def fetch_bytes(self, path: str) -> bytes:
        """GET a public/static path on the tasks service (e.g. a voice sample),
        no auth. Used to attach the voice preview MP3s."""
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(url)
                resp.raise_for_status()
        except httpx.HTTPError as e:
            raise TasksAPIError(0, f"fetch failed: {e}") from e
        return resp.content
```

Note: drop the placeholder `update_video_draft_field` (style/voice updates are handled by a tiny new backend PATCH added in B1b below). Keeping methods honest — implement B1b before B5 wiring uses it.

- [ ] **Step 1b: Add a draft style/voice update endpoint** (backend — small, belongs with A2 but wired here). In `routes_video.py` add:

```python
class DraftPatch(BaseModel):
    style: str | None = Field(None, max_length=50)
    voice: str | None = Field(None, max_length=50)


@router.post("/{job_id}/draft-set")
async def update_draft(
    job_id: str, body: DraftPatch, user: CurrentUser = Depends(current_user)
) -> dict:
    """Update style/voice on a 'collecting' draft (the Discord select handlers)."""
    if not _video_enabled():
        raise HTTPException(503, "Video generation is disabled")
    jid = _coerce_job_id(job_id)
    async with session() as s:
        job = (await s.execute(select(VideoJob).where(VideoJob.id == jid))).scalar_one_or_none()
        if job is None:
            raise HTTPException(404, "Video job not found")
        if not user.is_admin and job.user_email != user.email:
            raise HTTPException(403, "Not authorized for this video")
        if job.status != "collecting":
            raise HTTPException(409, "Video is not a draft")
        vals = {}
        if body.style is not None:
            if body.style not in STYLE_CONFIGS:
                raise HTTPException(400, f"Unknown style: {body.style}")
            vals["style"] = body.style
        if body.voice is not None:
            if not is_valid_voice(body.voice):
                raise HTTPException(400, f"Unknown voice: {body.voice}")
            vals["voice"] = body.voice
        if vals:
            await s.execute(update(VideoJob).where(VideoJob.id == jid).values(**vals))
            await s.commit()
    return {"status": "ok", **vals}
```

Replace the placeholder client method with:

```python
    async def set_video_draft_fields(
        self, user_email: str, job_id: str, *, style: str | None = None,
        voice: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if style is not None:
            body["style"] = style
        if voice is not None:
            body["voice"] = voice
        resp = await self._request(
            "POST", f"/api/video-jobs/{job_id}/draft-set", user_email, json=body)
        return resp.json()
```

Add a backend test `mcp-servers/tasks/tests/test_routes_video_draft.py::test_draft_set_updates_style_voice` (extend the file from A2):

```python
@pytest.mark.asyncio
async def test_draft_set_updates_style_voice():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        jid = (await c.post("/api/video-jobs/draft", headers=H, json={
            "title": "t", "prompt": "p"})).json()["id"]
        r = await c.post(f"/api/video-jobs/{jid}/draft-set", headers=H,
                         json={"style": "cinematic", "voice": "ryan"})
        assert r.status_code == 200 and r.json()["style"] == "cinematic"
        d = (await c.get("/api/video-jobs/current-draft", headers=H)).json()
        assert d["style"] == "cinematic" and d["voice"] == "ryan"
```

- [ ] **Step 2: Add the video-thread client methods** (after `set_user_builder_thread`, ~line 197)

```python
    async def get_user_video_thread(self, discord_id: str) -> str | None:
        resp = await self._internal_request(
            "GET", f"/discord-links/{discord_id}/video-thread")
        return resp.json().get("thread_id")

    async def set_user_video_thread(self, discord_id: str, thread_id: str) -> bool:
        await self._internal_request(
            "POST", f"/discord-links/{discord_id}/video-thread",
            json={"thread_id": thread_id})
        return True
```

- [ ] **Step 3: Write the failing tests** (fake `_request`/`_internal_request`, mirroring `test_discord_attachment_wiring.py`)

```python
# webhook-handler/tests/test_tasks_client_video.py
import pytest
from clients.tasks import TasksClient


def _client_with_capture(captured):
    client = TasksClient(base_url="http://tasks-test:8210")

    async def fake_request(method, path, email, json=None, **kw):
        captured.update(method=method, path=path, email=email, json=json)

        class _R:
            def json(self): return {"id": "j1", "status": "collecting",
                                    "queue_position": 0, "screenshot_count": 1}
            content = b"MP4BYTES"
        return _R()
    client._request = fake_request
    return client


@pytest.mark.asyncio
async def test_create_video_draft():
    cap = {}
    client = _client_with_capture(cap)
    await client.create_video_draft("e@x", "Tour", "walk it", "cinematic", "ryan")
    assert cap["path"] == "/api/video-jobs/draft"
    assert cap["json"] == {"title": "Tour", "prompt": "walk it",
                           "style": "cinematic", "voice": "ryan"}


@pytest.mark.asyncio
async def test_add_screenshots_urls_and_queue():
    cap = {}
    client = _client_with_capture(cap)
    await client.add_video_screenshots_urls("e@x", "j1",
                                            ["https://cdn.discordapp.com/a.png"])
    assert cap["path"] == "/api/video-jobs/j1/screenshots-by-url"
    assert cap["json"] == {"urls": ["https://cdn.discordapp.com/a.png"]}
    await client.queue_video("e@x", "j1")
    assert cap["path"] == "/api/video-jobs/j1/queue"


@pytest.mark.asyncio
async def test_download_video_bytes():
    client = _client_with_capture({})
    assert await client.download_video_bytes("e@x", "j1") == b"MP4BYTES"


@pytest.mark.asyncio
async def test_current_draft_none_on_404():
    from clients.tasks import TasksAPIError
    client = TasksClient(base_url="http://tasks-test:8210")

    async def fake_request(method, path, email, **kw):
        raise TasksAPIError(404, "No draft in progress")
    client._request = fake_request
    assert await client.get_current_video_draft("e@x") is None


@pytest.mark.asyncio
async def test_video_thread_accessors():
    cap = {}
    client = TasksClient(base_url="http://tasks-test:8210", internal_secret="s")

    async def fake_internal(method, path, json=None, **kw):
        cap.update(method=method, path=path, json=json)

        class _R:
            def json(self): return {"thread_id": "tid"}
        return _R()
    client._internal_request = fake_internal
    assert await client.get_user_video_thread("42") == "tid"
    assert cap["path"] == "/discord-links/42/video-thread"
    await client.set_user_video_thread("42", "tid2")
    assert cap["json"] == {"thread_id": "tid2"}
```

- [ ] **Step 4: Run** `cd webhook-handler && python -m pytest tests/test_tasks_client_video.py -v` → PASS. Also re-run the extended A2 backend test.

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/clients/tasks.py webhook-handler/tests/test_tasks_client_video.py mcp-servers/tasks/routes_video.py mcp-servers/tasks/tests/test_routes_video_draft.py
git commit -m "feat(video): TasksClient video methods + draft-set endpoint"
```

---

### Task B2: `handlers/video_panel.py` (pure builders + predicates)

**Files:**
- Create: `webhook-handler/handlers/video_panel.py`
- Test: `webhook-handler/tests/test_video_panel.py`

- [ ] **Step 1: Write the module** (mirrors `app_builder_panel.py` constants/patterns)

```python
"""Pure builders + custom_id helpers for the #video-generation Discord channel.

No I/O — imported by both the setup script and the interaction router. Namespace:
all component custom_ids start with "aiuivid:". See
docs/superpowers/specs/2026-06-19-discord-video-channel-design.md.
"""
from handlers.app_builder_panel import (  # reuse the shared component constants
    ACTION_ROW, BUTTON, SELECT_MENU, TEXT_INPUT, TEXT_PARAGRAPH, TEXT_SHORT,
    STYLE_PRIMARY, STYLE_SECONDARY, STYLE_SUCCESS, ROBOTIC_CYAN, _button,
)

# --- custom_id namespace ---
NEW_ID = "aiuivid:new"            # panel: New video button
LIST_ID = "aiuivid:list"          # panel: My videos button
NEW_MODAL_ID = "aiuivid:newmodal" # title+prompt modal
STYLE_PREFIX = "aiuivid:style:"   # style select  -> aiuivid:style:<job>
VOICE_PREFIX = "aiuivid:voice:"   # voice select  -> aiuivid:voice:<job>
GENERATE_PREFIX = "aiuivid:generate:"   # button -> aiuivid:generate:<job>
REFINE_PREFIX = "aiuivid:refine:"       # button -> aiuivid:refine:<job>
REFINE_MODAL_PREFIX = "aiuivid:refinemodal:"  # modal -> aiuivid:refinemodal:<job>
APPLY_PREFIX = "aiuivid:apply:"         # button -> aiuivid:apply:<job>
VERSION_PREFIX = "aiuivid:version:"     # select -> aiuivid:version:<job> (value=version_no)
TITLE_INPUT = "title"
PROMPT_INPUT = "prompt"
REFINE_INPUT = "change"

# style options shown in the select (value must match tasks STYLE_CONFIGS keys)
STYLES = [
    ("clean_product_demo", "Clean product demo", "Crisp, recommended default"),
    ("cinematic", "Cinematic", "Graded, glassy lower-thirds, ambient bed"),
    ("snappy_social", "Snappy social", "Punchy, bold pop-in captions"),
]


def _suffix_after(custom_id: str, prefix: str) -> str:
    if not custom_id.startswith(prefix):
        raise ValueError(f"not a {prefix!r} custom_id: {custom_id!r}")
    suffix = custom_id[len(prefix):]
    if not suffix:
        raise ValueError(f"{prefix!r} custom_id has no value: {custom_id!r}")
    return suffix


def build_video_embed() -> dict:
    return {
        "title": "AIUI · VIDEO STUDIO",
        "color": ROBOTIC_CYAN,
        "description": (
            "```\n"
            "> turn screenshots into a narrated walkthrough\n"
            "> New video -> name it, pick style + voice\n"
            "> add 1-12 screenshots with  /video add\n"
            "> Generate -> we render it in your private thread\n"
            "```"
        ),
        "footer": {"text": "AIUI · video generation"},
    }


def build_video_panel() -> dict:
    return {"content": "", "components": [
        {"type": ACTION_ROW, "components": [
            _button("New video", NEW_ID, STYLE_SUCCESS),
            _button("My videos", LIST_ID, STYLE_PRIMARY),
        ]},
    ]}


def build_video_modal() -> dict:
    """Type-9 modal data: Title (short) + Prompt (paragraph)."""
    return {
        "title": "New video"[:45],
        "custom_id": NEW_MODAL_ID,
        "components": [
            {"type": ACTION_ROW, "components": [{
                "type": TEXT_INPUT, "custom_id": TITLE_INPUT,
                "label": "Title", "style": TEXT_SHORT, "required": True,
                "max_length": 200, "placeholder": "e.g. Dashboard walkthrough",
            }]},
            {"type": ACTION_ROW, "components": [{
                "type": TEXT_INPUT, "custom_id": PROMPT_INPUT,
                "label": "Describe the narrated walkthrough",
                "style": TEXT_PARAGRAPH, "required": True, "max_length": 2000,
                "placeholder": "Walk the dashboard, highlight the charts, end on export.",
            }]},
        ],
    }


def build_refine_modal(job_id: str) -> dict:
    return {
        "title": "Refine video"[:45],
        "custom_id": f"{REFINE_MODAL_PREFIX}{job_id}",
        "components": [
            {"type": ACTION_ROW, "components": [{
                "type": TEXT_INPUT, "custom_id": REFINE_INPUT,
                "label": "What should change?", "style": TEXT_PARAGRAPH,
                "required": True, "max_length": 2000,
                "placeholder": "e.g. slow down scene 2 and use a warmer tone",
            }]},
        ],
    }


def build_style_select(job_id: str, current: str = "clean_product_demo") -> dict:
    options = [{
        "label": label, "value": key, "description": desc[:100],
        "default": key == current,
    } for key, label, desc in STYLES]
    return {"type": SELECT_MENU, "custom_id": f"{STYLE_PREFIX}{job_id}",
            "placeholder": "Pick a style…", "min_values": 1, "max_values": 1,
            "options": options}


def build_voice_select(job_id: str, voices: list[dict], current: str = "amy") -> dict:
    options = []
    for v in voices[:25]:
        vid = v.get("id")
        if not vid:
            continue
        label = f"{v.get('label', vid)} — {v.get('accent','')} {v.get('gender','')}".strip()
        options.append({"label": label[:100], "value": vid[:100],
                        "default": vid == current})
    return {"type": SELECT_MENU, "custom_id": f"{VOICE_PREFIX}{job_id}",
            "placeholder": "Pick a voice…", "min_values": 1, "max_values": 1,
            "options": options}


def build_studio_components(job_id: str, voices: list[dict]) -> list[dict]:
    """Style select + voice select + a Generate button, for the studio message."""
    return [
        {"type": ACTION_ROW, "components": [build_style_select(job_id)]},
        {"type": ACTION_ROW, "components": [build_voice_select(job_id, voices)]},
        {"type": ACTION_ROW, "components": [
            _button("Generate video", f"{GENERATE_PREFIX}{job_id}", STYLE_SUCCESS)]},
    ]


def build_generate_row(job_id: str) -> list[dict]:
    return [{"type": ACTION_ROW, "components": [
        _button("Generate video", f"{GENERATE_PREFIX}{job_id}", STYLE_SUCCESS)]}]


def build_done_components(job_id: str, versions: list[dict]) -> list[dict]:
    rows = [{"type": ACTION_ROW, "components": [
        _button("Refine", f"{REFINE_PREFIX}{job_id}", STYLE_PRIMARY)]}]
    opts = []
    for v in (versions or [])[:25]:
        n = v.get("version_no")
        if n is None:
            continue
        opts.append({"label": f"Version {n}" + (" (current)" if v.get("current") else ""),
                     "value": str(n)})
    if opts:
        rows.append({"type": ACTION_ROW, "components": [{
            "type": SELECT_MENU, "custom_id": f"{VERSION_PREFIX}{job_id}",
            "placeholder": "Revert to a version…", "min_values": 1, "max_values": 1,
            "options": opts}]})
    return rows


def build_proposal_components(job_id: str) -> list[dict]:
    return [{"type": ACTION_ROW, "components": [
        _button("Apply this change", f"{APPLY_PREFIX}{job_id}", STYLE_SUCCESS)]}]


# --- predicates / extractors ---
def is_vid_new(c: str) -> bool: return c == NEW_ID
def is_vid_list(c: str) -> bool: return c == LIST_ID
def is_vid_new_modal(c: str) -> bool: return c == NEW_MODAL_ID
def is_vid_style(c: str) -> bool: return c.startswith(STYLE_PREFIX)
def is_vid_voice(c: str) -> bool: return c.startswith(VOICE_PREFIX)
def is_vid_generate(c: str) -> bool: return c.startswith(GENERATE_PREFIX)
def is_vid_refine(c: str) -> bool: return c.startswith(REFINE_PREFIX)
def is_vid_refine_modal(c: str) -> bool: return c.startswith(REFINE_MODAL_PREFIX)
def is_vid_apply(c: str) -> bool: return c.startswith(APPLY_PREFIX)
def is_vid_version(c: str) -> bool: return c.startswith(VERSION_PREFIX)

def job_from_style(c: str) -> str: return _suffix_after(c, STYLE_PREFIX)
def job_from_voice(c: str) -> str: return _suffix_after(c, VOICE_PREFIX)
def job_from_generate(c: str) -> str: return _suffix_after(c, GENERATE_PREFIX)
def job_from_refine(c: str) -> str: return _suffix_after(c, REFINE_PREFIX)
def job_from_refine_modal(c: str) -> str: return _suffix_after(c, REFINE_MODAL_PREFIX)
def job_from_apply(c: str) -> str: return _suffix_after(c, APPLY_PREFIX)
def job_from_version(c: str) -> str: return _suffix_after(c, VERSION_PREFIX)
```

- [ ] **Step 2: Write the failing tests**

```python
# webhook-handler/tests/test_video_panel.py
import pytest
from handlers import video_panel as vp


def test_panel_has_two_buttons():
    comps = vp.build_video_panel()["components"][0]["components"]
    ids = {c["custom_id"] for c in comps}
    assert ids == {vp.NEW_ID, vp.LIST_ID}


def test_modal_fields():
    modal = vp.build_video_modal()
    assert modal["custom_id"] == vp.NEW_MODAL_ID
    ids = [c["components"][0]["custom_id"] for c in modal["components"]]
    assert ids == [vp.TITLE_INPUT, vp.PROMPT_INPUT]


def test_style_select_options_match_keys():
    sel = vp.build_style_select("j1")
    assert sel["custom_id"] == "aiuivid:style:j1"
    assert {o["value"] for o in sel["options"]} == {
        "clean_product_demo", "cinematic", "snappy_social"}


def test_voice_select_from_catalog():
    sel = vp.build_voice_select("j1", [{"id": "amy", "label": "Amy",
                                        "accent": "US", "gender": "Female"}])
    assert sel["options"][0]["value"] == "amy"


def test_custom_id_round_trip():
    assert vp.job_from_generate(f"{vp.GENERATE_PREFIX}abc") == "abc"
    assert vp.is_vid_generate("aiuivid:generate:abc")
    assert not vp.is_vid_generate("aiuivid:refine:abc")
    with pytest.raises(ValueError):
        vp.job_from_generate("aiuivid:generate:")


def test_done_components_include_versions():
    rows = vp.build_done_components("j1", [{"version_no": 1, "current": True}])
    assert any(c.get("type") == vp.SELECT_MENU
              for row in rows for c in row["components"])
```

- [ ] **Step 3: Run** `cd webhook-handler && python -m pytest tests/test_video_panel.py -v` → PASS. **Step 4: Commit**

```bash
git add webhook-handler/handlers/video_panel.py webhook-handler/tests/test_video_panel.py
git commit -m "feat(video): video_panel.py builders + custom_id helpers"
```

---

### Task B3: `DiscordClient.post_channel_file` (multipart attach)

**Files:**
- Modify: `webhook-handler/clients/discord.py` (add method after `post_channel_message`)
- Test: `webhook-handler/tests/test_discord_post_file.py`

- [ ] **Step 1: Add `import json` at the top if absent, then the method**

```python
    async def post_channel_file(
        self, channel_id: str, files: list[tuple[str, bytes, str]],
        content: str = "", components: list | None = None,
    ) -> bool:
        """Post a message with one or more file attachments (bot token, multipart).
        `files` = list of (filename, data, content_type). Discord allows <=10
        files. Never raises. Do NOT set Content-Type — httpx sets the multipart
        boundary itself."""
        url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages"
        body: dict = {"content": (content or "")[:2000],
                      "attachments": [{"id": i, "filename": fn}
                                      for i, (fn, _, _) in enumerate(files)]}
        if components:
            body["components"] = components
        multipart = {f"files[{i}]": (fn, data, ctype)
                     for i, (fn, data, ctype) in enumerate(files)}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    url,
                    headers={"Authorization": f"Bot {self.bot_token}"},
                    data={"payload_json": json.dumps(body)},
                    files=multipart,
                )
                if response.status_code in (200, 201):
                    return True
                logger.error(
                    f"Discord file post error: {response.status_code} {response.text}")
                return False
        except Exception as e:
            logger.error(f"Error posting Discord file: {e}")
            return False
```

- [ ] **Step 2: Write the failing test** (capture the httpx call)

```python
# webhook-handler/tests/test_discord_post_file.py
import json
import pytest
from clients.discord import DiscordClient


class _Resp:
    status_code = 200
    text = ""


@pytest.mark.asyncio
async def test_post_channel_file_builds_multipart(monkeypatch):
    captured = {}

    class _FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, headers=None, data=None, files=None):
            captured.update(url=url, headers=headers, data=data, files=files)
            return _Resp()

    monkeypatch.setattr("clients.discord.httpx.AsyncClient", _FakeClient)
    client = DiscordClient(application_id="app", bot_token="tok")
    ok = await client.post_channel_file(
        "chan", [("out.mp4", b"BYTES", "video/mp4")], content="done")
    assert ok
    assert "Content-Type" not in captured["headers"]
    body = json.loads(captured["data"]["payload_json"])
    assert body["attachments"] == [{"id": 0, "filename": "out.mp4"}]
    assert "files[0]" in captured["files"]
```

- [ ] **Step 3: Run** → PASS. **Step 4: Commit**

```bash
git add webhook-handler/clients/discord.py webhook-handler/tests/test_discord_post_file.py
git commit -m "feat(video): DiscordClient.post_channel_file (multipart attach)"
```

---

### Task B4: `CommandRouter` video runners + `_watch_video`

**Files:**
- Modify: `webhook-handler/handlers/commands.py` (constants, thread wrappers, runners, watcher)
- Test: `webhook-handler/tests/test_video_runners.py`, `webhook-handler/tests/test_watch_video.py`

- [ ] **Step 1: Add constants** near `BUILD_POLL_SECONDS` (line ~30)

```python
VIDEO_POLL_SECONDS = 6
VIDEO_MAX_POLLS = 120  # ~12 min, > render timeout (600s) + queue wait
VIDEO_MAX_CONSECUTIVE_ERRORS = 5
VIDEO_ATTACH_MAX_MB = int(os.environ.get("VIDEO_DISCORD_ATTACH_MAX_MB", "24"))
```

- [ ] **Step 2: Add thread wrappers** next to the builder-thread wrappers (line ~2048)

```python
    async def get_user_video_thread(self, discord_id: str) -> str | None:
        return await self._tasks_client.get_user_video_thread(discord_id)

    async def set_user_video_thread(self, discord_id: str, thread_id: str) -> bool:
        return await self._tasks_client.set_user_video_thread(discord_id, thread_id)
```

- [ ] **Step 3: Add the runner methods + watcher** (anywhere in `CommandRouter`, e.g. after `_watch_build`)

```python
    async def run_video_add(
        self, ctx: CommandContext, urls: list[str],
    ) -> None:
        """`/video add`: push Discord CDN screenshot URLs onto the caller's
        current draft. Replies (ephemeral) with the running count + a Generate
        button. Requires an in-progress draft (start one with New video)."""
        email = await self._resolve_email_for_ctx(ctx)
        if not email:
            await self._respond_not_linked(ctx)
            return
        if not urls:
            await ctx.respond("Attach 1-10 screenshots to `/video add`.")
            return
        draft = await self._tasks_client.get_current_video_draft(email)
        if not draft:
            await ctx.respond("No video in progress — click **New video** first.")
            return
        try:
            res = await self._tasks_client.add_video_screenshots_urls(
                email, draft["id"], urls)
        except TasksAPIError as e:
            await ctx.respond(f"Couldn't add screenshots: {e.message}")
            return
        count = res.get("count", 0)
        msg = f"Added screenshots — {count}/12 so far. Click **Generate video** when ready."
        if ctx.respond_components is not None:
            from handlers.video_panel import build_generate_row
            await ctx.respond_components(msg, build_generate_row(draft["id"]))
        else:
            await ctx.respond(msg)

    async def run_video_set_field(
        self, ctx: CommandContext, job_id: str, *, style: str | None = None,
        voice: str | None = None,
    ) -> None:
        email = await self._resolve_email_for_ctx(ctx)
        if not email:
            await self._respond_not_linked(ctx)
            return
        try:
            await self._tasks_client.set_video_draft_fields(
                email, job_id, style=style, voice=voice)
        except TasksAPIError as e:
            logger.warning("video set field failed job=%s: %s", job_id, e)

    async def run_video_generate(
        self, ctx: CommandContext, job_id: str,
    ) -> None:
        """Generate button: queue the draft + spawn the watcher."""
        email = await self._resolve_email_for_ctx(ctx)
        if not email:
            await self._respond_not_linked(ctx)
            return
        try:
            res = await self._tasks_client.queue_video(email, job_id)
        except TasksAPIError as e:
            await ctx.respond(f"Couldn't start the render: {e.message}")
            return
        qp = res.get("queue_position", 0)
        tail = f" (queue position {qp}; renders queue behind app builds)" if qp else ""
        await ctx.respond(f"Rendering your video…{tail} I'll post it here when it's done.")
        if ctx.notify_channel is not None:
            watcher = asyncio.create_task(self._watch_video(ctx, email, job_id))
            self._background_tasks.add(watcher)
            watcher.add_done_callback(self._background_tasks.discard)

    async def run_video_refine(
        self, ctx: CommandContext, job_id: str, message: str,
    ) -> None:
        email = await self._resolve_email_for_ctx(ctx)
        if not email:
            await self._respond_not_linked(ctx)
            return
        try:
            res = await self._tasks_client.refine_video(email, job_id, message)
        except TasksAPIError as e:
            await ctx.respond(f"Refine failed: {e.message}")
            return
        text = res.get("message", "")
        if res.get("can_apply") and ctx.notify_channel_msg is not None:
            from handlers.video_panel import build_proposal_components
            await ctx.notify_channel_msg({
                "content": text or "Here's the proposed change.",
                "components": build_proposal_components(job_id)})
        else:
            await ctx.respond(text or "Okay.")

    async def run_video_apply(
        self, ctx: CommandContext, job_id: str,
    ) -> None:
        email = await self._resolve_email_for_ctx(ctx)
        if not email:
            await self._respond_not_linked(ctx)
            return
        try:
            await self._tasks_client.apply_video(email, job_id)
        except TasksAPIError as e:
            await ctx.respond(f"Apply failed: {e.message}")
            return
        await ctx.respond("Applying the change and re-rendering…")
        if ctx.notify_channel is not None:
            watcher = asyncio.create_task(self._watch_video(ctx, email, job_id))
            self._background_tasks.add(watcher)
            watcher.add_done_callback(self._background_tasks.discard)

    async def run_video_revert(
        self, ctx: CommandContext, job_id: str, version_no: int,
    ) -> None:
        email = await self._resolve_email_for_ctx(ctx)
        if not email:
            await self._respond_not_linked(ctx)
            return
        try:
            res = await self._tasks_client.revert_video(email, job_id, version_no)
        except TasksAPIError as e:
            await ctx.respond(f"Revert failed: {e.message}")
            return
        if res.get("status") == "reverted":
            await self._deliver_video(ctx, email, job_id)
        else:
            await ctx.respond("Re-rendering that version…")
            if ctx.notify_channel is not None:
                watcher = asyncio.create_task(self._watch_video(ctx, email, job_id))
                self._background_tasks.add(watcher)
                watcher.add_done_callback(self._background_tasks.discard)

    async def run_video_list(self, ctx: CommandContext) -> None:
        email = await self._resolve_email_for_ctx(ctx)
        if not email:
            await self._respond_not_linked(ctx)
            return
        try:
            res = await self._tasks_client.list_videos(email)
        except TasksAPIError as e:
            await ctx.respond(f"Couldn't list your videos: {e.message}")
            return
        vids = res.get("videos", [])
        if not vids:
            await ctx.respond("You have no videos yet. Click **New video** to make one.")
            return
        lines = [f"- **{v.get('title') or v['id']}** — {v.get('status')}"
                 + (" (ready)" if v.get("output_available") else "")
                 for v in vids[:25]]
        await ctx.respond("Your videos:\n" + "\n".join(lines))

    async def _deliver_video(
        self, ctx: CommandContext, email: str, job_id: str,
    ) -> None:
        """Post the finished MP4 to the thread: attach when small enough, else a
        capability link. Then post Refine + version controls."""
        try:
            data = await self._tasks_client.get_video(email, job_id)
        except TasksAPIError:
            return
        title = data.get("title") or "your video"
        share_url = data.get("share_url")
        versions = []
        try:
            versions = (await self._tasks_client.video_versions(email, job_id)).get("versions", [])
        except TasksAPIError:
            pass
        from handlers.video_panel import build_done_components
        components = build_done_components(job_id, versions)
        attached = False
        try:
            blob = await self._tasks_client.download_video_bytes(email, job_id)
            if len(blob) <= VIDEO_ATTACH_MAX_MB * 1024 * 1024:
                attached = await self._discord.post_channel_file(
                    ctx.channel_id, [(f"{title[:60]}.mp4", blob, "video/mp4")],
                    content=f"**{title}** is ready.", components=components)
        except (TasksAPIError, Exception) as e:  # noqa: BLE001
            logger.warning("video attach failed job=%s: %s", job_id, e)
        if not attached:
            if share_url:
                await ctx.notify_channel(f"**{title}** is ready: {share_url}")
            else:
                await ctx.notify_channel(
                    f"**{title}** is ready, but it's too large to attach here. "
                    "Open it in the web Video Studio.")
            if ctx.notify_channel_msg is not None:
                await ctx.notify_channel_msg({"content": "Refine or revert:",
                                              "components": components})

    async def _watch_video(
        self, ctx: CommandContext, email: str, job_id: str,
        *, poll_seconds: int | None = None, max_polls: int | None = None,
    ) -> None:
        """Poll a video job until it terminates, then deliver it. Modeled on
        _watch_build: detached task, transient errors tolerated."""
        if ctx.notify_channel is None:
            return

        async def _notify(msg: str) -> None:
            try:
                await ctx.notify_channel(msg)
            except Exception as exc:  # noqa: BLE001
                logger.error("watch_video notify failed job=%s: %s", job_id, exc)

        poll_seconds = VIDEO_POLL_SECONDS if poll_seconds is None else poll_seconds
        max_polls = VIDEO_MAX_POLLS if max_polls is None else max_polls
        errors = 0
        for _ in range(max_polls):
            await asyncio.sleep(poll_seconds)
            try:
                st = await self._tasks_client.get_video(email, job_id)
                errors = 0
            except TasksAPIError as e:
                errors += 1
                logger.warning("watch_video status error (%s) job=%s", e.status, job_id)
                if errors >= VIDEO_MAX_CONSECUTIVE_ERRORS:
                    await _notify("Lost track of your video — check **My videos**.")
                    return
                continue
            status = st.get("status")
            if status == "done":
                await self._deliver_video(ctx, email, job_id)
                return
            if status == "failed":
                err = (st.get("error") or "").strip()
                await _notify(f"Video render failed.{(' ' + err) if err else ''}")
                return
        await _notify("Your video is still rendering — check **My videos** shortly.")
```

Note: this references `self._discord` for `post_channel_file`. `CommandRouter.__init__` doesn't hold a DiscordClient today (delivery goes through `ctx.notify_channel*` closures). To attach a file we need the client. **Add a `discord_client` param to `CommandRouter.__init__`** (default `None`, stored as `self._discord`), and pass it from `main.py` where the router is constructed. Update the `__init__` signature and the `main.py` `CommandRouter(...)` call accordingly. Where `self._discord` is `None` (e.g. Slack/voice), `_deliver_video` falls back to the link/notify path (guard the `post_channel_file` call with `if self._discord is not None`).

Apply this guard in `_deliver_video`: wrap the attach attempt in `if self._discord is not None:`.

- [ ] **Step 4: Wire `discord_client` into the router.** In `commands.py __init__` add param `discord_client=None` and `self._discord = discord_client`. In `webhook-handler/main.py` (the `CommandRouter(...)` construction at ~line 164) pass `discord_client=DiscordClient(...)` — but the discord client there is created later (line 188, only if configured). Reorder so the Discord client is created before the router, or set `command_router._discord = discord_client` right after the discord client is created (line ~191). Simplest: after `discord_client = DiscordClient(...)` at line 188, add `command_router._discord = discord_client`.

- [ ] **Step 5: Write failing tests**

```python
# webhook-handler/tests/test_watch_video.py
import pytest
from handlers.commands import CommandRouter, CommandContext


def _ctx(notifications):
    async def notify(msg): notifications.append(msg)
    return CommandContext(
        user_id="1", user_name="u", channel_id="thread1", raw_text="", subcommand="",
        arguments="", platform="discord", respond=notify, notify_channel=notify)


class _FakeTasks:
    def __init__(self, statuses): self._statuses = statuses; self._i = 0
    async def get_video(self, email, job_id):
        s = self._statuses[min(self._i, len(self._statuses) - 1)]; self._i += 1
        return s
    async def video_versions(self, email, job_id): return {"versions": []}
    async def download_video_bytes(self, email, job_id): return b"x" * 10


@pytest.mark.asyncio
async def test_watch_video_delivers_on_done(monkeypatch):
    r = CommandRouter.__new__(CommandRouter)
    r._tasks_client = _FakeTasks([{"status": "rendering"},
                                  {"status": "done", "title": "T", "share_url": "http://u"}])
    r._discord = None
    notes = []
    ctx = _ctx(notes)
    ctx.notify_channel_msg = None
    await r._watch_video(ctx, "e@x", "j1", poll_seconds=0, max_polls=5)
    assert any("ready" in n.lower() for n in notes)


@pytest.mark.asyncio
async def test_watch_video_reports_failure():
    r = CommandRouter.__new__(CommandRouter)
    r._tasks_client = _FakeTasks([{"status": "failed", "error": "boom"}])
    r._discord = None
    notes = []
    await r._watch_video(_ctx(notes), "e@x", "j1", poll_seconds=0, max_polls=3)
    assert any("failed" in n.lower() for n in notes)
```

```python
# webhook-handler/tests/test_video_runners.py
import pytest
from handlers.commands import CommandRouter, CommandContext


def _ctx(replies, components=None):
    async def respond(msg): replies.append(("text", msg))
    async def respond_components(msg, comps, embeds=None): replies.append(("comp", msg, comps))
    return CommandContext(
        user_id="1", user_name="u", channel_id="c", raw_text="", subcommand="",
        arguments="", platform="discord", respond=respond,
        respond_components=respond_components)


class _Tasks:
    def __init__(self): self.calls = []
    async def get_current_video_draft(self, email):
        return {"id": "j1", "screenshot_count": 0}
    async def add_video_screenshots_urls(self, email, jid, urls):
        self.calls.append(("add", jid, urls)); return {"count": len(urls)}
    async def queue_video(self, email, jid):
        self.calls.append(("queue", jid)); return {"queue_position": 0}


@pytest.mark.asyncio
async def test_run_video_add_pushes_urls(monkeypatch):
    r = CommandRouter.__new__(CommandRouter)
    r._tasks_client = _Tasks()
    async def fake_email(ctx): return "e@x"
    r._resolve_email_for_ctx = fake_email
    replies = []
    await r.run_video_add(_ctx(replies), ["https://cdn.discordapp.com/a.png"])
    assert ("add", "j1", ["https://cdn.discordapp.com/a.png"]) in r._tasks_client.calls
    assert replies and replies[0][0] == "comp"


@pytest.mark.asyncio
async def test_run_video_add_no_draft():
    r = CommandRouter.__new__(CommandRouter)
    class _NoDraft:
        async def get_current_video_draft(self, email): return None
    r._tasks_client = _NoDraft()
    async def fake_email(ctx): return "e@x"
    r._resolve_email_for_ctx = fake_email
    replies = []
    await r.run_video_add(_ctx(replies), ["https://cdn.discordapp.com/a.png"])
    assert "New video" in replies[0][1]
```

- [ ] **Step 6: Run** both test files → PASS. **Step 7: Commit**

```bash
git add webhook-handler/handlers/commands.py webhook-handler/main.py webhook-handler/tests/test_video_runners.py webhook-handler/tests/test_watch_video.py
git commit -m "feat(video): CommandRouter video runners + _watch_video delivery"
```

---

### Task B5: Route `aiuivid:*` components/modals + the `/video` slash command

**Files:**
- Modify: `webhook-handler/handlers/discord_commands.py` (import video_panel as `vid`; add `_all_attachments`; branches in `_handle_message_component` and `_handle_modal_submit`; a `_handle_video_command`; the `kind="video"` branch in `_get_or_make_thread`; dispatch `/video` in `_handle_application_command`)
- Test: `webhook-handler/tests/test_video_routing.py`

- [ ] **Step 1: Import + `_all_attachments`**. Add `from handlers import video_panel as vid` with the other panel imports. Add:

```python
    @staticmethod
    def _all_attachments(data: dict) -> list[dict]:
        """All resolved slash-command attachments (Discord option type 11), in
        resolved-map order, as {url, filename, content_type, size}."""
        atts = (data.get("resolved") or {}).get("attachments") or {}
        return [{"url": a.get("url"), "filename": a.get("filename"),
                 "content_type": a.get("content_type"), "size": a.get("size")}
                for a in atts.values()]
```

- [ ] **Step 2: `_get_or_make_thread` video kind** — add a branch before the `else:` (discord_commands.py:1205)

```python
        elif kind == "video":
            get_thread = self.router.get_user_video_thread
            set_thread = self.router.set_user_video_thread
            name = f"aiui-video-{user_name}"
```

- [ ] **Step 3: Component branches** — insert in `_handle_message_component` before the `if not is_panel_button(custom_id):` catch-all (line ~385)

```python
        # --- Video studio (aiuivid:*) ---
        if vid.is_vid_new(custom_id):
            return await self._handle_video_new(payload)
        if vid.is_vid_list(custom_id):
            return await self._handle_panel_route(
                payload, lambda ctx: self.router.run_video_list(ctx),
                raw_text="video list")
        if vid.is_vid_style(custom_id) or vid.is_vid_voice(custom_id):
            values = data.get("values") or []
            if not values:
                return {"type": DEFERRED_UPDATE_MESSAGE}
            is_style = vid.is_vid_style(custom_id)
            job_id = vid.job_from_style(custom_id) if is_style else vid.job_from_voice(custom_id)
            field = {"style": values[0]} if is_style else {"voice": values[0]}
            self._spawn(self._run_video_set(payload, job_id, field))
            return {"type": DEFERRED_UPDATE_MESSAGE}
        if vid.is_vid_generate(custom_id):
            try:
                job_id = vid.job_from_generate(custom_id)
            except ValueError:
                return {"type": DEFERRED_UPDATE_MESSAGE}
            return await self._handle_panel_route(
                payload, lambda ctx: self.router.run_video_generate(ctx, job_id),
                raw_text="video generate", ephemeral=True)
        if vid.is_vid_refine(custom_id):
            try:
                job_id = vid.job_from_refine(custom_id)
            except ValueError:
                return {"type": DEFERRED_UPDATE_MESSAGE}
            return {"type": MODAL, "data": vid.build_refine_modal(job_id)}
        if vid.is_vid_apply(custom_id):
            try:
                job_id = vid.job_from_apply(custom_id)
            except ValueError:
                return {"type": DEFERRED_UPDATE_MESSAGE}
            return await self._handle_panel_route(
                payload, lambda ctx: self.router.run_video_apply(ctx, job_id),
                raw_text="video apply", ephemeral=True)
        if vid.is_vid_version(custom_id):
            values = data.get("values") or []
            if not values:
                return {"type": DEFERRED_UPDATE_MESSAGE}
            try:
                job_id = vid.job_from_version(custom_id)
                version_no = int(values[0])
            except ValueError:
                return {"type": DEFERRED_UPDATE_MESSAGE}
            return await self._handle_panel_route(
                payload, lambda ctx: self.router.run_video_revert(ctx, job_id, version_no),
                raw_text="video revert", ephemeral=True)
```

This assumes `_handle_panel_route(payload, fn, *, raw_text, ephemeral=False)` exists. Verify its signature in `discord_commands.py`; it is used widely (e.g. line 270, 330). If it lacks an `ephemeral` kwarg, route generate/apply/revert through the same closure pattern as `_open_and_build` instead (build a ctx with `notify_channel`/`notify_channel_rich` bound to the thread `channel_id`, `_spawn` the runner, return `{"type": DEFERRED_CHANNEL_MESSAGE, "data": {"flags": 64}}`). The runners need `notify_channel` set so the watcher can post — `_handle_panel_route` must bind `notify_channel`; confirm it does (it builds a ctx like `_handle_application_command`). If it doesn't bind `notify_channel`, use the `_open_and_build`-style inline ctx for generate/apply/revert.

- [ ] **Step 4: `_handle_video_new` + `_run_video_set`** — the studio-open flow (model on `_handle_build_modal_submit`)

```python
    async def _handle_video_new(self, payload: dict[str, Any]) -> dict[str, Any]:
        """New video button -> open the Title+Prompt modal (synchronous)."""
        return {"type": MODAL, "data": vid.build_video_modal()}

    async def _run_video_set(self, payload: dict[str, Any], job_id: str, field: dict) -> None:
        member = payload.get("member", {})
        user = member.get("user", payload.get("user", {}))
        ctx = CommandContext(
            user_id=user.get("id", ""), user_name=user.get("username", "unknown"),
            channel_id=payload.get("channel_id", ""), raw_text="video set",
            subcommand="video", arguments="", platform="discord",
            respond=lambda m: asyncio.sleep(0))
        await self.router.run_video_set_field(ctx, job_id, **field)
```

- [ ] **Step 5: Modal-submit branches** — insert in `_handle_modal_submit` before the `if not is_panel_modal(custom_id):` catch-all (line ~837)

```python
        if vid.is_vid_new_modal(custom_id):
            return await self._handle_video_new_modal(payload)
        if vid.is_vid_refine_modal(custom_id):
            try:
                job_id = vid.job_from_refine_modal(custom_id)
            except ValueError:
                return {"type": DEFERRED_UPDATE_MESSAGE}
            change = self._extract_modal_value(data, vid.REFINE_INPUT)
            return await self._handle_panel_route(
                payload, lambda ctx: self.router.run_video_refine(ctx, job_id, change),
                raw_text="video refine")
```

- [ ] **Step 6: `_handle_video_new_modal`** — create the draft, open the video thread, post the studio message (model on `_open_and_build`)

```python
    async def _handle_video_new_modal(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = payload.get("data", {})
        title = self._extract_modal_value(data, vid.TITLE_INPUT)
        prompt = self._extract_modal_value(data, vid.PROMPT_INPUT)
        interaction_token = payload.get("token", "")
        member = payload.get("member", {})
        user = member.get("user", payload.get("user", {}))
        user_id = user.get("id", "")
        user_name = user.get("username", "unknown")
        channel_id = payload.get("channel_id", "")

        async def _open_studio() -> None:
            try:
                email = await self.router._resolve_email(user_id)
                if not email:
                    await self.discord.edit_original(
                        interaction_token=interaction_token,
                        content=onboarding.not_linked_text_discord(),
                        components=onboarding.link_button_row())
                    return
                draft = await self.router._tasks_client.create_video_draft(
                    email, title, prompt, "clean_product_demo", "amy")
                job_id = draft["id"]
                thread_id = await self._get_or_make_thread(
                    user_id, channel_id, user_name, kind="video")
                target = thread_id or channel_id
                if thread_id:
                    await self.discord.edit_original(
                        interaction_token=interaction_token,
                        content=f"Opening your video studio → <#{thread_id}>")
                else:
                    await self.discord.edit_original(
                        interaction_token=interaction_token,
                        content="Couldn't open a private thread; using this channel.")
                voices = (await self.router._tasks_client.get_video_voices()).get("voices", [])
                # Post the 6 voice samples as attachments (best-effort).
                try:
                    files = []
                    for v in voices:
                        sample = v.get("sample_url") or ""
                        if sample:
                            blob = await self.router._tasks_client.fetch_bytes(sample)
                            files.append((f"{v.get('id','voice')}.mp3", blob, "audio/mpeg"))
                    if files:
                        await self.discord.post_channel_file(
                            target, files[:10],
                            content="Voice previews — pick one in the menu below.")
                except Exception as exc:  # noqa: BLE001
                    logger.warning("voice sample post failed: %s", exc)
                await self.discord.post_channel_message(
                    target,
                    f"**{title}** — pick a style + voice, then add screenshots with "
                    "`/video add` (run it here), then click Generate.",
                    components=vid.build_studio_components(job_id, voices))
            except Exception as exc:  # noqa: BLE001
                logger.error("_open_studio failed user=%s: %s", user_id, exc)

        self._spawn(_open_studio())
        return {"type": DEFERRED_CHANNEL_MESSAGE, "data": {"flags": 64}}
```

- [ ] **Step 7: `/video` application-command dispatch** — at the top of `_handle_application_command` (line ~174), after `data = payload.get("data", {})`, add:

```python
        if data.get("name") == "video":
            return await self._handle_video_command(payload)
```

And add the handler:

```python
    async def _handle_video_command(self, payload: dict[str, Any]) -> dict[str, Any]:
        """`/video add <shot1..>` (attachments) and `/video list`."""
        data = payload.get("data", {})
        options = data.get("options", [])
        sub = options[0].get("name") if options else "list"
        interaction_token = payload.get("token", "")
        member = payload.get("member", {})
        user = member.get("user", payload.get("user", {}))
        channel_id = payload.get("channel_id", "")
        notify_channel, notify_channel_rich = self._channel_notifiers(channel_id)

        async def respond(msg: str) -> None:
            await self.discord.edit_original(interaction_token=interaction_token, content=msg)

        async def respond_components(msg: str, components: list, embeds: list | None = None) -> None:
            await self.discord.edit_original(
                interaction_token=interaction_token, content=msg, components=components)

        ctx = CommandContext(
            user_id=user.get("id", ""), user_name=user.get("username", "unknown"),
            channel_id=channel_id, raw_text=f"video {sub}", subcommand="video",
            arguments="", platform="discord", respond=respond,
            respond_components=respond_components,
            metadata={"interaction_token": interaction_token,
                      "guild_id": payload.get("guild_id", "")},
            notify_channel=notify_channel if channel_id else None,
            notify_channel_rich=notify_channel_rich if channel_id else None)

        if sub == "add":
            urls = [a["url"] for a in self._all_attachments(data) if a.get("url")]
            self._spawn(self.router.run_video_add(ctx, urls))
        else:
            self._spawn(self.router.run_video_list(ctx))
        return {"type": DEFERRED_CHANNEL_MESSAGE, "data": {"flags": 64}}
```

- [ ] **Step 8: Write the failing tests** (component dispatch returns the right type; `/video add` collects attachments)

```python
# webhook-handler/tests/test_video_routing.py
import pytest
from handlers.discord_commands import DiscordCommandHandler, MODAL, DEFERRED_CHANNEL_MESSAGE
from handlers import video_panel as vid


class _Router:
    def __init__(self): self.calls = []
    async def run_video_add(self, ctx, urls): self.calls.append(("add", urls))
    async def run_video_list(self, ctx): self.calls.append(("list",))


def _handler():
    h = DiscordCommandHandler.__new__(DiscordCommandHandler)
    h.router = _Router()
    h._bg_tasks = set()
    def _spawn(coro):
        import asyncio
        t = asyncio.ensure_future(coro); h._bg_tasks.add(t); return t
    h._spawn = _spawn
    return h


def test_new_button_opens_modal():
    h = _handler()
    import asyncio
    out = asyncio.get_event_loop().run_until_complete(
        h._handle_message_component({"data": {"custom_id": vid.NEW_ID}}))
    assert out["type"] == MODAL
    assert out["data"]["custom_id"] == vid.NEW_MODAL_ID


@pytest.mark.asyncio
async def test_video_add_collects_attachments():
    h = _handler()

    class _D:
        async def edit_original(self, **k): pass
    h.discord = _D()
    h._channel_notifiers = lambda cid: (None, None)
    payload = {"data": {"name": "video", "options": [{"name": "add", "type": 1}],
               "resolved": {"attachments": {
                   "1": {"url": "https://cdn.discordapp.com/a.png", "filename": "a.png"},
                   "2": {"url": "https://cdn.discordapp.com/b.png", "filename": "b.png"}}}},
               "token": "t", "channel_id": "c", "member": {"user": {"id": "9", "username": "u"}}}
    out = await h._handle_application_command(payload)
    assert out["type"] == DEFERRED_CHANNEL_MESSAGE
    # let the spawned task run
    import asyncio
    await asyncio.gather(*h._bg_tasks)
    assert h.router.calls == [("add", ["https://cdn.discordapp.com/a.png",
                                       "https://cdn.discordapp.com/b.png"])]
```

- [ ] **Step 9: Run** `cd webhook-handler && python -m pytest tests/test_video_routing.py -v` → PASS. **Step 10: Commit**

```bash
git add webhook-handler/handlers/discord_commands.py webhook-handler/tests/test_video_routing.py
git commit -m "feat(video): route aiuivid:* + /video slash command"
```

---

### Task B6: Register the `/video` slash command

**Files:**
- Modify: `scripts/register_discord_commands.py`
- Test: `webhook-handler/tests/test_register_video_command.py`

- [ ] **Step 1: Add `build_video_command_payload` + include it in the PUT.** After `build_command_payload` (line ~75):

```python
def build_video_command_payload() -> dict:
    """A top-level /video command: `add` (up to 10 screenshot attachments) and
    `list`. Subcommands mirror the /aiui structure (type SUB_COMMAND)."""
    shot_opts = [(f"shot{i}", f"Screenshot {i}", False, ATTACHMENT) for i in range(1, 11)]
    return {
        "name": "video",
        "description": "Generate narrated videos from screenshots",
        "options": [
            {"name": "add", "description": "Add screenshots to your current video",
             "type": SUB_COMMAND, "options": [_build_option(o) for o in shot_opts]},
            {"name": "list", "description": "List your videos",
             "type": SUB_COMMAND, "options": []},
        ],
    }
```

In `main()`, change the payload line (line ~95) to:

```python
    payload = [build_command_payload(), build_video_command_payload()]
```

- [ ] **Step 2: Write the failing test**

```python
# webhook-handler/tests/test_register_video_command.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts"))
import register_discord_commands as reg


def test_video_command_has_add_with_attachments():
    p = reg.build_video_command_payload()
    assert p["name"] == "video"
    add = next(o for o in p["options"] if o["name"] == "add")
    atts = [o for o in add["options"] if o["type"] == reg.ATTACHMENT]
    assert len(atts) == 10
    assert all(o["required"] is False for o in atts)
    assert any(o["name"] == "list" for o in p["options"])
```

- [ ] **Step 3: Run** → PASS. **Step 4: Commit**

```bash
git add scripts/register_discord_commands.py webhook-handler/tests/test_register_video_command.py
git commit -m "feat(video): register /video slash command (add + list)"
```

---

### Task B7: `setup_video_channel.py`

**Files:**
- Create: `webhook-handler/scripts/setup_video_channel.py`
- Test: `webhook-handler/tests/test_setup_video_channel.py`

- [ ] **Step 1: Write the script** (clone of `setup_recruiting_channel.py`)

```python
"""Create (or reuse) the Discord #video-generation channel and post its panel.

One-shot, idempotent. Usage:
    DISCORD_BOT_TOKEN=... DISCORD_GUILD_ID=... \
    [VIDEO_CHANNEL_ID=<snowflake>] [VIDEO_CHANNEL_NAME=video-generation] \
    python webhook-handler/scripts/setup_video_channel.py
The bot must be in the guild with Manage Channels + Send Messages.
"""
import os
import sys

import httpx

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
from handlers.video_panel import build_video_embed, build_video_panel  # noqa: E402

DISCORD_API = "https://discord.com/api/v10"
TEXT_CHANNEL = 0


def _find_channel(guild_id: str, name: str, headers: dict) -> str | None:
    with httpx.Client(timeout=30.0) as client:
        r = client.get(f"{DISCORD_API}/guilds/{guild_id}/channels", headers=headers)
    r.raise_for_status()
    for ch in r.json():
        if ch.get("type") == TEXT_CHANNEL and ch.get("name") == name:
            return ch["id"]
    return None


def _create_channel(guild_id: str, name: str, headers: dict) -> str:
    body = {"name": name, "type": TEXT_CHANNEL,
            "topic": "Generate narrated videos from screenshots with AIUI — use the panel below."}
    with httpx.Client(timeout=30.0) as client:
        r = client.post(f"{DISCORD_API}/guilds/{guild_id}/channels", headers=headers, json=body)
    r.raise_for_status()
    return r.json()["id"]


def _post_panel(channel_id: str, payload: dict, headers: dict) -> str:
    with httpx.Client(timeout=30.0) as client:
        r = client.post(f"{DISCORD_API}/channels/{channel_id}/messages", headers=headers, json=payload)
    r.raise_for_status()
    return r.json()["id"]


def _pin(channel_id: str, message_id: str, headers: dict) -> None:
    with httpx.Client(timeout=30.0) as client:
        r = client.put(f"{DISCORD_API}/channels/{channel_id}/pins/{message_id}", headers=headers)
    if r.status_code not in (200, 204):
        print(f"WARN: pin returned {r.status_code} {r.text}", file=sys.stderr)


def main() -> int:
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    guild_id = os.environ.get("DISCORD_GUILD_ID", "").strip()
    channel_id = os.environ.get("VIDEO_CHANNEL_ID", "").strip()
    channel_name = os.environ.get("VIDEO_CHANNEL_NAME", "video-generation").strip()
    if not token:
        print("ERROR: DISCORD_BOT_TOKEN must be set.", file=sys.stderr)
        return 1
    headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}
    payload = {**build_video_panel(), "embeds": [build_video_embed()]}
    try:
        if channel_id:
            print(f"Using channel ID from VIDEO_CHANNEL_ID: {channel_id}")
        else:
            if not guild_id:
                print("ERROR: DISCORD_GUILD_ID must be set when VIDEO_CHANNEL_ID is empty.",
                      file=sys.stderr)
                return 1
            found = _find_channel(guild_id, channel_name, headers)
            channel_id = found or _create_channel(guild_id, channel_name, headers)
            print(("Reusing" if found else "Created") + f" channel #{channel_name} ({channel_id})")
        message_id = _post_panel(channel_id, payload, headers)
        _pin(channel_id, message_id, headers)
    except httpx.HTTPStatusError as e:
        print(f"ERROR: Discord API {e.response.status_code}: {e.response.text}", file=sys.stderr)
        return 3
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 3
    print("OK — video panel posted and pinned.")
    print(f"Channel ID: {channel_id}  Message ID: {message_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Write the failing test** (the panel payload is well-formed)

```python
# webhook-handler/tests/test_setup_video_channel.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))


def test_payload_merges_panel_and_embed():
    import setup_video_channel as s
    from handlers.video_panel import build_video_panel, build_video_embed
    payload = {**build_video_panel(), "embeds": [build_video_embed()]}
    assert "components" in payload and payload["embeds"][0]["title"]
    assert s.DISCORD_API.endswith("/v10")
```

- [ ] **Step 3: Run** → PASS. **Step 4: Commit**

```bash
git add webhook-handler/scripts/setup_video_channel.py webhook-handler/tests/test_setup_video_channel.py
git commit -m "feat(video): setup_video_channel.py (create + post + pin panel)"
```

---

## Phase C — Wiring, public link routing, deploy

### Task C1: Caddy route + env for the no-login `share_url`

**Files:**
- Modify: `Caddyfile` (ensure `/tasks/api/video-jobs/*/download` reaches `tasks:8210` without the gateway/JWT)
- Modify: server `.env` (operator step — NOT committed): set `VIDEO_PUBLIC_BASE=https://ai-ui.coolestdomain.win/tasks` and (optional) `VIDEO_DISCORD_ATTACH_MAX_MB`, `VIDEO_URL_INTAKE_ALLOWED_HOSTS`.

- [ ] **Step 1: Inspect the Caddyfile** for the existing `/tasks/*` handling. Confirm whether `/tasks/api/video-jobs/{id}/download` already routes to `tasks:8210` (Caddy `uri strip_prefix /tasks`). If a generic `handle /tasks/*` already reverse-proxies to tasks with the strip, no change is needed. If only specific `/tasks/...` subpaths are routed, add:

```
handle /tasks/api/video-jobs/* {
    uri strip_prefix /tasks
    reverse_proxy tasks:8210
}
```

placed with the other `/tasks/*` handlers (before the catch-all that goes to Open WebUI). This bypasses the API gateway so the capability (`?cap=`) deep link works without a JWT.

- [ ] **Step 2: Add a routing test** (api-gateway test suite already has `test_tasks_routing.py`; add a Caddy-shape assertion only if a Caddy test harness exists — otherwise this is verified by the curl smoke in Task C2). Document the expectation in the commit message.

- [ ] **Step 3: Commit** (Caddyfile only)

```bash
git add Caddyfile
git commit -m "feat(video): route /tasks/api/video-jobs/*/download to tasks for no-login share links"
```

---

### Task C2: Deploy + verify

This task is run by an operator with SSH access; it is not a code change. Follow `CLAUDE.md` exactly.

- [ ] **Step 1: Ensure a clean tree and the branch is pushed/merged as the team requires.** The orchestrator refuses a dirty tree.

- [ ] **Step 2: Deploy the tasks service** (backend: migrations 025/026, routes_video, routes_discord_links, models, Caddyfile):

```bash
ORCH_HOST=46.224.193.25 ./scripts/deploy_orchestrator.sh
```

If rsync is unavailable locally (known: Git Bash lacks it), replicate manually: `scp` each changed file under `mcp-servers/tasks/` and the `Caddyfile` to `root@46.224.193.25:/root/proxy-server/...`, then `ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --build tasks caddy"`, and bump `.deploy-state`. Migrations 025/026 auto-run on tasks boot.

- [ ] **Step 3: Deploy webhook-handler** (MANUAL — orchestrator does not cover it). One `scp` per changed file (never `scp -r`):

```bash
scp webhook-handler/clients/tasks.py        root@46.224.193.25:/root/proxy-server/webhook-handler/clients/tasks.py
scp webhook-handler/clients/discord.py      root@46.224.193.25:/root/proxy-server/webhook-handler/clients/discord.py
scp webhook-handler/handlers/video_panel.py root@46.224.193.25:/root/proxy-server/webhook-handler/handlers/video_panel.py
scp webhook-handler/handlers/commands.py    root@46.224.193.25:/root/proxy-server/webhook-handler/handlers/commands.py
scp webhook-handler/handlers/discord_commands.py root@46.224.193.25:/root/proxy-server/webhook-handler/handlers/discord_commands.py
scp webhook-handler/main.py                 root@46.224.193.25:/root/proxy-server/webhook-handler/main.py
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --build webhook-handler"
```

- [ ] **Step 4: Register the `/video` command + create the channel** (one-time), inside the deployed container:

```bash
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml exec -e DISCORD_GUILD_ID=<guild> webhook-handler python /app/../scripts/register_discord_commands.py"
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml exec -e DISCORD_GUILD_ID=<guild> webhook-handler python /app/scripts/setup_video_channel.py"
```

(Adjust the `register_discord_commands.py` path to wherever repo-root `scripts/` lands in the image; if it isn't in the image, run it from a machine with `DISCORD_APPLICATION_ID`/`DISCORD_BOT_TOKEN`/`DISCORD_GUILD_ID` set.)

- [ ] **Step 5: Verify**

```bash
curl -fsS https://ai-ui.coolestdomain.win/tasks/healthz
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml ps webhook-handler"   # Up
# Smoke the new draft endpoint behind the gateway (needs a valid session/JWT); or hit tasks directly on the box:
ssh root@46.224.193.25 "curl -fsS -X POST localhost:8210/api/video-jobs/draft -H 'X-User-Email: you@aiui' -H 'Content-Type: application/json' -d '{\"title\":\"t\",\"prompt\":\"p\"}'"
```

- [ ] **Step 6: Live e2e** in Discord: New video → modal → studio thread (selects + 6 voice samples) → `/video add` with 1–2 screenshots → Generate → watch status → finished MP4 attached → Refine → Apply → Revert.

---

## Self-Review (completed by plan author)

- **Spec coverage:** §3 backend endpoints → A2/A3/A4/A5 + B1b (draft-set); migration → A1; video-thread → A6; §4 bot components → B2/B5; TasksClient → B1; `_watch_video`/runners → B4; file attach → B3; `/video` register → B6; setup script → B7; deploy → C2; share_url routing → C1/A5. All spec sections map to a task.
- **Placeholder scan:** none — every step has real code/commands. The one `NotImplementedError` placeholder in B1 Step 1 is explicitly removed in B1 Step 1b.
- **Type consistency:** custom_id prefixes (`aiuivid:*`), method names (`get_current_video_draft`, `set_video_draft_fields`, `download_video_bytes`, `post_channel_file`, `get_user_video_thread`), and the `share_url`/`queue_position`/`screenshot_count` field names are used identically across backend, client, panel, runners, and router.
- **Open risk flagged:** the no-login `share_url` depends on Caddy routing `/tasks/api/video-jobs/*/download` to tasks without the gateway (Task C1) — verified by curl in C2; if it can't be made to work, delivery still functions via inline attach for videos ≤ 24 MB, and the >24 MB case degrades to a "open in the web studio" message.
