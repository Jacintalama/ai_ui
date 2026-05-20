# Discord App Builder template selection — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a Discord user pick one of the existing App Builder templates with `/aiui aiuibuilder build <template> <description>`, plus `/aiui aiuibuilder templates` to list them — reusing the web's template machinery, forced to browser-storage so there's no Supabase gate.

**Architecture:** Extends the already-shipped user-scoped Discord build. The tasks service gains a `current_user` catalog endpoint and a `template_key` param on the build endpoint (injecting `build_rules_for(key,"none")` and copying the prebuilt base app, mirroring the web `create_task`). The bot lists the catalog and resolves an optional leading template key from the build args, falling back to template-less on any catalog hiccup.

**Tech Stack:** FastAPI + SQLAlchemy async (tasks), httpx + respx (bot + tests), pytest/pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-05-20-discord-aiuibuilder-templates-design.md`
**Builds on:** the shipped `2026-05-20-discord-aiuibuilder-build-*` work.

---

## Test execution environment (same as the build feature)

- No local Docker. Run with local Python (3.13):
  - Bot: from `webhook-handler/` → `python -m pytest tests/ -q`
  - Tasks: from `mcp-servers/tasks/` → `DATABASE_URL="postgresql+asyncpg://nope/nope" python -m pytest tests/test_routes_aiuibuilder.py -q` (run via Bash tool; dummy URL satisfies conftest import, no test hits a DB).
- All new tests are DB-free (TestClient + monkeypatch on tasks; respx on bot). Real-DB behavior is verified by the live template e2e after deploy (Task 5).

## File Structure

- Modify `mcp-servers/tasks/routes_aiuibuilder.py` — add `_compose_build_description`, the `TemplateBrief` model + `_template_note` + `GET /templates`, and a `template_key` param through `BuildRequest` → `start_build` → `_create_and_spawn_build`.
- Modify `mcp-servers/tasks/tests/test_routes_aiuibuilder.py` — new tests.
- Modify `webhook-handler/clients/tasks.py` — `list_templates` + `template_key` on `start_build`.
- Modify `webhook-handler/tests/test_tasks_client.py` — new/updated tests.
- Modify `webhook-handler/handlers/commands.py` — `templates` action + template resolution in `build`.
- Modify `webhook-handler/tests/test_aiuibuilder_build.py` — new tests + mock `list_templates` in existing build tests.
- Modify `scripts/e2e_backend_smoke.py` — add a catalog-endpoint check (Task 5).

---

## Task 1: tasks service — catalog endpoint + description composer

**Files:**
- Modify: `mcp-servers/tasks/routes_aiuibuilder.py`
- Test: `mcp-servers/tasks/tests/test_routes_aiuibuilder.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_routes_aiuibuilder.py`:

```python
def test_compose_build_description_template_less_matches_bind():
    # Template-less must be byte-identical to the shipped _bind_slug_description.
    out = rb._compose_build_description("todo-a1b2", None, "a todo list")
    assert out == rb._bind_slug_description("todo-a1b2", "a todo list")
    assert 'PROJECT NAME: "todo-a1b2"' in out
    assert "USER REQUEST:" in out
    assert "a todo list" in out


def test_compose_build_description_with_template_injects_rules():
    out = rb._compose_build_description("port-a1b2", "portfolio", "a UX designer named Maya")
    # Order: slug directive, then template rules, then the user request.
    assert 'PROJECT NAME: "port-a1b2"' in out
    assert "USER REQUEST:" in out
    assert "a UX designer named Maya" in out
    # build_rules_for("portfolio", "none") content is present (PURPOSE marker).
    assert "PURPOSE:" in out
    assert out.index('PROJECT NAME') < out.index("PURPOSE:") < out.index("USER REQUEST:")


def test_compose_build_description_caps_length():
    out = rb._compose_build_description("s-a1b2", "portfolio", "x" * 30000)
    assert len(out) == 20_000


def test_templates_catalog_requires_email():
    r = _client().get("/api/aiuibuilder/templates")
    assert r.status_code == 401


