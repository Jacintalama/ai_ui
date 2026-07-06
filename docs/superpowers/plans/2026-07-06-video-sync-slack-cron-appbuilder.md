# Video Generator on Slack, Cron, and App Builder - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One shared server-side video template registry feeding the web UI, new Slack/Discord template pickers, a dedicated `video` cron schedule kind, and a one-click "Walkthrough video" button in App Builder's My apps.

**Architecture:** The tasks service owns the registry (`video_templates.py` + `GET /api/video-jobs/templates`) and gains a `kind='video'` branch in the scheduler that drives the video pipeline directly (no LLM). The webhook-handler reads the registry through a non-blocking cache and adds thin UI on the existing Discord/Slack video panels, cron panels, and App Builder menus, reusing the existing job runners (`_watch_video`, `_watch_slack_video`).

**Tech Stack:** FastAPI + SQLAlchemy async + raw SQL migrations (tasks), aiohttp-style Discord/Slack block builders + pytest with AsyncMock (webhook-handler).

**Spec:** `docs/superpowers/specs/2026-07-06-video-sync-slack-cron-appbuilder-design.md`

## Global Constraints

- NO em-dashes or en-dashes anywhere (code, copy, comments, commits). Use `-` or commas; when the character itself is needed at runtime, write it as a `\u2013` / `\u2014` escape in code.
- NO AI/Claude attribution in commits or PRs. Author is Ralph Benitez (thunder500) only.
- NEVER touch `.env`. NEVER deploy local `mcp-servers/tasks/templates.py` (server copy is ahead; our NEW file `video_templates.py` is a different file and fine).
- Work on branch `feat/video-sync-surfaces` cut from `main`.
- tasks tests run from `mcp-servers/tasks/`; webhook-handler tests from `webhook-handler/`. Pre-existing known failures: `mcp-servers/tasks/tests/test_scheduler.py` fails COLLECTION locally (missing tzdata) - always exclude with `--ignore=tests/test_scheduler.py` unless the task says otherwise; webhook-handler has ~23 pre-existing failures unrelated to video - run per-file tests, not the whole suite.
- DB-gated tests (needing Postgres) skip locally; that is normal.
- The tasks app runs from the BAKED /app image on prod; deploy = rebuild, not restart. Deploy only in the final task.
- Style keys are exactly: `clean_product_demo`, `cinematic`, `snappy_social`. Template keys: `walkthrough`, `product`, `cinematic`, `social`. Default template key: `walkthrough`.
- New custom_id namespaces introduced by this plan: `aiuivid:tpl:` (Discord video template select), `aiuisched:newvid` / `aiuisched:vidmodal` / `aiuisched:vidtpl:` (Discord cron video), `aiuibuild:video:` (walkthrough button, both platforms), Slack callback `aiuisched_vidmodal`, Slack block/action ids `vid_template`, `sched_vid_*`.

---

### Task 1: Tasks service - template registry + `/templates` endpoint

**Files:**
- Create: `mcp-servers/tasks/video_templates.py`
- Modify: `mcp-servers/tasks/routes_video.py` (imports near line 45; new route right after `voices()` at lines 340-345)
- Test: `mcp-servers/tasks/tests/test_video_templates.py`

**Interfaces:**
- Produces: `video_templates.VIDEO_TEMPLATES: list[dict]`, `DEFAULT_TEMPLATE_KEY = "walkthrough"`, `template_catalog() -> list[dict]`, `get_template(key: str) -> dict | None`, `template_prompts() -> set[str]`; HTTP `GET /api/video-jobs/templates` returning `{"templates": [...], "default": "walkthrough"}`. Each template dict has keys: `key, emoji, name, badge (optional), desc, style, remotion, prompt`.
- Consumed by: Task 2 (video.html fetch), Task 3 (TasksClient), Task 7 (scheduler).

- [ ] **Step 1: Create the branch**

```bash
cd "/c/All/Work - Code/ai_ui" && git checkout -b feat/video-sync-surfaces
```

- [ ] **Step 2: Write the failing tests**

Create `mcp-servers/tasks/tests/test_video_templates.py`:

```python
from templates_video.style_config import STYLE_CONFIGS
from video_templates import (
    DEFAULT_TEMPLATE_KEY,
    VIDEO_TEMPLATES,
    get_template,
    template_catalog,
    template_prompts,
)


def test_registry_has_the_four_templates_in_order():
    assert [t["key"] for t in VIDEO_TEMPLATES] == [
        "walkthrough", "product", "cinematic", "social"]


def test_every_template_is_complete_and_valid():
    for t in VIDEO_TEMPLATES:
        assert t["key"] and t["name"] and t["emoji"]
        assert t["desc"] and t["prompt"]
        assert t["style"] in STYLE_CONFIGS
        assert t["remotion"] is True


def test_default_key_exists():
    assert get_template(DEFAULT_TEMPLATE_KEY) is not None


def test_catalog_returns_copies():
    cat = template_catalog()
    cat[0]["name"] = "mutated"
    assert VIDEO_TEMPLATES[0]["name"] == "Website Walkthrough"


def test_get_template_unknown_returns_none():
    assert get_template("nope") is None
    assert get_template("") is None


def test_template_prompts_is_the_prompt_set():
    assert template_prompts() == {t["prompt"] for t in VIDEO_TEMPLATES}


def test_templates_route_is_registered_before_job_id():
    """The literal /templates path must come before /{job_id} or FastAPI
    swallows it as a job id."""
    import routes_video
    paths = [r.path for r in routes_video.router.routes]
    assert "/api/video-jobs/templates" in paths
    assert paths.index("/api/video-jobs/templates") < paths.index("/api/video-jobs/{job_id}")
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd "/c/All/Work - Code/ai_ui/mcp-servers/tasks" && python -m pytest tests/test_video_templates.py -q`
Expected: FAIL / errors with `ModuleNotFoundError: No module named 'video_templates'`

- [ ] **Step 4: Create `mcp-servers/tasks/video_templates.py`**

The four entries are copied verbatim from `static/video.html` lines 2021-2046 (same keys, names, descs, styles, prompts). Emoji are written as escapes to keep the file ASCII-safe.

```python
"""Server-side registry of the video template presets.

Single source of truth for every surface: the web Video Studio grid, the
Slack and Discord panels, cron video schedules, and App Builder. Adding a
template here makes it appear everywhere (the web grid additionally expects
a preview clip at static/tpl-previews/<key>.mp4). No I/O - pure data.
"""

VIDEO_TEMPLATES: list[dict] = [
    {
        "key": "walkthrough",
        "emoji": "\U0001f5b1️",
        "name": "Website Walkthrough",
        "badge": "Recommended",
        "desc": "A cursor clicks through your pages like a guided tour.",
        "style": "clean_product_demo",
        "remotion": True,
        "prompt": (
            "Click through the site page by page like a guided tour. "
            "Introduce each page as it appears and highlight what a "
            "visitor can do there."
        ),
    },
    {
        "key": "product",
        "emoji": "\U0001f4e6",
        "name": "Product Demo",
        "desc": "Crisp and confident. Features front and center.",
        "style": "clean_product_demo",
        "remotion": True,
        "prompt": (
            "A crisp product demo. Present the key features confidently "
            "and end with a clear call to action."
        ),
    },
    {
        "key": "cinematic",
        "emoji": "\U0001f3ac",
        "name": "Cinematic Showcase",
        "desc": "Dramatic pacing, sweeping visuals, big finish.",
        "style": "cinematic",
        "remotion": True,
        "prompt": (
            "A cinematic showcase with dramatic pacing. Build atmosphere, "
            "sweep through the visuals, and land on a memorable closing line."
        ),
    },
    {
        "key": "social",
        "emoji": "⚡",
        "name": "Snappy Social",
        "desc": "Fast cuts and punchy lines, made for feeds.",
        "style": "snappy_social",
        "remotion": True,
        "prompt": (
            "A fast, punchy social clip. Short energetic lines, quick cuts, "
            "a hook in the first seconds, and a call to action at the end."
        ),
    },
]

DEFAULT_TEMPLATE_KEY = "walkthrough"


def template_catalog() -> list[dict]:
    """Picker payload for GET /api/video-jobs/templates (returns copies)."""
    return [dict(t) for t in VIDEO_TEMPLATES]


def get_template(key: str) -> dict | None:
    """The template with this key, as a copy. None when unknown/empty."""
    for t in VIDEO_TEMPLATES:
        if t["key"] == key:
            return dict(t)
    return None


def template_prompts() -> set[str]:
    """All template prompts - used to detect a prompt the user has not edited."""
    return {t["prompt"] for t in VIDEO_TEMPLATES}
```

- [ ] **Step 5: Add the endpoint in `routes_video.py`**

Add to the import block (near line 45, beside `from video_voices import ...`):

```python
from video_templates import DEFAULT_TEMPLATE_KEY, template_catalog
```

Insert directly AFTER the `voices()` endpoint (after line 345, before `/current-draft` / `/{job_id}`):

```python
# Registered BEFORE "/{job_id}" for the same reason as /voices: a literal
# path after the param route would be captured as a job id. No auth: it is
# a static, non-sensitive catalog shared by every surface.
@router.get("/templates")
async def templates() -> dict:
    """The selectable template presets for the create-form pickers."""
    return {"templates": template_catalog(), "default": DEFAULT_TEMPLATE_KEY}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd "/c/All/Work - Code/ai_ui/mcp-servers/tasks" && python -m pytest tests/test_video_templates.py -q`
Expected: 7 passed

- [ ] **Step 7: Regression-run the neighboring video tests**

Run: `cd "/c/All/Work - Code/ai_ui/mcp-servers/tasks" && python -m pytest tests/test_video_walk_plan.py tests/test_video_capture.py tests/test_video_worker.py -q`
Expected: all pass (42 + 4 + existing worker tests), no new failures

- [ ] **Step 8: Commit**

```bash
cd "/c/All/Work - Code/ai_ui" && git add mcp-servers/tasks/video_templates.py mcp-servers/tasks/routes_video.py mcp-servers/tasks/tests/test_video_templates.py && git commit -m "feat(video): server-side template registry + GET /api/video-jobs/templates"
```

---

### Task 2: Web UI - fetch templates from the registry (inline list becomes fallback)

**Files:**
- Modify: `mcp-servers/tasks/static/video.html` (VIDEO_TEMPLATES const at ~line 2021; `renderTplGrid()` at ~2069; init IIFE at ~2364)

**Interfaces:**
- Consumes: `GET /api/video-jobs/templates` from Task 1 (`const API = "/api/video-jobs"` is already defined at ~line 908).
- Produces: nothing for later tasks. No JS test harness exists for video.html; verification is manual (final task does the live check). Keep the change minimal.

- [ ] **Step 1: Make the grid read a mutable list**

Directly after the closing `];` of `VIDEO_TEMPLATES` (~line 2046), add:

```javascript
    // Live list rendered by the grid. Starts as the baked-in fallback and is
    // replaced by the server registry when /templates loads.
    let videoTemplates = VIDEO_TEMPLATES;
```

In `renderTplGrid()` change the loop line `for (const t of VIDEO_TEMPLATES) {` to:

```javascript
      for (const t of videoTemplates) {
```

(There is exactly one such loop. If any other code indexes `VIDEO_TEMPLATES` directly - search the file for `VIDEO_TEMPLATES` - switch those reads to `videoTemplates` too, EXCEPT the declaration itself.)

- [ ] **Step 2: Add `loadTemplates()` mirroring `loadVoices()`**

Add immediately above the `loadVoices()` function (~line 2267):

```javascript
    async function loadTemplates() {
      try {
        const res = await fetch(API + "/templates", { credentials: "same-origin" });
        if (!res.ok) throw new Error("templates " + res.status);
        const data = await res.json();
        const list = (data && data.templates) || [];
        if (!list.length) throw new Error("no templates");
        videoTemplates = list;
        renderTplGrid();
      } catch (e) {
        // Degrade gracefully: the baked-in VIDEO_TEMPLATES fallback stays.
      }
    }
```

- [ ] **Step 3: Call it from init**

Change the init IIFE (~lines 2364-2367) to:

```javascript
    (function init() {
      renderFromUrl();
      loadVoices();
      loadTemplates();
    })();
```

- [ ] **Step 4: Sanity-check the file parses**

Run: `cd "/c/All/Work - Code/ai_ui" && node --input-type=module -e "const fs=require('node:fs');const html=fs.readFileSync('mcp-servers/tasks/static/video.html','utf8');const m=html.match(/<script>([\s\S]*)<\/script>\s*<\/body>/);new Function(m[1]);console.log('JS OK')"`
Expected: `JS OK` (constructing the Function only parses; it does not run the DOM code). If node is unavailable, skip and rely on the final-task live check.

- [ ] **Step 5: Commit**

```bash
cd "/c/All/Work - Code/ai_ui" && git add mcp-servers/tasks/static/video.html && git commit -m "feat(video-ui): template grid loads from the server registry with inline fallback"
```

---

### Task 3: webhook-handler - TasksClient.get_video_templates + non-blocking template cache

**Files:**
- Modify: `webhook-handler/clients/tasks.py` (add beside `get_video_voices` at line 263)
- Create: `webhook-handler/handlers/video_templates.py`
- Test: `webhook-handler/tests/test_video_templates_cache.py`

