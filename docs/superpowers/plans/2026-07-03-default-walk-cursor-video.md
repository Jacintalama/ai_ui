# Default-flow Cursor Click-Through Walk Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a user starts a video with only a URL and no prompt (the Default flow), walk several real pages of the site and render with the smart cursor clicking the element that leads to each next page.

**Architecture:** A new multi-page `capture_walk` (Playwright) navigates same-origin links, screenshotting each page and recording the real click coordinate of the link it follows next; it advances by `page.goto(href)` (no DOM clicking) so the loop is deterministic and testable. A pure `build_walk_plan` turns the walk into the Remotion anim plan the template renderer already consumes (intro card, one clicked page per scene, outro card). The worker builds this plan for the Default flow and forces the template+cursor render path via the existing `ai_enabled` override, bypassing the global `AI_VIDEO_CODEGEN` flag. Custom flow and AI codegen are untouched.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy async, Playwright (chromium, already in the tasks container), pytest, Remotion (existing template renderer).

## Global Constraints

- Python style: type hints on all new function signatures; `async`/`await` for I/O; no hardcoded secrets.
- Never touch `.env`, `mcp-servers/tasks/templates.py`, or `docker-compose.unified.yml` port bindings.
- No em-dashes in code comments, copy, or commit messages. No AI attribution / `Co-Authored-By` in commits (author: Ralph Benitez / thunder500).
- Cursor renders only on `kind=="screenshot"` scenes with `click:{x,y,label}` where `y <= 0.72`.
- Walk safety: follow same-origin `<a href>` GET links only. Never buttons/forms/JS controls.
- Up to 4 pages, capped by the 40s max video duration. Music-bed only, no narration, in v1.
- No DB migration: walk data lives in `walk.json` on disk and inside `plan_json`.
- Screenshots live at `<APPS_DIR>/<slug>/.video/<job_id>/screenshots/screenshot-N.png`; `site_context.json` and the new `walk.json` sit in `<APPS_DIR>/<slug>/.video/<job_id>/`.

---

## File Structure

- Modify `mcp-servers/tasks/video_capture.py` — add `same_origin`, `COLLECT_ANCHORS_JS`, `pick_walk_target`, `_walk_with_page`, `capture_walk`. (Existing `capture_site`, SSRF guards, `extract_site_context`, `_CAPTURE_LOCK` stay.)
- Create `mcp-servers/tasks/video_walk_plan.py` — `_clean_headline`, `build_walk_plan`.
- Modify `mcp-servers/tasks/routes_video.py` — `capture_from_url` uses `capture_walk`, persists `walk.json`, raises capture timeout.
- Modify `mcp-servers/tasks/video_worker.py` — Default-flow plan selection (`build_walk_plan`) + `ai_enabled` override in dispatch.
- Tests: `tests/test_video_capture.py` (append), new `tests/test_video_walk_plan.py`, `tests/test_video_worker.py` (append), `tests/test_routes_video_capture.py` (append).

All test commands run from `mcp-servers/tasks/`.

---

### Task 1: `same_origin` helper

**Files:**
- Modify: `mcp-servers/tasks/video_capture.py`
- Test: `mcp-servers/tasks/tests/test_video_capture.py`

**Interfaces:**
- Produces: `same_origin(base_url: str, href: str) -> bool` — True when `href` is an http(s) link on the same registrable host as `base_url`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_video_capture.py`:
```python
from video_capture import same_origin


def test_same_origin_matches_same_host():
    assert same_origin("https://animepahe.ch/", "https://animepahe.ch/az-list/") is True


def test_same_origin_rejects_external_host():
    assert same_origin("https://animepahe.ch/", "https://google.com/") is False


def test_same_origin_rejects_non_http_schemes():
    base = "https://animepahe.ch/"
    assert same_origin(base, "mailto:a@b.com") is False
    assert same_origin(base, "tel:+123") is False
    assert same_origin(base, "javascript:void(0)") is False
    assert same_origin(base, "#top") is False


def test_same_origin_treats_www_as_same():
    assert same_origin("https://example.com/", "https://www.example.com/x") is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_video_capture.py -k same_origin -q`
Expected: FAIL with `ImportError: cannot import name 'same_origin'`.

- [ ] **Step 3: Write minimal implementation**

Add to `video_capture.py` (near the other URL helpers, after the imports):
```python
from urllib.parse import urlparse


def _registrable_host(host: str) -> str:
    """Lowercased host with a leading 'www.' stripped, for same-site comparison."""
    host = (host or "").lower()
    return host[4:] if host.startswith("www.") else host