def test_templates_catalog_shape_and_excludes_blank_custom():
    r = _client().get("/api/aiuibuilder/templates", headers={"X-User-Email": "a@x.com"})
    assert r.status_code == 200, r.text
    body = r.json()
    keys = {t["key"] for t in body}
    assert "portfolio" in keys
    assert "blank" not in keys and "custom" not in keys
    # No rules leaked.
    assert all("rules" not in t for t in body)
    # Each item has the brief fields.
    for t in body:
        assert set(t) >= {"key", "label", "emoji", "description", "has_app", "note"}


def test_templates_catalog_notes():
    r = _client().get("/api/aiuibuilder/templates", headers={"X-User-Email": "a@x.com"})
    by_key = {t["key"]: t for t in r.json()}
    assert "Supabase" in by_key["auth"]["note"]            # auth → web-only note
    assert by_key["crud"]["note"] == "saves in your browser"  # db-backed fallback
    assert by_key["portfolio"]["note"] == ""                # frontend-only
```

- [ ] **Step 2: Run to verify failure**

Run: `cd mcp-servers/tasks && DATABASE_URL="postgresql+asyncpg://nope/nope" python -m pytest tests/test_routes_aiuibuilder.py -q`
Expected: FAIL — `AttributeError: _compose_build_description` and 404/405 for the catalog route.

- [ ] **Step 3: Implement the composer + catalog endpoint**

In `routes_aiuibuilder.py`, add the composer right after `_bind_slug_description`:

```python
def _compose_build_description(slug: str, template_key: str | None, description: str) -> str:
    """Compose the agent build description.

    Template-less keeps the shipped slug-bound form byte-for-byte. With a
    template, inject that template's curated rules (storage forced to 'none' —
    no Supabase gate from Discord) between the slug directive and the user
    request, mirroring routes_tasks.create_task. Capped at 20k like the web."""
    if not template_key:
        return _bind_slug_description(slug, description)
    from templates import build_rules_for
    directive = (
        f'PROJECT NAME: "{slug}". Create the app at apps/{slug}/ and use this '
        f'exact slug throughout — do NOT invent a different folder name.'
    )
    rules = build_rules_for(template_key, "none").strip()
    user_req = "USER REQUEST:\n" + (description or "").strip()
    parts = [directive] + ([rules] if rules else []) + [user_req]
    return "\n\n".join(parts)[:20_000]
```

Add the catalog model + note helper near the other models (after `BuildStatusResponse`):

```python
# Catalog keys that are equivalent to a template-less Discord build (`custom`
# has no rules; `blank` asks clarifying questions that can't be answered over
# Discord). Excluded from the listing so the bot treats `build blank …` /
# `build custom …` as ordinary template-less builds.
_CATALOG_EXCLUDED_KEYS = frozenset({"blank", "custom"})


class TemplateBrief(BaseModel):
    key: str
    label: str
    emoji: str
    description: str
    has_app: bool
    note: str


def _template_note(key: str, storage: str) -> str:
    """Discord-facing storage hint. `auth` is the only template with no
    localStorage fallback, so it's flagged web-only; other db-backed templates
    degrade to browser storage; frontend-only templates need no note."""
    if key == "auth":
        return "needs Supabase — use the web App Builder"
    if storage == "supabase":
        return "saves in your browser"
    return ""
```

Add the route (place it next to `start_build`/`get_build_status`):

```python
@router.get("/templates", response_model=list[TemplateBrief])
async def list_build_templates(user: CurrentUser = Depends(current_user)):
    """User-scoped template catalog for the Discord bot. No `rules` (same
    prompt-injection guard as the admin /api/templates). Excludes blank/custom."""
    from templates import TEMPLATES, _has_template_app
    return [
        TemplateBrief(
            key=t.key,
            label=t.label,
            emoji=t.emoji,
            description=t.description,
            has_app=_has_template_app(t.key),
            note=_template_note(t.key, t.storage),
        )
        for t in TEMPLATES
        if t.key not in _CATALOG_EXCLUDED_KEYS
    ]
