# Video Studio Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-card delete control to the web Video Studio, and upgrade the kinetic animated renderer to read as a pro motion-graphics piece (real font, kinetic typography, browser-chrome frame, background depth + always-on motion, ffmpeg-synth ambient music).

**Architecture:** Two independent parts shipped by one tasks-service rebuild. Part B (delete) is a new `DELETE /api/video-jobs/{job_id}` FastAPI route + a trash `<span>` in the existing list-card JS. Part A (renderer) is changes to `video_anim.py` (HTML composition + ffmpeg arg builder), a `Dockerfile` font layer, and a one-line capture-route fix so the site host is persisted for the address pill. All offline-testable except the real-render visual pass.

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy async / Postgres (`tasks` schema), pytest + httpx ASGITransport, Playwright headless Chromium + ffmpeg (in-container), vanilla JS/HTML static page, Docker (python:3.11-slim / bookworm).

**Spec:** `docs/superpowers/specs/2026-06-25-video-studio-polish-design.md`

**Branch:** `feat/video-studio-polish` (already created, off origin/main; spec committed).

**Working dir for all commands:** `cd "C:/All/Work - Code/ai_ui/mcp-servers/tasks"` (the tasks service). Tests run from there: `python -m pytest tests/<file> -v`.

**Note on Reads:** a memory hook truncates `Read` to line 1 on several of these files. Use `Grep` with context (`-C`/`-A`) to view content; `Edit` still works because the harness registers the file as read.

---

## Build order

Part B first (Tasks 1-2) — small, unblocks the user's immediate ask. Then Part A (Tasks 3-9). Commit after every task.

---

## Part B: Delete icon on the web Video Studio

### Task 1: Backend `DELETE /api/video-jobs/{job_id}`

**Files:**
- Modify: `mcp-servers/tasks/routes_video.py` (add `import shutil`; add the delete route after the `GET /{job_id}` handler that ends at ~line 420)
- Test: `mcp-servers/tasks/tests/test_routes_video_delete.py` (create)

Mirror the existing `job_status` handler (`routes_video.py:361-420`) for ownership/404, the write handlers (e.g. `:200-203`) for the `session()` + `commit()` pattern, and the on-disk layout `_apps_dir()/slug/".video"/str(job_id)` (`:273`).

- [ ] **Step 1: Write the failing tests**

Create `mcp-servers/tasks/tests/test_routes_video_delete.py`:

```python
"""Tests for DELETE /api/video-jobs/{job_id}.

The route-registration and missing-auth (401) tests run offline (the auth guard
fires during dependency resolution, before any DB call). The owner/non-owner/
admin/404 happy paths need a real Postgres and are skipped offline (run at
deploy/CI), mirroring test_routes_video_status.py.
"""
import os
import uuid

import pytest
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("AIUI_FERNET_KEY", Fernet.generate_key().decode())

from main import app  # noqa: E402
from video_models import VideoJob  # noqa: E402

ADMIN = {"X-User-Email": "ralph@aiui.com", "X-User-Admin": "true"}
OWNER = {"X-User-Email": "owner@x.com", "X-User-Admin": "false"}
OTHER = {"X-User-Email": "other@x.com", "X-User-Admin": "false"}

_DB_URL = os.environ.get("DATABASE_URL", "")
_HAVE_DB = bool(_DB_URL) and "nowhere" not in _DB_URL


def test_delete_route_registered():
    """The job path supports the DELETE method."""
    methods = set()
    for r in app.routes:
        if getattr(r, "path", None) == "/api/video-jobs/{job_id}":
            methods |= set(getattr(r, "methods", set()) or set())
    assert "DELETE" in methods


async def test_delete_requires_auth():
    """No gateway identity headers -> 401 before any DB call."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.delete(f"/api/video-jobs/{uuid.uuid4()}")
    assert r.status_code == 401


@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_delete_owner_removes_row_and_dir(db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("APPS_DIR", str(tmp_path))
    job_id = uuid.uuid4()
    db_session.add(VideoJob(id=job_id, slug="alpha", user_email="owner@x.com",
                            prompt="p", status="done"))
    await db_session.commit()
    job_dir = tmp_path / "alpha" / ".video" / str(job_id)
    (job_dir / "screenshots").mkdir(parents=True)
    (job_dir / "screenshots" / "screenshot-1.png").write_bytes(b"x")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.delete(f"/api/video-jobs/{job_id}", headers=OWNER)
    assert r.status_code == 200
    assert r.json()["status"] == "deleted"
    assert not job_dir.exists()
    assert await db_session.get(VideoJob, job_id) is None


@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_delete_non_owner_forbidden(db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("APPS_DIR", str(tmp_path))
    job_id = uuid.uuid4()
    db_session.add(VideoJob(id=job_id, slug="alpha", user_email="owner@x.com",
                            prompt="p", status="done"))
    await db_session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.delete(f"/api/video-jobs/{job_id}", headers=OTHER)
    assert r.status_code == 403
    assert await db_session.get(VideoJob, job_id) is not None  # untouched


@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_delete_admin_can_delete_any(db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("APPS_DIR", str(tmp_path))
    job_id = uuid.uuid4()
    db_session.add(VideoJob(id=job_id, slug="alpha", user_email="owner@x.com",
                            prompt="p", status="done"))
    await db_session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.delete(f"/api/video-jobs/{job_id}", headers=ADMIN)
    assert r.status_code == 200


@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_delete_unknown_job_404(db_session):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.delete(f"/api/video-jobs/{uuid.uuid4()}", headers=ADMIN)
    assert r.status_code == 404
```

- [ ] **Step 2: Run the offline tests to verify they fail**

Run: `python -m pytest tests/test_routes_video_delete.py -v`
Expected: `test_delete_route_registered` FAILS (no DELETE method yet); `test_delete_requires_auth` FAILS with 405 (method not allowed). DB tests SKIP.

- [ ] **Step 3: Add `import shutil`**

In `routes_video.py`, add `import shutil` to the stdlib import block (alphabetical, after `import re` / near the other stdlib imports around lines 31-66). It is NOT currently imported.

- [ ] **Step 4: Add the DELETE handler**

Insert after the `GET /{job_id}/download` block is fine, but simplest is right after the `job_status` handler (ends ~line 420). Use the project's commuted ownership form (`not user.is_admin and job.user_email != user.email`) to match the file:

```python
@router.delete("/{job_id}")
async def delete_video_job(
    job_id: str,
    user: CurrentUser = Depends(current_user),
) -> dict:
    """Delete one video job: its DB row (video_job_versions cascade via the FK's
    ON DELETE CASCADE) and its on-disk job dir. Owner-or-admin only.

    Auth: any logged-in gateway identity (401 with no identity). A user may
    delete only their own video; an admin may delete anyone's (403 otherwise).
    A malformed or unknown id is a 404.
    """
    jid = _coerce_job_id(job_id)
    async with session() as s:
        job = await s.get(VideoJob, jid)
        if job is None:
            raise HTTPException(status_code=404, detail="Video job not found")
        if not user.is_admin and job.user_email != user.email:
            raise HTTPException(403, "Not authorized for this video")
        slug = job.slug
        try:
            await s.delete(job)
            await s.commit()
            shutil.rmtree(
                _apps_dir() / slug / ".video" / str(jid), ignore_errors=True)
        except Exception:  # noqa: BLE001 - surface a clean 500, not a stack trace
            logger.exception("failed to delete video job=%s", jid)
            raise HTTPException(500, "could not delete that video")
    return {"status": "deleted"}
```

Note: DB delete first (so the FK CASCADE fires on commit), then disk (`ignore_errors=True` so a missing dir is fine). `logger` already exists in the module.

- [ ] **Step 5: Run the offline tests to verify they pass**