def same_origin(base_url: str, href: str) -> bool:
    """True when href is an http(s) link on the same host as base_url."""
    try:
        b = urlparse(base_url)
        h = urlparse(href)
    except ValueError:
        return False
    if h.scheme not in ("http", "https"):
        return False
    return bool(h.netloc) and _registrable_host(h.hostname or "") == _registrable_host(b.hostname or "")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_video_capture.py -k same_origin -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/video_capture.py mcp-servers/tasks/tests/test_video_capture.py
git commit -m "feat(video): add same_origin helper for walk capture"
```

---

### Task 2: `pick_walk_target` + anchor-collection JS

**Files:**
- Modify: `mcp-servers/tasks/video_capture.py`
- Test: `mcp-servers/tasks/tests/test_video_capture.py`

**Interfaces:**
- Consumes: `same_origin` (Task 1).
- Produces:
  - `COLLECT_ANCHORS_JS: str` — a JS snippet returning a list of `{href, x, y, w, h, text}` (pixel box centers) for visible anchors.
  - `pick_walk_target(candidates: list[dict], base_url: str, visited: set[str], *, vw: int = 1280, vh: int = 800) -> dict | None` — returns `{"href": str, "x": float, "y": float, "label": str}` with x,y as viewport fractions, or None. Picks the largest visible same-origin, unvisited, non-denied link whose center is in the top 72%.
  - `normalize_url(url: str) -> str` — url without fragment and without a trailing slash, host lowercased (for visited-set dedupe).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_video_capture.py`:
```python
from video_capture import pick_walk_target, normalize_url, COLLECT_ANCHORS_JS


def _cand(href, x=100, y=300, w=200, h=120, text="link"):
    return {"href": href, "x": x, "y": y, "w": w, "h": h, "text": text}


def test_collect_anchors_js_is_a_function_expression():
    assert "querySelectorAll" in COLLECT_ANCHORS_JS
    assert "getBoundingClientRect" in COLLECT_ANCHORS_JS


def test_normalize_url_strips_fragment_and_trailing_slash():
    assert normalize_url("https://A.com/x/#frag") == "https://a.com/x"
    assert normalize_url("https://a.com/") == "https://a.com"


def test_pick_prefers_largest_same_origin_link():
    base = "https://site.com/"
    cands = [
        _cand("https://site.com/small", w=50, h=50, text="tiny"),
        _cand("https://site.com/big", w=300, h=200, text="Big Poster"),
    ]
    t = pick_walk_target(cands, base, set())
    assert t["href"] == "https://site.com/big"
    assert t["label"] == "Big Poster"
    assert 0.0 <= t["x"] <= 1.0 and 0.0 <= t["y"] <= 1.0


def test_pick_skips_external_and_visited_and_below_fold():
    base = "https://site.com/"
    cands = [
        _cand("https://other.com/x", w=400, h=400, text="external"),
        _cand("https://site.com/seen", w=400, h=400, text="seen"),
        _cand("https://site.com/low", y=760, w=400, h=100, text="below fold"),
        _cand("https://site.com/good", y=300, w=120, h=90, text="good"),
    ]
    visited = {normalize_url("https://site.com/seen")}
    t = pick_walk_target(cands, base, visited)
    assert t["href"] == "https://site.com/good"


def test_pick_skips_denylisted_hrefs():
    base = "https://site.com/"
    cands = [_cand("https://site.com/logout", w=400, h=400, text="Logout")]
    assert pick_walk_target(cands, base, set()) is None


def test_pick_returns_none_when_no_candidates():
    assert pick_walk_target([], "https://site.com/", set()) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_video_capture.py -k "pick or normalize or collect" -q`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Write minimal implementation**