```

- [ ] **Step 4: Run to verify pass**

Run: `cd mcp-servers/tasks && DATABASE_URL="postgresql+asyncpg://nope/nope" python -m pytest tests/test_routes_aiuibuilder.py -q`
Expected: PASS (all, incl. the 6 new).

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/routes_aiuibuilder.py mcp-servers/tasks/tests/test_routes_aiuibuilder.py
git commit -m "feat(tasks): aiuibuilder template catalog endpoint + description composer"
```

---

## Task 2: tasks service — `template_key` on the build endpoint

**Files:**
- Modify: `mcp-servers/tasks/routes_aiuibuilder.py`
- Test: `mcp-servers/tasks/tests/test_routes_aiuibuilder.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_routes_aiuibuilder.py`:

```python
def test_build_accepts_template_key(monkeypatch):
    seen = {}
    async def fake_create(email, seed, description, template_key=None):
        seen["template_key"] = template_key
        return ("11111111-1111-1111-1111-111111111111", "portfolio-a1b2")
    monkeypatch.setattr(rb, "_create_and_spawn_build", fake_create)
    r = _client().post(
        "/api/aiuibuilder/build",
        headers={"X-User-Email": "alice@x.com"},
        json={"description": "a designer site", "template_key": "portfolio"},
    )
    assert r.status_code == 201, r.text
    assert seen["template_key"] == "portfolio"


def test_build_invalid_template_key_422(monkeypatch):
    # Real _create_and_spawn_build must reject a bogus key BEFORE touching the DB.
    # We patch session() so the validation (which runs first) is what we observe.
    r = _client().post(
        "/api/aiuibuilder/build",
        headers={"X-User-Email": "alice@x.com"},
        json={"description": "x", "template_key": "definitely-not-a-template"},
    )
    assert r.status_code == 422


def test_build_template_key_optional(monkeypatch):
    seen = {}
    async def fake_create(email, seed, description, template_key=None):
        seen["template_key"] = template_key
        return ("t", "s")
    monkeypatch.setattr(rb, "_create_and_spawn_build", fake_create)
    r = _client().post(
        "/api/aiuibuilder/build",
        headers={"X-User-Email": "alice@x.com"},
        json={"description": "a todo list"},
    )
    assert r.status_code == 201
    assert seen["template_key"] is None
```

Note: `test_build_invalid_template_key_422` exercises the REAL `_create_and_spawn_build`. The
validation must happen before any DB access so this passes without a database (the bogus key
raises 422 before `session()` is touched).

- [ ] **Step 2: Run to verify failure**

Run: `cd mcp-servers/tasks && DATABASE_URL="postgresql+asyncpg://nope/nope" python -m pytest tests/test_routes_aiuibuilder.py -q`
Expected: FAIL — `BuildRequest` rejects `template_key`, and the bogus-key case won't 422.

- [ ] **Step 3: Implement**

In `routes_aiuibuilder.py`:

(a) Add the field to `BuildRequest`:
```python
class BuildRequest(BaseModel):
    description: str = Field(min_length=1, max_length=4000)
    name: str | None = Field(default=None, max_length=80)
    template_key: str | None = Field(default=None, max_length=64)
```

(b) Add `is_valid_key` to the top-level templates import (templates.py has no circular dep):
```python
from templates import build_rules_for, is_valid_key  # build_rules_for already used by composer
```
(If `build_rules_for` is currently a deferred import inside `_compose_build_description`, keep
it deferred there and only add `is_valid_key` at top — either is fine, just avoid duplicate
imports.)

(c) Change `_create_and_spawn_build` signature + validate + compose + scaffold. Replace the
function header and the slug/description/scaffold section:

```python
async def _create_and_spawn_build(
    email: str, seed: str, description: str, template_key: str | None = None,
) -> tuple[str, str]:
    """Create a BUILD task owned by `email` and spawn the agent run.

    One build platform-wide at a time: raises HTTPException(429) if any BUILD
    task is already in a live state. With `template_key`, the template's rules
    are injected (storage forced 'none') and its prebuilt base app is copied in.
    Returns (task_id, slug).
    """
    from claude_executor import build_prompt
    from routes_execution import _RUNNING, _run_execution
    from routes_tasks import _copy_template_app, _ensure_app_skeleton, _humanize_slug
    from templates import _has_template_app

    if template_key is not None and not is_valid_key(template_key):
        raise HTTPException(status_code=422, detail="Unknown template")

    meeting_id = uuid.uuid4()
    async with session() as s:
        await s.execute(text("SELECT pg_advisory_xact_lock(hashtext('aiuibuilder:build'))"))
        in_flight = (await s.execute(
            select(TaskItem.id).where(
                TaskItem.action_type == "BUILD",
                TaskItem.status.in_(_LIVE_BUILD_STATES),
            ).limit(1)
        )).scalar_one_or_none()
        if in_flight:
            raise HTTPException(status_code=429, detail="A build is already running")

        slug = await _unique_slug(s, seed)
        bound_description = _compose_build_description(slug, template_key, description)
        item = TaskItem(
            meeting_id=meeting_id,
            action_type="BUILD",
            assignee_name=email.split("@")[0],
            assignee_email=email,
            description=bound_description,
            priority="NICE_TO_HAVE",
            status="running",
            mode="ai",
            max_attempts=3,
            built_app_slug=slug,
        )
        s.add(item)
        await s.flush()
        execution = TaskExecution(task_id=item.id, status="running", log="")
        s.add(execution)
        await s.commit()
        await s.refresh(item)
        await s.refresh(execution)
        task_id, exec_id = item.id, execution.id

    # Scaffold: copy the prebuilt base app when the template has one, else the
    # empty skeleton. Best-effort — the agent recreates the dir if this fails.
    try:
        if template_key and _has_template_app(template_key):
            _copy_template_app(template_key, slug, app_name=_humanize_slug(slug))
        else:
            _ensure_app_skeleton(slug, None)
    except Exception:
        pass

    prompt = build_prompt(
        description=bound_description,
        action_type="BUILD",
        priority="NICE_TO_HAVE",
        meeting_title=str(meeting_id),
        meeting_date="",
        supabase_url=None,
        has_db_uri=False,
        slug=slug,
        user_email=email,
    )
    _RUNNING[task_id] = {"task": None}
    bg = asyncio.create_task(_run_execution(task_id, exec_id, prompt))
    _RUNNING[task_id]["task"] = bg
    return str(task_id), slug
```

(d) Pass `template_key` through the route:
```python
@router.post("/build", response_model=BuildResponse, status_code=201)
async def start_build(body: BuildRequest, user: CurrentUser = Depends(current_user)):
    """Fire a one-shot frontend-only build (optionally from a template)."""
    seed = body.name or body.description
    task_id, slug = await _create_and_spawn_build(
        user.email, seed, body.description, template_key=body.template_key,
    )
    return BuildResponse(task_id=task_id, slug=slug, status="running")
```

- [ ] **Step 4: Run to verify pass**

Run: `cd mcp-servers/tasks && DATABASE_URL="postgresql+asyncpg://nope/nope" python -m pytest tests/test_routes_aiuibuilder.py -q`
Expected: PASS (all). The shipped build tests (`test_build_happy_path`, `_busy_returns_429`,
status tests) still pass — they monkeypatch `_create_and_spawn_build` / `_load_owned_build`.

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/routes_aiuibuilder.py mcp-servers/tasks/tests/test_routes_aiuibuilder.py
git commit -m "feat(tasks): template_key on /api/aiuibuilder/build (rules + base-app copy)"
```

---

## Task 3: bot — `TasksClient.list_templates` + `template_key` on `start_build`

**Files:**
- Modify: `webhook-handler/clients/tasks.py`
- Test: `webhook-handler/tests/test_tasks_client.py`

- [ ] **Step 1: Write/Update failing tests**

In `tests/test_tasks_client.py`, **update** the existing `test_start_build_sends_only_user_email`
body assertion to include `template_key`, then append two tests:

Change in `test_start_build_sends_only_user_email`:
```python
        assert json.loads(req.content) == {
            "description": "a todo app", "name": None, "template_key": None}
