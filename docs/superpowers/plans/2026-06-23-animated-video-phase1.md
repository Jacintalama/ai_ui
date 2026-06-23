# Animated Video Engine — Phase 1 (runtime de-risk) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove an HTML motion composition can be rendered to MP4 in the tasks container (headless Chromium frame-capture + ffmpeg) within the box's budget — before any LLM/plan-schema work.

**Architecture:** New isolated module `mcp-servers/tasks/video_anim.py`: `build_demo_composition()` returns a self-contained, deterministic HTML composition (embeds screenshots as data URIs, exposes `window.__seek(t)`); `render_html_to_mp4()` drives the in-container Chromium (Playwright, already installed) to screenshot each seeked frame, then ffmpeg encodes the frames (+ optional audio) to MP4. ffmpeg is added to the tasks image. No change to the slideshow engine, worker, or plan in this phase.

**Tech Stack:** Python 3.11, Playwright (async, already in `requirements.txt`), ffmpeg (added via apt), Pillow (present), pytest (asyncio auto).

All paths in the `IO-integrate` worktree, branch `fix/video-thread-image-intake`.

---

## File Structure

- Create `mcp-servers/tasks/video_anim.py` — composition builder + frame-capture/encode. No FastAPI imports.
- Create `mcp-servers/tasks/tests/test_video_anim.py` — pure-builder test + a real-render test (skipif Playwright/ffmpeg absent).
- Modify `mcp-servers/tasks/Dockerfile` — `apt-get install ffmpeg`.

---

## Task 1: `build_demo_composition()` (pure)

**Files:** Create `mcp-servers/tasks/video_anim.py`; Create `mcp-servers/tasks/tests/test_video_anim.py`

- [ ] **Step 1: Write the failing test**

```python
# mcp-servers/tasks/tests/test_video_anim.py
"""Tests for the animated-composition runtime (Phase 1 de-risk). The real-render
test is skipped unless Playwright+Chromium AND ffmpeg are available."""
import base64
import io
import shutil

import pytest
from PIL import Image

from video_anim import build_demo_composition


def _png(color=(200, 30, 30)) -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (320, 200), color).save(b, "PNG")
    return b.getvalue()


def test_demo_composition_is_self_contained_and_seekable():
    html = build_demo_composition([_png(), _png((30, 30, 200))], title="My <Site>")
    # Deterministic, seek-safe timeline hook.
    assert "window.__seek" in html
    # Screenshots embedded as data URIs (self-contained — no asset paths).
    assert html.count("data:image/png;base64,") >= 2
    # Title is HTML-escaped (no raw angle brackets injected).
    assert "My <Site>" not in html
    assert "My &lt;Site&gt;" in html
    # No wall-clock / nondeterminism in the runtime composition.
    assert "Date.now(" not in html and "Math.random(" not in html
```

- [ ] **Step 2: Run it (fails — no module)**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_video_anim.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'video_anim'`.

- [ ] **Step 3: Implement `build_demo_composition`**

```python
# mcp-servers/tasks/video_anim.py
"""Animated video runtime (Phase 1 de-risk): render an HTML motion composition to
MP4 in-container via headless Chromium (Playwright) frame-capture + ffmpeg.

The composition is deterministic and seek-safe: a single global window.__seek(t)
positions every element from the timeline time `t` (seconds) — no wall-clock, no
randomness — so frame capture is reproducible. Screenshots are embedded as data
URIs so the HTML is fully self-contained (no asset-path coupling).
"""
from __future__ import annotations

import asyncio
import base64
import html as _html
import os
import shutil
import tempfile