Add to `video_capture.py`:
```python
COLLECT_ANCHORS_JS = """() => {
  const out = [];
  document.querySelectorAll('a[href]').forEach((a) => {
    const r = a.getBoundingClientRect();
    if (r.width < 10 || r.height < 10) return;
    out.push({
      href: a.href || "",
      x: r.x + r.width / 2,
      y: r.y + r.height / 2,
      w: r.width,
      h: r.height,
      text: (a.innerText || "").trim().slice(0, 48),
    });
  });
  return out;
}"""

# Hrefs whose path/text suggest a state-changing or dead-end action. Never walk into these.
_WALK_DENY = ("logout", "signout", "sign-out", "log-out", "delete", "remove", "/wp-admin")

# Visible band for a walk target: keep the eventual cursor inside the rendered frame.
_WALK_Y_MIN = 0.03
_WALK_Y_MAX = 0.72


def normalize_url(url: str) -> str:
    """URL without fragment or trailing slash, host lowercased (for dedupe)."""
    p = urlparse(url)
    host = (p.hostname or "").lower()
    netloc = host + (f":{p.port}" if p.port else "")
    path = p.path.rstrip("/")
    base = f"{p.scheme}://{netloc}{path}"
    return base + (f"?{p.query}" if p.query else "")


def pick_walk_target(
    candidates: list[dict],
    base_url: str,
    visited: set[str],
    *,
    vw: int = 1280,
    vh: int = 800,
) -> dict | None:
    """Largest visible same-origin, unvisited, non-denied link in the top 72%."""
    best = None
    best_area = 0.0
    for c in candidates:
        href = c.get("href") or ""
        if not same_origin(base_url, href):
            continue
        if normalize_url(href) in visited:
            continue
        low = href.lower()
        if any(word in low for word in _WALK_DENY):
            continue
        yf = c["y"] / vh
        xf = c["x"] / vw
        if not (_WALK_Y_MIN <= yf <= _WALK_Y_MAX and 0.0 <= xf <= 1.0):
            continue
        area = float(c.get("w", 0)) * float(c.get("h", 0))
        if area > best_area:
            best_area = area
            best = {"href": href, "x": round(xf, 3), "y": round(yf, 3),
                    "label": (c.get("text") or "").strip()}
    return best
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_video_capture.py -k "pick or normalize or collect" -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/video_capture.py mcp-servers/tasks/tests/test_video_capture.py
git commit -m "feat(video): add pick_walk_target and anchor collection for walk capture"
```

---

### Task 3: `_walk_with_page` loop + `capture_walk`

**Files:**
- Modify: `mcp-servers/tasks/video_capture.py`
- Test: `mcp-servers/tasks/tests/test_video_capture.py`

**Interfaces:**
- Consumes: `pick_walk_target`, `normalize_url`, `COLLECT_ANCHORS_JS`, `extract_site_context`, `assert_capturable`, `_CAPTURE_LOCK` (existing).
- Produces:
  - `async def _walk_with_page(page, start_url: str, *, max_pages: int, guard, vw: int, vh: int, settle_ms: int) -> tuple[list[bytes], list[dict], dict]` — the browser-agnostic walk loop. `page` must provide async `goto(url)`, `evaluate(script)`, `screenshot()`, `title()`, and a `url` property; `guard` is an async callable `guard(url) -> None` that raises to block a URL.
  - `async def capture_walk(url: str, *, max_pages: int = 4, viewport: tuple[int, int] = (1280, 800), nav_timeout_ms: int = 30000) -> tuple[list[bytes], list[dict], dict]` — creates a real Playwright page and runs `_walk_with_page`. Returns `(frames, walk, site_context)` where `walk[i] = {"url", "title", "click": {"x","y","label"} | None}`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_video_capture.py`:
```python
import pytest
from video_capture import _walk_with_page


class _FakePage:
    """Minimal page stub: programmed anchors per URL; goto follows them."""
    def __init__(self, anchors_by_url):
        self._anchors = anchors_by_url
        self.url = ""

    async def goto(self, url, **kw):
        self.url = url

    async def evaluate(self, script, *args):
        if "scrollTo" in script:
            return None
        if "querySelectorAll" in script:      # COLLECT_ANCHORS_JS
            return self._anchors.get(self.url, [])
        return {}                              # extract_site_context internals

    async def screenshot(self, **kw):
        return b"PNG:" + self.url.encode()

    async def title(self):
        return "Title " + self.url

    async def wait_for_timeout(self, ms):
        return None


async def _noop_guard(url):
    return None


@pytest.mark.asyncio
async def test_walk_follows_links_until_no_target():
    anchors = {
        "https://s.com/": [{"href": "https://s.com/a", "x": 100, "y": 300, "w": 300, "h": 200, "text": "A"}],
        "https://s.com/a": [{"href": "https://s.com/b", "x": 100, "y": 300, "w": 300, "h": 200, "text": "B"}],
        "https://s.com/b": [],   # dead end
    }
    page = _FakePage(anchors)
    frames, walk, ctx = await _walk_with_page(
        page, "https://s.com/", max_pages=4, guard=_noop_guard, vw=1280, vh=800, settle_ms=0)
    assert len(frames) == 3
    assert [w["url"] for w in walk] == ["https://s.com/", "https://s.com/a", "https://s.com/b"]
    assert walk[0]["click"]["label"] == "A"
    assert walk[2]["click"] is None            # last page has no onward click


