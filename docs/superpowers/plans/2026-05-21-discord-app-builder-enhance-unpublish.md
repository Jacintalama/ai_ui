# Discord App Builder — Enhance + Unpublish — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an **Enhance** button (popup → AI edits the existing app → updated preview) and an **Unpublish** button to the Discord app-builder channel, mirroring the publish feature already shipped.

**Architecture:** Two new user-scoped endpoints on the tasks service (`DELETE /api/aiuibuilder/{slug}/publish` for unpublish; `POST /api/aiuibuilder/{slug}/enhance` for enhance) reusing the existing unpublish/enhance machinery. On the webhook-handler side, add Enhance/Unpublish buttons + an Enhance modal, two `TasksClient` methods, `run_panel_enhance`/`run_panel_unpublish`, and dispatch — all mirroring the publish button/modal/watcher pattern.

**Tech Stack:** Python 3, FastAPI, httpx, pytest (`asyncio_mode = auto`), Discord HTTP API v10. webhook-handler tests run locally in `webhook-handler/.venv`; tasks-service DB tests need PostgreSQL (Postgres env / post-deploy), not the local Windows box.

---

## File Structure
- **Modify** `mcp-servers/tasks/routes_projects.py` — extract `_unpublish_slug`; admin route delegates.
- **Modify** `mcp-servers/tasks/routes_aiuibuilder.py` — user-scoped unpublish (DELETE) + enhance (POST) routes + `_create_and_spawn_enhance`.
- **Create** `mcp-servers/tasks/tests/test_routes_aiuibuilder_unpublish.py` — DB test (Postgres env).
- **Modify** `webhook-handler/clients/tasks.py` — `unpublish_app`, `enhance_app`.
- **Modify** `webhook-handler/clients/discord.py` — `edit_original` optional `components`.
- **Modify** `webhook-handler/handlers/app_builder_panel.py` — Enhance button on ready; `build_published_components`; `build_enhance_modal`; prefixes + parsers.
- **Modify** `webhook-handler/handlers/commands.py` — `CommandContext.on_published`; `run_panel_enhance`, `run_panel_unpublish`, error mappers; publish posts published-buttons.
- **Modify** `webhook-handler/handlers/discord_commands.py` — dispatch enhance/unpublish buttons + enhance modal; set `on_published`.
- Tests: `test_app_builder_panel.py`, `test_tasks_client.py`, `test_panel_build.py`, `test_app_builder_interactions.py`.

**webhook-handler test command (from `webhook-handler/`):**
`& "C:\Users\Acer Philippines\Desktop\Lukas Project\ai_ui\webhook-handler\.venv\Scripts\python.exe" -m pytest -q`
**tasks syntax check (from repo root):**
`& "C:\Users\Acer Philippines\Desktop\Lukas Project\ai_ui\webhook-handler\.venv\Scripts\python.exe" -m py_compile <files>`

---

## Task 1: Tasks — user-scoped Unpublish

**Files:** Modify `mcp-servers/tasks/routes_projects.py`, `mcp-servers/tasks/routes_aiuibuilder.py`; Create `mcp-servers/tasks/tests/test_routes_aiuibuilder_unpublish.py`.

> DB test needs Postgres — not runnable locally. `py_compile` all changed files; verify live after deploy.

- [ ] **Step 1: Extract `_unpublish_slug` in `routes_projects.py`.** Read the file; find `unpublish_app` (~line 1217). Add this helper immediately ABOVE the `@router.delete("/{slug}/publish", status_code=204)` decorator:

```python
async def _unpublish_slug(s, slug: str, email: str, *, is_admin: bool) -> None:
    """Core unpublish: owner-checked delete of the PublishedApp row. Idempotent
    (no row → no-op). Shared by the admin route and the user-scoped aiuibuilder
    route."""
    _validate_slug(slug)
    if not await _user_can_see_project(s, slug, email):
        raise HTTPException(status_code=403, detail="Not a member of this project")
    await _require_role(s, slug, email, "owner", is_admin=is_admin)
    existing = (
        await s.execute(select(PublishedApp).where(PublishedApp.slug == slug))
    ).scalar_one_or_none()
    if existing is None:
        return None
    await s.delete(existing)
    await s.commit()
    return None
```

Replace the admin route body with:

```python
@router.delete("/{slug}/publish", status_code=204)
async def unpublish_app(slug: str, user: AdminUser = Depends(current_admin)):
    async with session() as s:
        await _unpublish_slug(s, slug, user.email, is_admin=user.is_admin)
    return None
```

- [ ] **Step 2: User-scoped route in `routes_aiuibuilder.py`.** Update the import line `from routes_projects import _publish_slug, PublishStatus` to also import `_unpublish_slug`:
```python
from routes_projects import _publish_slug, _unpublish_slug, PublishStatus
```
Add at the end of the file:
```python
@router.delete("/{slug}/publish", status_code=204)
async def unpublish_built_app(slug: str, user: CurrentUser = Depends(current_user)):
    """User-scoped unpublish for a Discord-built app (owner-only). Mirrors
    publish_built_app; reuses the shared _unpublish_slug core."""
    async with session() as s:
        await _unpublish_slug(s, slug, user.email, is_admin=False)
    return None
```