```

Append:
```python
@pytest.mark.asyncio
async def test_start_build_includes_template_key(client):
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/api/aiuibuilder/build").mock(
            return_value=Response(201, json={"task_id": "t", "slug": "s", "status": "running"}))
        await client.start_build("a@x.com", "a designer site", template_key="portfolio")
        import json
        sent = json.loads(route.calls.last.request.content)
        assert sent["template_key"] == "portfolio"
        assert sent["description"] == "a designer site"


@pytest.mark.asyncio
async def test_list_templates_sends_only_user_email(client):
    with respx.mock(base_url=BASE) as mock:
        route = mock.get("/api/aiuibuilder/templates").mock(
            return_value=Response(200, json=[{"key": "portfolio", "label": "Portfolio",
                "emoji": "🎨", "description": "personal showcase", "has_app": True, "note": ""}]))
        result = await client.list_templates("a@x.com")
        assert result[0]["key"] == "portfolio"
        req = route.calls.last.request
        assert req.headers.get("x-user-email") == "a@x.com"
        assert "x-cron-secret" not in {k.lower() for k in req.headers}
```

- [ ] **Step 2: Run to verify failure**

Run: `cd webhook-handler && python -m pytest tests/test_tasks_client.py -q`
Expected: FAIL — `start_build` body lacks `template_key`; `list_templates` missing.

- [ ] **Step 3: Implement**

In `webhook-handler/clients/tasks.py`, update `start_build` and add `list_templates`:

```python
    async def start_build(
        self, user_email: str, description: str, name: str | None = None,
        template_key: str | None = None,
    ) -> dict[str, Any]:
        resp = await self._request(
            "POST", "/api/aiuibuilder/build", user_email,
            json={"description": description, "name": name, "template_key": template_key},
        )
        return resp.json()

    async def list_templates(self, user_email: str) -> list[dict[str, Any]]:
        resp = await self._request("GET", "/api/aiuibuilder/templates", user_email)
        return resp.json()
```

- [ ] **Step 4: Run to verify pass**

Run: `cd webhook-handler && python -m pytest tests/test_tasks_client.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/clients/tasks.py webhook-handler/tests/test_tasks_client.py
git commit -m "feat(bot): TasksClient.list_templates + template_key on start_build"
```

---

## Task 4: bot — `templates` action + template resolution in `build`

**Files:**
- Modify: `webhook-handler/handlers/commands.py`
- Test: `webhook-handler/tests/test_aiuibuilder_build.py`

- [ ] **Step 1: Update existing build tests + write new ones**

In `tests/test_aiuibuilder_build.py`, the `build` branch now fetches the catalog. **Add
`tc.list_templates = AsyncMock(return_value=[])` to every existing test whose `tc` reaches the
build branch** (`test_build_missing_description_shows_usage`, `test_build_happy_path_starts_and_acks`,
`test_build_unquoted_description_works`, `test_build_429_says_already_running`). With an empty
catalog, the first word never matches → template-less → those assertions hold unchanged.

**ALSO update the Layer-2 e2e** `webhook-handler/tests/test_discord_e2e_local.py::test_signed_aiuibuilder_build_reaches_start_build`:
it drives the real `build` branch through a real `TasksClient` against respx, so the new
`list_templates` call hits an unmocked URL → `respx.AllMockedAssertionError` (an `AssertionError`,
NOT a `TasksAPIError`, so it is NOT caught by the branch's `except TasksAPIError`) → the test
fails. Add a templates stub inside that test's `respx.mock(...)` block, alongside the existing
build/status/discord mocks:
```python
                mock.get(f"{settings.tasks_url}/api/aiuibuilder/templates").mock(
                    return_value=Response(200, json=[]))