Run: `python -m pytest tests/test_routes_video_delete.py -v`
Expected: `test_delete_route_registered` PASS, `test_delete_requires_auth` PASS (401), DB tests SKIP.

- [ ] **Step 6: Run the full video route suite (no regressions)**

Run: `python -m pytest tests/test_routes_video_status.py tests/test_routes_video_delete.py -v`
Expected: all pass/skip, 0 failures.

- [ ] **Step 7: Commit**

```bash
git add mcp-servers/tasks/routes_video.py mcp-servers/tasks/tests/test_routes_video_delete.py
git commit -m "feat(video): delete endpoint for video jobs (owner-or-admin, row + dir)"
```

---

### Task 2: Frontend trash icon on each video card

**Files:**
- Modify: `mcp-servers/tasks/static/video.html` (the `.vc-meta` CSS at `:492-496`; the `renderVideoList` card builder at `:1486-1510`)

Static HTML/JS — verified by manual check, not a unit test. The card is a `<button>` (`:1489`), so the trash control MUST be a `<span role="button">` (nested `<button>` is invalid HTML) with `stopPropagation` so clicking it does not also `openJob`.

- [ ] **Step 1: Add the `.vc-del` CSS**

After the `.video-card .vc-date` rule (`:496`), add:

```css
    .video-card .vc-del {
      flex-shrink: 0; cursor: pointer; color: var(--muted);
      font-size: 14px; line-height: 1; padding: 4px; border-radius: 6px;
      transition: color 0.15s, background 0.15s;
    }
    .video-card .vc-del:hover { color: #ef4444; background: rgba(239,68,68,0.12); }
```

The `.vc-meta` row is already `justify-content: space-between` so add the trash as the last child; date and trash sit on the right. Wrap date+trash if needed, but appending the span keeps the badge left and pushes date+trash right via the flex gap. To keep date next to the trash (not pushed apart), wrap them: see Step 2.

- [ ] **Step 2: Add the trash span in `renderVideoList`**

In `renderVideoList` (`:1486-1510`), after the existing `meta.appendChild(date);` and before `card.appendChild(meta);`, append a trash span. Keep the status badge on the left and group date+trash on the right by appending the trash directly to `meta` (space-between already separates badge from the date/trash cluster; add a small `gap`). Replace the meta-build block:

```javascript
        const meta = document.createElement("div");
        meta.className = "vc-meta";
        meta.appendChild(statusBadge(v.status));

        const right = document.createElement("div");
        right.style.cssText = "display:flex;align-items:center;gap:8px;";
        const date = document.createElement("span");
        date.className = "vc-date";
        date.textContent = fmtDate(v.created_at);
        right.appendChild(date);

        const del = document.createElement("span");
        del.className = "vc-del";
        del.setAttribute("role", "button");
        del.setAttribute("title", "Delete");
        del.setAttribute("aria-label", "Delete video");
        del.textContent = "🗑";  // wastebasket emoji
        del.addEventListener("click", (ev) => deleteVideo(ev, v.id));
        right.appendChild(del);

        meta.appendChild(right);
        card.appendChild(meta);
```

- [ ] **Step 3: Add the `deleteVideo` handler**

Add a function near `openJob` (`:1472`) / `showList` (`:1515`):

```javascript
    async function deleteVideo(ev, id) {
      ev.stopPropagation();          // don't also open the job
      ev.preventDefault();
      if (!confirm("Delete this video? This cannot be undone.")) return;
      try {
        const r = await fetch(API + "/" + encodeURIComponent(id), {
          method: "DELETE", headers: authHeaders(), credentials: "include" });
        if (!r.ok) { alert("Could not delete that video."); return; }
        // Re-fetch the list so the zero-video case routes to the create form
        // (showList already falls back to resetToCreate when empty).
        await showList();
      } catch (e) {
        console.warn("[video] delete failed", e);
        alert("Could not delete that video.");
      }
    }
```