- [ ] **Step 3: DB test** `mcp-servers/tasks/tests/test_routes_aiuibuilder_unpublish.py`:
```python
"""User-scoped unpublish: DELETE /api/aiuibuilder/{slug}/publish (needs Postgres)."""
from cryptography.fernet import Fernet as _Fernet
_AIUI_TEST_KEY = _Fernet.generate_key().decode()
import os
os.environ.setdefault("AIUI_FERNET_KEY", _AIUI_TEST_KEY)

import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from main import app
from models import PublishedApp, TaskItem


@pytest.fixture
def transport():
    return ASGITransport(app=app)


async def _owner_with_published(db_session, slug, email):
    db_session.add(TaskItem(
        meeting_id=uuid.uuid4(), action_type="BUILD",
        assignee_name=email.split("@")[0], assignee_email=email,
        description="x", priority="NICE_TO_HAVE", status="completed",
        mode="ai", max_attempts=3, built_app_slug=slug,
    ))
    db_session.add(PublishedApp(slug=slug, published_by=email, public_host=f"{slug}.example.com"))
    await db_session.commit()


async def test_owner_can_unpublish(db_session, transport):
    await _owner_with_published(db_session, "alpha", "alice@x.com")
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.delete("/api/aiuibuilder/alpha/publish", headers={"X-User-Email": "alice@x.com"})
    assert r.status_code == 204
    row = (await db_session.execute(select(PublishedApp).where(PublishedApp.slug == "alpha"))).scalar_one_or_none()
    assert row is None


async def test_unpublish_idempotent_when_not_published(db_session, transport):
    db_session.add(TaskItem(
        meeting_id=uuid.uuid4(), action_type="BUILD", assignee_name="a",
        assignee_email="alice@x.com", description="x", priority="NICE_TO_HAVE",
        status="completed", mode="ai", max_attempts=3, built_app_slug="alpha",
    ))
    await db_session.commit()
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.delete("/api/aiuibuilder/alpha/publish", headers={"X-User-Email": "alice@x.com"})
    assert r.status_code == 204


async def test_non_owner_cannot_unpublish(db_session, transport):
    await _owner_with_published(db_session, "alpha", "alice@x.com")
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.delete("/api/aiuibuilder/alpha/publish", headers={"X-User-Email": "mallory@x.com"})
    assert r.status_code == 403
    row = (await db_session.execute(select(PublishedApp).where(PublishedApp.slug == "alpha"))).scalar_one_or_none()
    assert row is not None  # still published
```

- [ ] **Step 4: Syntax check** (from repo root): `& "<venv python>" -m py_compile mcp-servers/tasks/routes_projects.py mcp-servers/tasks/routes_aiuibuilder.py mcp-servers/tasks/tests/test_routes_aiuibuilder_unpublish.py` → exit 0.
- [ ] **Step 5: Commit**
```bash
git add mcp-servers/tasks/routes_projects.py mcp-servers/tasks/routes_aiuibuilder.py mcp-servers/tasks/tests/test_routes_aiuibuilder_unpublish.py
git commit -m "feat(tasks): user-scoped unpublish endpoint for Discord apps

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Tasks — user-scoped Enhance

**Files:** Modify `mcp-servers/tasks/routes_aiuibuilder.py`.

> No standalone DB test (it spawns the agent); verified by the live enhance click after deploy. `py_compile` only.

- [ ] **Step 1: Add `_create_and_spawn_enhance` + the route in `routes_aiuibuilder.py`.** Read the file (note the existing `_create_and_spawn_build`, the `BuildResponse` model, imports of `session`, `select`, `text`, `uuid`, `TaskItem`, `TaskExecution`, `current_user`, `CurrentUser`, `HTTPException`). Add this request model near `BuildRequest`:
```python
class EnhanceRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
```
Add this function (mirrors `_create_and_spawn_build` but for an edit-in-place enhancement):
```python
async def _create_and_spawn_enhance(email: str, slug: str, prompt: str) -> tuple[str, str]:
    """Create an ENHANCE build task that edits apps/<slug>/ in place and spawn
    the agent. Reuses the executor's enhance path via the
    'Enhance apps/<slug>/: ' description prefix. One enhancement per app at a
    time (409 if one is already running). Returns (task_id, slug)."""
    from claude_executor import build_enhance_prompt
    from routes_execution import _RUNNING, _run_execution, _lookup_supabase_config
    from routes_projects import _require_role

    async with session() as s:
        # Find the app's most recent BUILD task (the enhance source).
        source = (await s.execute(
            select(TaskItem)
            .where(TaskItem.built_app_slug == slug, TaskItem.action_type == "BUILD")
            .order_by(TaskItem.created_at.desc())
            .limit(1)
        )).scalar_one_or_none()
        if source is None:
            raise HTTPException(status_code=404, detail="No app to enhance for that slug")

        # Editor/owner only (Discord builder is owner). is_admin=False.
        await _require_role(s, slug, email, "editor", is_admin=False)

        # Serialize check+insert per slug; reject a concurrent enhancement.
        await s.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"build:{slug}"},
        )
        in_flight = (await s.execute(
            select(TaskItem.id).where(
                TaskItem.built_app_slug == slug,
                TaskItem.status.in_(["running", "planning", "awaiting_input"]),
            ).limit(1)
        )).scalar_one_or_none()
        if in_flight:
            raise HTTPException(status_code=409, detail="An enhancement is already in progress")

        item = TaskItem(
            meeting_id=uuid.uuid4(),
            action_type="BUILD",
            assignee_name=email.split("@")[0],
            assignee_email=email,
            description=f"Enhance apps/{slug}/: {prompt.strip()[:400]}",
            priority="NICE_TO_HAVE",
            status="running",
            mode="ai",
            max_attempts=max(source.max_attempts or 1, 1),
            built_app_slug=slug,
            plan_status="approved",
        )
        s.add(item)
        await s.flush()
        execution = TaskExecution(task_id=item.id, status="running", log="")
        s.add(execution)
        await s.commit()
        await s.refresh(item)
        await s.refresh(execution)
        task_id, exec_id, max_attempts = item.id, execution.id, item.max_attempts
        supabase_url, has_db_uri = await _lookup_supabase_config(s, slug)

    prompt_text = build_enhance_prompt(
        slug=slug,
        user_request=prompt.strip(),
        attempt_count=0,
        max_attempts=max_attempts,
        supabase_url=supabase_url,
        has_db_uri=has_db_uri,
        user_email=email,
        attachments=None,
        selection_block="",
    )
    _RUNNING[task_id] = {"task": None, "proc": None}
    bg = asyncio.create_task(_run_execution(task_id, exec_id, prompt_text))
    _RUNNING[task_id]["task"] = bg
    return str(task_id), slug