**Interfaces:**
- Consumes: `GET /api/video-jobs/templates` (Task 1).
- Produces: `TasksClient.get_video_templates() -> dict`; module `handlers.video_templates` with `FALLBACK_TEMPLATES: list[dict]`, `DEFAULT_TEMPLATE_KEY = "walkthrough"`, `cached_templates() -> list[dict]` (never blocks, never empty), `get_template(key) -> dict | None`, `template_prompts() -> set[str]`, `cache_is_fresh() -> bool`, `async refresh_templates(tasks_client) -> bool`. Panels (Tasks 4, 5, 9, 10) call `cached_templates()` synchronously and spawn `refresh_templates()` in the background - the 3s interaction window must never wait on HTTP.

- [ ] **Step 1: Write the failing tests**

Create `webhook-handler/tests/test_video_templates_cache.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock

from handlers import video_templates as vtpl


@pytest.fixture(autouse=True)
def _reset_cache():
    vtpl._cache = list(vtpl.FALLBACK_TEMPLATES)
    vtpl._fetched_at = 0.0
    yield
    vtpl._cache = list(vtpl.FALLBACK_TEMPLATES)
    vtpl._fetched_at = 0.0


def test_fallback_has_the_four_templates():
    assert [t["key"] for t in vtpl.FALLBACK_TEMPLATES] == [
        "walkthrough", "product", "cinematic", "social"]
    for t in vtpl.FALLBACK_TEMPLATES:
        assert t["style"] and t["prompt"] and t["name"]


def test_cached_templates_never_empty_and_is_a_copy():
    got = vtpl.cached_templates()
    assert got
    got.clear()
    assert vtpl.cached_templates()


def test_get_template_and_unknown():
    assert vtpl.get_template("walkthrough")["style"] == "clean_product_demo"
    assert vtpl.get_template("nope") is None


def test_cache_starts_stale():
    assert vtpl.cache_is_fresh() is False


@pytest.mark.asyncio
async def test_refresh_replaces_cache_and_freshens():
    tc = MagicMock()
    tc.get_video_templates = AsyncMock(return_value={
        "templates": [{"key": "walkthrough", "name": "WT", "style": "cinematic",
                       "prompt": "p", "emoji": "x", "desc": "d", "remotion": True}],
        "default": "walkthrough"})
    ok = await vtpl.refresh_templates(tc)
    assert ok is True
    assert vtpl.cache_is_fresh() is True
    assert vtpl.cached_templates()[0]["style"] == "cinematic"


@pytest.mark.asyncio
async def test_refresh_failure_keeps_fallback():
    tc = MagicMock()
    tc.get_video_templates = AsyncMock(side_effect=RuntimeError("down"))
    ok = await vtpl.refresh_templates(tc)
    assert ok is False
    assert [t["key"] for t in vtpl.cached_templates()] == [
        "walkthrough", "product", "cinematic", "social"]


@pytest.mark.asyncio
async def test_refresh_empty_payload_keeps_fallback():
    tc = MagicMock()
    tc.get_video_templates = AsyncMock(return_value={"templates": []})
    ok = await vtpl.refresh_templates(tc)
    assert ok is False
    assert vtpl.cached_templates()


def test_template_prompts_includes_fallback_prompts():
    prompts = vtpl.template_prompts()
    for t in vtpl.FALLBACK_TEMPLATES:
        assert t["prompt"] in prompts
```

- [ ] **Step 2: Run to verify failure**

Run: `cd "/c/All/Work - Code/ai_ui/webhook-handler" && python -m pytest tests/test_video_templates_cache.py -q`
Expected: FAIL with `ModuleNotFoundError` / `ImportError` on `handlers.video_templates`

- [ ] **Step 3: Add the client method**

In `webhook-handler/clients/tasks.py`, directly above `get_video_voices` (line 263), add:

```python
    async def get_video_templates(self) -> dict[str, Any]:
        """Template preset catalog (static registry - not user-scoped)."""
        resp = await self._request("GET", "/api/video-jobs/templates", "system@aiui.local")
        return resp.json()
```

- [ ] **Step 4: Create `webhook-handler/handlers/video_templates.py`**

`FALLBACK_TEMPLATES` mirrors `mcp-servers/tasks/video_templates.py` exactly (same 4 dicts - copy them from Task 1 Step 4 verbatim, including the escape-form emoji). Then:

```python
"""Cached copy of the tasks service's video template registry.

Slack/Discord interactions must answer within ~3 seconds, so panels read a
module-level cache synchronously and spawn refresh_templates() in the
background. FALLBACK_TEMPLATES mirrors the server registry and covers the
window before the first successful refresh (and outages).
"""
import logging
import time

logger = logging.getLogger(__name__)

FALLBACK_TEMPLATES: list[dict] = [
    # ... the 4 template dicts, verbatim from mcp-servers/tasks/video_templates.py ...
]

DEFAULT_TEMPLATE_KEY = "walkthrough"
_TTL_SECONDS = 600.0

_cache: list[dict] = list(FALLBACK_TEMPLATES)
_fetched_at: float = 0.0


def cached_templates() -> list[dict]:
    """The current template list - never blocks, never empty."""
    return [dict(t) for t in _cache]


def get_template(key: str) -> dict | None:
    for t in _cache:
        if t.get("key") == key:
            return dict(t)
    return None


def template_prompts() -> set[str]:
    """Known template prompts (cache + fallback) - detects unedited prompts."""
    return ({t.get("prompt", "") for t in _cache}
            | {t["prompt"] for t in FALLBACK_TEMPLATES}) - {""}


def cache_is_fresh(now: float | None = None) -> bool:
    return ((now if now is not None else time.monotonic()) - _fetched_at) < _TTL_SECONDS


async def refresh_templates(tasks_client) -> bool:
    """Pull the registry from the tasks service. True on success; on any
    failure the previous cache (or fallback) stays in place."""
    global _cache, _fetched_at
    try:
        data = await tasks_client.get_video_templates()
        templates = [t for t in (data.get("templates") or []) if t.get("key")]
        if templates:
            _cache = templates
            _fetched_at = time.monotonic()
            return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("video template refresh failed: %s", exc)
    return False
```

NOTE for the implementer: replace the `# ...` comment with the actual four dicts; the test asserts their keys and non-empty fields.

- [ ] **Step 5: Run the tests**

Run: `cd "/c/All/Work - Code/ai_ui/webhook-handler" && python -m pytest tests/test_video_templates_cache.py -q`
Expected: 9 passed

- [ ] **Step 6: Commit**

```bash
cd "/c/All/Work - Code/ai_ui" && git add webhook-handler/clients/tasks.py webhook-handler/handlers/video_templates.py webhook-handler/tests/test_video_templates_cache.py && git commit -m "feat(video): tasks client template fetch + non-blocking template cache"
```

---

### Task 4: Discord video panel - template select + apply runner

**Files:**
- Modify: `webhook-handler/handlers/video_panel.py` (constants ~line 28; new builder after `build_mode_select` ~line 168; `build_options_components` at 200-211; predicates block 237-278)
- Modify: `webhook-handler/handlers/discord_commands.py` (select dispatch at ~427-445; `_open_video_options` at 1074-1105; new `_run_video_apply_template` beside `_run_video_set` at 1046)
- Modify: `webhook-handler/handlers/commands.py` (new runner beside `run_video_set_field` at ~2939)
- Test: `webhook-handler/tests/test_video_panel.py` (extend), `webhook-handler/tests/test_video_runners.py` (extend)

**Interfaces:**
- Consumes: `handlers.video_templates.cached_templates() / get_template() / cache_is_fresh() / refresh_templates()` (Task 3); `TasksClient.set_video_draft_fields` (exists).
- Produces: `TPL_PREFIX = "aiuivid:tpl:"`, `build_template_select(job_id, templates, current="") -> dict`, `is_vid_tpl(c)`, `job_from_tpl(c)`; `CommandRouter.run_video_apply_template(ctx, job_id: str, template_key: str) -> None`. Semantics: picking a template OVERWRITES the draft's style AND prompt with the template's (an explicit pick is intentional, matching the web grid); picking `custom` is a no-op.

- [ ] **Step 1: Write the failing builder tests**

Append to `webhook-handler/tests/test_video_panel.py`:

```python
from handlers.video_panel import (  # noqa: F811 - extend the existing import if present
    TPL_PREFIX, build_template_select, is_vid_tpl, job_from_tpl,
)

_TPLS = [
    {"key": "walkthrough", "emoji": "X", "name": "Website Walkthrough",
     "desc": "tour", "style": "clean_product_demo", "prompt": "p1"},
    {"key": "social", "emoji": "Y", "name": "Snappy Social",
     "desc": "feeds", "style": "snappy_social", "prompt": "p2"},
]


def test_template_select_has_custom_plus_templates():
    sel = build_template_select("j1", _TPLS)
    assert sel["custom_id"] == f"{TPL_PREFIX}j1"
    values = [o["value"] for o in sel["options"]]
    assert values == ["custom", "walkthrough", "social"]
    assert sel["options"][0]["default"] is True  # no current -> Custom default


def test_template_select_current_marks_default():
    sel = build_template_select("j1", _TPLS, current="social")
    by_val = {o["value"]: o for o in sel["options"]}
    assert by_val["social"]["default"] is True
    assert by_val["custom"]["default"] is False


def test_template_select_skips_keyless_entries():
    sel = build_template_select("j1", [{"name": "broken"}] + _TPLS)
    assert [o["value"] for o in sel["options"]] == ["custom", "walkthrough", "social"]


def test_tpl_predicates_round_trip():
    cid = f"{TPL_PREFIX}job-9"
    assert is_vid_tpl(cid)
    assert job_from_tpl(cid) == "job-9"
    assert not is_vid_tpl("aiuivid:style:job-9")


def test_options_components_include_template_row_when_given():
    from handlers.video_panel import build_options_components
    rows = build_options_components("j1", [{"id": "amy", "label": "Amy"}],
                                    templates=_TPLS)
    assert len(rows) == 5  # template + style + voice + mode + buttons
    first_ids = [c["custom_id"] for c in rows[0]["components"]]
    assert first_ids == [f"{TPL_PREFIX}j1"]


def test_options_components_no_template_row_when_absent():
    from handlers.video_panel import build_options_components
    rows = build_options_components("j1", [{"id": "amy", "label": "Amy"}])
    assert len(rows) == 4
```

- [ ] **Step 2: Run to verify failure**

Run: `cd "/c/All/Work - Code/ai_ui/webhook-handler" && python -m pytest tests/test_video_panel.py -q`
Expected: ImportError on `TPL_PREFIX`

- [ ] **Step 3: Implement the builders in `video_panel.py`**

Add to the custom_id namespace block (after line 28 `OPTIONS_PREFIX ...`):

```python
TPL_PREFIX = "aiuivid:tpl:"
```

Add after `build_mode_select` (line 168):

```python
def build_template_select(job_id: str, templates: list[dict], current: str = "") -> dict:
    """Template picker: Custom (default when nothing picked) + the registry
    entries. Values are template keys; 'custom' means no template."""
    options = [{"label": "Custom (no template)", "value": "custom",
                "description": "Write your own direction"[:100],
                "default": not current}]
    for t in templates[:24]:
        key = t.get("key")
        if not key:
            continue
        options.append({
            "label": f"{t.get('emoji', '')} {t.get('name', key)}".strip()[:100],
            "value": key[:100],
            "description": (t.get("desc") or "")[:100],
            "default": key == current,
        })
    return {"type": SELECT_MENU, "custom_id": f"{TPL_PREFIX}{job_id}",
            "placeholder": "Pick a template…", "min_values": 1, "max_values": 1,
            "options": options}
```

Replace `build_options_components` (lines 200-211) with:

```python
def build_options_components(job_id: str, voices: list[dict],
                             current_style: str = "clean_product_demo",
                             current_voice: str = "amy",
                             current_mode: str = "remotion",
                             templates: list[dict] | None = None,
                             current_template: str = "") -> list[dict]:
    rows: list[dict] = []
    if templates:
        rows.append({"type": ACTION_ROW, "components": [
            build_template_select(job_id, templates, current_template)]})
    rows += [
        {"type": ACTION_ROW, "components": [build_style_select(job_id, current_style)]},
        {"type": ACTION_ROW, "components": [build_voice_select(job_id, voices, current_voice)]},
        {"type": ACTION_ROW, "components": [build_mode_select(job_id, current_mode)]},
        {"type": ACTION_ROW, "components": [
            _button("Generate video", f"{GENERATE_PREFIX}{job_id}", STYLE_SUCCESS),
            _button("Back", f"{OPTIONS_BACK_PREFIX}{job_id}", STYLE_SECONDARY)]},
    ]
    return rows
```

