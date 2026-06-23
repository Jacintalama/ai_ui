# Animated Video Engine — Phase 3 v1 (make `animated` a real render mode) Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use `- [ ]`.

**Goal:** A video job can carry `render_mode='animated'` and the live worker renders it in-container via the Phase-2 engine (video-only), with the slideshow path byte-identical.

**Architecture:** Add a `render_mode` column (migration + model) + a draft param. In `video_worker._process_job`, branch on `render_mode`: animated → `generate_anim_plan` + `render_animated_job` (in-container Chromium+ffmpeg); slideshow → existing `generate_plan` + `VideoRenderExecutor` (agent VM), unchanged. Narration (Piper in-container) + the web/Discord "Animated" toggle are deferred to 3b/3c.

**Tech Stack:** Python 3.11, SQLAlchemy, FastAPI, Playwright+ffmpeg (Phase 1), pytest.

All paths in `IO-integrate`, branch `fix/video-thread-image-intake`.

---

## Task 1: `render_mode` — migration, model, draft param

**Files:** Create `mcp-servers/tasks/migrations/027_video_render_mode.sql`; Modify `video_models.py`, `routes_video.py`; Test `tests/test_video_render_mode.py` (new) + `tests/test_routes_video_capture.py` reuse.

- [ ] **Step 1: Migration**

Create `mcp-servers/tasks/migrations/027_video_render_mode.sql`:
```sql
-- 027_video_render_mode.sql  (idempotent; db.py re-runs every migration each startup)
ALTER TABLE tasks.video_jobs
  ADD COLUMN IF NOT EXISTS render_mode TEXT NOT NULL DEFAULT 'slideshow';
```

- [ ] **Step 2: Model field**

In `video_models.py`, in `VideoJob` after the `voice` column:
```python
    voice = Column(Text, nullable=True)
    render_mode = Column(Text, nullable=False, default="slideshow")
```

- [ ] **Step 3: Failing test (DraftRequest accepts/validates render_mode)**

Create `mcp-servers/tasks/tests/test_video_render_mode.py`:
```python
import os
from cryptography.fernet import Fernet
os.environ.setdefault("AIUI_FERNET_KEY", Fernet.generate_key().decode())

from routes_video import DraftRequest  # noqa: E402
from video_models import VideoJob  # noqa: E402


def test_draft_request_render_mode_default_and_valid():
    assert DraftRequest().render_mode == "slideshow"
    assert DraftRequest(render_mode="animated").render_mode == "animated"


def test_draft_request_rejects_unknown_render_mode():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        DraftRequest(render_mode="claymation")


def test_video_job_has_render_mode_column():
    assert "render_mode" in VideoJob.__table__.columns
```

- [ ] **Step 4: Run (fails)**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_video_render_mode.py -q`
Expected: FAIL — `DraftRequest` has no `render_mode`.

- [ ] **Step 5: Implement — DraftRequest + create_draft persist render_mode**

In `routes_video.py`, find `class DraftRequest(BaseModel):` and add the field (it currently has title/prompt/style/voice):
```python
    render_mode: str = Field("slideshow", pattern="^(slideshow|animated)$")
```
In `create_draft`, add `render_mode=body.render_mode` to the `VideoJob(...)` insert values (alongside `style=body.style, voice=body.voice, status="collecting"`).

- [ ] **Step 6: Run (passes)**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_video_render_mode.py -q`
Expected: PASS (3 tests).

- [ ] **Step 7: Commit**

```bash
git add mcp-servers/tasks/migrations/027_video_render_mode.sql mcp-servers/tasks/video_models.py mcp-servers/tasks/routes_video.py mcp-servers/tasks/tests/test_video_render_mode.py
git commit -m "feat(video-anim): render_mode column + draft param (slideshow|animated)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `render_animated_job` helper

**Files:** Modify `mcp-servers/tasks/video_anim.py`; Modify `tests/test_video_anim.py`

- [ ] **Step 1: Failing test**

Append to `tests/test_video_anim.py`:
```python
async def test_render_animated_job_reads_shots_and_renders(tmp_path, monkeypatch):
    import video_anim
    captured = {}

    async def fake_render(html, out_path, *, fps=24, duration_s=8.0, audio_path=None,
                          width=1280, height=720):
        captured["html"] = html
        captured["out"] = out_path
        with open(out_path, "wb") as f:
            f.write(b"\x00\x00\x00\x18ftypmp42")  # tiny stub
        return int(duration_s * fps)

    monkeypatch.setattr(video_anim, "render_html_to_mp4", fake_render)
    slug, jid = "vid-x", "11111111-1111-1111-1111-111111111111"
    shots_dir = tmp_path / slug / ".video" / jid / "screenshots"
    shots_dir.mkdir(parents=True)
    (shots_dir / "screenshot-1.png").write_bytes(_png())
    plan = {"title": "t", "narration_script": "", "scenes": [
        {"kind": "screenshot", "screenshot": "screenshot-1.png", "headline": "h",
         "motion": "zoom-in", "duration_s": 3.0}]}
    out = await video_anim.render_animated_job(str(tmp_path), slug, jid, plan)
    assert out.endswith("out.mp4") and os.path.exists(out)
    assert "data:image/png;base64," in captured["html"]   # the shot was embedded