```
Add the route at the end of the file:
```python
@router.post("/{slug}/enhance", response_model=BuildResponse, status_code=201)
async def enhance_built_app(slug: str, body: EnhanceRequest, user: CurrentUser = Depends(current_user)):
    """User-scoped enhance: edit an existing Discord-built app in place. Returns
    a BuildResponse so the Discord watcher can poll it like any build."""
    task_id, out_slug = await _create_and_spawn_enhance(user.email, slug, body.prompt)
    return BuildResponse(task_id=task_id, slug=out_slug, status="running")
```
(Confirm `asyncio` is imported at the top of the module — `_create_and_spawn_build` uses it, so it is.)

- [ ] **Step 2: Syntax check**: `& "<venv python>" -m py_compile mcp-servers/tasks/routes_aiuibuilder.py` → exit 0.
- [ ] **Step 3: Commit**
```bash
git add mcp-servers/tasks/routes_aiuibuilder.py
git commit -m "feat(tasks): user-scoped enhance endpoint (edit-in-place) for Discord apps

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: webhook-handler — buttons, published-components, enhance modal (pure)

**Files:** Modify `webhook-handler/handlers/app_builder_panel.py`; Test `webhook-handler/tests/test_app_builder_panel.py`.

- [ ] **Step 1: Append failing tests** to `test_app_builder_panel.py`:
```python
from handlers.app_builder_panel import (
    build_published_components, build_enhance_modal,
    is_enhance_button, slug_from_enhance_button,
    is_unpublish_button, slug_from_unpublish_button,
    is_enhance_modal, slug_from_enhance_modal,
    ENHANCE_PREFIX, UNPUBLISH_PREFIX, ENHANCE_MODAL_PREFIX,
    STYLE_PRIMARY, STYLE_DANGER, STYLE_LINK, ACTION_ROW, TEXT_INPUT,
)


def test_ready_components_now_include_enhance():
    rows = build_ready_components("slug-1", "https://x/preview/slug-1/")
    ids = [c.get("custom_id") for c in rows[0]["components"]]
    assert f"{ENHANCE_PREFIX}slug-1" in ids
    assert f"{PUBLISH_PREFIX}slug-1" in ids


def test_published_components_have_enhance_and_unpublish_and_live_link():
    rows = build_published_components("slug-1", "https://slug-1.ai-ui.coolestdomain.win/")
    btns = rows[0]["components"]
    ids = [b.get("custom_id") for b in btns]
    assert f"{ENHANCE_PREFIX}slug-1" in ids
    assert f"{UNPUBLISH_PREFIX}slug-1" in ids
    link = [b for b in btns if b["style"] == STYLE_LINK][0]
    assert link["url"] == "https://slug-1.ai-ui.coolestdomain.win/"
    assert "custom_id" not in link
    unpub = [b for b in btns if b.get("custom_id") == f"{UNPUBLISH_PREFIX}slug-1"][0]
    assert unpub["style"] == STYLE_DANGER


def test_enhance_modal_shape():
    data = build_enhance_modal("slug-1")
    assert data["custom_id"] == f"{ENHANCE_MODAL_PREFIX}slug-1"
    inp = data["components"][0]["components"][0]
    assert inp["type"] == TEXT_INPUT
    assert inp["custom_id"] == "change"
    assert inp["required"] is True


def test_new_parsers():
    assert is_enhance_button(f"{ENHANCE_PREFIX}s") and slug_from_enhance_button(f"{ENHANCE_PREFIX}s") == "s"
    assert is_unpublish_button(f"{UNPUBLISH_PREFIX}s") and slug_from_unpublish_button(f"{UNPUBLISH_PREFIX}s") == "s"
    assert is_enhance_modal(f"{ENHANCE_MODAL_PREFIX}s") and slug_from_enhance_modal(f"{ENHANCE_MODAL_PREFIX}s") == "s"
    import pytest
    for fn, pref in [(slug_from_enhance_button, ENHANCE_PREFIX),
                     (slug_from_unpublish_button, UNPUBLISH_PREFIX),
                     (slug_from_enhance_modal, ENHANCE_MODAL_PREFIX)]:
        with pytest.raises(ValueError):
            fn(pref)  # bare prefix, empty slug
```