```
(Empty catalog → the `build "a todo app"` interaction stays template-less, so the test's
`start_build`-reached + X-User-Email assertions are unchanged.)

Then append:

```python
@pytest.mark.asyncio
async def test_templates_action_lists():
    captured = []
    tc = MagicMock()
    tc.list_templates = AsyncMock(return_value=[
        {"key": "portfolio", "label": "Portfolio", "emoji": "🎨",
         "description": "personal showcase", "has_app": True, "note": ""},
        {"key": "crud", "label": "CRUD app", "emoji": "📝",
         "description": "manage records", "has_app": True, "note": "saves in your browser"},
    ])
    await _router({"100": "a@x.com"}, tc)._handle_aiuibuilder(_ctx("100", "templates", captured))
    reply = captured[-1]
    assert "portfolio" in reply and "crud" in reply
    assert "saves in your browser" in reply


@pytest.mark.asyncio
async def test_build_with_known_template_key(monkeypatch):
    captured = []
    tc = MagicMock()
    tc.list_templates = AsyncMock(return_value=[
        {"key": "portfolio", "label": "Portfolio", "emoji": "🎨",
         "description": "x", "has_app": True, "note": ""}])
    tc.start_build = AsyncMock(return_value={"task_id": "t1", "slug": "portfolio-a1b2", "status": "running"})
    monkeypatch.setattr(CommandRouter, "_watch_build",
                        lambda self, ctx, email, task_id, slug: _noop())
    await _router({"100": "a@x.com"}, tc)._handle_aiuibuilder(
        _ctx("100", "build portfolio a UX designer named Maya", captured, notify=None))
    # template_key resolved + description is the remainder after the key
    assert tc.start_build.call_args.kwargs["template_key"] == "portfolio"
    assert tc.start_build.call_args.args[1] == "a UX designer named Maya"
    assert any("Building" in m for m in captured)


@pytest.mark.asyncio
async def test_build_unknown_first_word_is_template_less():
    captured = []
    tc = MagicMock()
    tc.list_templates = AsyncMock(return_value=[
        {"key": "portfolio", "label": "Portfolio", "emoji": "🎨",
         "description": "x", "has_app": True, "note": ""}])
    tc.start_build = AsyncMock(return_value={"task_id": "t1", "slug": "s", "status": "running"})
    await _router({"100": "a@x.com"}, tc)._handle_aiuibuilder(
        _ctx("100", "build a kanban board for my team", captured, notify=None))
    assert tc.start_build.call_args.kwargs["template_key"] is None
    assert tc.start_build.call_args.args[1] == "a kanban board for my team"


@pytest.mark.asyncio
async def test_build_catalog_failure_falls_back_template_less():
    captured = []
    tc = MagicMock()
    tc.list_templates = AsyncMock(side_effect=TasksAPIError(0, "down"))
    tc.start_build = AsyncMock(return_value={"task_id": "t1", "slug": "s", "status": "running"})
    await _router({"100": "a@x.com"}, tc)._handle_aiuibuilder(
        _ctx("100", "build portfolio something", captured, notify=None))
    # Catalog down → can't recognize 'portfolio' → template-less, whole text is the description.
    assert tc.start_build.call_args.kwargs["template_key"] is None
    assert tc.start_build.call_args.args[1] == "portfolio something"


@pytest.mark.asyncio
async def test_build_key_only_synthesizes_description():
    captured = []
    tc = MagicMock()
    tc.list_templates = AsyncMock(return_value=[
        {"key": "portfolio", "label": "Portfolio", "emoji": "🎨",
         "description": "x", "has_app": True, "note": ""}])
    tc.start_build = AsyncMock(return_value={"task_id": "t1", "slug": "s", "status": "running"})
    await _router({"100": "a@x.com"}, tc)._handle_aiuibuilder(
        _ctx("100", "build portfolio", captured, notify=None))
    assert tc.start_build.call_args.kwargs["template_key"] == "portfolio"
    assert tc.start_build.call_args.args[1] == "a Portfolio"
```

Add this helper near the top of the test file (used by the monkeypatched `_watch_build`):
```python
async def _noop():
    return None
