# Video Pro Auto-Edit Brain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a paste-URL video genuinely well-edited by having the script generator SEE the screenshots (vision) + READ the page title/text, and write a pro kinetic script, instead of a one-slide-per-screenshot fallback.

**Architecture:** A new pure `video_vision` module turns screenshot files + page context into multimodal content blocks (downscaled images + labels + brief). `video_capture.capture_site` also extracts page title/headings/meta in the same Playwright pass and returns it. The animated/slideshow planners gain keyword-only `site_context` + `screenshot_paths` args; when paths are present they send images to claude-opus-4-8 with a stronger creative brief. Scene identity stays the bare basename throughout, so renderers/validators/fallbacks are untouched.

**Tech Stack:** Python, anthropic SDK (claude-opus-4-8, structured outputs, adaptive thinking), Pillow (downscale), Playwright (capture), pytest.

**Spec:** `docs/superpowers/specs/2026-06-25-video-pro-brain-design.md`

**Conventions:** run tests from `mcp-servers/tasks/`: `cd "C:/All/Work - Code/ai_ui/mcp-servers/tasks" && python -m pytest ...`. DB tests skip offline. NO em-dashes in code/comments. Commits plain, no AI attribution. Windows + Git Bash; `python` (fallback `py`).

---

## File Structure

- Create: `mcp-servers/tasks/video_vision.py` — pure: screenshots + context -> multimodal content blocks.
- Modify: `mcp-servers/tasks/video_capture.py` — add `extract_site_context(page)`; `capture_site` returns `(frames, site_context)`.
- Modify: `mcp-servers/tasks/routes_video.py` — unpack the tuple, write `site_context.json`.
- Modify: `mcp-servers/tasks/video_plan.py` — kinetic brief rewrite; `_resolve_brief`; vision-enabled `generate_anim_plan` + `generate_plan`.
- Modify: `mcp-servers/tasks/video_worker.py` — pass `site_context` + `screenshot_paths`.
- Tests: `tests/test_video_vision.py` (new), extend `tests/test_video_capture.py`, `tests/test_routes_video_capture.py`, `tests/test_video_plan.py`.

---

## Task 1: video_vision.py (multimodal content builder)

**Files:**
- Create: `mcp-servers/tasks/video_vision.py`
- Create: `mcp-servers/tasks/tests/test_video_vision.py`

- [ ] **Step 1: Write failing tests** `tests/test_video_vision.py`:

```python
"""Tests for video_vision.build_vision_content (pure, no network)."""
import base64
import io
import os

from PIL import Image

from video_vision import build_vision_content, MAX_VISION_IMAGES, VISION_MAX_EDGE


def _make_png(path, w, h):
    Image.new("RGB", (w, h), "white").save(path, "PNG")


def test_builds_leading_text_then_image_and_label(tmp_path):
    p = tmp_path / "shot-1.png"
    _make_png(p, 800, 600)
    parts = build_vision_content([("shot-1.png", str(p))], {"title": "Acme"}, "Make it punchy")
    assert parts[0]["type"] == "text"
    assert "Make it punchy" in parts[0]["text"] and "Acme" in parts[0]["text"]
    assert parts[1]["type"] == "image"
    assert parts[1]["source"]["type"] == "base64"
    assert parts[1]["source"]["media_type"] == "image/jpeg"
    assert parts[2]["type"] == "text" and parts[2]["text"].startswith("shot-1.png")


def test_downscales_large_image(tmp_path):
    p = tmp_path / "big.png"
    _make_png(p, 4000, 3000)
    parts = build_vision_content([("big.png", str(p))], {}, "b")
    img_block = next(b for b in parts if b["type"] == "image")
    raw = base64.standard_b64decode(img_block["source"]["data"])
    with Image.open(io.BytesIO(raw)) as im:
        assert max(im.size) <= VISION_MAX_EDGE


def test_caps_at_max_images(tmp_path):
    imgs = []
    for i in range(MAX_VISION_IMAGES + 4):
        p = tmp_path / f"s{i}.png"
        _make_png(p, 400, 300)
        imgs.append((f"s{i}.png", str(p)))
    parts = build_vision_content(imgs, {}, "b")
    assert sum(1 for b in parts if b["type"] == "image") == MAX_VISION_IMAGES


def test_skips_unreadable_image(tmp_path):
    good = tmp_path / "good.png"
    _make_png(good, 400, 300)
    parts = build_vision_content(
        [("missing.png", str(tmp_path / "missing.png")), ("good.png", str(good))],
        {}, "b")
    images = [b for b in parts if b["type"] == "image"]
    labels = [b["text"] for b in parts if b["type"] == "text" and b["text"].startswith(("good", "missing"))]
    assert len(images) == 1
    assert any(l.startswith("good.png") for l in labels)
```