@pytest.mark.asyncio
async def test_walk_dedupes_and_respects_max_pages():
    # Every page links back to home -> must stop via visited-dedupe, not loop.
    anchors = {
        "https://s.com/": [{"href": "https://s.com/x", "x": 100, "y": 300, "w": 300, "h": 200, "text": "X"}],
        "https://s.com/x": [{"href": "https://s.com/", "x": 100, "y": 300, "w": 300, "h": 200, "text": "Home"}],
    }
    page = _FakePage(anchors)
    frames, walk, ctx = await _walk_with_page(
        page, "https://s.com/", max_pages=4, guard=_noop_guard, vw=1280, vh=800, settle_ms=0)
    assert len(frames) == 2                     # home, x, then x's only link is visited -> stop
    assert walk[1]["click"] is None
```

Note: the repo already configures pytest-asyncio (existing async tests in this dir). If `test_walk_*` errors with "async def not natively supported", add `@pytest.mark.asyncio` (already present) and confirm `pytest.ini`/`pyproject` has `asyncio_mode`; the other async tests in `tests/` establish the pattern.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_video_capture.py -k walk_ -q`
Expected: FAIL with `ImportError: cannot import name '_walk_with_page'`.

- [ ] **Step 3: Write minimal implementation**

Add to `video_capture.py`:
```python
async def _walk_with_page(page, start_url, *, max_pages, guard, vw, vh, settle_ms):
    """Browser-agnostic walk: goto -> screenshot(top) -> pick next same-origin
    link -> record its click coord -> goto it. Stops on no target, revisit, or
    max_pages. Returns (frames, walk, site_context)."""
    frames: list[bytes] = []
    walk: list[dict] = []
    visited: set[str] = set()
    site_context: dict = {}
    cur = start_url
    for i in range(max_pages):
        await guard(cur)
        await page.goto(cur, wait_until="domcontentloaded", timeout=None)
        if settle_ms:
            await page.wait_for_timeout(settle_ms)
        await page.evaluate("window.scrollTo(0, 0)")
        frames.append(await page.screenshot())
        real_url = page.url or cur
        visited.add(normalize_url(real_url))
        if i == 0:
            site_context = await extract_site_context(page)
        candidates = await page.evaluate(COLLECT_ANCHORS_JS)
        target = pick_walk_target(candidates or [], real_url, visited, vw=vw, vh=vh)
        walk.append({
            "url": real_url,
            "title": await page.title(),
            "click": (None if not target
                      else {"x": target["x"], "y": target["y"], "label": target["label"]}),
        })
        if not target:
            break
        cur = target["href"]
    return frames, walk, site_context


async def capture_walk(url, *, max_pages=4, viewport=(1280, 800), nav_timeout_ms=30000):
    """Navigate up to max_pages same-origin pages, screenshotting each and
    recording the click that leads to the next. Falls back to a single page when
    the site has no followable link."""
    from playwright.async_api import async_playwright  # local import, mirrors capture_site

    await assert_capturable(url)
    vw, vh = viewport
    async with _CAPTURE_LOCK:
        async with async_playwright() as p:
            browser = await p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
            try:
                page = await browser.new_page(viewport={"width": vw, "height": vh})
                page.set_default_navigation_timeout(nav_timeout_ms)
                await page.route("**/*", _route)  # existing SSRF route interceptor
                frames, walk, ctx = await _walk_with_page(
                    page, url, max_pages=max_pages, guard=assert_capturable,
                    vw=vw, vh=vh, settle_ms=2500)
            finally:
                await browser.close()
    return frames, walk, ctx
```