(5 action rows total with templates - exactly Discord's per-message max.)

Add to the predicates block (beside `is_vid_style` etc., lines 237-278):

```python
def is_vid_tpl(c: str) -> bool: return c.startswith(TPL_PREFIX)
def job_from_tpl(c: str) -> str: return _suffix_after(c, TPL_PREFIX)
```

- [ ] **Step 4: Run the builder tests**

Run: `cd "/c/All/Work - Code/ai_ui/webhook-handler" && python -m pytest tests/test_video_panel.py -q`
Expected: all pass (52 existing + 6 new)

- [ ] **Step 5: Write the failing runner test**

Append to `webhook-handler/tests/test_video_runners.py` (uses the file's existing `_router`/`_ctx` helpers):

```python
@pytest.mark.asyncio
async def test_run_video_apply_template_sets_style_and_prompt():
    tc = MagicMock()
    tc.set_video_draft_fields = AsyncMock(return_value={"status": "ok"})
    r = _router(tc)
    ctx = _ctx()
    await r.run_video_apply_template(ctx, "job1", "walkthrough")
    tc.set_video_draft_fields.assert_awaited_once()
    kwargs = tc.set_video_draft_fields.await_args.kwargs
    assert kwargs["style"] == "clean_product_demo"
    assert "guided tour" in kwargs["prompt"]


@pytest.mark.asyncio
async def test_run_video_apply_template_custom_is_noop():
    tc = MagicMock()
    tc.set_video_draft_fields = AsyncMock()
    r = _router(tc)
    await r.run_video_apply_template(_ctx(), "job1", "custom")
    tc.set_video_draft_fields.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_video_apply_template_unknown_key_is_noop():
    tc = MagicMock()
    tc.set_video_draft_fields = AsyncMock()
    r = _router(tc)
    await r.run_video_apply_template(_ctx(), "job1", "nope")
    tc.set_video_draft_fields.assert_not_awaited()
```

Run: `cd "/c/All/Work - Code/ai_ui/webhook-handler" && python -m pytest tests/test_video_runners.py -q`
Expected: 3 new FAIL (`AttributeError: run_video_apply_template`)

- [ ] **Step 6: Implement the runner in `commands.py`**

Add directly after `run_video_set_field` (ends ~line 2952):

```python
    async def run_video_apply_template(self, ctx: CommandContext, job_id: str,
                                       template_key: str) -> None:
        """Template pick from the options card: write the template's style and
        script onto the draft. An explicit pick intentionally overwrites the
        prompt (same behavior as picking a template card on the web)."""
        if template_key == "custom":
            return
        from handlers import video_templates as vtpl
        tpl = vtpl.get_template(template_key)
        if tpl is None:
            logger.warning("unknown video template pick: %s", template_key)
            return
        email = await self._resolve_email_for_ctx(ctx)
        if not email:
            return
        try:
            await self._tasks_client.set_video_draft_fields(
                email, job_id, style=tpl["style"], prompt=tpl["prompt"])
        except TasksAPIError as e:
            logger.warning("video apply template failed job=%s: %s", job_id, e)
```

- [ ] **Step 7: Wire the Discord dispatch + options card**

In `discord_commands.py`, inside the video select branch (the `if (vid.is_vid_style(...) or vid.is_vid_voice(...) or vid.is_vid_mode(...))` block at ~427), add a NEW sibling branch ABOVE it:

```python
        if vid.is_vid_tpl(custom_id):
            values = data.get("values") or []
            if not values:
                return {"type": DEFERRED_UPDATE_MESSAGE}
            job_id = vid.job_from_tpl(custom_id)
            self._spawn(self._run_video_apply_template(payload, job_id, values[0]))
            return {"type": DEFERRED_UPDATE_MESSAGE}
```

Add beside `_run_video_set` (~line 1046):

```python
    async def _run_video_apply_template(self, payload: dict[str, Any],
                                        job_id: str, template_key: str) -> None:
        """Background apply for a template pick (select ACK'd with no edit)."""
        member = payload.get("member", {})
        user = member.get("user", payload.get("user", {}))
        ctx = CommandContext(
            user_id=user.get("id", ""), user_name=user.get("username", "unknown"),
            channel_id=payload.get("channel_id", ""), raw_text="video template",
            subcommand="video", arguments="", platform="discord",
            respond=lambda m: asyncio.sleep(0))
        await self.router.run_video_apply_template(ctx, job_id, template_key)
```

In `_open_video_options` (1074-1105): import the cache at the top of the file (`from handlers import video_templates as vtpl` beside the other handler imports), then pass templates into the builder call and keep the cache warm:

```python
        if not vtpl.cache_is_fresh():
            self._spawn(vtpl.refresh_templates(self.router._tasks_client))
        components = vid.build_options_components(
            job_id, voices,
            current_style=draft.get("style", "clean_product_demo"),
            current_voice=draft.get("voice", "amy"),
            current_mode=draft.get("render_mode", "remotion"),
            templates=vtpl.cached_templates())
```

(Adapt the exact variable names to the existing `_open_video_options` body - only the two new keyword args and the freshness spawn are new.)

- [ ] **Step 8: Run the tests**

Run: `cd "/c/All/Work - Code/ai_ui/webhook-handler" && python -m pytest tests/test_video_runners.py tests/test_video_panel.py tests/test_video_routing.py -q`
Expected: all pass, no regressions

- [ ] **Step 9: Commit**

```bash
cd "/c/All/Work - Code/ai_ui" && git add webhook-handler/handlers/video_panel.py webhook-handler/handlers/discord_commands.py webhook-handler/handlers/commands.py webhook-handler/tests/test_video_panel.py webhook-handler/tests/test_video_runners.py && git commit -m "feat(video): Discord video panel template picker"
```

---

### Task 5: Slack video modal - template select with views.update prefill

**Files:**
- Modify: `webhook-handler/handlers/slack_video_panel.py` (`build_video_modal` at 168-227; `parse_video_modal` at 230-261)
- Modify: `webhook-handler/clients/slack.py` (add `update_modal` beside `open_modal`)
- Modify: `webhook-handler/handlers/slack_interactions.py` (modal open at 411-418; new block_actions branch; `_run_slack_video` at 1241-1281)
- Test: `webhook-handler/tests/test_slack_video_panel.py` (extend), `webhook-handler/tests/test_slack_video_interactions.py` (extend)

**Interfaces:**
- Consumes: `handlers.video_templates` cache (Task 3).
- Produces: `build_video_modal(channel_id, templates=None, initial_prompt="", initial_template="")`; block_id/action_id `"vid_template"` with `dispatch_action: True`; `parse_video_modal` result gains `"template"` key (`""` = none). `SlackClient.update_modal(view_id: str, view: dict) -> bool`. Submit semantics: template picked + prompt empty -> template prompt; template picked -> template style wins.

- [ ] **Step 1: Write the failing panel tests**

Append to `webhook-handler/tests/test_slack_video_panel.py` (reuse its `_make_view` fixture, extending it so state can include a `vid_template` selected_option; follow the file's existing pattern):

```python
_TPLS = [
    {"key": "walkthrough", "emoji": "X", "name": "Website Walkthrough",
     "desc": "tour", "style": "clean_product_demo", "prompt": "tpl prompt one"},
    {"key": "social", "emoji": "Y", "name": "Snappy Social",
     "desc": "feeds", "style": "snappy_social", "prompt": "tpl prompt two"},
]


def _template_block(modal):
    return next(b for b in modal["blocks"] if b.get("block_id") == "vid_template")


def test_video_modal_has_optional_template_select_with_dispatch():
    modal = build_video_modal("C42", templates=_TPLS)
    block = _template_block(modal)
    assert block["optional"] is True
    assert block["dispatch_action"] is True
    el = block["element"]
    assert el["type"] == "static_select"
    assert el["action_id"] == "vid_template"
    assert [o["value"] for o in el["options"]] == ["walkthrough", "social"]


def test_video_modal_without_templates_has_no_template_block():
    modal = build_video_modal("C42")
    assert not any(b.get("block_id") == "vid_template" for b in modal["blocks"])


def test_video_modal_initial_prompt_and_template():
    modal = build_video_modal("C42", templates=_TPLS,
                              initial_prompt="tpl prompt two",
                              initial_template="social")
    prompt_block = next(b for b in modal["blocks"] if b.get("block_id") == "prompt")
    assert prompt_block["element"]["initial_value"] == "tpl prompt two"
    el = _template_block(modal)["element"]
    assert el["initial_option"]["value"] == "social"


def test_parse_video_modal_reads_template():
    view = _make_view()  # extend the fixture: add vid_template selected_option "social"
    view["state"]["values"]["vid_template"] = {
        "vid_template": {"type": "static_select",
                         "selected_option": {"value": "social"}}}
    assert parse_video_modal(view)["template"] == "social"


def test_parse_video_modal_template_defaults_empty():
    view = _make_view()
    assert parse_video_modal(view)["template"] == ""
```

Run: `cd "/c/All/Work - Code/ai_ui/webhook-handler" && python -m pytest tests/test_slack_video_panel.py -q`
Expected: new tests FAIL (TypeError: unexpected keyword argument 'templates')

- [ ] **Step 2: Implement the modal changes in `slack_video_panel.py`**

Change the `build_video_modal` signature and insert the template block right after the `url` block (and add `initial_value` support to the prompt input):

```python
def build_video_modal(channel_id: str, templates: list[dict] | None = None,
                      initial_prompt: str = "", initial_template: str = "") -> dict:
```

Template block (insert between the url and prompt blocks; only when `templates`):

```python
    template_block = None
    if templates:
        options = [_opt(f"{t.get('emoji', '')} {t.get('name', t['key'])}".strip()[:75],
                        t["key"]) for t in templates if t.get("key")]
        element = {"type": "static_select", "action_id": "vid_template",
                   "placeholder": {"type": "plain_text", "text": "Custom (no template)"},
                   "options": options}
        if initial_template:
            match = [o for o in options if o["value"] == initial_template]
            if match:
                element["initial_option"] = match[0]
        template_block = {
            "type": "input", "block_id": "vid_template", "optional": True,
            "dispatch_action": True,
            "label": {"type": "plain_text", "text": "Template"},
            "element": element,
        }
```

Then build the blocks list conditionally including `template_block`, and give the prompt input `initial_value` when `initial_prompt` is non-empty. If `_plain_input` does not support an initial value, add an optional `initial_value: str = ""` parameter to it that sets `element["initial_value"]` only when non-empty (Slack rejects empty initial_value).

In `parse_video_modal`, add before the return:

```python
    template = _sel(state, "vid_template", "vid_template", "")
```

and include `"template": template` in the returned dict.

- [ ] **Step 3: Add `SlackClient.update_modal`**

In `webhook-handler/clients/slack.py`, find `open_modal` (it POSTs to Slack's `views.open`). Add `update_modal` DIRECTLY below it using the identical transport, auth headers, and error handling - changing only the API method and payload:

```python
    async def update_modal(self, view_id: str, view: dict) -> bool:
        """views.update: replace an open modal's contents (template prefill).
        Same transport as open_modal; returns True when Slack acks ok."""
        if not view_id:
            return False
        # Mirror open_modal exactly, but POST to views.update with
        # {"view_id": view_id, "view": view} and return the ok bool.
```

The implementer MUST copy open_modal's actual request lines (client, base URL constant, headers, response parsing) so behavior matches; the docstring and guard above are fixed.

- [ ] **Step 4: Wire open + prefill + submit in `slack_interactions.py`**

At the top: `from handlers import video_templates as vtpl` (beside the `svp` import at line 75).

(a) Modal OPEN (lines 411-418): pass templates and keep the cache warm; the open itself stays synchronous:

```python
        if svp.is_vid_new(action_id):
            if not vtpl.cache_is_fresh():
                task = asyncio.create_task(
                    vtpl.refresh_templates(self.router._tasks_client))
                self.router._background_tasks.add(task)
                task.add_done_callback(self.router._background_tasks.discard)
            await self.slack.open_modal(
                trigger_id, svp.build_video_modal(
                    channel_id, templates=vtpl.cached_templates()))
            return {}
```

(b) PREFILL - new block_actions branch immediately after the `is_vid_new` branch:

```python
        if action_id == "vid_template" and payload.get("view"):
            view = payload["view"] or {}
            values = (view.get("state", {}) or {}).get("values", {}) or {}
            sel = (values.get("vid_template", {}) or {}).get("vid_template", {}) or {}
            key = (sel.get("selected_option") or {}).get("value", "")
            tpl = vtpl.get_template(key)
            current_prompt = svp._txt(values, "prompt", "prompt")
            # Never clobber text the user typed: only prefill when the prompt
            # is empty or still equals a known template script.
            if tpl and (not current_prompt or current_prompt in vtpl.template_prompts()):
                new_view = svp.build_video_modal(
                    view.get("private_metadata") or "",
                    templates=vtpl.cached_templates(),
                    initial_prompt=tpl["prompt"], initial_template=key)
                await self.slack.update_modal(view.get("id", ""), new_view)
            return {}
```

(c) SUBMIT fallback - in `_run_slack_video` (1241-1281), before the `create_video_draft` call:

```python
        tpl = vtpl.get_template((fields.get("template") or "").strip())
        if tpl:
            if not (fields.get("prompt") or "").strip():
                fields["prompt"] = tpl["prompt"]
            fields["style"] = tpl["style"]
```

- [ ] **Step 5: Write the interaction tests**

Append to `webhook-handler/tests/test_slack_video_interactions.py` (reuse its `_handler`/`_video_router`/`_block_actions_payload` helpers; the payload helper needs an optional `view` argument for these - extend it following the file's style):

```python
@pytest.mark.asyncio
async def test_template_select_prefills_when_prompt_empty():
    router = _video_router()
    handler, slack = _handler(router)
    slack.update_modal = AsyncMock(return_value=True)
    payload = _block_actions_payload("vid_template")
    payload["view"] = {
        "id": "V1", "private_metadata": "C-vid",
        "state": {"values": {
            "vid_template": {"vid_template": {
                "type": "static_select",
                "selected_option": {"value": "walkthrough"}}},
            "prompt": {"prompt": {"type": "plain_text_input", "value": ""}},
        }},
    }
    resp = await handler.handle_interaction(payload)
    assert resp == {}
    slack.update_modal.assert_awaited_once()
    view_id, new_view = slack.update_modal.call_args.args
    assert view_id == "V1"
    prompt_block = next(b for b in new_view["blocks"] if b.get("block_id") == "prompt")
    assert "guided tour" in prompt_block["element"]["initial_value"]


@pytest.mark.asyncio
async def test_template_select_never_clobbers_user_text():
    router = _video_router()
    handler, slack = _handler(router)
    slack.update_modal = AsyncMock(return_value=True)
    payload = _block_actions_payload("vid_template")
    payload["view"] = {
        "id": "V1", "private_metadata": "C-vid",
        "state": {"values": {
            "vid_template": {"vid_template": {
                "type": "static_select",
                "selected_option": {"value": "walkthrough"}}},
            "prompt": {"prompt": {"type": "plain_text_input",
                                   "value": "my own words"}},
        }},
    }
    await handler.handle_interaction(payload)
    slack.update_modal.assert_not_awaited()


@pytest.mark.asyncio
async def test_submit_with_template_and_empty_prompt_uses_template_script():
    router = _video_router()
    handler, slack = _handler(router)
    fields = {"url": "https://x.com", "prompt": "", "title": None,
              "style": "clean_product_demo", "voice": "amy",
              "mode": "remotion", "template": "social", "channel_id": "C1"}
    await handler._run_slack_video("U1", fields)
    call = router._tasks_client.create_video_draft.await_args
    assert "punchy social clip" in call.args[2]      # prompt arg
    assert call.args[3] == "snappy_social"            # style arg
```

Run: `cd "/c/All/Work - Code/ai_ui/webhook-handler" && python -m pytest tests/test_slack_video_panel.py tests/test_slack_video_interactions.py -q`
Expected: all pass (existing + new)

- [ ] **Step 6: Commit**

```bash
cd "/c/All/Work - Code/ai_ui" && git add webhook-handler/handlers/slack_video_panel.py webhook-handler/handlers/slack_interactions.py webhook-handler/clients/slack.py webhook-handler/tests/test_slack_video_panel.py webhook-handler/tests/test_slack_video_interactions.py && git commit -m "feat(video): Slack video modal template picker with prefill"
```

---

### Task 6: Tasks service - schedule `kind` + `video_config` (migration, model, API)

**Files:**
- Create: `mcp-servers/tasks/migrations/030_schedule_kind_video.sql`
- Modify: `mcp-servers/tasks/models.py` (Schedule at 113-144; the sqlalchemy dialect import at the top)
- Modify: `mcp-servers/tasks/routes_schedules.py` (`CreateScheduleIn` at 53-63; `create_schedule` at 83-124; the list route at 66-80)
- Test: `mcp-servers/tasks/tests/test_schedule_kind.py`

**Interfaces:**
- Produces: `Schedule.kind` (Text, NOT NULL, server_default `'agent'`), `Schedule.video_config` (JSONB, nullable). API: `CreateScheduleIn` accepts `kind: str = "agent"` and `video_config: dict | None = None`; create validates `kind in ("agent", "video")` and, for video, `video_config.url` is http(s). List rows include `"kind"`.
- Consumed by: Task 7 (scheduler branch), Tasks 9-10 (creation UIs).

- [ ] **Step 1: Write the failing tests**

Create `mcp-servers/tasks/tests/test_schedule_kind.py`:

```python
import pytest
from pydantic import ValidationError

from models import Schedule
from routes_schedules import CreateScheduleIn, _validate_kind


def test_schedule_model_has_kind_and_video_config_columns():
    cols = Schedule.__table__.columns
    assert "kind" in cols
    assert cols["kind"].server_default.arg == "agent"
    assert cols["kind"].nullable is False
    assert "video_config" in cols
    assert cols["video_config"].nullable is True


def test_create_in_defaults_to_agent():
    body = CreateScheduleIn(name="n", cron_expr="* * * * *", prompt="p")
    assert body.kind == "agent"
    assert body.video_config is None


def test_validate_kind_rejects_unknown():
    with pytest.raises(Exception):
        _validate_kind("banana", None)


def test_validate_kind_video_requires_http_url():
    with pytest.raises(Exception):
        _validate_kind("video", {})
    with pytest.raises(Exception):
        _validate_kind("video", {"url": "ftp://x"})
    _validate_kind("video", {"url": "https://example.com"})  # no raise


def test_validate_kind_agent_ignores_config():
    _validate_kind("agent", None)  # no raise
```

Run: `cd "/c/All/Work - Code/ai_ui/mcp-servers/tasks" && python -m pytest tests/test_schedule_kind.py -q`
Expected: FAIL (`ImportError: cannot import name '_validate_kind'` / missing columns)

- [ ] **Step 2: Write the migration**

Create `mcp-servers/tasks/migrations/030_schedule_kind_video.sql` (migrations re-run EVERY boot - must be idempotent, matching 028's pattern):

```sql
-- 030: dedicated schedule kinds. 'agent' = existing prompt/executor runs
-- (all current rows); 'video' = direct video render of video_config.
-- Idempotent: db.py re-runs every migration each startup.
ALTER TABLE tasks.schedules
  ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'agent',
  ADD COLUMN IF NOT EXISTS video_config JSONB;
ALTER TABLE tasks.schedules DROP CONSTRAINT IF EXISTS schedules_kind_check;
ALTER TABLE tasks.schedules
  ADD CONSTRAINT schedules_kind_check CHECK (kind IN ('agent', 'video'));
```

- [ ] **Step 3: Extend the model**

In `mcp-servers/tasks/models.py`, ensure the postgres dialect import includes JSONB (extend the existing line, e.g. `from sqlalchemy.dialects.postgresql import JSONB, UUID` - JSONB may already be imported for other models; check first). Add to `Schedule` after `delivery_platform` (line 142):

```python
    # 'agent' (default) = prompt via the remote executor; 'video' = direct
    # video render of video_config (no LLM). See scheduler._run_video_schedule.
    kind = Column(Text, nullable=False, server_default="agent", default="agent")
    # For kind='video': {url, template, prompt, voice, title}. NULL otherwise.
    video_config = Column(JSONB, nullable=True)
```

- [ ] **Step 4: Extend the API**

In `routes_schedules.py`, add to `CreateScheduleIn` (lines 53-63):

```python
    kind: str = "agent"
    video_config: dict | None = None
```

Add a module-level helper above `create_schedule`:

```python
def _validate_kind(kind: str, video_config: dict | None) -> None:
    """400 on an unknown kind or a video schedule without a usable URL."""
    if kind not in ("agent", "video"):
        raise HTTPException(status_code=400, detail="kind must be 'agent' or 'video'")
    if kind == "video":
        url = ((video_config or {}).get("url") or "").strip()
        if not url.lower().startswith(("http://", "https://")):
            raise HTTPException(status_code=400,
                                detail="video_config.url must be an http(s) URL")
```

In `create_schedule` (after the croniter validation at ~line 101) add:

```python
    _validate_kind(body.kind, body.video_config)
```

and add to the `Schedule(...)` constructor call:

```python
            kind=body.kind,
            video_config=body.video_config,
```

In the list route (66-80), add `"kind": s.kind,` to the per-row dict it returns (find the dict comprehension/loop building each row and add the key beside `"name"`).

- [ ] **Step 5: Run the tests**

Run: `cd "/c/All/Work - Code/ai_ui/mcp-servers/tasks" && python -m pytest tests/test_schedule_kind.py -q`
Expected: 5 passed

Also regression: `python -m pytest tests/ -q --ignore=tests/test_scheduler.py -k "schedule"`
Expected: no new failures (DB-gated tests skip)

- [ ] **Step 6: Commit**

```bash
cd "/c/All/Work - Code/ai_ui" && git add mcp-servers/tasks/migrations/030_schedule_kind_video.sql mcp-servers/tasks/models.py mcp-servers/tasks/routes_schedules.py mcp-servers/tasks/tests/test_schedule_kind.py && git commit -m "feat(cron): schedule kind + video_config columns and API"
```

---

### Task 7: Tasks service - scheduler runs `kind='video'` directly

**Files:**
- Modify: `mcp-servers/tasks/scheduler.py` (branch in `_run_scheduled_task` at 204; extras through `_finalize_run` at 288 and `_deliver_result` at 252)
- Test: `mcp-servers/tasks/tests/test_scheduler_video.py`

**Interfaces:**
- Consumes: `video_templates.get_template` (Task 1); `Schedule.kind` / `video_config` (Task 6); routes_video's `create_draft(DraftRequest, user)`, `capture_from_url(job_id, CaptureUrlRequest, user)`, `queue_job(job_id, user)` called as plain async functions with a constructed `auth.CurrentUser(email=sched.user_email)` - this reuses every existing guard (kill switches, SSRF, daily limit, disk).
- Produces: `_run_scheduled_task` returns `(status, result, extras)` for BOTH kinds (agent path returns `extras={}`); `_deliver_result(..., extras: dict | None = None)` merges extras into the delivery JSON. Video extras: `{"video_job_id": <id>, "video_user_email": <email>}` (consumed by Task 8). Seam functions for tests: `_start_video_job(user, cfg, title, prompt, style) -> str` and `_check_video_job(job_id) -> tuple[str, str, str]` (status, error, share_link), plus module constants `VIDEO_SCHEDULE_WAIT_SECONDS` (env `VIDEO_SCHEDULE_WAIT_SECONDS`, default 900) and `VIDEO_SCHEDULE_POLL_SECONDS = 10`.

- [ ] **Step 1: Write the failing tests**

Create `mcp-servers/tasks/tests/test_scheduler_video.py` (pure: both seams monkeypatched, no DB):

```python
import pytest

import scheduler


class _Sched:
    def __init__(self, cfg):
        self.id = "sid-1"
        self.user_email = "u@x.com"
        self.name = "Weekly site video"
        self.kind = "video"
        self.video_config = cfg


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(scheduler, "VIDEO_SCHEDULE_POLL_SECONDS", 0)
    monkeypatch.setattr(scheduler, "VIDEO_SCHEDULE_WAIT_SECONDS", 3)


@pytest.mark.asyncio
async def test_video_schedule_success_returns_link_and_extras(monkeypatch):
    async def start(user, cfg, title, prompt, style):
        assert user.email == "u@x.com"
        assert cfg["url"] == "https://site.com"
        return "job-1"
    checks = iter([("rendering", "", ""), ("done", "", "https://dl/x.mp4?cap=t")])
    async def check(job_id):
        return next(checks)
    monkeypatch.setattr(scheduler, "_start_video_job", start)
    monkeypatch.setattr(scheduler, "_check_video_job", check)
    status, result, extras = await scheduler._run_video_schedule(
        _Sched({"url": "https://site.com"}))
    assert status == "completed"
    assert "https://dl/x.mp4?cap=t" in result
    assert extras == {"video_job_id": "job-1", "video_user_email": "u@x.com"}


@pytest.mark.asyncio
async def test_video_schedule_failure_is_clean(monkeypatch):
    async def start(user, cfg, title, prompt, style):
        return "job-1"
    async def check(job_id):
        return ("failed", "Could not capture that page", "")
    monkeypatch.setattr(scheduler, "_start_video_job", start)
    monkeypatch.setattr(scheduler, "_check_video_job", check)
    status, result, extras = await scheduler._run_video_schedule(
        _Sched({"url": "https://site.com"}))
    assert status == "failed"
    assert "Could not capture that page" in result
    assert extras == {}


@pytest.mark.asyncio
async def test_video_schedule_timeout_points_to_studio(monkeypatch):
    async def start(user, cfg, title, prompt, style):
        return "job-1"
    async def check(job_id):
        return ("rendering", "", "")
    monkeypatch.setattr(scheduler, "_start_video_job", start)
    monkeypatch.setattr(scheduler, "_check_video_job", check)
    status, result, extras = await scheduler._run_video_schedule(
        _Sched({"url": "https://site.com"}))
    assert status == "timeout"
    assert "still rendering" in result


@pytest.mark.asyncio
async def test_video_schedule_start_httperror_is_clean(monkeypatch):
    from fastapi import HTTPException
    async def start(user, cfg, title, prompt, style):
        raise HTTPException(429, "Daily video limit reached")
    monkeypatch.setattr(scheduler, "_start_video_job", start)
    status, result, extras = await scheduler._run_video_schedule(
        _Sched({"url": "https://site.com"}))
    assert status == "failed"
    assert "Daily video limit reached" in result


@pytest.mark.asyncio
async def test_video_schedule_missing_url_fails_fast(monkeypatch):
    called = False
    async def start(user, cfg, title, prompt, style):
        nonlocal called; called = True
    monkeypatch.setattr(scheduler, "_start_video_job", start)
    status, result, extras = await scheduler._run_video_schedule(_Sched({}))
    assert status == "failed" and not called


@pytest.mark.asyncio
async def test_template_key_fills_prompt_and_style(monkeypatch):
    seen = {}
    async def start(user, cfg, title, prompt, style):
        seen["prompt"], seen["style"] = prompt, style
        return "job-1"
    async def check(job_id):
        return ("done", "", "")
    monkeypatch.setattr(scheduler, "_start_video_job", start)
    monkeypatch.setattr(scheduler, "_check_video_job", check)
    await scheduler._run_video_schedule(
        _Sched({"url": "https://site.com", "template": "cinematic"}))
    assert seen["style"] == "cinematic"
    assert "cinematic showcase" in seen["prompt"].lower()


@pytest.mark.asyncio
async def test_no_template_no_prompt_stays_empty_for_walk_default(monkeypatch):
    seen = {}
    async def start(user, cfg, title, prompt, style):
        seen["prompt"] = prompt
        return "job-1"
    async def check(job_id):
        return ("done", "", "")
    monkeypatch.setattr(scheduler, "_start_video_job", start)
    monkeypatch.setattr(scheduler, "_check_video_job", check)
    await scheduler._run_video_schedule(_Sched({"url": "https://site.com"}))
    assert seen["prompt"] == ""
```

Run: `cd "/c/All/Work - Code/ai_ui/mcp-servers/tasks" && python -m pytest tests/test_scheduler_video.py -q`
Expected: FAIL (`AttributeError: _run_video_schedule`). NOTE: this NEW test file imports `scheduler` fine; the pre-existing broken file is `tests/test_scheduler.py` (tzdata) and stays ignored.

- [ ] **Step 2: Implement in `scheduler.py`**

Add after the module constants (near `_RUN_SEMAPHORE`):

```python
VIDEO_SCHEDULE_WAIT_SECONDS = int(os.environ.get("VIDEO_SCHEDULE_WAIT_SECONDS", "900"))
VIDEO_SCHEDULE_POLL_SECONDS = 10


async def _start_video_job(user, cfg: dict, title: str, prompt: str, style: str) -> str:
    """Create + capture + queue a video job through the real route functions,
    reusing every guard (kill switches, SSRF, daily limit, disk). Returns the
    job id. Raises fastapi.HTTPException on any guard failure."""
    from routes_video import (
        CaptureUrlRequest, DraftRequest, capture_from_url, create_draft, queue_job,
    )
    draft = await create_draft(DraftRequest(title=title, prompt=prompt, style=style), user)
    job_id = str(draft["id"])
    await capture_from_url(job_id, CaptureUrlRequest(url=cfg["url"].strip()), user)
    await queue_job(job_id, user)
    return job_id


async def _check_video_job(job_id: str) -> tuple[str, str, str]:
    """One poll: (status, error, share_link). share_link only when done."""
    import uuid as _u
    from video_models import VideoJob
    async with session() as s:
        job = await s.get(VideoJob, _u.UUID(job_id))
    if job is None:
        return "missing", "the job disappeared", ""
    link = ""
    if job.status == "done":
        base = os.environ.get("VIDEO_PUBLIC_BASE", "").rstrip("/")
        if base:
            try:
                from video_capability import mint_video_capability
                tok = mint_video_capability(job.user_email, job.slug, str(job.id))
                link = f"{base}/api/video-jobs/{job.id}/download?cap={tok}"
            except RuntimeError:
                link = ""
    return job.status, (job.error or ""), link


async def _run_video_schedule(sched: Schedule) -> tuple[str, str, dict]:
    """kind='video': render the configured walkthrough directly (no LLM).
    Returns (status, result_message, delivery_extras)."""
    from fastapi import HTTPException
    from auth import CurrentUser
    from video_templates import get_template

    cfg = dict(getattr(sched, "video_config", None) or {})
    url = (cfg.get("url") or "").strip()
    if not url:
        return "failed", "This video schedule has no website URL configured.", {}
    tpl = get_template((cfg.get("template") or "").strip())
    prompt = (cfg.get("prompt") or "").strip()
    if not prompt and tpl:
        prompt = tpl["prompt"]
    style = (tpl or {}).get("style") or "clean_product_demo"
    title = ((cfg.get("title") or sched.name) or "Scheduled video")[:200]
    user = CurrentUser(email=sched.user_email, is_admin=False)
    try:
        job_id = await _start_video_job(user, cfg, title, prompt, style)
    except HTTPException as exc:
        return "failed", f"Could not start the video: {exc.detail}", {}
    except Exception as exc:  # noqa: BLE001
        logger.exception("video schedule %s start failed", sched.id)
        return "failed", f"Could not start the video: {scrub(str(exc))[:300]}", {}

    polls = max(1, VIDEO_SCHEDULE_WAIT_SECONDS // max(1, VIDEO_SCHEDULE_POLL_SECONDS or 1))
    for _ in range(polls):
        await asyncio.sleep(VIDEO_SCHEDULE_POLL_SECONDS)
        try:
            status, error, link = await _check_video_job(job_id)
        except Exception:  # noqa: BLE001
            logger.exception("video schedule %s poll failed", sched.id)
            continue
        if status == "done":
            extras = {"video_job_id": job_id, "video_user_email": sched.user_email}
            if link:
                return "completed", f"\U0001f3ac {title} is ready: {link}", extras
            return "completed", (f"\U0001f3ac {title} is ready. "
                                 "Open the web Video Studio to watch it."), extras
        if status in ("failed", "missing"):
            err = (error or "").strip()
            return "failed", f"Video render failed.{(' ' + err) if err else ''}", {}
    return "timeout", (f"\U0001f3ac {title} is still rendering. "
                       "Check the web Video Studio shortly."), {}
```

NOTE: `VIDEO_SCHEDULE_POLL_SECONDS = 10` but the loop math uses `max(1, ...)` guards so tests can set it to 0 (sleep(0) yields).

- [ ] **Step 3: Branch + thread the extras**

`_run_scheduled_task` (line 204): add the branch as the FIRST thing inside the semaphore, and make the agent path return a 3-tuple:

```python
    async with _RUN_SEMAPHORE:
        if getattr(sched, "kind", "agent") == "video":
            return await _run_video_schedule(sched)
        item = await _create_task_from_schedule(sched)
        ...
        # existing early-exception return becomes:  return "failed", "", {}
        ...
        return status, result, {}
```

`_finalize_run` (line 288): unpack and pass through:

```python
        status, result, extras = await _run_scheduled_task(sched)
        ...
            await _deliver_result(delivery_channel, platform, sched.name, status,
                                  result, str(sched.id), extras=extras)
```

`_deliver_result` (line 252): add `extras: dict | None = None` to the signature and merge into the JSON payload:

```python
                json={
                    "channel_id": channel_id,
                    "platform": platform,
                    "schedule_name": schedule_name,
                    "status": status,
                    "result": scrub(result or "")[:6000],
                    "schedule_id": schedule_id,
                    **(extras or {}),
                },
```

- [ ] **Step 4: Run the tests**

Run: `cd "/c/All/Work - Code/ai_ui/mcp-servers/tasks" && python -m pytest tests/test_scheduler_video.py tests/test_schedule_kind.py -q`
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
cd "/c/All/Work - Code/ai_ui" && git add mcp-servers/tasks/scheduler.py mcp-servers/tasks/tests/test_scheduler_video.py && git commit -m "feat(cron): scheduler renders kind=video schedules through the video pipeline"
```

---

### Task 8: webhook-handler - schedule-result delivery attaches the MP4 on Discord

**Files:**
- Modify: `webhook-handler/main.py` (`ScheduleResultIn` model + `/internal/schedule-result` at ~770-816)
- Test: `webhook-handler/tests/test_schedule_result_video.py`

**Interfaces:**
- Consumes: extras `video_job_id` / `video_user_email` in the delivery payload (Task 7); `TasksClient.download_video_bytes` (exists); `DiscordClient.post_channel_file(channel_id, files, content=..., components=...)` (exists, `clients/discord.py:143`); `VIDEO_ATTACH_MAX_MB` (exists, `handlers/commands.py:42`).
- Produces: `ScheduleResultIn` gains `video_job_id: str = ""` and `video_user_email: str = ""`. Discord delivery of a completed video schedule attaches the MP4 when `<= VIDEO_ATTACH_MAX_MB`, else posts the text (which already carries the share link). Slack keeps link-only text (no upload path exists). Any attach failure falls through to the existing text post - delivery NEVER gets worse than today.

- [ ] **Step 1: Write the failing tests**

Create `webhook-handler/tests/test_schedule_result_video.py`. Follow the mocking style of the existing `/internal/schedule-result` tests (find them: `grep -rn "schedule-result" webhook-handler/tests/` - reuse that file's client/fixture pattern for auth header and app wiring). The three cases:

```python
# Case 1: discord + video_job_id + small blob -> post_channel_file called with
#   ("<schedule_name>.mp4", blob, "video/mp4"), content == formatted message,
#   and post_channel_message NOT called.
# Case 2: discord + video_job_id + blob > VIDEO_ATTACH_MAX_MB -> falls through
#   to post_channel_message with the formatted text.
# Case 3: download raises -> falls through to post_channel_message (delivered).
```

Write them as real tests (assert on the mocked discord client's calls), mocking `download_video_bytes` on whatever tasks-client object main.py exposes (see Step 2).

Run: `cd "/c/All/Work - Code/ai_ui/webhook-handler" && python -m pytest tests/test_schedule_result_video.py -q`
Expected: FAIL (unknown fields / no attach behavior)

- [ ] **Step 2: Implement**

In `main.py`, find `ScheduleResultIn` (the request model for `/internal/schedule-result`) and add:

```python
    video_job_id: str = ""
    video_user_email: str = ""
```

In the DISCORD branch of `schedule_result` (after `message = _format_schedule_result(...)`, before `post_channel_message`), insert:

```python
    if body.video_job_id and body.video_user_email:
        from handlers.commands import VIDEO_ATTACH_MAX_MB
        tasks_client = getattr(command_router, "_tasks_client", None)
        if tasks_client is not None:
            try:
                blob = await tasks_client.download_video_bytes(
                    body.video_user_email, body.video_job_id)
                if len(blob) <= VIDEO_ATTACH_MAX_MB * 1024 * 1024:
                    ok = await discord_client.post_channel_file(
                        body.channel_id,
                        [(f"{(body.schedule_name or 'video')[:60]}.mp4", blob, "video/mp4")],
                        content=message)
                    if ok:
                        return {"status": "delivered"}
            except Exception as exc:  # noqa: BLE001
                logger.warning("schedule video attach failed job=%s: %s",
                               body.video_job_id, exc)
    # fall through to the plain text post below
```

NOTE: `command_router` above is whatever global name main.py gives the CommandRouter instance (grep `CommandRouter(` in main.py and use that variable). If main.py holds a TasksClient directly, use it instead. The Slack branch is untouched (it runs before the Discord branch and returns early).

- [ ] **Step 3: Run the tests**

Run: `cd "/c/All/Work - Code/ai_ui/webhook-handler" && python -m pytest tests/test_schedule_result_video.py -q`
Expected: 3 passed. Also run the file containing the pre-existing schedule-result tests - no regressions.

- [ ] **Step 4: Commit**

```bash
cd "/c/All/Work - Code/ai_ui" && git add webhook-handler/main.py webhook-handler/tests/test_schedule_result_video.py && git commit -m "feat(cron): schedule-result delivery attaches finished video MP4 on Discord"
```

---

### Task 9: Discord cron - "Schedule a video" flow

**Files:**
- Modify: `webhook-handler/handlers/app_builder_panel.py` (constants at 418-431; `build_schedules_dashboard` at 453-465; new builders after `build_schedule_modal` at 544)
- Modify: `webhook-handler/handlers/discord_commands.py` (component dispatch near `is_sched_new` at 302; modal-submit routing at 1442; `_create_pending_schedule` at 1711-1766)
- Modify: `webhook-handler/handlers/commands.py` (`run_schedule_create` at 2351-2372)
- Modify: `webhook-handler/clients/tasks.py` (`create_schedule` at 86-105)
- Test: `webhook-handler/tests/test_schedule_video_panel.py`

**Interfaces:**
- Consumes: `handlers.video_templates.cached_templates()` (Task 3); tasks API `kind`/`video_config` (Task 6); the existing `_pending_schedules` token flow + `SCHED_CONFIRM_PREFIX`/`SCHED_CANCEL_PREFIX` confirm buttons + `parse_when`.
- Produces: constants `SCHED_NEWVID_ID = "aiuisched:newvid"`, `SCHED_VIDMODAL_ID = "aiuisched:vidmodal"`, `SCHED_VIDTPL_PREFIX = "aiuisched:vidtpl:"`, inputs `SCHED_VID_URL_INPUT = "vid_url"`, `SCHED_VID_WHAT_INPUT = "vid_what"`, `SCHED_VID_WHEN_INPUT = "vid_when"`; builders `build_video_schedule_modal() -> dict` and `build_video_schedule_confirm_components(token, templates) -> list[dict]`. `TasksClient.create_schedule(..., kind: str = "agent", video_config: dict | None = None)`; `run_schedule_create(..., kind="agent", video_config=None)`. Pending entries carry optional `"kind"` and `"video_config"` keys; the template select on the confirm card mutates `pending["video_config"]["template"]` in place (value `"none"` -> `""`).

- [ ] **Step 1: Write the failing builder tests**

Create `webhook-handler/tests/test_schedule_video_panel.py`:

```python
from handlers.app_builder_panel import (
    SCHED_CANCEL_PREFIX, SCHED_CONFIRM_PREFIX, SCHED_NEWVID_ID, SCHED_VIDMODAL_ID,
    SCHED_VIDTPL_PREFIX, SCHED_VID_URL_INPUT, SCHED_VID_WHAT_INPUT,
    SCHED_VID_WHEN_INPUT, build_schedules_dashboard,
    build_video_schedule_confirm_components, build_video_schedule_modal,
)

_TPLS = [{"key": "walkthrough", "emoji": "X", "name": "Website Walkthrough",
          "desc": "tour", "style": "clean_product_demo", "prompt": "p"}]


def _ids(rows):
    return [c.get("custom_id") for row in rows for c in row.get("components", [])]


def test_dashboard_has_video_button():
    panel = build_schedules_dashboard([])
    assert SCHED_NEWVID_ID in _ids(panel["components"])


def test_video_modal_inputs_and_custom_id():
    modal = build_video_schedule_modal()
    assert modal["custom_id"] == SCHED_VIDMODAL_ID
    inputs = [c for row in modal["components"] for c in row["components"]]
    ids = [i["custom_id"] for i in inputs]
    assert ids == [SCHED_VID_URL_INPUT, SCHED_VID_WHAT_INPUT, SCHED_VID_WHEN_INPUT]
    by_id = {i["custom_id"]: i for i in inputs}
    assert by_id[SCHED_VID_URL_INPUT]["required"] is True
    assert by_id[SCHED_VID_WHAT_INPUT]["required"] is False
    assert by_id[SCHED_VID_WHEN_INPUT]["required"] is True


def test_video_confirm_card_has_template_select_and_buttons():
    rows = build_video_schedule_confirm_components("tok1", _TPLS)
    ids = _ids(rows)
    assert f"{SCHED_VIDTPL_PREFIX}tok1" in ids
    assert f"{SCHED_CONFIRM_PREFIX}tok1" in ids
    assert f"{SCHED_CANCEL_PREFIX}tok1" in ids
    select = rows[0]["components"][0]
    values = [o["value"] for o in select["options"]]
    assert values[0] == "none"
    assert "walkthrough" in values
    assert select["options"][0]["default"] is True
```

Run: `cd "/c/All/Work - Code/ai_ui/webhook-handler" && python -m pytest tests/test_schedule_video_panel.py -q`
Expected: ImportError

- [ ] **Step 2: Implement the builders in `app_builder_panel.py`**

Add to the `aiuisched:` constants block (after line 431):

```python
SCHED_NEWVID_ID = "aiuisched:newvid"      # Schedule-a-video button (exact match)
SCHED_VIDMODAL_ID = "aiuisched:vidmodal"  # video schedule modal (exact match)
SCHED_VIDTPL_PREFIX = "aiuisched:vidtpl:" # template select on confirm card :<token>
SCHED_VID_URL_INPUT = "vid_url"
SCHED_VID_WHAT_INPUT = "vid_what"
SCHED_VID_WHEN_INPUT = "vid_when"
```

In `build_schedules_dashboard` (453-465) add the button beside New schedule:

```python
    rows = [{"type": ACTION_ROW, "components": [
        _button("➕ New schedule", SCHED_NEW_ID, STYLE_SUCCESS),
        _button("\U0001f3ac Schedule a video", SCHED_NEWVID_ID, STYLE_PRIMARY)]}]
```

Add after `build_schedule_modal` (line 544):

```python
def build_video_schedule_modal() -> dict:
    """Type-9 MODAL: website URL + optional direction + natural-language when."""
    return {
        "title": "Schedule a video"[:45],
        "custom_id": SCHED_VIDMODAL_ID,
        "components": [
            {"type": ACTION_ROW, "components": [{
                "type": TEXT_INPUT, "custom_id": SCHED_VID_URL_INPUT,
                "label": "Website URL", "style": TEXT_SHORT, "required": True,
                "max_length": 500, "placeholder": "https://yoursite.com",
            }]},
            {"type": ACTION_ROW, "components": [{
                "type": TEXT_INPUT, "custom_id": SCHED_VID_WHAT_INPUT,
                "label": "What should the video show? (optional)",
                "style": TEXT_PARAGRAPH, "required": False, "max_length": 2000,
                "placeholder": "Leave blank for the guided cursor walkthrough.",
            }]},
            {"type": ACTION_ROW, "components": [{
                "type": TEXT_INPUT, "custom_id": SCHED_VID_WHEN_INPUT,
                "label": "How often?", "style": TEXT_SHORT, "required": True,
                "max_length": 60,
                "placeholder": "every Monday 9am  /  every morning",
            }]},
        ],
    }


def build_video_schedule_confirm_components(token: str, templates: list[dict]) -> list[dict]:
    """Confirm card for a video schedule: optional template select above the
    shared Confirm/Cancel buttons (Discord modals cannot hold selects)."""
    options = [{"label": "No template (guided walkthrough)", "value": "none",
                "default": True}]
    for t in templates[:24]:
        key = t.get("key")
        if not key:
            continue
        options.append({"label": f"{t.get('emoji', '')} {t.get('name', key)}".strip()[:100],
                        "value": key[:100],
                        "description": (t.get("desc") or "")[:100]})
    select = {"type": SELECT_MENU, "custom_id": f"{SCHED_VIDTPL_PREFIX}{token}",
              "placeholder": "Template (optional)", "min_values": 1, "max_values": 1,
              "options": options}
    return [
        {"type": ACTION_ROW, "components": [select]},
        {"type": ACTION_ROW, "components": [
            _button("✅ Create video schedule", f"{SCHED_CONFIRM_PREFIX}{token}", STYLE_SUCCESS),
            _button("✖ Cancel", f"{SCHED_CANCEL_PREFIX}{token}", STYLE_SECONDARY)]},
    ]
```

Run the builder tests - now green.

- [ ] **Step 3: Extend the client + router create path**

`clients/tasks.py` `create_schedule` (86-105): add `kind: str = "agent"` and `video_config: dict | None = None` to the signature, and before the `_request` call:

```python
        # Only include non-default kinds so existing create payloads stay
        # byte-identical for agent schedules.
        if kind and kind != "agent":
            body["kind"] = kind
        if video_config is not None:
            body["video_config"] = video_config
```

`handlers/commands.py` `run_schedule_create` (2351-2372): add the same two keyword params and pass them through to `self._tasks_client.create_schedule(...)`.

- [ ] **Step 4: Wire the Discord flow in `discord_commands.py`**

(a) Component dispatch - beside `is_sched_new` (line 302), import the new names from app_builder_panel and add:

```python
        if custom_id == SCHED_NEWVID_ID:
            return {"type": MODAL, "data": build_video_schedule_modal()}
        if custom_id.startswith(SCHED_VIDTPL_PREFIX):
            token = custom_id[len(SCHED_VIDTPL_PREFIX):]
            values = (payload.get("data", {}) or {}).get("values") or []
            pending = self._pending_schedules.get(token)
            if pending and values and pending.get("video_config") is not None:
                picked = values[0]
                pending["video_config"]["template"] = "" if picked == "none" else picked
            return {"type": DEFERRED_UPDATE_MESSAGE}
```

(b) Modal-submit routing - beside `is_sched_modal` (line 1442):

```python
        if custom_id == SCHED_VIDMODAL_ID:
            return await self._handle_video_schedule_modal_submit(payload)
```

(c) The submit handler - add beside `_handle_schedule_modal_submit` (1559). Needs `from urllib.parse import urlparse` at the top of the file if not present:

```python
    async def _handle_video_schedule_modal_submit(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Video schedule modal submit: validate URL + parse the NL 'when',
        then show a confirm card with an optional template select. The
        schedule is only created when the user clicks Confirm."""
        data = payload.get("data", {})
        url = self._extract_modal_value(data, SCHED_VID_URL_INPUT)
        what = self._extract_modal_value(data, SCHED_VID_WHAT_INPUT)
        when = self._extract_modal_value(data, SCHED_VID_WHEN_INPUT)
        if not url.lower().startswith(("http://", "https://")):
            return {"type": CHANNEL_MESSAGE_WITH_SOURCE, "data": {
                "content": "That URL doesn't look right. It must start with http:// or https://.",
                "flags": 64}}
        parsed = parse_when(when)
        if parsed is None:
            return {"type": CHANNEL_MESSAGE_WITH_SOURCE, "data": {
                "content": ("I couldn't read that schedule. Try *every morning*, "
                            "*every Monday 9am*, or *every 30 minutes*."),
                "flags": 64}}
        cron, human = parsed
        host = urlparse(url).hostname or url
        name = f"{human}: video of {host}"[:120]
        token = uuid.uuid4().hex[:16]
        self._pending_schedules[token] = {
            "name": name, "cron": cron,
            "prompt": f"Video walkthrough of {url}",
            "human": human, "run_once": False,
            "kind": "video",
            "video_config": {"url": url, "prompt": what, "template": "",
                             "title": f"{host} walkthrough"},
        }
        from handlers import video_templates as vtpl
        if not vtpl.cache_is_fresh():
            self._spawn(vtpl.refresh_templates(self.router._tasks_client))
        return {"type": CHANNEL_MESSAGE_WITH_SOURCE, "data": {
            "content": (f"\U0001f3ac **{human}** - a video of {host}.\n"
                        "Pick a template (optional), then confirm."),
            "components": build_video_schedule_confirm_components(
                token, vtpl.cached_templates()),
            "flags": 64}}
```

(d) `_create_pending_schedule` (1711-1766): pass kind/video_config through the existing `run_schedule_create` call:

```python
            await self.router.run_schedule_create(
                ctx, name=pending["name"], cron=pending["cron"],
                prompt=pending["prompt"], delivery_channel_id=target,
                run_once=pending.get("run_once", False),
                kind=pending.get("kind", "agent"),
                video_config=pending.get("video_config"),
            )
```

- [ ] **Step 5: Add interaction tests**

Append to `tests/test_schedule_video_panel.py` - follow the interaction-test style used by the existing Discord schedule tests (grep `_handle_schedule_modal_submit` in tests/ and mirror that file's payload builders):

```python
# Test A: SCHED_NEWVID_ID component -> response type 9 (MODAL) with
#   data.custom_id == SCHED_VIDMODAL_ID.
# Test B: video modal submit with bad URL -> ephemeral error mentioning http.
# Test C: video modal submit with good URL + "every morning" -> response
#   contains build_video_schedule_confirm_components ids and a
#   _pending_schedules entry with kind == "video" and video_config.url set.
# Test D: SCHED_VIDTPL_PREFIX select with value "walkthrough" mutates the
#   pending entry's video_config["template"]; value "none" clears it.
# Test E: confirm path passes kind/video_config to run_schedule_create
#   (mock router.run_schedule_create; drive _create_pending_schedule).
```

Write these as real tests with assertions (the comments above define the required behavior, not placeholders to leave).

Run: `cd "/c/All/Work - Code/ai_ui/webhook-handler" && python -m pytest tests/test_schedule_video_panel.py -q`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
cd "/c/All/Work - Code/ai_ui" && git add webhook-handler/handlers/app_builder_panel.py webhook-handler/handlers/discord_commands.py webhook-handler/handlers/commands.py webhook-handler/clients/tasks.py webhook-handler/tests/test_schedule_video_panel.py && git commit -m "feat(cron): Discord schedule-a-video flow with template confirm card"
```

---

### Task 10: Slack cron - "Schedule a video" flow

**Files:**
- Modify: `webhook-handler/handlers/slack_schedule_panel.py` (constants at 29-42; new builder beside `build_schedule_modal` at 172-247; the dashboard builder that carries the New schedule button - grep `New schedule` in this file)
- Modify: `webhook-handler/handlers/slack_interactions.py` (the block_actions branch that opens `build_schedule_modal` - grep `build_schedule_modal(` ; the `SCHED_MODAL_ID` view_submission branch at 885-969)
- Test: `webhook-handler/tests/test_slack_schedule_video.py`

**Interfaces:**
- Consumes: `handlers.video_templates` cache (Task 3); `TasksClient.create_schedule(..., kind, video_config)` (Task 9); `schedule_picker.picks_to_cron` + `slack_picks_from_view` (exist).
- Produces: `SCHED_VIDEO_MODAL_ID = "aiuisched_vidmodal"` (Slack callback_ids use `_`, matching `SCHED_MODAL_ID`'s existing style - confirm the existing value and stay consistent with its separator), blocks `sched_vid_url` / `sched_vid_url_input`, `sched_vid_tpl` / `sched_vid_tpl_input`, `sched_vid_what` / `sched_vid_what_input`; `build_video_schedule_modal(templates) -> dict` reusing the SAME repeat/time/weekday/date picker blocks as `build_schedule_modal` (factor them into `_when_picker_blocks() -> list[dict]` used by both builders).

- [ ] **Step 1: Write the failing tests**

Create `webhook-handler/tests/test_slack_schedule_video.py`:

```python
from handlers.slack_schedule_panel import (
    SCHED_VIDEO_MODAL_ID, build_schedule_modal, build_video_schedule_modal,
)

_TPLS = [{"key": "walkthrough", "emoji": "X", "name": "Website Walkthrough",
          "desc": "tour", "style": "clean_product_demo", "prompt": "p"}]


def _block(modal, block_id):
    return next(b for b in modal["blocks"] if b.get("block_id") == block_id)


def test_video_modal_callback_and_inputs():
    modal = build_video_schedule_modal(_TPLS)
    assert modal["callback_id"] == SCHED_VIDEO_MODAL_ID
    url = _block(modal, "sched_vid_url")
    assert url["element"]["action_id"] == "sched_vid_url_input"
    tpl = _block(modal, "sched_vid_tpl")
    assert tpl["optional"] is True
    assert [o["value"] for o in tpl["element"]["options"]] == ["walkthrough"]
    what = _block(modal, "sched_vid_what")
    assert what["optional"] is True


def test_video_modal_shares_when_pickers_with_agent_modal():
    agent = build_schedule_modal()
    video = build_video_schedule_modal(_TPLS)
    agent_when = [b["block_id"] for b in agent["blocks"]
                  if b.get("block_id", "").startswith(("sched_repeat", "sched_time",
                                                        "sched_weekday", "sched_date"))]
    video_when = [b["block_id"] for b in video["blocks"]
                  if b.get("block_id", "").startswith(("sched_repeat", "sched_time",
                                                        "sched_weekday", "sched_date"))]
    assert agent_when == video_when and agent_when
```

Run: `cd "/c/All/Work - Code/ai_ui/webhook-handler" && python -m pytest tests/test_slack_schedule_video.py -q`
Expected: ImportError

- [ ] **Step 2: Implement the modal in `slack_schedule_panel.py`**

Add constants beside the existing ones (29-42):

```python
SCHED_VIDEO_MODAL_ID = "aiuisched_vidmodal"
SCHED_VID_URL_BLOCK_ID = "sched_vid_url"
SCHED_VID_URL_INPUT_ID = "sched_vid_url_input"
SCHED_VID_TPL_BLOCK_ID = "sched_vid_tpl"
SCHED_VID_TPL_ACTION_ID = "sched_vid_tpl_input"
SCHED_VID_WHAT_BLOCK_ID = "sched_vid_what"
SCHED_VID_WHAT_INPUT_ID = "sched_vid_what_input"
```

Factor the four picker blocks (Repeat / Time / Weekday / Date) out of `build_schedule_modal` into a module-level `_when_picker_blocks() -> list[dict]` returning them verbatim, and have `build_schedule_modal` use it (`"blocks": [<what block>] + _when_picker_blocks()`). Then:

```python
def build_video_schedule_modal(templates: list[dict]) -> dict:
    """Create-video-schedule modal: URL + optional template + optional
    direction, plus the same native when-pickers as the agent modal."""
    tpl_options = [_opt(f"{t.get('emoji', '')} {t.get('name', t['key'])}".strip()[:75],
                        t["key"]) for t in templates if t.get("key")]
    blocks = [
        {"type": "input", "block_id": SCHED_VID_URL_BLOCK_ID,
         "label": {"type": "plain_text", "text": "Website URL"},
         "element": {"type": "plain_text_input",
                     "action_id": SCHED_VID_URL_INPUT_ID, "max_length": 500,
                     "placeholder": {"type": "plain_text",
                                     "text": "https://yoursite.com"}}},
        {"type": "input", "block_id": SCHED_VID_TPL_BLOCK_ID, "optional": True,
         "label": {"type": "plain_text", "text": "Template"},
         "element": {"type": "static_select",
                     "action_id": SCHED_VID_TPL_ACTION_ID,
                     "placeholder": {"type": "plain_text",
                                     "text": "No template (guided walkthrough)"},
                     "options": tpl_options}},
        {"type": "input", "block_id": SCHED_VID_WHAT_BLOCK_ID, "optional": True,
         "label": {"type": "plain_text", "text": "What should the video show?"},
         "element": {"type": "plain_text_input",
                     "action_id": SCHED_VID_WHAT_INPUT_ID, "multiline": True,
                     "max_length": 2000,
                     "placeholder": {"type": "plain_text",
                                     "text": "Leave blank for the guided cursor walkthrough."}}},
    ] + _when_picker_blocks()
    return {
        "type": "modal", "callback_id": SCHED_VIDEO_MODAL_ID,
        "title": {"type": "plain_text", "text": "Schedule a video"[:_TITLE_MAX]},
        "submit": {"type": "plain_text", "text": "Create"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": blocks,
    }
```

Add a "\U0001f3ac Schedule a video" button (action_id `SCHED_NEWVID_ID` imported from `app_builder_panel`) next to the existing New-schedule button in this file's dashboard builder (grep `New schedule`).

- [ ] **Step 3: Wire `slack_interactions.py`**

(a) Open: find the block_actions branch that opens `build_schedule_modal()` (grep). Add a sibling branch:

```python
        if action_id == SCHED_NEWVID_ID:
            from handlers import video_templates as vtpl
            if not vtpl.cache_is_fresh():
                task = asyncio.create_task(
                    vtpl.refresh_templates(self.router._tasks_client))
                self.router._background_tasks.add(task)
                task.add_done_callback(self.router._background_tasks.discard)
            await self.slack.open_modal(
                trigger_id, build_video_schedule_modal(vtpl.cached_templates()))
            return {}
```

(b) Submit: add a `SCHED_VIDEO_MODAL_ID` branch beside the `SCHED_MODAL_ID` branch (885-969), reusing its exact structure (email resolve, `open_dm`, `slack_picks_from_view` + `picks_to_cron` + `PastTimeError`/pick-error handling, background `_create()` task) with these differences:

```python
            url = self._sched_value(view, SCHED_VID_URL_BLOCK_ID, SCHED_VID_URL_INPUT_ID)
            if not url.lower().startswith(("http://", "https://")):
                return {"response_action": "errors",
                        "errors": {SCHED_VID_URL_BLOCK_ID: "Enter a valid http(s) URL"}}
            what = self._sched_value(view, SCHED_VID_WHAT_BLOCK_ID, SCHED_VID_WHAT_INPUT_ID)
            state = (view.get("state", {}) or {}).get("values", {}) or {}
            sel = ((state.get(SCHED_VID_TPL_BLOCK_ID, {}) or {})
                   .get(SCHED_VID_TPL_ACTION_ID, {}) or {})
            tpl_key = (sel.get("selected_option") or {}).get("value", "")
            from urllib.parse import urlparse
            host = urlparse(url).hostname or url
            name = f"{human}: video of {host}"[:120]
            # inside _create(), the create call becomes:
            await self.router._tasks_client.create_schedule(
                email, name=name, cron=cron,
                prompt=f"Video walkthrough of {url}",
                delivery_channel_id=dm, delivery_platform="slack",
                run_once=run_once, kind="video",
                video_config={"url": url, "template": tpl_key, "prompt": what,
                              "title": f"{host} walkthrough"})
            await self.slack.post_message(
                channel=dm, text=f"✅ Scheduled - a video of {host} runs {human}")
```

No connector-intent gating for video schedules (they never touch Gmail/Drive).

- [ ] **Step 4: Interaction tests**

Append to `tests/test_slack_schedule_video.py`, mirroring the existing Slack schedule submit tests (grep `SCHED_MODAL_ID` in tests/ for the view/state fixture style):

```python
# Test A: SCHED_NEWVID_ID block_action -> slack.open_modal awaited with a view
#   whose callback_id == SCHED_VIDEO_MODAL_ID.
# Test B: video view_submission with bad URL -> {"response_action": "errors"}
#   keyed by sched_vid_url; create_schedule NOT called.
# Test C: happy path (url + daily 09:00 picks) -> create_schedule awaited with
#   kind="video", video_config.url == url, delivery_platform == "slack",
#   and a DM confirmation posted.
# Test D: template selected -> video_config["template"] == picked key.
```

Write these as real asserting tests. Run: `cd "/c/All/Work - Code/ai_ui/webhook-handler" && python -m pytest tests/test_slack_schedule_video.py -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
cd "/c/All/Work - Code/ai_ui" && git add webhook-handler/handlers/slack_schedule_panel.py webhook-handler/handlers/slack_interactions.py webhook-handler/tests/test_slack_schedule_video.py && git commit -m "feat(cron): Slack schedule-a-video modal with template pick"
```

---

### Task 11: App Builder - "Walkthrough video" button (Discord)

**Files:**
- Modify: `webhook-handler/handlers/app_builder_panel.py` (`build_project_menu_components` at 385-412; constants near `DELETE_PREFIX` at 305-310)
- Modify: `webhook-handler/handlers/discord_commands.py` (component dispatch beside `is_app_delete` at ~287)
- Modify: `webhook-handler/handlers/commands.py` (new runner near `run_panel_menu` at 2282)
- Test: `webhook-handler/tests/test_app_walkthrough_video.py`

**Interfaces:**
- Consumes: `_handle_video_route` (discord_commands.py:986 - provides notify_channel/notify_channel_msg so `_watch_video` + `_deliver_video` work); `TasksClient.get_project_status / create_video_draft / capture_video_screenshots / queue_video` (exist); `PUBLIC_DOMAIN` (commands.py:47).
- Produces: `WALKVIDEO_PREFIX = "aiuibuild:video:"` + menu button; `CommandRouter.run_app_walkthrough_video(ctx, slug: str) -> None`. Behavior: empty prompt + remotion + cursor_click -> the backend's default walk-cursor path; MP4 posts back into the thread the menu lives in via the existing watcher.

- [ ] **Step 1: Write the failing tests**

Create `webhook-handler/tests/test_app_walkthrough_video.py` (reuse `_router`/`_ctx` helpers style from `test_video_runners.py` - copy those two helpers into this file if they are not importable):

```python
import pytest
from unittest.mock import AsyncMock, MagicMock

from handlers.app_builder_panel import WALKVIDEO_PREFIX, build_project_menu_components


def test_project_menu_has_walkthrough_video_button():
    rows = build_project_menu_components("myapp", published=False,
                                         preview_url="https://x/p/", owner="o@x.com")
    ids = [c.get("custom_id") for row in rows for c in row.get("components", [])]
    assert f"{WALKVIDEO_PREFIX}myapp" in ids


@pytest.mark.asyncio
async def test_run_app_walkthrough_video_drives_pipeline_with_empty_prompt():
    tc = MagicMock()
    tc.get_project_status = AsyncMock(return_value={
        "name": "My App", "published": False, "public_url": ""})
    tc.create_video_draft = AsyncMock(return_value={"id": "vj1"})
    tc.capture_video_screenshots = AsyncMock(return_value={"count": 4})
    tc.queue_video = AsyncMock(return_value={"status": "queued", "queue_position": 0})
    r = _router(tc)
    r._watch_video = AsyncMock()
    nc = AsyncMock()
    ctx = _ctx(notify_channel=nc)
    await r.run_app_walkthrough_video(ctx, "myapp")
    draft_call = tc.create_video_draft.await_args
    assert draft_call.args[2] == ""                      # empty prompt -> walk default
    assert draft_call.kwargs["render_mode"] == "remotion"
    cap_call = tc.capture_video_screenshots.await_args
    assert "/tasks/preview-app/myapp/" in cap_call.args[2]
    tc.queue_video.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_app_walkthrough_video_prefers_public_url():
    tc = MagicMock()
    tc.get_project_status = AsyncMock(return_value={
        "name": "My App", "published": True, "public_url": "https://live.app/"})
    tc.create_video_draft = AsyncMock(return_value={"id": "vj1"})
    tc.capture_video_screenshots = AsyncMock(return_value={"count": 4})
    tc.queue_video = AsyncMock(return_value={"status": "queued"})
    r = _router(tc)
    r._watch_video = AsyncMock()
    await r.run_app_walkthrough_video(_ctx(notify_channel=AsyncMock()), "myapp")
    assert tc.capture_video_screenshots.await_args.args[2] == "https://live.app/"


@pytest.mark.asyncio
async def test_run_app_walkthrough_video_status_error_is_clean():
    from clients.tasks import TasksAPIError
    tc = MagicMock()
    tc.get_project_status = AsyncMock(side_effect=TasksAPIError(404, "not found"))
    tc.create_video_draft = AsyncMock()
    r = _router(tc)
    ctx = _ctx()
    await r.run_app_walkthrough_video(ctx, "myapp")
    tc.create_video_draft.assert_not_awaited()
    ctx.respond.assert_awaited()
```

Run: `cd "/c/All/Work - Code/ai_ui/webhook-handler" && python -m pytest tests/test_app_walkthrough_video.py -q`
Expected: ImportError on `WALKVIDEO_PREFIX`

- [ ] **Step 2: Implement**

`app_builder_panel.py` - constant beside `DELETE_PREFIX` (305-310):

```python
WALKVIDEO_PREFIX = "aiuibuild:video:"    # walkthrough-video button -> :<slug>
```

In `build_project_menu_components` (385-412), add BEFORE the Status button append:

```python
    buttons.append(_button("\U0001f3ac Walkthrough video",
                           f"{WALKVIDEO_PREFIX}{slug}", STYLE_PRIMARY))
```

(The existing 5-per-row chunking absorbs the extra button.)

`discord_commands.py` - dispatch beside `is_app_delete` (~287); import `WALKVIDEO_PREFIX`:

```python
        if custom_id.startswith(WALKVIDEO_PREFIX):
            slug = custom_id[len(WALKVIDEO_PREFIX):]
            return await self._handle_video_route(
                payload, lambda ctx, s=slug: self.router.run_app_walkthrough_video(ctx, s),
                raw_text=f"aiuibuilder video {slug}")
```

(`_handle_video_route` is used, NOT `_handle_panel_route`, because the runner needs `notify_channel`/`notify_channel_msg` for `_watch_video` delivery.)

`commands.py` - add near `run_panel_menu` (2282):

```python
    async def run_app_walkthrough_video(self, ctx: CommandContext, slug: str) -> None:
        """My apps 'Walkthrough video': render the default cursor walkthrough
        of the app's live (or preview) URL and post the MP4 back here."""
        email = await self._resolve_email_for_ctx(ctx)
        if not email:
            await self._respond_not_linked(ctx)
            return
        try:
            status = await self._tasks_client.get_project_status(email, slug)
        except TasksAPIError as e:
            await ctx.respond(self._format_status_error(e))
            return
        name = status.get("name", slug)
        url = (status.get("public_url") or "").strip()
        if not url:
            if not PUBLIC_DOMAIN:
                await ctx.respond("No public domain is configured, so I can't reach the app preview.")
                return
            url = f"https://{PUBLIC_DOMAIN}/tasks/preview-app/{slug}/"
        try:
            draft = await self._tasks_client.create_video_draft(
                email, f"{name} walkthrough", "", "clean_product_demo", "amy",
                render_mode="remotion", animation_preset="cursor_click")
            job_id = str(draft.get("id") or "")
            await ctx.respond(f"\U0001f3ac Filming a walkthrough of **{name}** - capturing pages now.")
            await self._tasks_client.capture_video_screenshots(email, job_id, url)
            res = await self._tasks_client.queue_video(email, job_id)
        except TasksAPIError as e:
            await ctx.respond(self._format_tasks_error(e))
            return
        qp = res.get("queue_position", 0)
        tail = f" (queue position {qp})" if qp else ""
        if ctx.notify_channel is not None:
            await ctx.notify_channel(
                f"Rendering the walkthrough{tail} - I'll post it here when it's done.")
            watcher = asyncio.create_task(self._watch_video(ctx, email, job_id))
            self._background_tasks.add(watcher)
            watcher.add_done_callback(self._on_video_watcher_done)
```

(If `_format_tasks_error` does not exist in commands.py, use the same error formatter `run_schedule_create` uses - grep it and match.)

- [ ] **Step 3: Run tests + regressions**

Run: `cd "/c/All/Work - Code/ai_ui/webhook-handler" && python -m pytest tests/test_app_walkthrough_video.py tests/test_video_runners.py -q`
Expected: all pass

- [ ] **Step 4: Commit**

```bash
cd "/c/All/Work - Code/ai_ui" && git add webhook-handler/handlers/app_builder_panel.py webhook-handler/handlers/discord_commands.py webhook-handler/handlers/commands.py webhook-handler/tests/test_app_walkthrough_video.py && git commit -m "feat(appbuilder): Discord walkthrough-video button in My apps"
```

---

### Task 12: App Builder - "Walkthrough video" button (Slack)

**Files:**
- Modify: `webhook-handler/handlers/slack_app_builder_panel.py` (`build_apps_list_blocks` at 355-431; constants at 15-36)
- Modify: `webhook-handler/handlers/slack_interactions.py` (the prefix/handler dispatch loop at 187-203; new `_do_walkthrough_video` beside `_do_delete` at 1377)
- Test: `webhook-handler/tests/test_slack_app_walkthrough_video.py`

**Interfaces:**
- Consumes: `WALKVIDEO_PREFIX = "aiuibuild:video:"` - import it from `handlers.app_builder_panel` (defined in Task 11; do NOT redefine); `_watch_slack_video(email, job_id, user_id, channel)` (slack_interactions.py:1200 - delivers the share_url to the DM); `settings.tasks_public_url`.
- Produces: a "Walkthrough video" button on each My-apps row; `_do_walkthrough_video(payload, slug)`.

- [ ] **Step 1: Write the failing tests**

Create `webhook-handler/tests/test_slack_app_walkthrough_video.py`:

```python
import pytest
from unittest.mock import AsyncMock

from handlers.app_builder_panel import WALKVIDEO_PREFIX
from handlers.slack_app_builder_panel import build_apps_list_blocks


def _action_ids(blocks):
    return [e.get("action_id") for b in blocks if b.get("type") == "actions"
            for e in b.get("elements", [])]


def test_apps_list_rows_have_walkthrough_button():
    blocks = build_apps_list_blocks(
        [{"slug": "myapp", "name": "My App", "published": False}], owner="o@x.com")
    assert f"{WALKVIDEO_PREFIX}myapp" in _action_ids(blocks)


def test_walkthrough_button_present_for_published_apps_too():
    blocks = build_apps_list_blocks(
        [{"slug": "myapp", "name": "My App", "published": True,
          "public_url": "https://live.app/"}], owner="o@x.com")
    assert f"{WALKVIDEO_PREFIX}myapp" in _action_ids(blocks)
```

Plus interaction tests mirroring `test_slack_video_interactions.py`'s `_handler`/router fixtures:

```python
# Test C: block_action with action_id f"{WALKVIDEO_PREFIX}myapp" spawns the
#   handler; after the background task runs: get_project_status awaited,
#   create_video_draft awaited with prompt "" and render_mode "remotion",
#   capture_video_screenshots awaited with the preview URL, queue_video
#   awaited, and _watch_slack_video awaited.
# Test D: get_project_status raises -> a clean error DM is posted and
#   create_video_draft is NOT called.
```

Write C and D as real asserting tests. Run: `cd "/c/All/Work - Code/ai_ui/webhook-handler" && python -m pytest tests/test_slack_app_walkthrough_video.py -q`
Expected: FAIL (button absent / handler missing)

- [ ] **Step 2: Implement**

`slack_app_builder_panel.py`: import `WALKVIDEO_PREFIX` from `handlers.app_builder_panel` (this file already imports other shared constants from there - extend that import). In `build_apps_list_blocks`, add to `row_buttons` right before `_delete_button(...)` in BOTH the published and draft branches (it is appended after the branch merge, so one insertion where `row_buttons.append(_delete_button(slug, name))` happens):

```python
        row_buttons.append(_button("Walkthrough video", f"{WALKVIDEO_PREFIX}{slug}"))
```

(The existing 5-per-actions-block chunk loop absorbs the extra element.)

`slack_interactions.py`: add to the prefix/handler dispatch tuple (187-203):

```python
            (WALKVIDEO_PREFIX, self._do_walkthrough_video),
```

placing it ABOVE the `(DELETE_PREFIX, ...)` entry (both start `aiuibuild:` and are disjoint, but keep video before delete for readability). Import `WALKVIDEO_PREFIX` beside the other app-builder imports. Add beside `_do_delete` (1377):

```python
    async def _do_walkthrough_video(self, payload: dict[str, Any], slug: str) -> None:
        """My apps 'Walkthrough video': render the default cursor walkthrough
        of the app and DM the finished video link."""
        user_id: str = payload.get("user", {}).get("id", "")
        try:
            email = await self._bail_if_not_linked(user_id)
            if not email:
                return
            tasks = self.router._tasks_client
            status = await tasks.get_project_status(email, slug)
            name = status.get("name", slug)
            url = (status.get("public_url") or "").strip()
            if not url:
                url = f"{settings.tasks_public_url.rstrip('/')}/tasks/preview-app/{slug}/"
            dm = await self.slack.open_dm(user_id)
            if dm:
                await self.slack.post_message(
                    channel=dm,
                    text=f"\U0001f3ac Filming a walkthrough of {name} - I'll post the video here.")
            draft = await tasks.create_video_draft(
                email, f"{name} walkthrough", "", "clean_product_demo", "amy",
                render_mode="remotion", animation_preset="cursor_click")
            job_id = str(draft.get("id") or "")
            await tasks.capture_video_screenshots(email, job_id, url)
            await tasks.queue_video(email, job_id)
            await self._watch_slack_video(email, job_id, user_id, "")
        except Exception as exc:  # noqa: BLE001
            logger.error("_do_walkthrough_video failed slug=%s user=%s: %s",
                         slug, user_id, exc)
            try:
                dm = await self.slack.open_dm(user_id)
                if dm:
                    await self.slack.post_message(
                        channel=dm,
                        text="Something went wrong starting the walkthrough video. Try again shortly.")
            except Exception:  # noqa: BLE001
                pass
```

(`settings` - confirm slack_interactions.py already imports it; if not, `from config import settings`.)

- [ ] **Step 3: Run tests**

Run: `cd "/c/All/Work - Code/ai_ui/webhook-handler" && python -m pytest tests/test_slack_app_walkthrough_video.py tests/test_slack_video_interactions.py -q`
Expected: all pass

- [ ] **Step 4: Commit**

```bash
cd "/c/All/Work - Code/ai_ui" && git add webhook-handler/handlers/slack_app_builder_panel.py webhook-handler/handlers/slack_interactions.py webhook-handler/tests/test_slack_app_walkthrough_video.py && git commit -m "feat(appbuilder): Slack walkthrough-video button in My apps"
```

---

### Task 13: Final review, dash scan, full feature suites

**Files:** none new - review pass over the whole branch.

- [ ] **Step 1: Dash scan** (no em/en dashes anywhere in the diff)

Run: `cd "/c/All/Work - Code/ai_ui" && git diff main...HEAD | grep -nP '[\x{2013}\x{2014}]' || echo CLEAN`
Expected: `CLEAN` (the `…` ellipsis in select placeholders is fine; only U+2013/U+2014 are banned)

- [ ] **Step 2: Full feature test sweep**

```bash
cd "/c/All/Work - Code/ai_ui/mcp-servers/tasks" && python -m pytest tests/test_video_templates.py tests/test_schedule_kind.py tests/test_scheduler_video.py tests/test_video_walk_plan.py tests/test_video_capture.py tests/test_video_worker.py tests/test_routes_video_capture.py -q
cd "/c/All/Work - Code/ai_ui/webhook-handler" && python -m pytest tests/test_video_templates_cache.py tests/test_video_panel.py tests/test_video_runners.py tests/test_video_routing.py tests/test_slack_video_panel.py tests/test_slack_video_interactions.py tests/test_schedule_video_panel.py tests/test_slack_schedule_video.py tests/test_schedule_result_video.py tests/test_app_walkthrough_video.py tests/test_slack_app_walkthrough_video.py tests/test_setup_slack_video_channel.py -q
```
Expected: all pass (DB-gated skips OK)

- [ ] **Step 3: Whole-branch code review**

Dispatch a code-reviewer subagent over `git diff main...HEAD` against the spec (`docs/superpowers/specs/2026-07-06-video-sync-slack-cron-appbuilder-design.md`). Fix anything Important+; re-run the affected tests; commit fixes.

- [ ] **Step 4: Merge readiness**

Use superpowers:finishing-a-development-branch. Default: merge `feat/video-sync-surfaces` into `main` locally; hold the GitHub push for Ralph's go-ahead (his standing pattern).

---

### Task 14: Deploy + go-live + prod verification

**Files:** none - operational. Follow CLAUDE.md deploy rules exactly.

- [ ] **Step 1: Preconditions**

- Working tree clean, branch merged to `main` locally.
- `ssh -i ~/.ssh/aiui_vps -o IdentitiesOnly=yes root@46.224.193.25 "echo ok"` succeeds. STOP if not.
- Confirm with Ralph before deploying if he has not already said to ship.

- [ ] **Step 2: Deploy the tasks service** (orchestrator handles mcp-servers/ + smoke)

```bash
cd "/c/All/Work - Code/ai_ui" && ORCH_HOST=46.224.193.25 ./scripts/deploy_orchestrator.sh
```

REMINDER: never push local `mcp-servers/tasks/templates.py`; the orchestrator diffs by SHA so it only ships committed changes - verify `templates.py` is NOT in the diff it prints.

- [ ] **Step 3: Deploy webhook-handler** (NOT covered by the orchestrator; one scp per changed file, never `scp -r`)

```bash
cd "/c/All/Work - Code/ai_ui"
for f in $(git diff --name-only <last-deployed-sha>..HEAD -- webhook-handler/); do
  scp -i ~/.ssh/aiui_vps -o IdentitiesOnly=yes "$f" "root@46.224.193.25:/root/proxy-server/$f"
done
ssh -i ~/.ssh/aiui_vps -o IdentitiesOnly=yes root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --build webhook-handler"
```

- [ ] **Step 4: Slack panel go-live**

```bash
ssh -i ~/.ssh/aiui_vps -o IdentitiesOnly=yes root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml exec -T webhook-handler python /app/scripts/setup_slack_video_channel.py"
```

Then pin the posted panel message in the Slack video channel (or ask Ralph to pin if the bot lacks the scope - the cron channel had this limitation).

- [ ] **Step 5: Verify**

```bash
curl -fsS https://ai-ui.coolestdomain.win/tasks/healthz
curl -fsS https://ai-ui.coolestdomain.win/api/video-jobs/templates   # via gateway; expect the 4 templates JSON
ssh -i ~/.ssh/aiui_vps -o IdentitiesOnly=yes root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml ps webhook-handler tasks"
```

- Check migration applied: `docker compose ... exec -T postgres psql -U <user> -d <db> -c "\\d tasks.schedules"` shows `kind` and `video_config`.
- Live checks: web `/video-generator` still renders the template grid (now server-fed); Discord video options card shows the Template select; Slack New-video modal shows Template; create a `video` schedule via run-now (`POST /schedules/{id}/run-now` path or the panel button) and confirm the MP4/link lands in the thread; click Walkthrough video on a test app in My apps (both platforms).
- md5 spot-check deployed files vs main (LF-normalized), per the usual routine.

- [ ] **Step 6: Record state**

Update memory (SYNC STATE line + a project memory note for this feature) with what is deployed and verified.

---

## Self-review notes (already applied)

- Spec coverage: registry (T1), web fetch (T2), client+cache (T3), Discord panel (T4), Slack panel + prefill + go-live (T5, T14), cron columns/API (T6), scheduler branch + delivery (T7, T8), cron UIs (T9, T10), App Builder buttons (T11, T12), error handling embedded per task, testing (each task + T13), deploy/verify (T14).
- Deviations from the spec, agreed rationale: (1) Discord cannot prefill modal text inputs or put selects in modals, so the Discord template pick lives on the options card (video panel) and on the confirm card (cron), writing style+prompt onto the draft directly - equivalent editable behavior. (2) The webhook-handler keeps a fallback template list inside the cache module (outage window only; server registry stays the source of truth). (3) video.html has no JS test harness; Task 2 verifies by parse-check + the Task 14 live check.
- Type consistency: `run_video_apply_template(ctx, job_id, template_key)`, `_run_video_schedule -> (status, result, extras)`, `create_schedule(..., kind, video_config)`, `WALKVIDEO_PREFIX` defined once in app_builder_panel.py and imported by the Slack panel - all cross-referenced above.