Using `await showList()` (rather than hand-removing the node) reuses the existing empty -> `resetToCreate()` routing at `:1525-1527`, so the last-card case is handled for free.

- [ ] **Step 4: Manual verification**

The page is static; no unit test. Verify the markup is well-formed (the `<span role="button">` is inside the card `<button>`, no nested `<button>`), `stopPropagation` is present, and the DELETE URL is `API + "/" + id`. (Live verification happens after deploy in Task 9.)

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/static/video.html
git commit -m "feat(video): trash icon on studio video cards (confirm + delete + refresh)"
```

---

## Part A: Kinetic renderer polish

### Task 3: Reliable font in the Docker image

**Files:**
- Modify: `mcp-servers/tasks/Dockerfile` (the apt-get RUN at `:4-9`)

The base `python:3.11-slim` (bookworm) has no fontconfig, so a bare `fc-cache` would be "command not found" and break the `&&` chain. Install `fontconfig` in the same apt list FIRST, plus `fonts-inter` (so the existing `font-family:Inter` resolves) and `fonts-liberation2` (fallback), then `fc-cache -f`.

- [ ] **Step 1: Extend the apt install line**

Change the package line (`:5`) and add `fc-cache` before `rm -rf`:

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates git openssh-client rsync ffmpeg \
        fontconfig fonts-inter fonts-liberation2 \
    && fc-cache -f \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g @anthropic-ai/claude-code \
    && rm -rf /var/lib/apt/lists/*
```

- [ ] **Step 2: Verify the package names resolve (build-time)**

This is verified when the image builds in Task 9. If `fonts-inter` is unavailable in the pinned repo, fall back to `fonts-roboto` (also bookworm) and update the CSS font-family accordingly. Do not silently drop the font.

- [ ] **Step 3: Commit**

```bash
git add mcp-servers/tasks/Dockerfile
git commit -m "build(video): install Inter + fontconfig so renderer text resolves in-container"
```

---

### Task 4: Persist the site host for the address pill

**Files:**
- Modify: `mcp-servers/tasks/routes_video.py` (the `capture_from_url` handler, the `site_context` write at `:801-808`)
- Test: `mcp-servers/tasks/tests/test_routes_video_capture.py` (add a DB-gated test)

`extract_site_context` returns only `{title, headings, meta_description}` — no host. The host is computed at `:801` (`urlparse(body.url).hostname`) but only used for filenames. Persist it so the composition's address pill can render.

- [ ] **Step 1: Add the failing test**

Append to `tests/test_routes_video_capture.py` (it already mocks `capture_site` and sets `APPS_DIR`):

```python
@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_capture_persists_host_in_site_context(db_session, tmp_path, monkeypatch):
    """The persisted site_context.json includes the site host for the address pill."""
    import json
    monkeypatch.setenv("APPS_DIR", str(tmp_path))

    async def fake_capture(url, *, max_frames=5):
        return [_png()], {"title": "Example"}

    monkeypatch.setattr(routes_video, "capture_site", fake_capture)
    # ... create a draft job owned by HEAD's user (mirror test_capture_endpoint_stores_frames
    # for the job row + slug), then POST capture-from-url with {"url": "https://example.com/x"}.
    # After a 200, read <APPS_DIR>/<slug>/.video/<jid>/site_context.json:
    #   ctx = json.loads(ctx_path.read_text())
    #   assert ctx["host"] == "example.com"
```

(Fill in the job-row setup by copying `test_capture_endpoint_stores_frames` directly above it — same slug/jid/owner wiring.)

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_routes_video_capture.py -k host -v`
Expected: SKIP offline (no DB). If a real DB is present, FAIL (no `host` key). If you cannot run with a DB locally, rely on the structural change + CI.

- [ ] **Step 3: Persist the host**

In `capture_from_url`, change the site_context write block (`:804-808`) to inject host (and url) before writing:

```python
    try:
        site_context = {**(site_context or {}), "host": host, "url": body.url}
        ctx_path = _apps_dir() / slug / ".video" / str(jid) / "site_context.json"
        ctx_path.write_text(json.dumps(site_context))
    except Exception:  # noqa: BLE001 - context is best-effort
        logger.warning("could not write site_context for job=%s", jid)