Note for the implementer: confirm the exact name/signature of the existing route interceptor (`_route`) and `_CAPTURE_LOCK` in `video_capture.py` and match them; if `_route` needs a different arg shape, wire it as `capture_site` does. `capture_walk` is exercised end to end by the manual VPS verification step at the end of this plan; the unit tests cover `_walk_with_page` with a fake page.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_video_capture.py -k walk_ -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/video_capture.py mcp-servers/tasks/tests/test_video_capture.py
git commit -m "feat(video): add capture_walk multi-page navigator"
```

---

### Task 4: `build_walk_plan`

**Files:**
- Create: `mcp-servers/tasks/video_walk_plan.py`
- Test: `mcp-servers/tasks/tests/test_video_walk_plan.py`

**Interfaces:**
- Consumes: `sanitize_anim_clicks` from `video_plan` (existing, keeps click only on `kind=="screenshot"` scenes with numeric x,y in [0,1]).
- Produces:
  - `_clean_headline(title: str) -> str` — first clause of a page title, site-suffix stripped, <= 48 chars.
  - `build_walk_plan(walk: list[dict], screenshot_names: list[str], site_context: dict, *, fps: int = 24, max_duration_s: float = 40.0) -> dict` — returns `{"scenes": [...]}`. Scenes: intro card, one `kind=="screenshot"` scene per walked page (`screenshot`=filename, `click`=that page's real click when present, `motion` cycled, `headline` from title, `subtext`=url path), outro card. Trailing page scenes are dropped if the total would exceed `max_duration_s`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_video_walk_plan.py`:
```python
from video_walk_plan import build_walk_plan, _clean_headline


def test_clean_headline_strips_site_suffix():
    assert _clean_headline("Home | Animepahe") == "Home"
    assert _clean_headline("Watch X Episode 1 - Animepahe") == "Watch X Episode 1"
    assert _clean_headline("") == ""


def _walk():
    return [
        {"url": "https://s.com/", "title": "Home | S", "click": {"x": 0.09, "y": 0.47, "label": "Show"}},
        {"url": "https://s.com/watch", "title": "Watch | S", "click": {"x": 0.35, "y": 0.69, "label": "Play"}},
        {"url": "https://s.com/series", "title": "Series | S", "click": None},
    ]


def test_build_walk_plan_shape():
    plan = build_walk_plan(_walk(), ["screenshot-1.png", "screenshot-2.png", "screenshot-3.png"],
                           {"host": "s.com"})
    scenes = plan["scenes"]
    # intro + 3 pages + outro
    assert len(scenes) == 5
    assert scenes[0]["kind"] == "intro" and "screenshot" not in scenes[0]
    assert scenes[-1]["kind"] == "outro"
    page_scenes = scenes[1:-1]
    assert [s["screenshot"] for s in page_scenes] == ["screenshot-1.png", "screenshot-2.png", "screenshot-3.png"]
    assert page_scenes[0]["click"] == {"x": 0.09, "y": 0.47, "label": "Show"}
    assert "click" not in page_scenes[2]           # None click omitted
    assert page_scenes[0]["headline"] == "Home"


def test_build_walk_plan_respects_duration_cap():
    walk = [{"url": f"https://s.com/{i}", "title": f"P{i}", "click": None} for i in range(20)]
    names = [f"screenshot-{i+1}.png" for i in range(20)]
    plan = build_walk_plan(walk, names, {"host": "s.com"}, max_duration_s=40.0)
    total = sum(s["duration_s"] for s in plan["scenes"])
    assert total <= 40.0
    assert plan["scenes"][0]["kind"] == "intro" and plan["scenes"][-1]["kind"] == "outro"


def test_build_walk_plan_single_page():
    walk = [{"url": "https://s.com/", "title": "Only | S", "click": None}]
    plan = build_walk_plan(walk, ["screenshot-1.png"], {"host": "s.com"})
    assert [s["kind"] for s in plan["scenes"]] == ["intro", "screenshot", "outro"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_video_walk_plan.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'video_walk_plan'`.

- [ ] **Step 3: Write minimal implementation**