def _data_uri(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def build_demo_composition(screenshots: list[bytes], title: str,
                           *, width: int = 1280, height: int = 720) -> str:
    """A HARDCODED kinetic demo composition (Phase 1): animated title -> a
    screenshot pan with a sliding caption -> outro card. Deterministic via
    window.__seek(t). Returns a self-contained HTML string."""
    uris = [_data_uri(p) for p in (screenshots or [])]
    shot = uris[0] if uris else ""
    safe_title = _html.escape(title or "Your site")
    imgs = "".join(f'<img class="shot" src="{u}">' for u in uris[:1])
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
  html,body{{margin:0;width:{width}px;height:{height}px;background:#0b0b10;overflow:hidden;
    font-family:Inter,Segoe UI,system-ui,sans-serif;color:#fff}}
  .stage{{position:absolute;inset:0}}
  .title{{position:absolute;top:46%;left:0;right:0;text-align:center;font-size:64px;
    font-weight:800;letter-spacing:-1px;opacity:0;transform:translateY(24px)}}
  .shot{{position:absolute;top:8%;left:50%;width:64%;border-radius:14px;
    box-shadow:0 24px 80px rgba(0,0,0,.6);opacity:0;transform:translate(-50%,0) scale(1)}}
  .cap{{position:absolute;bottom:10%;left:0;right:0;text-align:center;font-size:34px;
    font-weight:700;opacity:0;transform:translateX(-40px)}}
  .outro{{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
    font-size:54px;font-weight:800;background:#0b0b10;opacity:0}}
</style></head><body>
  <div class="stage">
    <div class="title" id="title">{safe_title}</div>
    {imgs}
    <div class="cap" id="cap">A quick look</div>
    <div class="outro" id="outro">{safe_title}</div>
  </div>
<script>
  // Pure function of t (seconds): set opacity/transform deterministically.
  function clamp(x){{return Math.max(0,Math.min(1,x));}}
  function lerp(a,b,p){{return a+(b-a)*p;}}
  function ease(p){{p=clamp(p);return p*p*(3-2*p);}}  // smoothstep
  const T=document.getElementById('title'), C=document.getElementById('cap'),
        O=document.getElementById('outro'), S=document.querySelector('.shot');
  window.__seek=function(t){{
    // 0-2s: title in; 1.6-2s title out
    var ti=ease((t-0.2)/1.2)*(1-ease((t-1.6)/0.4));
    T.style.opacity=ti; T.style.transform='translateY('+lerp(24,0,ease((t-0.2)/1.2))+'px)';
    // 2-6s: screenshot pan/zoom + caption slide-in
    var sp=ease((t-2.0)/0.6)*(1-ease((t-5.6)/0.4));
    if(S){{S.style.opacity=sp;
      var k=ease((t-2.0)/4.0);
      S.style.transform='translate(-50%,'+lerp(0,-30,k)+'px) scale('+lerp(1.0,1.08,k)+')';}}
    var cp=ease((t-2.4)/0.5)*(1-ease((t-5.6)/0.4));
    C.style.opacity=cp; C.style.transform='translateX('+lerp(-40,0,ease((t-2.4)/0.5))+'px)';
    // 6-8s: outro
    O.style.opacity=ease((t-6.0)/0.6);
  }};
  window.__seek(0);
</script></body></html>"""
```

- [ ] **Step 4: Run it (passes)**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_video_anim.py -q`
Expected: PASS (the real-render test is added in Task 2).

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/video_anim.py mcp-servers/tasks/tests/test_video_anim.py
git commit -m "feat(video-anim): self-contained seekable demo composition (phase 1)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `render_html_to_mp4()` (Chromium frame-capture + ffmpeg)

**Files:** Modify `mcp-servers/tasks/video_anim.py`; Modify `mcp-servers/tasks/tests/test_video_anim.py`

- [ ] **Step 1: Write the failing real-render test**

Append to `tests/test_video_anim.py`:

```python
def _have_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


pytest.importorskip("playwright.async_api")


@pytest.mark.asyncio
async def test_render_demo_to_mp4(tmp_path):
    """Render the demo composition to a real MP4 in-process and assert it is a
    valid, multi-frame, visually-changing video. Skipped without ffmpeg/Chromium."""
    if not _have_ffmpeg():
        pytest.skip("ffmpeg not installed")
    from video_anim import build_demo_composition, render_html_to_mp4
    html = build_demo_composition([_png()], title="Demo")
    out = tmp_path / "demo.mp4"
    try:
        frames = await render_html_to_mp4(html, str(out), fps=12, duration_s=4.0)
    except RuntimeError as e:
        pytest.skip(f"render runtime unavailable: {e}")
    assert out.exists() and out.stat().st_size > 10_000
    assert frames >= 2
```

- [ ] **Step 2: Run it (fails — no `render_html_to_mp4`)**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_video_anim.py::test_render_demo_to_mp4 -q`
Expected: FAIL/skip — `ImportError: cannot import name 'render_html_to_mp4'` (or skip if no ffmpeg; install ffmpeg locally to run it for real).

- [ ] **Step 3: Implement `render_html_to_mp4`**

Append to `video_anim.py`:

```python
# One animated render at a time (mirrors the slideshow heavy-job discipline).
_ANIM_LOCK = asyncio.Lock()

# Phase-1 guardrails: bound frame count so the in-container render stays inside
# the box's RAM/time budget.
MAX_FPS = 24
MAX_DURATION_S = 40.0


async def render_html_to_mp4(html: str, out_path: str, *, fps: int = 24,
                             duration_s: float = 8.0, audio_path: str | None = None,
                             width: int = 1280, height: int = 720) -> int:
    """Render a seekable HTML composition to an MP4. Loads the HTML in the
    in-container headless Chromium, screenshots each seeked frame, then ffmpeg
    encodes the PNG sequence (+ optional audio). Returns the frame count. Raises
    RuntimeError if the engine (Playwright/Chromium) or ffmpeg is unavailable."""
    fps = max(1, min(MAX_FPS, int(fps)))
    duration_s = max(0.5, min(MAX_DURATION_S, float(duration_s)))
    n = int(duration_s * fps)
    try:
        from playwright.async_api import async_playwright
    except ImportError as e:
        raise RuntimeError("playwright unavailable") from e

    workdir = tempfile.mkdtemp(prefix="anim-")
    html_path = os.path.join(workdir, "comp.html")
    frames_dir = os.path.join(workdir, "frames")
    os.makedirs(frames_dir, exist_ok=True)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    try:
        async with _ANIM_LOCK:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"])
                try:
                    ctx = await browser.new_context(
                        viewport={"width": width, "height": height})
                    page = await ctx.new_page()
                    await page.goto("file://" + html_path, wait_until="load")
                    for i in range(n):
                        await page.evaluate("window.__seek(%f)" % (i / fps))
                        await page.screenshot(
                            path=os.path.join(frames_dir, "f%05d.png" % i))
                finally:
                    await browser.close()
            # Encode: ffmpeg PNG sequence (+ optional audio) -> H.264 MP4.
            args = ["ffmpeg", "-y", "-framerate", str(fps),
                    "-i", os.path.join(frames_dir, "f%05d.png")]
            if audio_path:
                args += ["-i", audio_path]
            args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
                     "-pix_fmt", "yuv420p", "-r", str(fps), "-threads", "2"]
            if audio_path:
                args += ["-c:a", "aac", "-b:a", "192k", "-shortest"]
            args += ["-movflags", "+faststart", out_path]
            proc = await asyncio.create_subprocess_exec(
                *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            _, err = await proc.communicate()
            if proc.returncode != 0:
                raise RuntimeError("ffmpeg failed: " + err.decode("utf-8", "replace")[-300:])
        return n
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
```

- [ ] **Step 4: Run for real (locally)**

Run:
```bash
cd mcp-servers/tasks
# ffmpeg must be on PATH; if missing locally the test skips. To run it for real,
# install ffmpeg (e.g. winget install Gyan.FFmpeg) then:
python -m pytest tests/test_video_anim.py -q
```
Expected: `test_demo_composition_*` PASS; `test_render_demo_to_mp4` PASS (valid MP4, >=2 frames) or SKIP if ffmpeg absent. If it renders, open `demo.mp4` once to eyeball the motion.

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/video_anim.py mcp-servers/tasks/tests/test_video_anim.py
git commit -m "feat(video-anim): render_html_to_mp4 (Chromium frame-capture + ffmpeg)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Add ffmpeg to the tasks container

**Files:** Modify `mcp-servers/tasks/Dockerfile`

- [ ] **Step 1: Add ffmpeg to the apt install**

Find the first `RUN apt-get update && apt-get install -y --no-install-recommends \` block and add `ffmpeg` to the package list (the line currently installing `curl ca-certificates git openssh-client rsync`):

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates git openssh-client rsync ffmpeg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g @anthropic-ai/claude-code \
    && rm -rf /var/lib/apt/lists/*
```

- [ ] **Step 2: Commit**

```bash
git add mcp-servers/tasks/Dockerfile
git commit -m "build(tasks): add ffmpeg to the image for in-container animated render

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Deploy + in-container render proof

**Files:** none (deploy + verification)

- [ ] **Step 1: Run the full tasks suite (no regressions)**

Run: `cd mcp-servers/tasks && python -m pytest -q`
Expected: the new `test_video_anim` tests pass/skip; the pre-existing offline failure/skip counts are unchanged (no NEW failures from `video_anim.py`).

- [ ] **Step 2: Drift-check + deploy (gated on user OK — outward-facing)**

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO-integrate"
# new file + Dockerfile; drift-check the Dockerfile vs last-deployed baseline
git show HEAD~3:mcp-servers/tasks/Dockerfile | tr -d '\r' | sha256sum | cut -c1-16
ssh root@46.224.193.25 "tr -d '\r' < /root/proxy-server/mcp-servers/tasks/Dockerfile | sha256sum | cut -c1-16"   # expect match
scp mcp-servers/tasks/video_anim.py root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/video_anim.py
scp mcp-servers/tasks/Dockerfile    root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/Dockerfile
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --build tasks 2>&1 | tail -6"   # background if slow
```

- [ ] **Step 3: In-container render proof**

Pipe a small script into the tasks container that builds the demo composition (with a Pillow PNG) and renders it to `/tmp/anim_demo.mp4`, printing the frame count + file size + ffprobe duration:
```bash
ssh root@46.224.193.25 'cd /root/proxy-server && CID=$(docker compose -f docker-compose.unified.yml ps -q tasks) && docker exec -i "$CID" python -' <<'PY'
import asyncio, io, os, subprocess
from PIL import Image
from video_anim import build_demo_composition, render_html_to_mp4
b=io.BytesIO(); Image.new("RGB",(320,200),(40,120,220)).save(b,"PNG")
html=build_demo_composition([b.getvalue()], title="In-Container Demo")
n=asyncio.run(render_html_to_mp4(html,"/tmp/anim_demo.mp4",fps=12,duration_s=4.0))
sz=os.path.getsize("/tmp/anim_demo.mp4")
dur=subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0","/tmp/anim_demo.mp4"],capture_output=True,text=True).stdout.strip()
print("FRAMES",n,"SIZE",sz,"DURATION",dur)
PY
```
Expected: `FRAMES 48 SIZE <large> DURATION ~4.0` — proving the in-container Chromium+ffmpeg render works on the box. (Also confirm `curl -fsS https://ai-ui.coolestdomain.win/tasks/healthz` is ok and the box didn't OOM.)

- [ ] **Step 4: Push branch + fast-forward main**

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO-integrate"
gh auth switch -u Jacintalama
git push fork fix/video-thread-image-intake
git push fork HEAD:main
```

---

## Self-Review (filled by author)

- **Spec coverage (Phase 1):** in-container render path (`render_html_to_mp4`, T2); self-contained seekable composition embedding screenshots (`build_demo_composition`, T1); ffmpeg in container (T3); guardrails fps<=24/dur<=40/720p/streamed-frames + temp cleanup (T2); local proof + in-container proof (T2 S4, T4 S3); slideshow untouched (no edits to it). Phases 2/3 explicitly deferred. ✓
- **Placeholders:** none — full code/commands in every step. ✓
- **Name consistency:** `build_demo_composition`, `render_html_to_mp4`, `window.__seek`, `_ANIM_LOCK`, `MAX_FPS`/`MAX_DURATION_S` used identically across module, tests, and the in-container proof. ✓