```

- [ ] **Step 2: Run to verify failure**

Run: `cd webhook-handler && python -m pytest tests/test_aiuibuilder_build.py -q`
Expected: FAIL — no `templates` action; `build` doesn't resolve a template key / pass `template_key`.

- [ ] **Step 3: Implement the `templates` action + `build` resolution**

In `handlers/commands.py` `_handle_aiuibuilder`, add a `templates` branch BEFORE the `build`
branch (after the `action`/`remainder` split):

```python
        if action == "templates":
            try:
                catalog = await self._tasks_client.list_templates(email)
            except TasksAPIError as e:
                await ctx.respond(self._format_build_error(e))
                return
            if not catalog:
                await ctx.respond("No templates available right now.")
                return
            lines = ["**App Builder templates** — `aiui aiuibuilder build <template> <description>`"]
            for t in catalog:
                note = f" — {t['note']}" if t.get("note") else ""
                lines.append(f"`{t['key']}` — {t['label']}: {t['description']}{note}")
            reply = "\n".join(lines)
            if len(reply) > 1990:
                reply = reply[:1980] + "\n… +more"
            await ctx.respond(reply)
            return
```

Replace the existing `build` branch body with template resolution:

```python
        if action == "build":
            # Resolve an optional leading template key from the RAW remainder,
            # before quote-stripping, so `build portfolio "a designer"` works.
            rem = (remainder or "").strip()
            sub = rem.split(None, 1)
            first = (sub[0] if sub else "").lower()
            after = sub[1] if len(sub) > 1 else ""

            # Catalog lets us recognize template keys; resilient — a failure
            # just means a template-less build (the user still gets an app).
            label_by_key: dict[str, str] = {}
            try:
                label_by_key = {t["key"]: t["label"]
                                for t in await self._tasks_client.list_templates(email)}
            except TasksAPIError:
                label_by_key = {}

            if first in label_by_key:
                template_key = first
                description = after.strip().strip('"').strip()
                if not description:
                    description = f"a {label_by_key[first]}"
            else:
                template_key = None
                description = rem.strip('"').strip()

            if not description:
                await ctx.respond(
                    'Usage: `aiuibuilder build [template] <description>` — e.g. '
                    '`aiuibuilder build portfolio a UX designer named Maya`. '
                    'See `aiuibuilder templates`.'
                )
                return
            try:
                result = await self._tasks_client.start_build(
                    email, description, template_key=template_key)
            except TasksAPIError as e:
                await ctx.respond(self._format_build_error(e))
                return
            slug = result["slug"]
            task_id = result["task_id"]
            tnote = f" (from the {label_by_key[template_key]} template)" if template_key else ""
            await ctx.respond(
                f"Building `{slug}`{tnote} … I'll post the link here when it's ready "
                "(usually a few minutes)."
            )
            if ctx.notify_channel is not None:
                watcher = asyncio.create_task(self._watch_build(ctx, email, task_id, slug))
                self._background_tasks.add(watcher)
                watcher.add_done_callback(self._background_tasks.discard)
            return
```

Update the usage `else` line and `_handle_help`:
- usage: `"Usage: `/aiui aiuibuilder <build|templates|list|status|open> [args]`"`
- help: `"`/aiui aiuibuilder <build|templates|list|status|open>` — Build (optionally from a template) & manage your apps\n"`

- [ ] **Step 4: Run to verify pass (+ no regressions)**

Run: `cd webhook-handler && python -m pytest tests/test_aiuibuilder_build.py tests/test_aiuibuilder_handler.py tests/test_discord_e2e_local.py -q`
Expected: PASS (all — incl. the e2e, which now stubs the templates endpoint). Then the FULL
suite: `python -m pytest tests/ -q` — all pass. If `test_discord_e2e_local.py` fails with an
`AllMockedAssertionError`/`AssertionError` about an unmocked `/api/aiuibuilder/templates`, the
templates stub from Step 1 is missing — add it.

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/handlers/commands.py webhook-handler/tests/test_aiuibuilder_build.py
git commit -m "feat(bot): /aiui aiuibuilder templates + template resolution in build"
```

---

## Task 5: live catalog smoke + deploy + real template build

**Files:**
- Modify: `scripts/e2e_backend_smoke.py`

- [ ] **Step 1: Add a catalog check to the smoke**