```

(`host` is already defined at `:801`.)

- [ ] **Step 4: Run the capture suite**

Run: `python -m pytest tests/test_routes_video_capture.py -v`
Expected: offline tests pass, DB tests skip (or pass with a DB), 0 failures.

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/routes_video.py mcp-servers/tasks/tests/test_routes_video_capture.py
git commit -m "feat(video): persist site host in site_context for the renderer address pill"
```

---

### Task 5: Polish `build_composition` (frame + kinetic type + depth)

**Files:**
- Modify: `mcp-servers/tasks/video_anim.py` (`build_composition` at `:87-147`)
- Test: `mcp-servers/tasks/tests/test_video_anim.py` (extend; KEEP the no-injection test at `:45`)

This is the visual core. Keep it deterministic and seek-safe (pure function of `t`), keep headline text out of markup (delivered via the existing `SCENES` JSON + JS `textContent`), and add a `site_context` keyword arg with a default so existing callers/tests keep working.

New signature:
```python
def build_composition(plan: dict, shots: dict[str, bytes],
                      *, width: int = 1280, height: int = 720,
                      site_context: dict | None = None) -> str:
```

Changes inside the returned HTML/CSS/JS:
1. **Background depth (CSS):** replace `background:#0b0b10` on `html,body` with a dark radial gradient + a soft radial glow layer behind the frame + a subtle grain/vignette overlay div. Keep `overflow:hidden`.
2. **Browser-chrome frame:** wrap `#img` in a `.frame` container with a `.bar` (3 traffic-light dots + an `.addr` pill). Set the `.addr` text from `site_context.host` via JS `textContent` (empty/omitted when absent). The frame sits on a padded stage (not full-bleed) with a large soft shadow.
3. **Type hierarchy:** add a small uppercase `.eyebrow` (kicker) element above/near the headline (text from `site_context.title` or a generic kicker, via `textContent`). Keep `#headline` bold/tight; keep `#subtext`.
4. **Kinetic typography (JS, NOT markup):** in `__seek`, split `sc.headline` into words at runtime and build per-word `<span>`s inside `H` (clear + rebuild on scene change, or build once per scene index and cache), each with a fade+rise offset = pure function of word index + scene progress `p`. Never interpolate words into the server-side HTML string (preserves the no-injection guarantee).
5. **Always-on Ken Burns + smoother easing:** layer a gentle scale ~1.0->1.06 + small drift on every screenshot scene on top of its chosen motion; use a smoother ease (e.g. smootherstep `p*p*p*(p*(6p-15)+10)`); tighten the fade envelope so scenes cross through the bg rather than hard-cutting.

- [ ] **Step 1: Add/adjust structural tests**

In `tests/test_video_anim.py`, KEEP `test_build_composition_is_deterministic_and_safe` (`:32-46`) as-is — it must still pass (no-injection, `window.__seek`, embedded data URI, duration). Add:

```python
def test_build_composition_has_frame_and_eyebrow_and_kinetic_words():
    from video_anim import build_composition
    plan = {"title": "Demo", "narration_script": "", "scenes": [
        {"kind": "screenshot", "screenshot": "screenshot-1.png",
         "headline": "Fast and clean", "motion": "zoom-in", "duration_s": 3.0}]}
    shots = {"screenshot-1.png": _png()}
    html = build_composition(plan, shots, site_context={"host": "example.com",
                                                        "title": "Example"})
    assert "window.__seek" in html
    assert "example.com" in html          # address pill host present
    assert "class=\"eyebrow\"" in html or "id=\"eyebrow\"" in html
    # Kinetic word-split is done in JS at runtime, NOT as literal markup spans.
    assert ".split(" in html              # the per-word splitter is present
    # Still injection-safe: headline text not in markup.
    assert "Fast and clean" not in html.split("<script")[0]


def test_build_composition_omits_host_when_absent():
    from video_anim import build_composition
    plan = {"title": "D", "narration_script": "", "scenes": [
        {"kind": "title", "headline": "Hi", "motion": "rise", "duration_s": 2.0}]}
    html = build_composition(plan, {})    # no site_context
    # Address pill renders but with no host text baked in.
    assert "example.com" not in html
```

- [ ] **Step 2: Run to verify the new tests fail**

Run: `python -m pytest tests/test_video_anim.py -v`
Expected: the two new tests FAIL (no frame/eyebrow/host yet); existing ones still pass.

- [ ] **Step 3: Implement the new `build_composition`**

Rewrite the function body. Keep `scenes`/`data` construction (`:92-107`) unchanged. Pass host/title/eyebrow as JSON-embedded values consumed via `textContent` (NOT f-string interpolation of user text into markup — the host/title come from site_context which is page-scraped, so still route through JSON+textContent to be safe). Add the CSS (gradient/glow/grain, `.frame`/`.bar`/`.addr`/`.eyebrow`) and the JS word-splitter + Ken Burns + smootherstep. Reference the existing `__seek` structure (`:128-146`).

- [ ] **Step 4: Run to verify all pass**

Run: `python -m pytest tests/test_video_anim.py -v`
Expected: all pass (including the kept no-injection test).

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/video_anim.py mcp-servers/tasks/tests/test_video_anim.py
git commit -m "feat(video): pro composition — browser frame, kinetic type, depth, Ken Burns"
```

---

### Task 6: Ambient music bed in `render_html_to_mp4`

**Files:**
- Modify: `mcp-servers/tasks/video_anim.py` (`render_html_to_mp4` ffmpeg arg build at `:197-206`; factor a pure helper)
- Test: `mcp-servers/tasks/tests/test_video_anim.py` (add a helper test)

Synthesize a soft ambient pad with ffmpeg lavfi (layered low sine + slow tremolo + lowpass + fade), mix UNDER narration when present (duck via low fixed level ~0.12 in amix, or sidechaincompress), play at moderate level when no narration. The bed is UNCONDITIONAL (always an audio stream) and the encode always uses `-shortest` against the finite PNG-sequence video.

CRITICAL constraints (from spec review):
- Do NOT change `render_html_to_mp4`'s signature — the `fake_render` stubs in tests pin it (`test_video_anim.py:77-78,110-111`). The bed is internal; `render_animated_job` still passes `audio_path=narration.wav` as today.
- The moment a `filter_complex` produces a named audio label you MUST add explicit `-map 0:v -map "[aout]"` (the current command relies on implicit mapping).
- Factor the ffmpeg argv construction into a pure helper so it is unit-testable without running ffmpeg.

- [ ] **Step 1: Write the helper test**

Add to `tests/test_video_anim.py`:

```python
def test_ffmpeg_args_include_ambient_and_mapping():
    from video_anim import _build_ffmpeg_args
    # With narration: ambient lavfi input + amix + explicit maps + shortest.
    args = _build_ffmpeg_args("frames/f%05d.png", "out.mp4", fps=24,
                              audio_path="narration.wav", duration_s=8.0)
    joined = " ".join(args)
    assert "lavfi" in joined                 # ambient synth input
    assert "amix" in joined                  # narration + bed mixed
    assert "-map" in joined and "[aout]" in joined
    assert "-shortest" in args