- [ ] **Step 2: Run, confirm FAIL** (ImportError).

- [ ] **Step 3: Implement** in `app_builder_panel.py`. Add `STYLE_DANGER = 4` after `STYLE_SUCCESS`. Add the new prefixes after `PUBLISH_PREFIX`:
```python
ENHANCE_PREFIX = "aiuibuild:enhance:"
UNPUBLISH_PREFIX = "aiuibuild:unpublish:"
ENHANCE_MODAL_PREFIX = "aiuibuild:enhancemodal:"
```
Update `build_ready_components` to add an Enhance button (after the Publish button, before the preview link):
```python
def build_ready_components(slug: str, preview_url: str = "") -> list[dict]:
    """Action row for the build-ready message: green Publish + blurple Enhance,
    plus an 'Open preview' link button when preview_url is set."""
    buttons: list[dict] = [
        _button("\U0001f7e2 Publish", f"{PUBLISH_PREFIX}{slug}", STYLE_SUCCESS),
        _button("✏️ Enhance", f"{ENHANCE_PREFIX}{slug}", STYLE_PRIMARY),
    ]
    if preview_url:
        buttons.append({"type": BUTTON, "style": STYLE_LINK,
                        "label": "\U0001f517 Open preview", "url": preview_url})
    return [{"type": ACTION_ROW, "components": buttons}]
```
Append the new builders + parsers:
```python
def build_published_components(slug: str, public_url: str = "") -> list[dict]:
    """Buttons on the 'Published!' message: blurple Enhance + red Unpublish,
    plus an 'Open live' link button."""
    buttons: list[dict] = [
        _button("✏️ Enhance", f"{ENHANCE_PREFIX}{slug}", STYLE_PRIMARY),
        _button("\U0001f50c Unpublish", f"{UNPUBLISH_PREFIX}{slug}", STYLE_DANGER),
    ]
    if public_url:
        buttons.append({"type": BUTTON, "style": STYLE_LINK,
                        "label": "\U0001f517 Open live", "url": public_url})
    return [{"type": ACTION_ROW, "components": buttons}]


def build_enhance_modal(slug: str) -> dict:
    """Type-9 MODAL data: a paragraph 'What do you want to change?' field."""
    return {
        "title": "Enhance your app"[:45],
        "custom_id": f"{ENHANCE_MODAL_PREFIX}{slug}",
        "components": [{
            "type": ACTION_ROW,
            "components": [{
                "type": TEXT_INPUT,
                "custom_id": "change",
                "label": "What do you want to change?",
                "style": TEXT_PARAGRAPH,
                "required": True,
                "max_length": 2000,
                "placeholder": "e.g. make the header green and add an About section",
            }],
        }],
    }


def _slug_after(custom_id: str, prefix: str) -> str:
    if not custom_id.startswith(prefix):
        raise ValueError(f"not a {prefix!r} custom_id: {custom_id!r}")
    slug = custom_id[len(prefix):]
    if not slug:
        raise ValueError(f"{prefix!r} custom_id has no slug: {custom_id!r}")
    return slug


def is_enhance_button(custom_id: str) -> bool:
    return custom_id.startswith(ENHANCE_PREFIX)


def slug_from_enhance_button(custom_id: str) -> str:
    return _slug_after(custom_id, ENHANCE_PREFIX)


def is_unpublish_button(custom_id: str) -> bool:
    return custom_id.startswith(UNPUBLISH_PREFIX)


def slug_from_unpublish_button(custom_id: str) -> str:
    return _slug_after(custom_id, UNPUBLISH_PREFIX)


def is_enhance_modal(custom_id: str) -> bool:
    return custom_id.startswith(ENHANCE_MODAL_PREFIX)


def slug_from_enhance_modal(custom_id: str) -> str:
    return _slug_after(custom_id, ENHANCE_MODAL_PREFIX)
```