```

- [ ] **Step 2: Run (fails)**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_video_anim.py::test_render_animated_job_reads_shots_and_renders -q`
Expected: FAIL — no `render_animated_job`.

- [ ] **Step 3: Implement**

In `video_anim.py`, after `render_html_to_mp4`:
```python
async def render_animated_job(apps_dir: str, slug: str, job_id: str, plan: dict,
                              *, fps: int = 24) -> str:
    """Render an animated job's plan to out.mp4 in-container: read the job's
    screenshots from disk, build the composition, render via Chromium+ffmpeg.
    Returns the output path. (Video-only in v1; audio is a fast-follow.)"""
    shots_dir = os.path.join(apps_dir, slug, ".video", job_id, "screenshots")
    shots: dict[str, bytes] = {}
    if os.path.isdir(shots_dir):
        for name in sorted(os.listdir(shots_dir)):
            p = os.path.join(shots_dir, name)
            if os.path.isfile(p):
                with open(p, "rb") as f:
                    shots[name] = f.read()
    html = build_composition(plan, shots)
    out = os.path.join(apps_dir, slug, ".video", job_id, "out.mp4")
    dur = min(MAX_DURATION_S, composition_duration(plan) or 8.0)
    await render_html_to_mp4(html, out, fps=fps, duration_s=dur)
    return out
```

- [ ] **Step 4: Run (passes)** — `python -m pytest tests/test_video_anim.py -q` → PASS (real-render still skips).

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/video_anim.py mcp-servers/tasks/tests/test_video_anim.py
git commit -m "feat(video-anim): render_animated_job (read shots -> compose -> render in-container)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Worker branch on `render_mode`

**Files:** Modify `mcp-servers/tasks/video_worker.py`

- [ ] **Step 1: Add imports**

In `video_worker.py`, alongside `from video_plan import generate_plan`:
```python
from video_plan import generate_plan, generate_anim_plan
from video_anim import render_animated_job
```

- [ ] **Step 2: Branch in `_process_job`**

In `_process_job`, change the job-field read to include render_mode:
```python
            slug, prompt, plan, pending_summary = job.slug, job.prompt, job.plan_json, job.pending_summary
            style = job.style
            voice = job.voice
            render_mode = job.render_mode
```
In Stage 1 (scripting), pick the generator by mode:
```python
            plan = await (generate_anim_plan(prompt, screenshots) if render_mode == "animated"
                          else generate_plan(prompt, screenshots))
```
In Stage 2 (rendering), branch the render:
```python
        if render_mode == "animated":
            out = await render_animated_job(APPS_DIR, slug, str(job_id), plan)
        else:
            out = await VideoRenderExecutor().render(slug, str(job_id), plan, style=style, voice=voice)
```
(Everything else — gates, heavy_lock, versioning, done/failed — is unchanged, so the slideshow path is byte-identical.)

- [ ] **Step 3: Sanity import + full tasks video tests**

Run: `cd mcp-servers/tasks && python -c "import video_worker" && python -m pytest tests/test_video_worker.py tests/test_video_anim.py tests/test_video_plan.py tests/test_video_render_mode.py -q`
Expected: import OK; tests PASS (real-render/DB skip offline).

- [ ] **Step 4: Commit**