def test_ffmpeg_args_ambient_without_narration():
    from video_anim import _build_ffmpeg_args
    args = _build_ffmpeg_args("frames/f%05d.png", "out.mp4", fps=24,
                              audio_path=None, duration_s=8.0)
    joined = " ".join(args)
    assert "lavfi" in joined                 # bed plays even with no narration
    assert "-shortest" in args               # finite PNG video bounds the sine
    assert "-map" in joined and "[aout]" in joined
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_video_anim.py -k ffmpeg -v`
Expected: FAIL (`_build_ffmpeg_args` not defined).

- [ ] **Step 3: Implement `_build_ffmpeg_args` and use it**

Extract a module-level pure function that returns the argv list, building: input 0 = PNG sequence; input 1 = `-f lavfi -i <ambient sine graph>` (always); input 2 = narration file (only if `audio_path`); a `filter_complex` that produces `[aout]` (amix of narration+bed when narration present, else just the bed processed), with explicit `-map 0:v -map "[aout]"`, `-c:a aac -b:a 192k -shortest`, plus the existing video opts (`libx264 veryfast crf 21 yuv420p -r fps -threads 2 +faststart`). Keep `MAX_FPS`/duration clamping in `render_html_to_mp4`; call `_build_ffmpeg_args(...)` to get `args` in place of the inline list at `:198-206`.

Example ambient graph (tune in Task 8): `sine=frequency=110:sample_rate=44100,volume=0.18,tremolo=f=0.15:d=0.5,lowpass=f=600,afade=t=in:st=0:d=1.5`. Keep it simple (cheap on the 3.7GB box).

- [ ] **Step 4: Run to verify pass + no regressions**

Run: `python -m pytest tests/test_video_anim.py -v`
Expected: all pass, including the two `fake_render` job tests (signature unchanged) and the real-render test (still skips/passes).

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/video_anim.py mcp-servers/tasks/tests/test_video_anim.py
git commit -m "feat(video): ffmpeg-synth ambient music bed, ducked under narration"
```

---

### Task 7: Wire `site_context.json` into `render_animated_job`

**Files:**
- Modify: `mcp-servers/tasks/video_anim.py` (`render_animated_job` at `:243-263`)
- Test: `mcp-servers/tasks/tests/test_video_anim.py` (extend the existing job test)

- [ ] **Step 1: Add the failing assertion**

Extend `test_render_animated_job_reads_shots_and_renders` (`:73-95`) — write a `site_context.json` into the job dir and assert the host reaches the composition HTML:

```python
    # (add inside the test, after creating shots_dir)
    (tmp_path / slug / ".video" / jid / "site_context.json").write_text(
        '{"host": "example.com", "title": "Example"}')
    # (after the render call)
    assert "example.com" in captured["html"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_video_anim.py -k render_animated_job_reads -v`
Expected: FAIL (host not in html — not loaded yet).

- [ ] **Step 3: Load and pass site_context**

Currently `html = build_composition(...)` is at `:256` and `job_dir` is computed AFTER it at `:257`. Move the `job_dir` assignment up so it precedes the load, REMOVE the now-duplicate `job_dir` line at the old `:257`, load the context, and pass it. Note the module imports `json as _json` (`:14`) — there is no bare `json`, so call `_json.load`:

```python
    job_dir = os.path.join(apps_dir, slug, ".video", job_id)
    site_context: dict = {}
    ctx_path = os.path.join(job_dir, "site_context.json")
    if os.path.isfile(ctx_path):
        try:
            with open(ctx_path, encoding="utf-8") as f:
                site_context = _json.load(f)
        except Exception:  # noqa: BLE001 - context is best-effort
            site_context = {}
    html = build_composition(plan, shots, site_context=site_context)
```