- [ ] **Step 2: Run, confirm FAIL** (module missing):
`cd "C:/All/Work - Code/ai_ui/mcp-servers/tasks" && python -m pytest tests/test_video_vision.py -v`

- [ ] **Step 3: Create `video_vision.py`:**

```python
"""Turn captured screenshots + page context into multimodal content blocks for
the planner's vision call. Pure (no network). The downscaled JPEGs here are ONLY
for the model to understand the page; the final render uses the full-res PNGs.
"""
from __future__ import annotations

import base64
import io
import logging

from PIL import Image

logger = logging.getLogger("video_vision")

MAX_VISION_IMAGES = 8
VISION_MAX_EDGE = 1568  # long-edge cap: ~1.6k image tokens each (vs ~4.8k full-res)


def _downscale_jpeg_b64(path: str) -> str | None:
    """Open, downscale to <= VISION_MAX_EDGE on the long edge, re-encode JPEG,
    base64. Returns None (skip) on any failure. Pillow's default MAX_IMAGE_PIXELS
    decompression-bomb guard is left ON so an oversize upload is skipped here."""
    try:
        with Image.open(path) as im:
            im = im.convert("RGB")
            w, h = im.size
            scale = min(1.0, VISION_MAX_EDGE / max(w, h))
            if scale < 1.0:
                im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=80)
        return base64.standard_b64encode(buf.getvalue()).decode("ascii")
    except Exception as e:  # noqa: BLE001 - corrupt/oversize/missing -> skip, never raise
        logger.warning("vision downscale skipped %s: %s", path, e)
        return None


def _context_text(site_context: dict) -> str:
    ctx = site_context or {}
    title = (ctx.get("title") or "").strip()
    headings = "; ".join(ctx.get("headings") or [])
    meta = (ctx.get("meta_description") or "").strip()
    bits = []
    if title:
        bits.append(f"Page title: {title}")
    if headings:
        bits.append(f"Key text on the pages: {headings}")
    if meta:
        bits.append(f"Description: {meta}")
    return "\n".join(bits)


def build_vision_content(images, site_context, brief) -> list[dict]:
    """images: ordered list of (basename, abs_path). Returns a user-content list:
    a leading text block (brief + page context), then per image an image block
    followed by a small text label naming the exact basename (so the model can
    reference it in scene['screenshot']). Caps at MAX_VISION_IMAGES; skips
    unreadable files."""
    header = (brief or "").strip()
    ctx = _context_text(site_context)
    if ctx:
        header = (header + "\n\n" + ctx).strip()
    parts: list[dict] = [{"type": "text",
                          "text": header or "Make a strong short product video from these pages."}]
    page = 0
    for basename, path in list(images)[:MAX_VISION_IMAGES]:
        b64 = _downscale_jpeg_b64(path)
        if b64 is None:
            continue
        page += 1
        parts.append({"type": "image",
                      "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}})
        parts.append({"type": "text", "text": f"{basename} (page {page})"})
    return parts
```

- [ ] **Step 4: Run, confirm PASS:**
`cd "C:/All/Work - Code/ai_ui/mcp-servers/tasks" && python -m pytest tests/test_video_vision.py -v`