- [ ] **Step 4: Run** `tests/test_app_builder_panel.py -q` → pass; then full suite `-q` → green.
- [ ] **Step 5: Commit**
```bash
git add webhook-handler/handlers/app_builder_panel.py webhook-handler/tests/test_app_builder_panel.py
git commit -m "feat(discord): enhance/unpublish buttons, published-components, enhance modal

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: webhook-handler — TasksClient methods + edit_original components

**Files:** Modify `webhook-handler/clients/tasks.py`, `webhook-handler/clients/discord.py`; Test `webhook-handler/tests/test_tasks_client.py`.

- [ ] **Step 1: Append failing tests** to `test_tasks_client.py` (uses the file's `client` fixture, `BASE`, `Response`, `respx`):
```python
@pytest.mark.asyncio
async def test_unpublish_app_deletes(client):
    with respx.mock(base_url=BASE) as mock:
        route = mock.delete("/api/aiuibuilder/slug-1/publish").mock(return_value=Response(204))
        ok = await client.unpublish_app("alice@x.com", "slug-1")
    assert ok is True
    req = route.calls.last.request
    assert req.headers.get("x-user-email") == "alice@x.com"
    assert "x-cron-secret" not in {k.lower() for k in req.headers}


@pytest.mark.asyncio
async def test_enhance_app_posts(client):
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/api/aiuibuilder/slug-1/enhance").mock(
            return_value=Response(201, json={"task_id": "t1", "slug": "slug-1", "status": "running"})
        )
        out = await client.enhance_app("alice@x.com", "slug-1", "make header green")
    assert out["task_id"] == "t1"
    req = route.calls.last.request
    assert req.headers.get("x-user-email") == "alice@x.com"
    assert "x-cron-secret" not in {k.lower() for k in req.headers}
    import json as _j
    assert _j.loads(req.content)["prompt"] == "make header green"
```

- [ ] **Step 2: Run, confirm FAIL** (no `unpublish_app`/`enhance_app`).

- [ ] **Step 3a: Implement in `clients/tasks.py`** (after `publish_app`; `_request` returns the httpx `Response`):
```python
    async def unpublish_app(self, user_email: str, slug: str) -> bool:
        await self._request("DELETE", f"/api/aiuibuilder/{slug}/publish", user_email)
        return True

    async def enhance_app(self, user_email: str, slug: str, prompt: str) -> dict[str, Any]:
        resp = await self._request(
            "POST", f"/api/aiuibuilder/{slug}/enhance", user_email,
            json={"prompt": prompt},
        )
        return resp.json()
```

- [ ] **Step 3b: `edit_original` optional components in `clients/discord.py`.** Read the file; replace the `edit_original` method so it accepts components:
```python
    async def edit_original(self, interaction_token: str, content: str,
                            components: list | None = None) -> bool:
        """Edit the original deferred response message. Optionally attaches
        message `components` (e.g. Enhance/Unpublish buttons)."""
        content = content[:2000]
        url = (
            f"{DISCORD_API_BASE}/webhooks/{self.application_id}"
            f"/{interaction_token}/messages/@original"
        )
        body: dict = {"content": content}
        if components is not None:
            body["components"] = components
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.patch(url, json=body)
                if response.status_code in (200, 204):
                    logger.info("Discord original message edited")
                    return True
                logger.error(f"Discord edit error: {response.status_code} {response.text}")
                return False
        except Exception as e:
            logger.error(f"Error editing Discord message: {e}")
            return False
```

- [ ] **Step 4: Run** `tests/test_tasks_client.py -q` → pass; full suite green.
- [ ] **Step 5: Commit**
```bash
git add webhook-handler/clients/tasks.py webhook-handler/clients/discord.py webhook-handler/tests/test_tasks_client.py
git commit -m "feat(discord): TasksClient.unpublish_app/enhance_app; edit_original components

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: webhook-handler — router methods (enhance, unpublish, published buttons)

**Files:** Modify `webhook-handler/handlers/commands.py`; Test `webhook-handler/tests/test_panel_build.py`.

- [ ] **Step 1: Append failing tests** to `test_panel_build.py` (reuses `_ctx`, `_router`, `AsyncMock`, `MagicMock`, `TasksAPIError`, `asyncio`):
```python
@pytest.mark.asyncio
async def test_enhance_unmapped_user_rejected():
    captured = []
    await _router({}, MagicMock()).run_panel_enhance(_ctx("9", captured), "slug-1", "change")
    assert any("isn't linked" in m for m in captured)


@pytest.mark.asyncio
async def test_enhance_happy_path_starts_watcher(monkeypatch):
    watched = {}
    async def fake_watch(self, ctx, email, task_id, slug):
        watched["args"] = (email, task_id, slug)
    monkeypatch.setattr(CommandRouter, "_watch_build", fake_watch)
    captured = []
    tc = MagicMock()
    tc.enhance_app = AsyncMock(return_value={"task_id": "t9", "slug": "slug-1", "status": "running"})
    async def notify(m): pass
    await _router({"100": "a@x.com"}, tc).run_panel_enhance(_ctx("100", captured, notify=notify), "slug-1", "make it blue")
    tc.enhance_app.assert_awaited_once_with("a@x.com", "slug-1", "make it blue")
    await asyncio.sleep(0)
    assert watched.get("args") == ("a@x.com", "t9", "slug-1")
    assert any("pdating" in m or "nhanc" in m for m in captured)  # "Updating"/"Enhancing"


@pytest.mark.asyncio
async def test_enhance_conflict_409():
    captured = []
    tc = MagicMock(); tc.enhance_app = AsyncMock(side_effect=TasksAPIError(409, "busy"))
    await _router({"100": "a@x.com"}, tc).run_panel_enhance(_ctx("100", captured), "slug-1", "x")
    assert any("already" in m.lower() for m in captured)


@pytest.mark.asyncio
async def test_unpublish_happy_path():
    captured = []
    tc = MagicMock(); tc.unpublish_app = AsyncMock(return_value=True)
    await _router({"100": "a@x.com"}, tc).run_panel_unpublish(_ctx("100", captured), "slug-1")
    tc.unpublish_app.assert_awaited_once_with("a@x.com", "slug-1")
    assert any("offline" in m.lower() for m in captured)


@pytest.mark.asyncio
async def test_unpublish_not_owner_403():
    captured = []
    tc = MagicMock(); tc.unpublish_app = AsyncMock(side_effect=TasksAPIError(403, "no"))
    await _router({"100": "a@x.com"}, tc).run_panel_unpublish(_ctx("100", captured), "slug-1")
    assert any("owner" in m.lower() for m in captured)
```