```bash
git add mcp-servers/tasks/video_worker.py
git commit -m "feat(video-anim): worker renders render_mode=animated in-container (slideshow unchanged)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Deploy + real-worker e2e

**Files:** none.

- [ ] **Step 1: Drift-check + scp + rebuild**

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO-integrate"
for f in video_models.py routes_video.py video_anim.py video_worker.py; do
  git show HEAD~3:mcp-servers/tasks/$f 2>/dev/null | tr -d '\r' | sha256sum | cut -c1-16
  ssh root@46.224.193.25 "tr -d '\r' < /root/proxy-server/mcp-servers/tasks/$f | sha256sum | cut -c1-16"
done   # pairs should match (server = last-deployed) for files unchanged since; investigate any DIFF
scp mcp-servers/tasks/migrations/027_video_render_mode.sql root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/migrations/027_video_render_mode.sql
for f in video_models.py routes_video.py video_anim.py video_worker.py; do scp mcp-servers/tasks/$f root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/$f; done
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --build tasks 2>&1 | tail -5"   # background if slow; migration 027 auto-runs on boot
```

- [ ] **Step 2: Confirm migration applied + healthz**

```bash
ssh root@46.224.193.25 'cd /root/proxy-server && docker compose -f docker-compose.unified.yml exec -T postgres psql -U postgres -d aiui_tasks -c "select column_name from information_schema.columns where table_schema=\"tasks\" and table_name=\"video_jobs\" and column_name=\"render_mode\";" 2>/dev/null; curl -fsS https://ai-ui.coolestdomain.win/tasks/healthz'
```
(If the psql db/user differ, use the tasks app: `docker exec -i <tasks> python -` importing `db.session` + a select on `information_schema`.)
Expected: `render_mode` row present; healthz ok.

- [ ] **Step 3: Real-worker e2e (animated job through the live pipeline)**

Pipe a script into the tasks container that: creates an animated draft (via the app DB or `POST /draft` with X-User-Email + render_mode='animated'), drops a screenshot on disk, queues it, then polls until done and reports status + output_path. Concretely use the HTTP API in-container:
```bash
ssh root@46.224.193.25 'cd /root/proxy-server && CID=$(docker compose -f docker-compose.unified.yml ps -q tasks) && docker exec -i "$CID" python -' <<'PY'
import asyncio, io, time, httpx
from PIL import Image
H={"X-User-Email":"anim-e2e@aiui.local"}
base="http://localhost:8210/api/video-jobs"
def png():
    b=io.BytesIO(); Image.new("RGB",(1200,750),(30,90,180)).save(b,"PNG"); return b.getvalue()
with httpx.Client(timeout=120) as c:
    d=c.post(base+"/draft",headers=H,json={"title":"Anim E2E","prompt":"Walk through my portfolio","style":"clean_product_demo","voice":"amy","render_mode":"animated"}); jid=d.json()["id"]
    # add a screenshot via the disk-backed upload endpoint
    c.post(f"{base}/{jid}/screenshots",headers=H,files=[("files",("s1.png",png(),"image/png"))])
    q=c.post(f"{base}/{jid}/queue",headers=H); print("queue",q.status_code,q.text[:120])
    for _ in range(30):
        j=c.get(f"{base}/{jid}",headers=H).json(); st=j["status"]
        if st in ("done","failed"): print("FINAL",st,"out=",j.get("output_available")); break
        time.sleep(8)
PY
```
Expected: `queue 200` then `FINAL done out= True` — an animated job rendered by the LIVE worker. Confirm a slideshow job still works too (regression check): create one WITHOUT render_mode and confirm it reaches done.

- [ ] **Step 4: Push branch + main**

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO-integrate"
gh auth switch -u Jacintalama && git push fork fix/video-thread-image-intake && git push fork HEAD:main
```

---

## Deferred to Phase 3b/3c
- **Narration** in animated renders (Piper in the tasks container; `render_html_to_mp4` already accepts `audio_path`).
- **UI surfacing:** an "Animated" toggle in the web create page + Discord (pass `render_mode` to `/draft`).
- **Refine on animated jobs** (the refine path assumes slideshow plans).

## Self-Review
- **Spec coverage:** render_mode (T1), in-container animated render helper (T2), worker branch keeping slideshow byte-identical (T3), real-worker e2e + slideshow regression check (T4). Phase-3 narration + UI explicitly deferred. ✓
- **Placeholders:** none. ✓
- **Name consistency:** `render_mode`, `generate_anim_plan`, `render_animated_job`, `build_composition`, `composition_duration`, `DraftRequest.render_mode` consistent across model/migration/endpoint/worker/tests. ✓