Append to `scripts/e2e_backend_smoke.py` `main()`:
```python
        print("\n=== 9) GET /api/aiuibuilder/templates (catalog, user-scoped) ===")
        r = await c.get(f"{BASE}/api/aiuibuilder/templates", headers={"X-User-Email": EMAIL})
        body = r.json() if r.status_code == 200 else []
        keys = [t.get("key") for t in body] if isinstance(body, list) else []
        print(f"  status={r.status_code} count={len(keys)} has_portfolio={'portfolio' in keys} "
              f"excludes_blank={'blank' not in keys}")

        print("\n=== 10) same WITHOUT X-User-Email should 401 ===")
        r = await c.get(f"{BASE}/api/aiuibuilder/templates")
        print(f"  status={r.status_code} (expect 401)")
```

- [ ] **Step 2: Full local suites green**

```bash
cd webhook-handler && python -m pytest tests/ -q
cd ../mcp-servers/tasks && DATABASE_URL="postgresql+asyncpg://nope/nope" python -m pytest tests/test_routes_aiuibuilder.py -q
```
Expected: all PASS.

- [ ] **Step 3: Deploy (Workflow A — individual SCP + rebuild both services)**

```bash
SRV=root@46.224.193.25
DST=/root/proxy-server
scp mcp-servers/tasks/routes_aiuibuilder.py  $SRV:$DST/mcp-servers/tasks/routes_aiuibuilder.py
scp webhook-handler/clients/tasks.py         $SRV:$DST/webhook-handler/clients/tasks.py
scp webhook-handler/handlers/commands.py     $SRV:$DST/webhook-handler/handlers/commands.py
scp scripts/e2e_backend_smoke.py             $SRV:$DST/scripts/e2e_backend_smoke.py
ssh $SRV "cd $DST && docker compose -f docker-compose.unified.yml up -d --build tasks webhook-handler"
```

- [ ] **Step 4: Health + live smoke**

```bash
ssh root@46.224.193.25 "docker exec tasks curl -sf http://localhost:8210/healthz && echo OK"
ssh root@46.224.193.25 "docker exec -i webhook-handler python - < /dev/stdin" < scripts/e2e_backend_smoke.py
```
Expected: `/healthz` OK; step 9 → 200 with portfolio present and blank excluded; step 10 → 401.

- [ ] **Step 5: Live template-build e2e (real agent, throwaway email, then clean up)**

Drive a real template build through the deployed API exactly as the bot does (X-User-Email
only, `template_key="portfolio"`), poll to completion, confirm assigned slug == final slug and
the preview serves, then admin-delete the throwaway project. (Same harness as the build
feature's live e2e; one build slot, ~1-3 min.)

- [ ] **Step 6: Real Discord verification**

```
/aiui aiuibuilder templates
/aiui aiuibuilder build portfolio a UX designer named Maya, 4 case studies, serif headers
```
Expect the catalog list, then "Building `portfolio-xxxx` (from the Portfolio template) …" and a
preview link a few minutes later.

- [ ] **Step 7: Commit + push**

```bash
git add scripts/e2e_backend_smoke.py
git commit -m "test(scripts): live smoke for aiuibuilder template catalog"
git push fork HEAD:main
```

> Do NOT push `.env` or secrets. Only the files above.

---

## Definition of Done

- [ ] `GET /api/aiuibuilder/templates` (user-scoped) lists the real templates, excludes blank/custom, flags auth + db-backed notes, leaks no rules.
- [ ] `POST /api/aiuibuilder/build` accepts `template_key`: valid key injects rules + copies the base app; invalid key → 422; omitted → template-less unchanged. Storage forced "none" (no Supabase gate).
- [ ] Bot `templates` lists; `build <template> <desc>` resolves the key (unknown → template-less; catalog down → template-less; key-only → synthesized desc).
- [ ] X-User-Email only end-to-end (asserted). No regressions in the shipped build/list/status/open tests.
- [ ] All local tests green. Deployed; `/healthz` + catalog smoke green; one real template build produced a working preview.
- [ ] Pushed to `fork main`. No secrets.