- [ ] **Step 2: Run, confirm FAIL** (`run_panel_enhance`/`run_panel_unpublish` missing).

- [ ] **Step 3a: Add `on_published` to `CommandContext`** (after `notify_channel_rich`):
```python
    notify_channel_rich: Optional[Callable[[str, str, str], Awaitable[None]]] = None
    # (public_url) -> edit the publish reply to show the live URL + Enhance/Unpublish
    # buttons. Set by the Discord layer; None elsewhere.
    on_published: Optional[Callable[[str], Awaitable[None]]] = None
```

- [ ] **Step 3b: Add the two methods** in `commands.py` after `run_panel_publish` (before `_format_tasks_error`):
```python
    async def run_panel_enhance(self, ctx: CommandContext, slug: str, prompt: str) -> None:
        """App Builder Enhance: edit an existing app from a typed change, then
        watch it like a build and post the updated preview."""
        email = self._discord_user_email_map.get(ctx.user_id)
        if not email:
            await ctx.respond("Your Discord account isn't linked. Ask Lukas to add you.")
            return
        prompt = (prompt or "").strip()
        if not prompt:
            await ctx.respond("Tell me what to change.")
            return
        try:
            result = await self._tasks_client.enhance_app(email, slug, prompt)
        except TasksAPIError as e:
            await ctx.respond(self._format_enhance_error(e))
            return
        task_id = result["task_id"]
        await ctx.respond(
            f"Updating `{slug}` … I'll post the new preview here when it's ready."
        )
        if ctx.notify_channel is not None:
            watcher = asyncio.create_task(self._watch_build(ctx, email, task_id, slug))
            self._background_tasks.add(watcher)
            watcher.add_done_callback(self._background_tasks.discard)

    async def run_panel_unpublish(self, ctx: CommandContext, slug: str) -> None:
        """App Builder Unpublish: take a live app offline."""
        email = self._discord_user_email_map.get(ctx.user_id)
        if not email:
            await ctx.respond("Your Discord account isn't linked. Ask Lukas to add you.")
            return
        try:
            await self._tasks_client.unpublish_app(email, slug)
        except TasksAPIError as e:
            await ctx.respond(self._format_unpublish_error(e))
            return
        await ctx.respond(f"`{slug}` is offline now (unpublished).")

    def _format_enhance_error(self, e: TasksAPIError) -> str:
        if e.status == 0:
            return "Tasks service unreachable, try again."
        if e.status == 409:
            return "An update is already in progress — try again in a minute."
        if e.status in (401, 403):
            return "Only the app's owner or an editor can change it."
        if e.status == 404:
            return "No app found to enhance (build it first)."
        if e.status in (400, 422):
            return "Couldn't start the update — check your description."
        return f"Couldn't start the update (error {e.status})."

    def _format_unpublish_error(self, e: TasksAPIError) -> str:
        if e.status == 0:
            return "Tasks service unreachable, try again."
        if e.status in (401, 403):
            return "Only the app's owner can unpublish it."
        if e.status == 404:
            return "It's not live right now."
        return f"Couldn't unpublish (error {e.status})."
```

- [ ] **Step 3c: Use `on_published` in `run_panel_publish`.** Find the success line in `run_panel_publish`:
```python
        url = (result.get("public_url") or "").strip()
        url_part = f" Live at {url}" if url else ""
        await ctx.respond(f"\U0001f389 Published!{url_part}")
```
Replace with:
```python
        url = (result.get("public_url") or "").strip()
        if ctx.on_published is not None and url:
            try:
                await ctx.on_published(url)
                return
            except Exception as exc:  # noqa: BLE001
                logger.error("on_published failed slug=%s: %s", slug, exc)
        url_part = f" Live at {url}" if url else ""
        await ctx.respond(f"\U0001f389 Published!{url_part}")
```