Create `video_walk_plan.py`:
```python
"""Deterministic Remotion plan for the Default flow: turn a captured site walk
into an intro card -> clicked-page scenes -> outro card, using the real click
coordinates so the smart cursor lands on the element that advanced each page."""
from urllib.parse import urlparse

from video_plan import sanitize_anim_clicks

_MOTIONS = ["zoom-in", "fade", "pan-up", "zoom-out"]
_CARD_S = 2.6
_PAGE_S = 4.0
_SEP = (" | ", " - ", " – ", " :: ", " · ")


def _clean_headline(title: str) -> str:
    text = " ".join((title or "").split())
    for sep in _SEP:
        i = text.find(sep)
        if i > 0:
            text = text[:i]
            break
    return text.strip()[:48]


def _subtext(url: str) -> str:
    path = urlparse(url).path.strip("/")
    return path.split("/")[0].replace("-", " ").title() if path else "Home"


def build_walk_plan(walk, screenshot_names, site_context, *, fps=24, max_duration_s=40.0):
    """Intro card + one screenshot scene per walked page (with its real click) +
    outro card. Drops trailing page scenes so the total fits max_duration_s."""
    host = (site_context or {}).get("host") or "your site"
    # How many page scenes fit alongside the two cards.
    budget = max_duration_s - 2 * _CARD_S
    max_pages = max(0, int(budget // _PAGE_S))
    pairs = list(zip(walk, screenshot_names))[:max_pages]

    scenes = [{
        "kind": "intro", "headline": host, "subtext": "A quick tour",
        "motion": "fade", "duration_s": _CARD_S,
    }]
    for i, (w, name) in enumerate(pairs):
        scene = {
            "kind": "screenshot",
            "screenshot": name,
            "headline": _clean_headline(w.get("title", "")) or host,
            "subtext": _subtext(w.get("url", "")),
            "motion": _MOTIONS[i % len(_MOTIONS)],
            "duration_s": _PAGE_S,
        }
        click = w.get("click")
        if isinstance(click, dict) and "x" in click and "y" in click:
            scene["click"] = {"x": click["x"], "y": click["y"], "label": click.get("label", "")}
        scenes.append(scene)
    scenes.append({
        "kind": "outro", "headline": host, "subtext": "Watch anytime",
        "motion": "fade", "duration_s": _CARD_S,
    })
    return sanitize_anim_clicks({"scenes": scenes})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_video_walk_plan.py -q`
Expected: PASS (5 passed).

Verify `sanitize_anim_clicks` returns the plan dict (not None) and preserves `scenes`; if its signature differs, adapt the call. Check its definition at `video_plan.py:431-460`.

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/video_walk_plan.py mcp-servers/tasks/tests/test_video_walk_plan.py
git commit -m "feat(video): add build_walk_plan for Default-flow videos"
```

---

### Task 5: capture route persists `walk.json`

**Files:**
- Modify: `mcp-servers/tasks/routes_video.py` (`capture_from_url`, around `:808-864`)
- Test: `mcp-servers/tasks/tests/test_routes_video_capture.py`

**Interfaces:**
- Consumes: `capture_walk` (Task 3).
- Produces: after a capture, `<APPS_DIR>/<slug>/.video/<job_id>/walk.json` exists containing the `walk` list; screenshots and `site_context.json` are written as before.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_routes_video_capture.py` (follow the existing fixtures/pattern in that file for app setup, auth header `X-User-Email`, and monkeypatching capture). Mirror how the existing capture test patches `capture_site`:
```python
def test_capture_from_url_writes_walk_json(monkeypatch, tmp_path, client, draft_job):
    # draft_job: (job_id, slug) for a collecting draft owned by test user (existing fixture)
    job_id, slug = draft_job
    fake_walk = [
        {"url": "https://s.com/", "title": "Home", "click": {"x": 0.1, "y": 0.4, "label": "A"}},
        {"url": "https://s.com/a", "title": "A", "click": None},
    ]

    async def fake_capture_walk(url, **kw):
        return ([b"PNG1", b"PNG2"], fake_walk, {"title": "Home"})

    monkeypatch.setattr("routes_video.capture_walk", fake_capture_walk)

    r = client.post(f"/api/video-jobs/{job_id}/capture-from-url",
                    json={"url": "https://s.com/", "max_frames": 4},
                    headers={"X-User-Email": "u@example.com"})
    assert r.status_code == 200

    import json
    walk_path = tmp_path_for_job(slug, job_id) / "walk.json"   # helper mirroring APPS_DIR layout
    assert walk_path.exists()
    assert json.loads(walk_path.read_text())[0]["click"]["label"] == "A"
```
If the existing capture test uses a different fixture/helper naming, reuse those exact helpers instead of `draft_job`/`tmp_path_for_job`; the assertion that matters is `walk.json` exists with the walk content.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_routes_video_capture.py -k walk_json -q`
Expected: FAIL (route still calls `capture_site`; no `walk.json` written; `AttributeError` on `routes_video.capture_walk` patch or missing file).

- [ ] **Step 3: Write minimal implementation**

In `routes_video.py`:
1. Update the import: add `capture_walk` next to `capture_site` (find the `from video_capture import ...` line).
2. In `capture_from_url` (~`:847`), replace the single-page capture call and add walk persistence:
```python
        # Multi-page walk: screenshots + the real click coord that advances each page.
        captured, walk, site_context = await asyncio.wait_for(
            capture_walk(body.url, max_pages=min(body.max_frames or 4, 4)),
            timeout=90.0,
        )