- [ ] **Step 5: Commit:**
```bash
cd "C:/All/Work - Code/ai_ui" && git add mcp-servers/tasks/video_vision.py mcp-servers/tasks/tests/test_video_vision.py && git commit -m "feat(video): multimodal content builder for the planner vision call"
```

---

## Task 2: Page-context extraction in capture

**Files:**
- Modify: `mcp-servers/tasks/video_capture.py`
- Modify: `mcp-servers/tasks/routes_video.py`
- Modify: `mcp-servers/tasks/tests/test_video_capture.py`, `tests/test_routes_video_capture.py`

- [ ] **Step 1: Write a failing test** for the pure extractor in `tests/test_video_capture.py` (append):

```python
import pytest
from video_capture import extract_site_context


class _FakePage:
    def __init__(self, title="T", headings=None, meta="M", fail=False):
        self._title, self._headings, self._meta, self._fail = title, headings or ["A", "B"], meta, fail
    async def title(self):
        if self._fail:
            raise RuntimeError("boom")
        return self._title
    async def evaluate(self, js):
        if self._fail:
            raise RuntimeError("boom")
        return self._headings if "querySelectorAll" in js else self._meta


@pytest.mark.asyncio
async def test_extract_site_context_reads_fields():
    ctx = await extract_site_context(_FakePage(title="Acme", headings=["Hero", "Pricing"], meta="desc"))
    assert ctx["title"] == "Acme"
    assert ctx["headings"] == ["Hero", "Pricing"]
    assert ctx["meta_description"] == "desc"


@pytest.mark.asyncio
async def test_extract_site_context_never_raises():
    ctx = await extract_site_context(_FakePage(fail=True))
    assert ctx == {"title": "", "headings": [], "meta_description": ""}
```

- [ ] **Step 2: Run, confirm FAIL** (`extract_site_context` missing):
`cd "C:/All/Work - Code/ai_ui/mcp-servers/tasks" && python -m pytest tests/test_video_capture.py -k extract_site_context -v`

- [ ] **Step 3: Implement.**
(a) Add to `video_capture.py`:
```python
async def extract_site_context(page) -> dict:
    """Best-effort page title + first headings + meta description. Never raises;
    a failure on any field yields an empty value so capture never fails over it."""
    try:
        title = await page.title()
    except Exception:  # noqa: BLE001
        title = ""
    try:
        headings = await page.evaluate(
            "Array.from(document.querySelectorAll('h1,h2,h3')).slice(0,8)"
            ".map(e => (e.innerText || '').trim()).filter(Boolean)"
        )
    except Exception:  # noqa: BLE001
        headings = []
    try:
        meta = await page.evaluate(
            "(document.querySelector('meta[name=\"description\"]') || {}).content || ''"
        )
    except Exception:  # noqa: BLE001
        meta = ""
    return {
        "title": (title or "")[:200],
        "headings": [(h or "")[:120] for h in (headings or [])][:8],
        "meta_description": (meta or "")[:400],
    }
```
(b) In `capture_site`, change the return type to `tuple[list[bytes], dict]`. After the post-redirect `await assert_capturable(page.url)` and the frame loop, before `finally: await browser.close()`, capture context:
```python
                    site_context = await extract_site_context(page)
```
Initialize `site_context: dict = {}` near `frames: list[bytes] = []` so it exists even on early exits. Change the final `return frames` to `return frames, site_context`. Update the docstring/return annotation to `-> tuple[list[bytes], dict]`. (The early `raise CaptureError(...)` paths are unchanged; only the success return becomes a tuple.)

(c) In `routes_video.py` (~line 793) unpack the tuple and write the context file:
```python
        captured, site_context = await asyncio.wait_for(
            capture_site(body.url, max_frames=frames), timeout=40.0)
```
After `shots = await _store_screenshot_blobs(slug, str(jid), blobs)` and before the return, add:
```python
        try:
            ctx_path = _apps_dir() / slug / ".video" / str(jid) / "site_context.json"
            ctx_path.write_text(__import__("json").dumps(site_context))
        except Exception:  # noqa: BLE001 - context is best-effort
            logger.warning("could not write site_context for job=%s", jid)
```
(Use the existing `json` import if present at module top instead of `__import__`; prefer `import json` at top and `json.dumps`.)