- [ ] **Step 4: Run** `tests/test_panel_build.py -q` → pass; full suite green.
- [ ] **Step 5: Commit**
```bash
git add webhook-handler/handlers/commands.py webhook-handler/tests/test_panel_build.py
git commit -m "feat(discord): run_panel_enhance/unpublish + published-message buttons hook

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: webhook-handler — dispatch enhance/unpublish buttons + enhance modal

**Files:** Modify `webhook-handler/handlers/discord_commands.py`; Test `webhook-handler/tests/test_app_builder_interactions.py`.

- [ ] **Step 1: Append failing tests** to `test_app_builder_interactions.py` (reuses `_handler`, `asyncio`, `MagicMock`):
```python
from handlers.app_builder_panel import ENHANCE_PREFIX, UNPUBLISH_PREFIX, ENHANCE_MODAL_PREFIX


@pytest.mark.asyncio
async def test_enhance_button_opens_modal():
    handler = _handler(MagicMock())
    payload = {"type": 3, "id": "i", "token": "t",
               "data": {"custom_id": f"{ENHANCE_PREFIX}slug-1"},
               "member": {"user": {"id": "100", "username": "u"}}, "channel_id": "c"}
    resp = await handler.handle_interaction(payload)
    assert resp["type"] == 9
    assert resp["data"]["custom_id"] == f"{ENHANCE_MODAL_PREFIX}slug-1"


@pytest.mark.asyncio
async def test_unpublish_button_routes():
    captured = {}
    async def fake_unpub(ctx, slug): captured["slug"] = slug
    router = MagicMock(); router.run_panel_unpublish = fake_unpub
    handler = _handler(router)
    payload = {"type": 3, "id": "i", "token": "tok",
               "data": {"custom_id": f"{UNPUBLISH_PREFIX}slug-1"},
               "member": {"user": {"id": "100", "username": "u"}}, "channel_id": "c"}
    resp = await handler.handle_interaction(payload)
    assert resp["type"] == 5
    await asyncio.sleep(0)
    assert captured["slug"] == "slug-1"


@pytest.mark.asyncio
async def test_enhance_modal_submit_routes():
    captured = {}
    async def fake_enh(ctx, slug, prompt): captured.update(slug=slug, prompt=prompt)
    router = MagicMock(); router.run_panel_enhance = fake_enh
    handler = _handler(router)
    payload = {"type": 5, "id": "i", "token": "tok",
               "data": {"custom_id": f"{ENHANCE_MODAL_PREFIX}slug-1",
                        "components": [{"type": 1, "components": [
                            {"type": 4, "custom_id": "change", "value": "make it blue"}]}]},
               "member": {"user": {"id": "100", "username": "u"}}, "channel_id": "c"}
    resp = await handler.handle_interaction(payload)
    assert resp["type"] == 5
    await asyncio.sleep(0)
    assert captured == {"slug": "slug-1", "prompt": "make it blue"}
```

- [ ] **Step 2: Run, confirm FAIL.**

- [ ] **Step 3a: Imports.** Add to the existing `from handlers.app_builder_panel import (...)` block:
```python
    build_enhance_modal,
    build_published_components,
    is_enhance_button, slug_from_enhance_button,
    is_unpublish_button, slug_from_unpublish_button,
    is_enhance_modal, slug_from_enhance_modal,
```

- [ ] **Step 3b: Dispatch new buttons** in `_handle_message_component` — add these branches BEFORE the existing `is_publish_button` branch:
```python
        if is_enhance_button(custom_id):
            slug = slug_from_enhance_button(custom_id)
            return {"type": MODAL, "data": build_enhance_modal(slug)}
        if is_unpublish_button(custom_id):
            return await self._handle_unpublish_component(payload, custom_id)
```
(Keep the existing publish branch + the malformed-id try/except inside `_handle_publish_component`. Wrap the `slug_from_enhance_button` line so a malformed id no-ops: if it raises `ValueError`, fall through — simplest is to guard with `is_enhance_button` which is already checked; the bare-prefix case raises, so wrap:)
```python
        if is_enhance_button(custom_id):
            try:
                slug = slug_from_enhance_button(custom_id)
            except ValueError:
                logger.info(f"Ignoring malformed enhance custom_id: {custom_id}")
                return {"type": DEFERRED_UPDATE_MESSAGE}
            return {"type": MODAL, "data": build_enhance_modal(slug)}
        if is_unpublish_button(custom_id):
            return await self._handle_unpublish_component(payload, custom_id)
```

- [ ] **Step 3c: `_handle_unpublish_component`** (place after `_handle_publish_component`):
```python
    async def _handle_unpublish_component(self, payload: dict[str, Any], custom_id: str) -> dict[str, Any]:
        """Unpublish button click → run_panel_unpublish in the background, ACK deferred."""
        try:
            slug = slug_from_unpublish_button(custom_id)
        except ValueError:
            logger.info(f"Ignoring malformed unpublish custom_id: {custom_id}")
            return {"type": DEFERRED_UPDATE_MESSAGE}
        interaction_token = payload.get("token", "")
        member = payload.get("member", {})
        user = member.get("user", payload.get("user", {}))
        async def respond(msg: str) -> None:
            await self.discord.edit_original(interaction_token=interaction_token, content=msg)
        ctx = CommandContext(
            user_id=user.get("id", ""), user_name=user.get("username", "unknown"),
            channel_id=payload.get("channel_id", ""),
            raw_text=f"aiuibuilder unpublish {slug}", subcommand="aiuibuilder",
            arguments="", platform="discord", respond=respond,
            metadata={"interaction_token": interaction_token},
        )
        asyncio.create_task(self.router.run_panel_unpublish(ctx, slug))
        return {"type": DEFERRED_CHANNEL_MESSAGE}