After this, the existing `out = os.path.join(job_dir, "out.mp4")` line still works (job_dir now defined above it); delete the old standalone `job_dir = os.path.join(...)` that sat between build_composition and `out`.

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_video_anim.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/video_anim.py mcp-servers/tasks/tests/test_video_anim.py
git commit -m "feat(video): load site_context.json and feed host/title into the composition"
```

---

### Task 8: Visual iteration (real render, view a frame)

**Files:** none new — tune CSS/timings in `video_anim.py`.

Not a unit test; a build-time visual check done after the image is rebuilt (run inside the container during/after Task 9, or against a local Chromium+ffmpeg if available).

- [ ] **Step 1: Render one real animated job** (a captured URL job) on the box and extract a mid frame:

```bash
# in-container (after Task 9 build), pick a recent done animated job dir:
ffmpeg -y -ss 3 -i out.mp4 -frames:v 1 /tmp/frame.png
```

- [ ] **Step 2: View the frame** (scp it down or view via the studio). Check: font renders as Inter (not a generic fallback), browser frame + address pill look right, headline words stagger in, background has depth, screenshot drifts (Ken Burns), no clipping at 1280x720.
- [ ] **Step 3: Tune** sizes/colors/timings/ambient levels in `video_anim.py`; re-render; repeat (budget a few iterations).
- [ ] **Step 4: Confirm audio** stream exists: `ffprobe out.mp4` shows an aac audio stream.
- [ ] **Step 5: Commit any tuning**

```bash
git add mcp-servers/tasks/video_anim.py
git commit -m "polish(video): tune composition sizes/timings/ambient from rendered frames"
```

---

### Task 9: Deploy to the tasks service

Per CLAUDE.md + memory: drift-check container files vs git first (normalize CRLF with `tr -d '\r'`), upload LF via `git show HEAD:path | ssh -i ~/.ssh/aiui_vps -o IdentitiesOnly=yes root@46.224.193.25 "cat > /root/proxy-server/mcp-servers/tasks/path"` (<=3 files per ssh call), then rebuild. NEVER deploy `templates.py`. NEVER touch `.env`.

- [ ] **Step 1: Commit everything; ensure clean working tree** (deploy needs it).
- [ ] **Step 2: Drift-check** each changed file (`routes_video.py`, `static/video.html`, `video_anim.py`, `Dockerfile`) against the running container with `tr -d '\r' | sha256sum`. Expect them BEHIND, not drifted; investigate any drift before overwriting.
- [ ] **Step 3: Upload** the changed files (LF) via `git show HEAD:<path> | ssh ... "cat > <dest>"`, <=3 files per Bash call.
- [ ] **Step 4: Rebuild** (Dockerfile font layer makes a rebuild necessary):

```bash
ssh -i ~/.ssh/aiui_vps -o IdentitiesOnly=yes root@46.224.193.25 \
  "cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --build tasks"
```

- [ ] **Step 5: Verify health:** `curl -fsS https://ai-ui.coolestdomain.win/tasks/healthz`.
- [ ] **Step 6: Verify delete live:** open the studio, confirm the trash icon appears on cards, delete one (confirm dialog -> card gone; deleting the last routes to the create form).
- [ ] **Step 7: Verify renderer live:** generate one animated video from a URL; confirm the framed/typeset/music output looks pro (view a frame + `ffprobe` shows audio). Do Task 8's visual iteration here if not already done.
- [ ] **Step 8: Update memory** `project_video_branches_2026-06-24.md` with: renderer polish + web delete shipped, branch, deploy outcome.

---

## Notes / risks
- Font apt package name must exist in the bookworm repo — verified at build (Task 3 Step 2); fall back to `fonts-roboto` + CSS update if not.
- The ambient lavfi graph must stay cheap (the box has ~3.7GB RAM); keep the filtergraph simple and always pair the infinite sine with `-shortest`.
- Keep the no-HTML-injection guarantee: all dynamic text (headline, host, title) flows through JSON + JS `textContent`, never f-string-interpolated into markup. The `test_video_anim.py:45` assertion must stay green.
- `render_html_to_mp4`'s signature is frozen by the `fake_render` test stubs — the ambient bed is internal; do not add kwargs.
- Visual quality is judged by viewing rendered frames; budget a few iterations (Task 8).