(d) Update `tests/test_routes_video_capture.py` `fake_capture` (~line 90) to return the tuple:
```python
    async def fake_capture(url, *, max_frames=5):
        return [_png(), _png(), _png()], {"title": "Example"}
```
(e) Update `tests/test_video_capture.py` real capture tests (~lines 61, 106) to unpack:
```python
        frames, _ctx = await capture_site("https://example.com", max_frames=2)
```
and the local-server one similarly (`frames, _ctx = await capture_site(...)`). These tests skip when chromium is absent, but keep them correct.

- [ ] **Step 4: Run:**
`cd "C:/All/Work - Code/ai_ui/mcp-servers/tasks" && python -m pytest tests/test_video_capture.py tests/test_routes_video_capture.py -v && python -c "import routes_video, video_capture; print('import ok')"`
Expected: extract tests pass; capture/route tests pass or skip; import ok.

- [ ] **Step 5: Commit:**
```bash
cd "C:/All/Work - Code/ai_ui" && git add mcp-servers/tasks/video_capture.py mcp-servers/tasks/routes_video.py mcp-servers/tasks/tests/test_video_capture.py mcp-servers/tasks/tests/test_routes_video_capture.py && git commit -m "feat(video): capture page title/headings/meta as site_context"
```

---

## Task 3: Kinetic creative brief + brief resolution

**Files:**
- Modify: `mcp-servers/tasks/video_plan.py`
- Modify: `mcp-servers/tasks/tests/test_video_plan.py`

- [ ] **Step 1: Write failing tests** (append to `tests/test_video_plan.py`):

```python
def test_resolve_brief_default_when_empty():
    from video_plan import _resolve_brief
    b = _resolve_brief("")
    assert "director" in b.lower()


def test_resolve_brief_uses_user_direction():
    from video_plan import _resolve_brief
    b = _resolve_brief("energetic, focus on pricing")
    assert "energetic, focus on pricing" in b


def test_anim_brief_is_director_grade():
    from video_plan import ANIM_BEST_PRACTICES
    low = ANIM_BEST_PRACTICES.lower()
    assert "hook" in low and "cta" in low  # arc language present
```

- [ ] **Step 2: Run, confirm FAIL:**
`cd "C:/All/Work - Code/ai_ui/mcp-servers/tasks" && python -m pytest tests/test_video_plan.py -k "resolve_brief or director_grade" -v`

- [ ] **Step 3: Implement.**
(a) Replace the `ANIM_BEST_PRACTICES` constant with a stronger creative-director brief (keep referencing the kind title/screenshot/outro structure and ANIM_MOTIONS the schema/renderer require):
```python
ANIM_BEST_PRACTICES = (
    "You are a professional motion-graphics editor. From the screenshots and page "
    "text, work out what the product is and who it is for, then cut a punchy "
    "kinetic video - NOT a slideshow.\n"
    "- ARC: open with a HOOK title beat (what it is / why care), then 2-4 "
    "SCREENSHOT beats on the strongest features or benefits, then a short OUTRO/CTA. "
    "Use ONLY the best shots; skip weak or repetitive ones.\n"
    "- HEADLINES: punchy, benefit-led, <= ~8 words. Say why it matters; never read "
    "the UI verbatim. Optional subtext is one short supporting line.\n"
    "- MOTION choreographs around the screenshot (it is the hero). Choose the motion "
    "that fits the beat: zoom-in to focus a feature, pan-up/pan-left to reveal long "
    "content, rise/fade for text beats. Vary it - do NOT reuse one motion every "
    "scene.\n"
    "- NARRATION: conversational, one idea per scene, speakable in the scene's "
    "duration (~2.5 words/second).\n"
    "- PACING: 2.5-5s per scene, vary the lengths, keep it tight (20-35s ideal, hard "
    "cap 40s). Avoid a run of identical durations.\n"
    "- Reference ONLY the provided screenshot filenames, exactly as given, and only "
    "on scenes with kind 'screenshot'."
)
```
(b) Add a brief resolver:
```python
def _resolve_brief(prompt: str) -> str:
    """The per-job creative brief sent in the user turn. The user's free-text
    direction steers the editor; an empty prompt puts the editor in charge."""
    clean = (prompt or "").strip()
    if clean:
        return f"Creative direction from the user: {clean}"
    return (
        "No brief was given. You are the director: study these pages and make the "
        "best short product video (about 20-40 seconds). Decide the story, pick the "
        "strongest shots, and choreograph the motion, captions, and pacing yourself."
    )
```