```

- [ ] **Step 3d: Enhance modal submit** in `_handle_modal_submit` — add BEFORE the existing `is_panel_modal` branch:
```python
        if is_enhance_modal(custom_id):
            try:
                slug = slug_from_enhance_modal(custom_id)
            except ValueError:
                logger.info(f"Ignoring malformed enhance modal custom_id: {custom_id}")
                return {"type": DEFERRED_UPDATE_MESSAGE}
            change = self._extract_modal_value(data, "change")
            interaction_token = payload.get("token", "")
            member = payload.get("member", {})
            user = member.get("user", payload.get("user", {}))
            channel_id = payload.get("channel_id", "")
            notify_channel, notify_channel_rich = self._channel_notifiers(channel_id)
            async def respond(msg: str) -> None:
                await self.discord.edit_original(interaction_token=interaction_token, content=msg)
            ctx = CommandContext(
                user_id=user.get("id", ""), user_name=user.get("username", "unknown"),
                channel_id=channel_id, raw_text=f"aiuibuilder enhance {slug}",
                subcommand="aiuibuilder", arguments="", platform="discord", respond=respond,
                metadata={"interaction_token": interaction_token},
                notify_channel=notify_channel if channel_id else None,
                notify_channel_rich=notify_channel_rich if channel_id else None,
            )
            asyncio.create_task(self.router.run_panel_enhance(ctx, slug, change))
            return {"type": DEFERRED_CHANNEL_MESSAGE}
```
(Note: `data` is already read at the top of `_handle_modal_submit`; if not, read `data = payload.get("data", {})` first. `_extract_modal_value`, `CommandContext`, `_channel_notifiers`, `DEFERRED_CHANNEL_MESSAGE`, `DEFERRED_UPDATE_MESSAGE`, `MODAL` all already exist.)

- [ ] **Step 3e: Wire `on_published`** in `_handle_publish_component` — where it builds the publish `ctx`, set `on_published` so the published reply gets buttons. Add an `on_published` closure and pass it to the ctx:
```python
        async def on_published(public_url: str) -> None:
            await self.discord.edit_original(
                interaction_token=interaction_token,
                content=f"\U0001f389 Published! Live at {public_url}".rstrip(),
                components=build_published_components(slug, public_url),
            )
```
and add `on_published=on_published,` to that `CommandContext(...)`.

- [ ] **Step 4: Run** `tests/test_app_builder_interactions.py tests/test_discord_notify_wiring.py -q` → pass; then full suite `-q` → green.
- [ ] **Step 5: Commit**
```bash
git add webhook-handler/handlers/discord_commands.py webhook-handler/tests/test_app_builder_interactions.py
git commit -m "feat(discord): dispatch enhance/unpublish buttons + enhance modal; publish buttons

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Full verification + final review
- [ ] **Step 1:** From `webhook-handler/`: `& "<venv python>" -m pytest -q` → all green, no regressions.
- [ ] **Step 2:** `py_compile` the changed tasks files (Tasks 1-2) → exit 0.
- [ ] **Step 3:** Fix any reds with systematic-debugging; don't weaken tests.
- [ ] **Step 4:** Final commit if Step 3 changed anything.

---

## Deployment (two services, per `CLAUDE.md`)
1. **tasks:** `scp` `routes_projects.py` + `routes_aiuibuilder.py` → `docker compose ... up -d --build tasks`. NEVER deploy `templates.py`.
2. **webhook-handler:** `scp` `clients/tasks.py`, `clients/discord.py`, `handlers/app_builder_panel.py`, `handlers/commands.py`, `handlers/discord_commands.py` → rebuild.
Verify `/tasks/healthz`, bot `Up`, then: build an app → click **Enhance** (type a change) → confirm updated preview; **Publish** → click **Unpublish** → confirm offline.

---

## Self-Review Notes
- **Spec coverage:** unpublish endpoint+helper (Task 1); enhance endpoint+spawn (Task 2); client methods + edit_original components (Task 4); buttons/published-components/modal/parsers (Task 3); router methods + on_published (Task 5); dispatch + modal submit + on_published wiring (Task 6); verify (Task 7); deploy (section). Element-picker out of scope (noted). ✔
- **Type/name consistency:** `_unpublish_slug`, `_create_and_spawn_enhance`, `EnhanceRequest`, `unpublish_app`/`enhance_app`, `build_published_components`, `build_enhance_modal`, `ENHANCE_PREFIX`/`UNPUBLISH_PREFIX`/`ENHANCE_MODAL_PREFIX`, `is_*`/`slug_from_*`, `run_panel_enhance`/`run_panel_unpublish`, `_format_enhance_error`/`_format_unpublish_error`, `on_published`, `_handle_unpublish_component` — consistent across tasks. ✔
- **No placeholders:** complete code in every step. ✔