```
3. After `site_context.json` is written (~`:858-863`), also write `walk.json`:
```python
        walk_path = os.path.join(job_video_dir, "walk.json")   # same dir as site_context.json
        with open(walk_path, "w", encoding="utf-8") as f:
            json.dump(walk, f)
```
Use the same directory variable the route already uses for `site_context.json`; confirm `json` and `os` are imported at the top of the module (add if missing).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_routes_video_capture.py -k walk_json -q`
Expected: PASS.

Then run the whole capture route test module to catch regressions:
Run: `python -m pytest tests/test_routes_video_capture.py -q`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/routes_video.py mcp-servers/tasks/tests/test_routes_video_capture.py
git commit -m "feat(video): capture-from-url walks pages and persists walk.json"
```

---

### Task 6: worker routing (Default flow -> walk plan + template cursor)

**Files:**
- Modify: `mcp-servers/tasks/video_worker.py` (`_process_job`, plan selection `:125-146`, dispatch `:155-173`)
- Test: `mcp-servers/tasks/tests/test_video_worker.py`

**Interfaces:**
- Consumes: `build_walk_plan` (Task 4), `_planner_inputs` (existing), `ai_codegen_enabled` / `render_remotion_or_ai` (existing).
- Produces: for a `remotion` job with an empty prompt and a readable `walk.json`, the worker builds the plan via `build_walk_plan` and dispatches with `ai_enabled=False`. Non-empty prompt or missing `walk.json` keeps current behaviour.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_video_worker.py`. Follow the module's existing job/DB fixtures and `_fake_job` helper. Two behaviours to lock:
```python
def test_default_flow_uses_walk_plan(monkeypatch):
    calls = {}

    def fake_build_walk_plan(walk, names, ctx, **kw):
        calls["walk_plan"] = True
        return {"scenes": [{"kind": "intro", "duration_s": 2.6}]}

    # Assert render dispatch receives ai_enabled=False for empty prompt.
    async def fake_render_or_ai(*a, ai_enabled=None, **kw):
        calls["ai_enabled"] = ai_enabled
        return "/out.mp4"

    monkeypatch.setattr("video_worker.build_walk_plan", fake_build_walk_plan, raising=False)
    monkeypatch.setattr("video_worker.render_remotion_or_ai", fake_render_or_ai, raising=False)
    # ... arrange a remotion job with prompt="" and a walk.json present (use module fixtures),
    #     run _process_job, then:
    assert calls.get("walk_plan") is True
    assert calls.get("ai_enabled") is False


def test_custom_flow_skips_walk_plan(monkeypatch):
    calls = {}
    monkeypatch.setattr("video_worker.build_walk_plan",
                        lambda *a, **k: calls.setdefault("walk_plan", True), raising=False)
    # ... arrange a remotion job with prompt="make it punchy", run _process_job ...
    assert "walk_plan" not in calls
```
Match the exact arrangement (async runner, DB session, monkeypatching `generate_anim_plan`) to the patterns already in `test_video_worker.py` / `test_video_pipeline.py`. The two assertions that matter: Default -> `build_walk_plan` called and `ai_enabled=False`; Custom -> `build_walk_plan` not called.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_video_worker.py -k "walk_plan or custom_flow" -q`
Expected: FAIL (worker does not call `build_walk_plan`; `ai_enabled` not forced).

- [ ] **Step 3: Write minimal implementation**

In `video_worker.py`:
1. Add imports near the other video imports:
```python
from video_walk_plan import build_walk_plan
```
2. Add a small loader helper (near `_planner_inputs`, `:41-54`):
```python
def _load_walk(slug: str, job_id: str) -> list | None:
    """Read the persisted page walk for a job, or None if absent/unreadable."""
    path = os.path.join(APPS_DIR, slug, ".video", job_id, "walk.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) and data else None
    except (OSError, ValueError):
        return None
```
Confirm `os` and `json` are imported in `video_worker.py` (add if missing).
3. In `_process_job`, compute the flag once after reading job columns (after `:122`):
```python
    is_default = not (prompt or "").strip()
```
4. Plan selection (`:125-146`) — add the Default-flow branch first:
```python
    if not plan:
        screenshots, screenshot_paths, site_context = _planner_inputs(slug, str(job_id))
        walk = _load_walk(slug, str(job_id)) if is_default else None
        if render_mode == "remotion" and walk:
            names = [name for name, _ in screenshot_paths]  # filenames in capture order
            plan = build_walk_plan(walk, names, site_context)
        elif render_mode in ("animated", "remotion"):
            plan = await generate_anim_plan(
                prompt, screenshots, site_context=site_context,
                screenshot_paths=screenshot_paths, animation_preset=animation_preset)
        else:
            plan = await generate_plan(
                prompt, screenshots, site_context=site_context,
                screenshot_paths=screenshot_paths)
```
Match `_planner_inputs`'s actual return shape for `screenshot_paths` (list of `(name, abs_path)`); use `name` for the plan's screenshot filenames.
5. Dispatch (`:163-171`) — force the template+cursor path for the Default flow:
```python
    elif render_mode == "remotion":
        from video_codegen import render_remotion_or_ai, ai_codegen_enabled
        ai_enabled = (not is_default) and ai_codegen_enabled()
        ss, ss_paths, ctx = (
            _planner_inputs(slug, str(job_id)) if ai_enabled else (None, None, None)
        )
        out = await render_remotion_or_ai(
            APPS_DIR, slug, str(job_id), plan, prompt,
            voice=voice, animation_preset=animation_preset,
            screenshots=ss, screenshot_paths=ss_paths, site_context=ctx,
            ai_enabled=ai_enabled, _template_job=render_remotion_job)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_video_worker.py -k "walk_plan or custom_flow" -q`
Expected: PASS.

Then the worker + pipeline modules:
Run: `python -m pytest tests/test_video_worker.py tests/test_video_pipeline.py tests/test_video_render_mode.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/video_worker.py mcp-servers/tasks/tests/test_video_worker.py
git commit -m "feat(video): Default flow builds walk plan and forces template cursor path"
```

---

### Task 7: full suite + manual VPS verification

**Files:** none (verification only).

- [ ] **Step 1: Run the full tasks test suite**

Run: `python -m pytest -q`
Expected: PASS (no regressions). Investigate any failure before proceeding.

- [ ] **Step 2: Em-dash / attribution scan on changed files**

Run:
```bash
git diff --name-only origin/main... | grep -E '\.(py)$' | xargs grep -n "[—–]" || echo "clean"
```
Expected: `clean` (or only pre-existing hits outside the new code). Fix any new occurrences.

- [ ] **Step 3: Deploy to VPS and verify a real Default-flow job**

Deploy the changed tasks files per CLAUDE.md (scp changed files, rebuild the `tasks` container). Then run a real Default flow (URL, no prompt) for a multi-page site through the normal draft -> capture-from-url -> queue path, or trigger it via the Discord "Generate now" button. Poll to `done`, download the mp4, extract frames at click moments with ffmpeg, and confirm: multiple distinct pages appear and the cursor lands on the clicked element on each page (same verification used for the animepahe demo). `AI_VIDEO_CODEGEN=1` must remain set on the box; the Default flow should still render the cursor because the worker forces `ai_enabled=False`.

- [ ] **Step 4: Final commit / branch push**

```bash
git status
# branch feat/default-walk-cursor-video already holds the commits; push when ready
```

---

## Self-Review

**Spec coverage:**
- capture_walk (multi-page, same-origin only, single-page fallback) -> Tasks 1-3. Fallback: `capture_walk` returns 1 page when no target found (Task 3 loop `break`), and the worker/plan handle a 1-page walk (Task 4 `test_build_walk_plan_single_page`).
- build_walk_plan (intro/pages/outro, real clicks, duration cap, no narration) -> Task 4.
- walk.json persistence -> Task 5.
- Worker routing (Default -> walk plan; force template via `ai_enabled=False`; Custom unchanged; missing walk.json -> fallback) -> Task 6.
- Safety (same-origin links only, deny-list, y<=0.72) -> Tasks 1-2. SSRF guard on every navigated URL -> Task 3 (`guard=assert_capturable`).
- No migration -> confirmed (walk.json + plan_json only).

**Placeholder scan:** No TBD/TODO; every code step shows complete code. The two integration tasks (5, 6) instruct the implementer to reuse the module's existing fixtures rather than inventing new ones; the assertion targets are explicit.

**Type consistency:** `capture_walk`/`_walk_with_page` return `(frames, walk, site_context)` used identically in Tasks 5-6. `walk` item shape `{"url","title","click":{"x","y","label"}|None}` is consistent across Tasks 3, 4, 5, 6. `pick_walk_target` returns `{"href","x","y","label"}` (href for navigation, x/y/label for the scene) consumed in Task 3. `build_walk_plan(walk, screenshot_names, site_context)` signature matches its call in Task 6.