- [ ] **Step 4: Run, confirm PASS** (and existing plan tests still pass):
`cd "C:/All/Work - Code/ai_ui/mcp-servers/tasks" && python -m pytest tests/test_video_plan.py -v`

- [ ] **Step 5: Commit:**
```bash
cd "C:/All/Work - Code/ai_ui" && git add mcp-servers/tasks/video_plan.py mcp-servers/tasks/tests/test_video_plan.py && git commit -m "feat(video): pro kinetic creative brief + default/custom brief resolution"
```

---

## Task 4: Vision-enabled planners

**Files:**
- Modify: `mcp-servers/tasks/video_plan.py`
- Modify: `mcp-servers/tasks/tests/test_video_plan.py`

- [ ] **Step 1: Write failing tests** (append). The existing `_FakeClient`/`_Messages` records calls; add a path that asserts image content + the fallback:

```python
def test_generate_anim_plan_sends_images(tmp_path, monkeypatch):
    import anthropic, json as _json
    from PIL import Image
    from video_plan import generate_anim_plan
    p = tmp_path / "a.png"; Image.new("RGB", (400, 300), "white").save(p, "PNG")
    canned = {"title": "t", "narration_script": "",
              "scenes": [{"kind": "screenshot", "screenshot": "a.png", "headline": "h",
                          "motion": "zoom-in", "duration_s": 3.0}]}
    fake = _FakeClient(_json.dumps(canned))
    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **k: fake)
    import asyncio
    plan = asyncio.get_event_loop().run_until_complete(
        generate_anim_plan("x", ["a.png"], site_context={"title": "Acme"},
                           screenshot_paths=[("a.png", str(p))], attempts=1))
    assert plan["scenes"][0]["screenshot"] == "a.png"
    sent = fake.messages.calls[0]
    content = sent["messages"][0]["content"]
    assert isinstance(content, list)
    assert any(b.get("type") == "image" for b in content)
    assert sent["max_tokens"] >= 4096


def test_generate_anim_plan_falls_back_on_api_error(tmp_path, monkeypatch):
    import anthropic
    from PIL import Image
    from video_plan import generate_anim_plan
    p = tmp_path / "a.png"; Image.new("RGB", (400, 300), "white").save(p, "PNG")

    class _Boom:
        class messages:
            @staticmethod
            def create(*a, **k):
                raise RuntimeError("api down")
    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **k: _Boom())
    import asyncio
    plan = asyncio.get_event_loop().run_until_complete(
        generate_anim_plan("hi there", ["a.png"], screenshot_paths=[("a.png", str(p))], attempts=2))
    assert plan["scenes"]  # deterministic fallback, valid by construction
```
(Match the file's existing async-test style; if it uses `pytest.mark.asyncio` + `async def`, write these as `async def` and `await` instead of `run_until_complete`. Read the file head and mirror it.)

- [ ] **Step 2: Run, confirm FAIL** (kwargs not accepted / no image content):
`cd "C:/All/Work - Code/ai_ui/mcp-servers/tasks" && python -m pytest tests/test_video_plan.py -k "sends_images or falls_back_on_api" -v`

- [ ] **Step 3: Implement.** Add the import at top of `video_plan.py`:
```python
from video_vision import build_vision_content
```
Rewrite `generate_anim_plan` to accept the new kwargs and use vision when paths are present:
```python
async def generate_anim_plan(prompt: str, screenshots: list[str], *,
                             site_context: dict | None = None,
                             screenshot_paths: list[tuple[str, str]] | None = None,
                             attempts: int = 3) -> dict:
    client = anthropic.Anthropic()
    sys = build_anim_system_prompt()
    use_vision = bool(screenshot_paths)
    if use_vision:
        content = build_vision_content(screenshot_paths, site_context or {}, _resolve_brief(prompt))
    else:
        content = f"Prompt: {prompt}\nScreenshots: {screenshots}"
    last_err: Exception | None = None
    for i in range(max(1, attempts)):
        try:
            kwargs = dict(
                model="claude-opus-4-8",
                max_tokens=4096 if use_vision else 2048,
                system=sys,
                output_config={"format": {"type": "json_schema", "schema": ANIM_PLAN_SCHEMA}},
                messages=[{"role": "user", "content": content}],
            )
            if use_vision:
                kwargs["thinking"] = {"type": "adaptive"}
            msg = client.messages.create(**kwargs)
            text = next(b.text for b in msg.content if b.type == "text")
            plan = json.loads(text)
            plan["scenes"] = (plan.get("scenes") or [])[:ANIM_MAX_SCENES]
            validate_anim_plan(plan, screenshots)
            return plan
        except Exception as e:  # noqa: BLE001 - retry on bad plan / API hiccup
            last_err = e
            logger.warning("generate_anim_plan attempt %d/%d failed: %s: %s",
                           i + 1, attempts, type(e).__name__, e)
    logger.warning("generate_anim_plan falling back after %d attempts (%s)", attempts, last_err)
    plan = _anim_fallback_plan(prompt, screenshots)
    validate_anim_plan(plan, screenshots)
    return plan
```
Apply the SAME pattern to `generate_plan` (new kwargs, vision content when paths present, `max_tokens=4096 if use_vision else 2048`, `thinking` adaptive on the vision path, schema `PLAN_SCHEMA`, keep `clamp_plan` + `validate_plan` + the existing fallback). `screenshots` stays basenames for `validate_*` and the fallback.

- [ ] **Step 4: Run, confirm PASS** (new + existing):
`cd "C:/All/Work - Code/ai_ui/mcp-servers/tasks" && python -m pytest tests/test_video_plan.py -v`

- [ ] **Step 5: Commit:**
```bash
cd "C:/All/Work - Code/ai_ui" && git add mcp-servers/tasks/video_plan.py mcp-servers/tasks/tests/test_video_plan.py && git commit -m "feat(video): planners send screenshots as vision + page context to claude-opus-4-8"
```

---

## Task 5: Worker wiring

**Files:**
- Modify: `mcp-servers/tasks/video_worker.py`
- Modify: `mcp-servers/tasks/tests/` (add a worker-scripting test if the file exists; else assert via the planner test)

- [ ] **Step 1: Write a failing test.** If `tests/test_video_worker*.py` exists, add a test that the scripting stage passes `screenshot_paths` + `site_context` to a monkeypatched planner. Otherwise add a minimal test asserting the path/context assembly helper. Concretely, factor the assembly into a tiny pure helper in video_worker.py and test it:

```python
def test_build_planner_args(tmp_path, monkeypatch):
    import os, json, video_worker
    shots = tmp_path / "vid-x" / ".video" / "JID" / "screenshots"
    shots.mkdir(parents=True)
    (shots / "a.png").write_bytes(b"x"); (shots / "b.png").write_bytes(b"y")
    (tmp_path / "vid-x" / ".video" / "JID" / "site_context.json").write_text(json.dumps({"title": "T"}))
    monkeypatch.setattr(video_worker, "APPS_DIR", str(tmp_path))
    names, paths, ctx = video_worker._planner_inputs("vid-x", "JID")
    assert names == ["a.png", "b.png"]
    assert paths == [("a.png", os.path.join(str(shots), "a.png")),
                     ("b.png", os.path.join(str(shots), "b.png"))]
    assert ctx == {"title": "T"}
```

- [ ] **Step 2: Run, confirm FAIL** (`_planner_inputs` missing):
`cd "C:/All/Work - Code/ai_ui/mcp-servers/tasks" && python -m pytest tests/ -k build_planner_args -v`

- [ ] **Step 3: Implement.** Ensure `import json` at the top of video_worker.py (add if missing). Add the helper:
```python
def _planner_inputs(slug: str, job_id: str):
    """(basenames, [(basename, abs_path)], site_context) for the scripting stage."""
    shots_dir = os.path.join(APPS_DIR, slug, ".video", str(job_id), "screenshots")
    names = sorted(os.listdir(shots_dir)) if os.path.isdir(shots_dir) else []
    paths = [(n, os.path.join(shots_dir, n)) for n in names]
    ctx = {}
    ctx_path = os.path.join(APPS_DIR, slug, ".video", str(job_id), "site_context.json")
    if os.path.isfile(ctx_path):
        try:
            with open(ctx_path, encoding="utf-8") as f:
                ctx = json.load(f) or {}
        except Exception:  # noqa: BLE001
            ctx = {}
    return names, paths, ctx
```
In the scripting stage, replace the screenshots-listing + planner call with:
```python
            screenshots, screenshot_paths, site_context = _planner_inputs(slug, str(job_id))
            plan = await (
                generate_anim_plan(prompt, screenshots, site_context=site_context,
                                   screenshot_paths=screenshot_paths)
                if render_mode == "animated"
                else generate_plan(prompt, screenshots, site_context=site_context,
                                   screenshot_paths=screenshot_paths)
            )
```

- [ ] **Step 4: Run:**
`cd "C:/All/Work - Code/ai_ui/mcp-servers/tasks" && python -m pytest tests/ -k "planner_args or worker" -v && python -c "import video_worker; print('ok')"`

- [ ] **Step 5: Commit:**
```bash
cd "C:/All/Work - Code/ai_ui" && git add mcp-servers/tasks/video_worker.py mcp-servers/tasks/tests/ && git commit -m "feat(video): worker passes screenshot paths + site_context to the planners"
```

---

## Task 6: Full-suite verification + deploy notes

- [ ] **Step 1: Full tasks suite:**
`cd "C:/All/Work - Code/ai_ui/mcp-servers/tasks" && python -m pytest -q`
Expected: new tests pass; DB-guarded/chromium tests skip offline; no NEW failures vs the pre-existing baseline.

- [ ] **Step 2: Lint + em-dash scan on new code:**
`cd "C:/All/Work - Code/ai_ui/mcp-servers/tasks" && ruff check video_vision.py video_plan.py video_capture.py video_worker.py routes_video.py 2>&1 | tail -20`
`cd "C:/All/Work - Code/ai_ui/mcp-servers/tasks" && grep -nP "[\x{2013}\x{2014}]" video_vision.py | head || echo clean`

- [ ] **Step 3: Deploy notes (do not run blindly; follow CLAUDE.md):**
- tasks service: deploy mcp-servers via the orchestrator OR per-file scp + `docker compose -f docker-compose.unified.yml up -d --build tasks`, using the working key `~/.ssh/aiui_vps`. NEVER deploy local `mcp-servers/tasks/templates.py` (server is ahead).
- No DB change, no new env var (reuses the existing ANTHROPIC key the video pipeline already uses).
- Verify on host: paste a real URL with Animated mode and NO prompt; confirm the rendered video reflects real product understanding (named features, sensible shot selection, varied motion) rather than one-slide-per-shot.

---

## Out of scope (separate specs)

- Sub-project 2: kinetic-renderer polish (richer motion/typography in video_anim.py).
- Sub-project 3: the Default vs Custom buttons on Discord + Slack.
