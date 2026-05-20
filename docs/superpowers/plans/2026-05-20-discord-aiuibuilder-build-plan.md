# Discord one-shot App Builder build (`/aiui aiuibuilder build`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a Discord user fire a one-shot App Builder build with `/aiui aiuibuilder build "<description>"` and have the bot post the preview link in the channel when it finishes.

**Architecture:** A new user-scoped (X-User-Email, *not* admin) build endpoint on the tasks service reuses the existing `_run_execution` agent pipeline; the webhook-handler bot fires the build, replies "building…", and watches it in a background coroutine, posting the result via a bot-token channel message (the interaction token expires at 15 min). One build runs platform-wide at a time (3.8 GB RAM / single agent VM).

**Tech Stack:** FastAPI + SQLAlchemy async (tasks service), httpx + respx (bot + tests), Discord Interactions API v10, pytest/pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-05-20-discord-aiuibuilder-build-design.md`

---

## Test execution environment (read before starting)

- **No local Docker.** Both suites run with the local Python (3.13) for fast TDD:
  - Bot: from `webhook-handler/` → `python -m pytest tests/ -q`
  - Tasks: from `mcp-servers/tasks/` → `DATABASE_URL="postgresql+asyncpg://nope/nope" python -m pytest tests/ -q`
    (run via the Bash tool so the inline env var works; the dummy URL satisfies `conftest.py` import — no test touches a real DB).
- All new tests are **DB-free** (TestClient + monkeypatch on the tasks side, respx on the bot side). Real-DB behavior is verified by the live backend smoke + a real Discord build after deploy (Task 10).

## File Structure

**tasks service (`mcp-servers/tasks/`):**
- Create `routes_aiuibuilder.py` — the entire user-scoped build feature: request/response models, pure helpers (`_slugify`, `_make_slug`, `_public_build_status`, `_preview_url`), DB helpers (`_slug_taken`, `_unique_slug`, `_create_and_spawn_build`, `_load_owned_build`), and the two routes. One file, one responsibility.
- Modify `main.py` — mount the new router (2 lines).
- Create `tests/test_routes_aiuibuilder.py` — pure-helper unit tests + monkeypatched route tests.

**bot (`webhook-handler/`):**
- Modify `clients/tasks.py` — add `start_build` + `get_build_status`.
- Modify `clients/discord.py` — add `post_channel_message`.
- Modify `handlers/commands.py` — `CommandContext.notify_channel` field; `_handle_aiuibuilder` `build` branch; `_watch_build`; `_format_build_error`; help text.
- Modify `handlers/discord_commands.py` — wire `notify_channel`.
- Create/extend `tests/test_aiuibuilder_build.py`, extend `tests/test_tasks_client.py`, `tests/test_discord_client.py` (new), `tests/test_discord_e2e_local.py`.

**deploy:** `scripts/e2e_backend_smoke.py` (extend), then SCP + rebuild `tasks` and `webhook-handler`.

---

## Task 1: tasks service — pure helpers + module skeleton

**Files:**
- Create: `mcp-servers/tasks/routes_aiuibuilder.py`
- Test: `mcp-servers/tasks/tests/test_routes_aiuibuilder.py`

- [ ] **Step 1: Write the failing tests (pure helpers only)**

```python
# mcp-servers/tasks/tests/test_routes_aiuibuilder.py
"""User-scoped one-shot build endpoint (/api/aiuibuilder)."""
import os
import sys

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://nope/nope")
if not os.environ.get("AIUI_FERNET_KEY"):
    from cryptography.fernet import Fernet as _Fernet
    os.environ["AIUI_FERNET_KEY"] = _Fernet.generate_key().decode()

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import re
import routes_aiuibuilder as rb

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,80}$")


def test_slugify_basic():
    assert rb._slugify("A Todo List With Dark Mode") == "a-todo-list-with-dark"


def test_slugify_strips_punctuation_and_empty_fallback():
    assert rb._slugify("!!!  ") == "app"
    assert rb._slugify("My App!!! v2") == "my-app-v2"


def test_make_slug_has_suffix_and_matches_route_regex():
    s = rb._make_slug("Todo List")
    assert s.startswith("todo-list-")
    assert _SLUG_RE.match(s)
    # 4-hex suffix
    assert re.search(r"-[0-9a-f]{4}$", s)


def test_public_build_status_mapping():
    assert rb._public_build_status("completed") == "completed"
    assert rb._public_build_status("failed") == "failed"
    for s in ("running", "planning", "awaiting_input", "pending"):
        assert rb._public_build_status(s) == "running"


def test_preview_url_shape():
    assert rb._preview_url("todo-a1b2") == (
        "https://ai-ui.coolestdomain.win/tasks/preview-app/todo-a1b2/"
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd mcp-servers/tasks && DATABASE_URL="postgresql+asyncpg://nope/nope" python -m pytest tests/test_routes_aiuibuilder.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'routes_aiuibuilder'`.

- [ ] **Step 3: Create the module with models + pure helpers**

```python
# mcp-servers/tasks/routes_aiuibuilder.py
"""User-scoped one-shot App Builder build entry point (for Discord).

`current_user` (X-User-Email) auth — NOT admin. Mirrors what the web
create+execute flow does, but ownership-scoped to the caller, reusing the
existing _run_execution agent pipeline. No new tables.
"""
import asyncio
import logging
import os
import re
import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, text

from auth import CurrentUser, current_user
from db import session
from models import ProjectMember, PublishedApp, TaskExecution, TaskItem

logger = logging.getLogger("tasks.aiuibuilder")

router = APIRouter(prefix="/api/aiuibuilder")

# Route-slug regex (hyphen-only). Defined locally to avoid a circular import
# from main.py (which imports this router); mirrors main._SLUG_ROUTE_RE.
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,80}$")

# Internal TaskItem.status values that mean "a build is occupying the agent".
_LIVE_BUILD_STATES = ("running", "planning", "awaiting_input")

# Same default as routes_projects.PUBLIC_DOMAIN.
PUBLIC_DOMAIN = os.environ.get("AIUI_PUBLIC_DOMAIN", "ai-ui.coolestdomain.win")


class BuildRequest(BaseModel):
    description: str = Field(min_length=1, max_length=4000)
    name: str | None = Field(default=None, max_length=80)


class BuildResponse(BaseModel):
    task_id: str
    slug: str
    status: str


class BuildStatusResponse(BaseModel):
    status: str
    slug: str
    preview_url: str | None = None
    error: str | None = None


def _slugify(seed: str) -> str:
    """Lowercase + hyphenate the first ~6 words; cap length. Pure (no DB)."""
    s = re.sub(r"[^a-z0-9]+", "-", (seed or "").strip().lower())
    words = [w for w in s.split("-") if w][:6]
    base = "-".join(words)[:40].strip("-")
    return base or "app"


def _make_slug(seed: str) -> str:
    """Slugify + a 4-hex suffix for uniqueness (collision-checked elsewhere)."""
    return f"{_slugify(seed)}-{secrets.token_hex(2)}"


def _public_build_status(task_status: str) -> str:
    """Map an internal TaskItem.status to the small public build status."""
    if task_status == "completed":
        return "completed"
    if task_status == "failed":
        return "failed"
    return "running"


def _preview_url(slug: str) -> str:
    return f"https://{PUBLIC_DOMAIN}/tasks/preview-app/{slug}/"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd mcp-servers/tasks && DATABASE_URL="postgresql+asyncpg://nope/nope" python -m pytest tests/test_routes_aiuibuilder.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/routes_aiuibuilder.py mcp-servers/tasks/tests/test_routes_aiuibuilder.py
git commit -m "feat(tasks): aiuibuilder build module skeleton + pure helpers"
```

---

## Task 2: tasks service — `POST /api/aiuibuilder/build`

**Files:**
- Modify: `mcp-servers/tasks/routes_aiuibuilder.py`
- Modify: `mcp-servers/tasks/main.py`
- Test: `mcp-servers/tasks/tests/test_routes_aiuibuilder.py`

- [ ] **Step 1: Write failing route tests (monkeypatched — no DB)**

Append to `tests/test_routes_aiuibuilder.py`:

```python
from unittest.mock import AsyncMock
from fastapi import HTTPException
from fastapi.testclient import TestClient


def _client():
    from main import app
    return TestClient(app, raise_server_exceptions=False)


def test_build_requires_email():
    r = _client().post("/api/aiuibuilder/build", json={"description": "a todo app"})
    assert r.status_code == 401


def test_build_happy_path(monkeypatch):
    async def fake_create(email, seed, description):
        assert email == "alice@x.com"
        return ("11111111-1111-1111-1111-111111111111", "todo-list-a1b2")
    monkeypatch.setattr(rb, "_create_and_spawn_build", fake_create)

    r = _client().post(
        "/api/aiuibuilder/build",
        headers={"X-User-Email": "alice@x.com"},
        json={"description": "a todo list with dark mode"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["slug"] == "todo-list-a1b2"
    assert body["status"] == "running"
    assert body["task_id"] == "11111111-1111-1111-1111-111111111111"


def test_build_busy_returns_429(monkeypatch):
    async def busy(email, seed, description):
        raise HTTPException(status_code=429, detail="A build is already running")
    monkeypatch.setattr(rb, "_create_and_spawn_build", busy)

    r = _client().post(
        "/api/aiuibuilder/build",
        headers={"X-User-Email": "alice@x.com"},
        json={"description": "another app"},
    )
    assert r.status_code == 429


def test_build_validation_empty_description(monkeypatch):
    # description min_length=1 — empty string is a 422 before our code runs.
    r = _client().post(
        "/api/aiuibuilder/build",
        headers={"X-User-Email": "alice@x.com"},
        json={"description": ""},
    )
    assert r.status_code == 422
```

- [ ] **Step 2: Run to verify failure**

Run: `cd mcp-servers/tasks && DATABASE_URL="postgresql+asyncpg://nope/nope" python -m pytest tests/test_routes_aiuibuilder.py -q`
Expected: FAIL — `404` (route not mounted) and `AttributeError: _create_and_spawn_build`.

- [ ] **Step 3: Implement DB helpers, the create-and-spawn helper, and the route**

Append to `routes_aiuibuilder.py`:

```python
async def _slug_taken(s, slug: str) -> bool:
    """True if `slug` collides in items / published_apps / project_members.
    Mirrors the rename collision check in routes_projects.py."""
    if (await s.execute(
        select(TaskItem.id).where(TaskItem.built_app_slug == slug).limit(1)
    )).scalar_one_or_none():
        return True
    if (await s.execute(
        select(PublishedApp.slug).where(PublishedApp.slug == slug).limit(1)
    )).scalar_one_or_none():
        return True
    return bool((await s.execute(
        select(ProjectMember.slug).where(ProjectMember.slug == slug).limit(1)
    )).scalar_one_or_none())


async def _unique_slug(s, seed: str) -> str:
    """A route-valid slug not already used. Regenerates the suffix on clash."""
    for _ in range(8):
        slug = _make_slug(seed)
        if _SLUG_RE.match(slug) and not await _slug_taken(s, slug):
            return slug
    return f"app-{secrets.token_hex(4)}"


async def _create_and_spawn_build(email: str, seed: str, description: str) -> tuple[str, str]:
    """Create a BUILD task owned by `email` and spawn the agent run.

    One build platform-wide at a time: raises HTTPException(429) if any BUILD
    task is already in a live state. Returns (task_id, slug).
    """
    # Deferred imports avoid a circular import at module load time.
    from claude_executor import build_prompt
    from routes_execution import _RUNNING, _run_execution
    from routes_tasks import _ensure_app_skeleton

    meeting_id = uuid.uuid4()
    async with session() as s:
        # Serialize the guard so two near-simultaneous builds can't both pass.
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
        item = TaskItem(
            meeting_id=meeting_id,
            action_type="BUILD",
            assignee_name=email.split("@")[0],
            assignee_email=email,
            description=(description or "").strip()[:20_000],
            priority="NICE_TO_HAVE",
            status="running",
            mode="ai",
            max_attempts=3,
            built_app_slug=slug,
        )
        s.add(item)
        await s.commit()
        await s.refresh(item)

        execution = TaskExecution(task_id=item.id, status="running", log="")
        s.add(execution)
        await s.commit()
        await s.refresh(execution)
        task_id, exec_id = item.id, execution.id

    # Scaffold the empty app dir (best-effort — agent recreates if it fails).
    try:
        _ensure_app_skeleton(slug, None)
    except Exception:
        pass

    prompt = build_prompt(
        description=(description or "").strip()[:20_000],
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


@router.post("/build", response_model=BuildResponse, status_code=201)
async def start_build(body: BuildRequest, user: CurrentUser = Depends(current_user)):
    """Fire a one-shot, template-less, frontend-only build for the caller."""
    seed = body.name or body.description
    task_id, slug = await _create_and_spawn_build(user.email, seed, body.description)
    return BuildResponse(task_id=task_id, slug=slug, status="running")
```

- [ ] **Step 4: Mount the router in `main.py`**

In `mcp-servers/tasks/main.py`, with the other router imports (near line 11-24) add:
```python
from routes_aiuibuilder import router as aiuibuilder_router
```
and with the other `app.include_router(...)` calls (near line 84-95) add:
```python
app.include_router(aiuibuilder_router)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd mcp-servers/tasks && DATABASE_URL="postgresql+asyncpg://nope/nope" python -m pytest tests/test_routes_aiuibuilder.py -q`
Expected: PASS (9 passed).

- [ ] **Step 6: Commit**

```bash
git add mcp-servers/tasks/routes_aiuibuilder.py mcp-servers/tasks/main.py mcp-servers/tasks/tests/test_routes_aiuibuilder.py
git commit -m "feat(tasks): POST /api/aiuibuilder/build (user-scoped, one-at-a-time)"
```

---

## Task 3: tasks service — `GET /api/aiuibuilder/build/{task_id}`

**Files:**
- Modify: `mcp-servers/tasks/routes_aiuibuilder.py`
- Test: `mcp-servers/tasks/tests/test_routes_aiuibuilder.py`

- [ ] **Step 1: Write failing tests (monkeypatch the DB load)**

Append to `tests/test_routes_aiuibuilder.py`:

```python
import types


def _fake_item(status, slug, result=None, assignee="alice@x.com"):
    return types.SimpleNamespace(
        status=status, built_app_slug=slug, result=result, assignee_email=assignee,
    )


def test_build_status_requires_email():
    r = _client().get("/api/aiuibuilder/build/11111111-1111-1111-1111-111111111111")
    assert r.status_code == 401


def test_build_status_unknown_or_other_user_404(monkeypatch):
    async def load_none(email, task_id):
        return None
    monkeypatch.setattr(rb, "_load_owned_build", load_none)
    r = _client().get(
        "/api/aiuibuilder/build/11111111-1111-1111-1111-111111111111",
        headers={"X-User-Email": "alice@x.com"},
    )
    assert r.status_code == 404


def test_build_status_completed_has_preview(monkeypatch):
    async def load(email, task_id):
        return _fake_item("completed", "todo-a1b2")
    monkeypatch.setattr(rb, "_load_owned_build", load)
    r = _client().get(
        "/api/aiuibuilder/build/11111111-1111-1111-1111-111111111111",
        headers={"X-User-Email": "alice@x.com"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "completed"
    assert body["preview_url"] == "https://ai-ui.coolestdomain.win/tasks/preview-app/todo-a1b2/"
    assert body["error"] is None


def test_build_status_failed_has_error_no_preview(monkeypatch):
    async def load(email, task_id):
        return _fake_item("failed", "todo-a1b2", result="agent crashed: boom")
    monkeypatch.setattr(rb, "_load_owned_build", load)
    r = _client().get(
        "/api/aiuibuilder/build/11111111-1111-1111-1111-111111111111",
        headers={"X-User-Email": "alice@x.com"},
    )
    body = r.json()
    assert body["status"] == "failed"
    assert body["preview_url"] is None
    assert "boom" in body["error"]


def test_build_status_running_no_preview(monkeypatch):
    async def load(email, task_id):
        return _fake_item("running", "todo-a1b2")
    monkeypatch.setattr(rb, "_load_owned_build", load)
    r = _client().get(
        "/api/aiuibuilder/build/11111111-1111-1111-1111-111111111111",
        headers={"X-User-Email": "alice@x.com"},
    )
    body = r.json()
    assert body["status"] == "running"
    assert body["preview_url"] is None
```

- [ ] **Step 2: Run to verify failure**

Run: `cd mcp-servers/tasks && DATABASE_URL="postgresql+asyncpg://nope/nope" python -m pytest tests/test_routes_aiuibuilder.py -q`
Expected: FAIL — `AttributeError: _load_owned_build` / route 404 unmounted → 405/404.

- [ ] **Step 3: Implement the load helper + route**

Append to `routes_aiuibuilder.py`:

```python
async def _load_owned_build(email: str, task_id: uuid.UUID) -> TaskItem | None:
    """Return the task iff it exists AND is owned by `email`, else None.
    None → the route answers 404 (not 403) so existence isn't leaked."""
    async with session() as s:
        item = (await s.execute(
            select(TaskItem).where(TaskItem.id == task_id)
        )).scalar_one_or_none()
    if item is None or item.assignee_email != email:
        return None
    return item


@router.get("/build/{task_id}", response_model=BuildStatusResponse)
async def get_build_status(task_id: uuid.UUID, user: CurrentUser = Depends(current_user)):
    item = await _load_owned_build(user.email, task_id)
    if item is None:
        raise HTTPException(status_code=404, detail="not found")
    status = _public_build_status(item.status)
    slug = item.built_app_slug or ""
    return BuildStatusResponse(
        status=status,
        slug=slug,
        preview_url=_preview_url(slug) if status == "completed" and slug else None,
        error=(item.result or "")[:500] if status == "failed" else None,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd mcp-servers/tasks && DATABASE_URL="postgresql+asyncpg://nope/nope" python -m pytest tests/test_routes_aiuibuilder.py -q`
Expected: PASS (14 passed).

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/routes_aiuibuilder.py mcp-servers/tasks/tests/test_routes_aiuibuilder.py
git commit -m "feat(tasks): GET /api/aiuibuilder/build/{task_id} (owner-scoped status)"
```

---

## Task 4: bot — `TasksClient.start_build` + `get_build_status`

**Files:**
- Modify: `webhook-handler/clients/tasks.py`
- Test: `webhook-handler/tests/test_tasks_client.py`

- [ ] **Step 1: Write failing tests**

Append to `webhook-handler/tests/test_tasks_client.py`:

```python
@pytest.mark.asyncio
async def test_start_build_sends_only_user_email(client):
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/api/aiuibuilder/build").mock(
            return_value=Response(201, json={
                "task_id": "t1", "slug": "todo-a1b2", "status": "running"})
        )
        result = await client.start_build("alice@x.com", "a todo app")
        assert result["slug"] == "todo-a1b2"
        req = route.calls.last.request
        assert req.headers.get("x-user-email") == "alice@x.com"
        assert "x-cron-secret" not in {k.lower() for k in req.headers}
        import json
        assert json.loads(req.content) == {"description": "a todo app", "name": None}


@pytest.mark.asyncio
async def test_start_build_429_raises(client):
    with respx.mock(base_url=BASE) as mock:
        mock.post("/api/aiuibuilder/build").mock(
            return_value=Response(429, json={"detail": "A build is already running"}))
        with pytest.raises(TasksAPIError) as exc:
            await client.start_build("alice@x.com", "another app")
        assert exc.value.status == 429


@pytest.mark.asyncio
async def test_get_build_status_endpoint(client):
    with respx.mock(base_url=BASE) as mock:
        route = mock.get("/api/aiuibuilder/build/t1").mock(
            return_value=Response(200, json={
                "status": "completed", "slug": "todo-a1b2",
                "preview_url": "https://ai-ui.coolestdomain.win/tasks/preview-app/todo-a1b2/",
                "error": None}))
        result = await client.get_build_status("alice@x.com", "t1")
        assert result["status"] == "completed"
        req = route.calls.last.request
        assert req.headers.get("x-user-email") == "alice@x.com"
        assert "x-cron-secret" not in {k.lower() for k in req.headers}
```

- [ ] **Step 2: Run to verify failure**

Run: `cd webhook-handler && python -m pytest tests/test_tasks_client.py -q`
Expected: FAIL — `AttributeError: 'TasksClient' object has no attribute 'start_build'`.

- [ ] **Step 3: Implement the methods**

Append to the `TasksClient` class in `webhook-handler/clients/tasks.py`:

```python
    async def start_build(
        self, user_email: str, description: str, name: str | None = None,
    ) -> dict[str, Any]:
        resp = await self._request(
            "POST", "/api/aiuibuilder/build", user_email,
            json={"description": description, "name": name},
        )
        return resp.json()

    async def get_build_status(
        self, user_email: str, task_id: str,
    ) -> dict[str, Any]:
        resp = await self._request(
            "GET", f"/api/aiuibuilder/build/{task_id}", user_email,
        )
        return resp.json()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd webhook-handler && python -m pytest tests/test_tasks_client.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/clients/tasks.py webhook-handler/tests/test_tasks_client.py
git commit -m "feat(bot): TasksClient.start_build + get_build_status (X-User-Email only)"
```

---

## Task 5: bot — `DiscordClient.post_channel_message`

**Files:**
- Modify: `webhook-handler/clients/discord.py`
- Test: `webhook-handler/tests/test_discord_client.py` (new)

- [ ] **Step 1: Write failing tests**

```python
# webhook-handler/tests/test_discord_client.py
"""DiscordClient.post_channel_message — bot-token channel post (outlives the
15-minute interaction-token window)."""
import pytest
import respx
from httpx import Response

from clients.discord import DiscordClient, DISCORD_API_BASE


@pytest.fixture
def dc():
    return DiscordClient(application_id="app1", bot_token="bot-tok")


@pytest.mark.asyncio
async def test_post_channel_message_uses_bot_token(dc):
    with respx.mock() as mock:
        route = mock.post(f"{DISCORD_API_BASE}/channels/c1/messages").mock(
            return_value=Response(200, json={"id": "m1"}))
        ok = await dc.post_channel_message("c1", "hello")
        assert ok is True
        req = route.calls.last.request
        assert req.headers.get("authorization") == "Bot bot-tok"
        import json
        assert json.loads(req.content) == {"content": "hello"}


@pytest.mark.asyncio
async def test_post_channel_message_truncates_2000(dc):
    with respx.mock() as mock:
        route = mock.post(f"{DISCORD_API_BASE}/channels/c1/messages").mock(
            return_value=Response(200, json={"id": "m1"}))
        await dc.post_channel_message("c1", "x" * 5000)
        import json
        assert len(json.loads(route.calls.last.request.content)["content"]) == 2000


@pytest.mark.asyncio
async def test_post_channel_message_returns_false_on_error(dc):
    with respx.mock() as mock:
        mock.post(f"{DISCORD_API_BASE}/channels/c1/messages").mock(
            return_value=Response(403, json={"message": "no perms"}))
        assert await dc.post_channel_message("c1", "hi") is False
```

- [ ] **Step 2: Run to verify failure**

Run: `cd webhook-handler && python -m pytest tests/test_discord_client.py -q`
Expected: FAIL — `AttributeError: 'DiscordClient' object has no attribute 'post_channel_message'`.

- [ ] **Step 3: Implement the method**

Append to the `DiscordClient` class in `webhook-handler/clients/discord.py`:

```python
    async def post_channel_message(self, channel_id: str, content: str) -> bool:
        """Post a fresh message to a channel using the bot token.

        Unlike followup_message/edit_original (interaction token, 15-min TTL),
        this works indefinitely — used to report a build result that may finish
        after the interaction window closes. Requires the bot to have Send
        Messages in the channel. Never raises.
        """
        content = content[:2000]
        url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    url,
                    headers={"Authorization": f"Bot {self.bot_token}"},
                    json={"content": content},
                )
                if response.status_code in (200, 201):
                    return True
                logger.error(
                    f"Discord channel post error: {response.status_code} {response.text}"
                )
                return False
        except Exception as e:
            logger.error(f"Error posting Discord channel message: {e}")
            return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd webhook-handler && python -m pytest tests/test_discord_client.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/clients/discord.py webhook-handler/tests/test_discord_client.py
git commit -m "feat(bot): DiscordClient.post_channel_message (bot-token channel post)"
```

---

## Task 6: bot — `build` branch + `notify_channel` field + error mapping + help

**Files:**
- Modify: `webhook-handler/handlers/commands.py`
- Test: `webhook-handler/tests/test_aiuibuilder_build.py` (new)

- [ ] **Step 1: Write failing tests**

```python
# webhook-handler/tests/test_aiuibuilder_build.py
"""_handle_aiuibuilder `build` action."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from handlers.commands import CommandRouter, CommandContext
from clients.tasks import TasksAPIError


def _ctx(user_id, args, captured, notify=None):
    async def respond(msg):
        captured.append(msg)
    return CommandContext(
        user_id=user_id, user_name="tester", channel_id="c1",
        raw_text=f"aiuibuilder {args}", subcommand="aiuibuilder", arguments=args,
        platform="discord", respond=respond, metadata={}, notify_channel=notify,
    )


def _router(mapping, tasks_client):
    return CommandRouter(
        openwebui_client=MagicMock(),
        n8n_client=MagicMock(api_key=""),
        discord_user_email_map=mapping,
        tasks_client=tasks_client,
    )


@pytest.mark.asyncio
async def test_build_unmapped_user_rejected():
    captured = []
    await _router({}, MagicMock())._handle_aiuibuilder(_ctx("999", 'build "x"', captured))
    assert any("isn't linked" in m for m in captured)


@pytest.mark.asyncio
async def test_build_missing_description_shows_usage():
    captured = []
    tc = MagicMock(); tc.start_build = AsyncMock()
    await _router({"100": "a@x.com"}, tc)._handle_aiuibuilder(_ctx("100", "build", captured))
    assert any("Usage" in m for m in captured)
    tc.start_build.assert_not_awaited()


@pytest.mark.asyncio
async def test_build_happy_path_starts_and_acks(monkeypatch):
    captured = []
    tc = MagicMock()
    tc.start_build = AsyncMock(return_value={"task_id": "t1", "slug": "todo-a1b2", "status": "running"})
    # Don't actually run the watcher in this test.
    watched = {}
    async def fake_watch(self, ctx, email, task_id, slug):
        watched["args"] = (email, task_id, slug)
    monkeypatch.setattr(CommandRouter, "_watch_build", fake_watch)

    async def notify(msg):
        pass
    await _router({"100": "a@x.com"}, tc)._handle_aiuibuilder(
        _ctx("100", 'build "a todo list with dark mode"', captured, notify=notify)
    )
    await asyncio.sleep(0)  # let the create_task scheduled watcher run
    tc.start_build.assert_awaited_once()
    # description passed without surrounding quotes
    assert tc.start_build.call_args.args[1] == "a todo list with dark mode"
    assert any("Building" in m and "todo-a1b2" in m for m in captured)
    assert watched["args"] == ("a@x.com", "t1", "todo-a1b2")


@pytest.mark.asyncio
async def test_build_unquoted_description_works():
    captured = []
    tc = MagicMock()
    tc.start_build = AsyncMock(return_value={"task_id": "t1", "slug": "s", "status": "running"})
    await _router({"100": "a@x.com"}, tc)._handle_aiuibuilder(
        _ctx("100", "build a todo list", captured, notify=None)
    )
    assert tc.start_build.call_args.args[1] == "a todo list"


@pytest.mark.asyncio
async def test_build_429_says_already_running():
    captured = []
    tc = MagicMock()
    tc.start_build = AsyncMock(side_effect=TasksAPIError(429, "A build is already running"))
    await _router({"100": "a@x.com"}, tc)._handle_aiuibuilder(
        _ctx("100", 'build "x"', captured, notify=None)
    )
    assert any("already running" in m.lower() for m in captured)


@pytest.mark.asyncio
async def test_existing_list_still_works():
    """Regression: refactored arg-parsing must not break list/status/open."""
    captured = []
    tc = MagicMock(); tc.list_projects = AsyncMock(return_value=[])
    await _router({"100": "a@x.com"}, tc)._handle_aiuibuilder(_ctx("100", "list", captured))
    assert any("no projects" in m.lower() for m in captured)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd webhook-handler && python -m pytest tests/test_aiuibuilder_build.py -q`
Expected: FAIL — `CommandContext.__init__() got an unexpected keyword argument 'notify_channel'` and missing `build` handling.

- [ ] **Step 3: Add the `notify_channel` field to `CommandContext`**

In `webhook-handler/handlers/commands.py`, in the `CommandContext` dataclass (top of file), add after `metadata`:
```python
    notify_channel: Optional[Callable[[str], Awaitable[None]]] = None
```
(`Optional`, `Callable`, `Awaitable` are already imported.)

- [ ] **Step 4: Refactor `_handle_aiuibuilder` arg-parsing and add the `build` branch**

Replace the parsing preamble of `_handle_aiuibuilder` (the `try: tokens = shlex.split(...)` block and `action`/`rest` derivation) with action-from-plain-split, then add the `build` branch BEFORE the `list/status/open` block:

```python
        # Action is the first word; the remainder is parsed per-action so a
        # build description can contain spaces/quotes without shlex choking.
        parts = (ctx.arguments or "").strip().split(None, 1)
        action = parts[0].lower() if parts else ""
        remainder = parts[1] if len(parts) > 1 else ""

        if action == "build":
            description = remainder.strip().strip('"').strip()
            if not description:
                await ctx.respond(
                    'Usage: `aiuibuilder build <description>` — '
                    'e.g. `aiuibuilder build a todo list with dark mode`'
                )
                return
            try:
                result = await self._tasks_client.start_build(email, description)
            except TasksAPIError as e:
                await ctx.respond(self._format_build_error(e))
                return
            slug = result["slug"]
            task_id = result["task_id"]
            await ctx.respond(
                f"Building `{slug}` … I'll post the link here when it's ready "
                "(usually a few minutes)."
            )
            if ctx.notify_channel is not None:
                asyncio.create_task(self._watch_build(ctx, email, task_id, slug))
            return

        try:
            rest = shlex.split(remainder) if remainder else []
        except ValueError:
            await ctx.respond("Couldn't parse args. Try `aiuibuilder list`.")
            return
```

Then update the existing `list/status/open` branches to use `action` and `rest`
(they already reference `action`/`rest` — only the derivation changed; `rest[0]`
is still the slug for `status`/`open`).

- [ ] **Step 5: Add `_format_build_error` (next to `_format_tasks_error`)**

```python
    def _format_build_error(self, e: TasksAPIError) -> str:
        """Build-flavored error text (NOT the schedule-flavored _format_tasks_error)."""
        if e.status == 0:
            return "Tasks service unreachable, try again."
        if e.status == 429:
            return "A build is already running — try again in a few minutes."
        if e.status in (401, 403):
            return "Your Discord account isn't linked. Ask Lukas to add you."
        if e.status in (400, 422):
            return "Couldn't start the build — check your description and try again."
        return f"Couldn't start the build (error {e.status})."
```

- [ ] **Step 6: Update help/usage text**

In `_handle_aiuibuilder`'s final `else` usage line, change to:
```python
            await ctx.respond("Usage: `/aiui aiuibuilder <build|list|status|open> [args]`")
```
In `_handle_help`, change the aiuibuilder line to:
```python
            "`/aiui aiuibuilder <build|list|status|open>` — Build & manage your apps\n"
```

- [ ] **Step 7: Run tests to verify they pass (and no regressions)**

Run: `cd webhook-handler && python -m pytest tests/test_aiuibuilder_build.py tests/test_aiuibuilder_handler.py -q`
Expected: PASS (all).

- [ ] **Step 8: Commit**

```bash
git add webhook-handler/handlers/commands.py webhook-handler/tests/test_aiuibuilder_build.py
git commit -m "feat(bot): /aiui aiuibuilder build branch + notify_channel + build error map"
```

---

## Task 7: bot — `_watch_build` background watcher

**Files:**
- Modify: `webhook-handler/handlers/commands.py`
- Test: `webhook-handler/tests/test_aiuibuilder_build.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_aiuibuilder_build.py`:

```python
@pytest.mark.asyncio
async def test_watch_build_notifies_on_completed():
    notified = []
    async def notify(msg):
        notified.append(msg)
    ctx = _ctx("100", "build x", [], notify=notify)
    tc = MagicMock()
    tc.get_build_status = AsyncMock(side_effect=[
        {"status": "running", "slug": "s"},
        {"status": "completed", "slug": "s",
         "preview_url": "https://ai-ui.coolestdomain.win/tasks/preview-app/s/"},
    ])
    r = _router({"100": "a@x.com"}, tc)
    await r._watch_build(ctx, "a@x.com", "t1", "s", poll_seconds=0, max_polls=5)
    assert len(notified) == 1
    assert "https://ai-ui.coolestdomain.win/tasks/preview-app/s/" in notified[0]


@pytest.mark.asyncio
async def test_watch_build_notifies_on_failed():
    notified = []
    async def notify(msg):
        notified.append(msg)
    ctx = _ctx("100", "build x", [], notify=notify)
    tc = MagicMock()
    tc.get_build_status = AsyncMock(return_value={"status": "failed", "slug": "s"})
    r = _router({"100": "a@x.com"}, tc)
    await r._watch_build(ctx, "a@x.com", "t1", "s", poll_seconds=0, max_polls=5)
    assert len(notified) == 1
    assert "failed" in notified[0].lower()


@pytest.mark.asyncio
async def test_watch_build_timeout_message():
    notified = []
    async def notify(msg):
        notified.append(msg)
    ctx = _ctx("100", "build x", [], notify=notify)
    tc = MagicMock()
    tc.get_build_status = AsyncMock(return_value={"status": "running", "slug": "s"})
    r = _router({"100": "a@x.com"}, tc)
    await r._watch_build(ctx, "a@x.com", "t1", "s", poll_seconds=0, max_polls=3)
    assert len(notified) == 1
    assert "still building" in notified[0].lower()


@pytest.mark.asyncio
async def test_watch_build_survives_transient_errors():
    notified = []
    async def notify(msg):
        notified.append(msg)
    ctx = _ctx("100", "build x", [], notify=notify)
    tc = MagicMock()
    tc.get_build_status = AsyncMock(side_effect=[
        TasksAPIError(0, "boom"),
        {"status": "completed", "slug": "s",
         "preview_url": "https://ai-ui.coolestdomain.win/tasks/preview-app/s/"},
    ])
    r = _router({"100": "a@x.com"}, tc)
    await r._watch_build(ctx, "a@x.com", "t1", "s", poll_seconds=0, max_polls=5)
    assert any("preview-app/s/" in m for m in notified)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd webhook-handler && python -m pytest tests/test_aiuibuilder_build.py -k watch -q`
Expected: FAIL — `AttributeError: 'CommandRouter' object has no attribute '_watch_build'`.

- [ ] **Step 3: Implement `_watch_build` + module constants**

Near the top of `commands.py` (after `logger = ...`), add:
```python
BUILD_POLL_SECONDS = 12
BUILD_MAX_POLLS = 150  # ~30 min at 12s
BUILD_MAX_CONSECUTIVE_ERRORS = 5
```
Add the method to `CommandRouter`:
```python
    async def _watch_build(
        self, ctx: CommandContext, email: str, task_id: str, slug: str,
        *, poll_seconds: int | None = None, max_polls: int | None = None,
    ) -> None:
        """Poll the build until it terminates, then post the result to the
        channel via ctx.notify_channel (bot-token message — outlives the
        interaction window). Defensive: transient errors don't kill the loop."""
        if ctx.notify_channel is None:
            return
        poll_seconds = BUILD_POLL_SECONDS if poll_seconds is None else poll_seconds
        max_polls = BUILD_MAX_POLLS if max_polls is None else max_polls
        errors = 0
        for _ in range(max_polls):
            await asyncio.sleep(poll_seconds)
            try:
                st = await self._tasks_client.get_build_status(email, task_id)
                errors = 0
            except TasksAPIError as e:
                errors += 1
                logger.warning("watch_build status error (%s) task=%s", e.status, task_id)
                if errors >= BUILD_MAX_CONSECUTIVE_ERRORS:
                    await ctx.notify_channel(
                        f"Lost track of `{slug}` — check `/aiui aiuibuilder status {slug}`."
                    )
                    return
                continue
            status = st.get("status")
            if status == "completed":
                url = st.get("preview_url") or ""
                await ctx.notify_channel(f"`{slug}` is ready: {url}".rstrip())
                return
            if status == "failed":
                await ctx.notify_channel(
                    f"Build failed for `{slug}`. Open the App Builder to retry."
                )
                return
        await ctx.notify_channel(
            f"`{slug}` is still building — check `/aiui aiuibuilder status {slug}`."
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd webhook-handler && python -m pytest tests/test_aiuibuilder_build.py -q`
Expected: PASS (all build + watch tests).

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/handlers/commands.py webhook-handler/tests/test_aiuibuilder_build.py
git commit -m "feat(bot): _watch_build background watcher posts build result to channel"
```

---

## Task 8: bot — wire `notify_channel` in the Discord handler

**Files:**
- Modify: `webhook-handler/handlers/discord_commands.py`
- Test: `webhook-handler/tests/test_discord_notify_wiring.py` (new)

- [ ] **Step 1: Write failing test**

```python
# webhook-handler/tests/test_discord_notify_wiring.py
"""DiscordCommandHandler wires ctx.notify_channel → post_channel_message."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from handlers.discord_commands import DiscordCommandHandler


@pytest.mark.asyncio
async def test_notify_channel_posts_to_channel(monkeypatch):
    discord = MagicMock()
    discord.edit_original = AsyncMock(return_value=True)
    discord.post_channel_message = AsyncMock(return_value=True)

    captured_ctx = {}
    async def fake_execute(ctx):
        captured_ctx["ctx"] = ctx
    router = MagicMock()
    router.execute = fake_execute

    handler = DiscordCommandHandler(discord_client=discord, command_router=router)
    payload = {
        "type": 2, "id": "i1", "token": "tok",
        "data": {"name": "aiui", "options": [
            {"name": "aiuibuilder", "type": 1,
             "options": [{"name": "args", "type": 3, "value": 'build "x"'}]}]},
        "member": {"user": {"id": "100", "username": "tester"}},
        "channel_id": "chan-123",
    }
    resp = await handler.handle_interaction(payload)
    assert resp["type"] == 5
    await asyncio.sleep(0)  # let the dispatched execute() run

    ctx = captured_ctx["ctx"]
    assert ctx.notify_channel is not None
    await ctx.notify_channel("hello")
    discord.post_channel_message.assert_awaited_once_with("chan-123", "hello")


@pytest.mark.asyncio
async def test_notify_channel_none_without_channel():
    discord = MagicMock()
    discord.edit_original = AsyncMock(return_value=True)
    captured_ctx = {}
    async def fake_execute(ctx):
        captured_ctx["ctx"] = ctx
    router = MagicMock(); router.execute = fake_execute
    handler = DiscordCommandHandler(discord_client=discord, command_router=router)
    payload = {
        "type": 2, "id": "i1", "token": "tok",
        "data": {"name": "aiui", "options": [
            {"name": "status", "type": 1, "options": []}]},
        "member": {"user": {"id": "100", "username": "t"}},
        # no channel_id
    }
    await handler.handle_interaction(payload)
    await asyncio.sleep(0)
    assert captured_ctx["ctx"].notify_channel is None
```

- [ ] **Step 2: Run to verify failure**

Run: `cd webhook-handler && python -m pytest tests/test_discord_notify_wiring.py -q`
Expected: FAIL — `ctx.notify_channel is None` (not wired yet).

- [ ] **Step 3: Wire it in `discord_commands.py`**

In `_handle_application_command`, after the `respond` closure and before building `ctx`, add a `notify_channel` closure; then pass it into `CommandContext` and set conditionally on `channel_id` truthiness:

```python
        async def notify_channel(msg: str) -> None:
            await self.discord.post_channel_message(channel_id, msg)

        ctx = CommandContext(
            user_id=user_id,
            user_name=user_name,
            channel_id=channel_id,
            raw_text=f"{subcommand} {arguments}".strip(),
            subcommand=subcommand,
            arguments=arguments,
            platform="discord",
            respond=respond,
            metadata={
                "interaction_id": payload.get("id", ""),
                "interaction_token": interaction_token,
                "guild_id": payload.get("guild_id", ""),
            },
            notify_channel=notify_channel if channel_id else None,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd webhook-handler && python -m pytest tests/test_discord_notify_wiring.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/handlers/discord_commands.py webhook-handler/tests/test_discord_notify_wiring.py
git commit -m "feat(bot): wire ctx.notify_channel → DiscordClient.post_channel_message"
```

---

## Task 9: bot — Layer-2 e2e (signed interaction → start_build, X-User-Email only)

**Files:**
- Modify: `webhook-handler/tests/test_discord_e2e_local.py`

- [ ] **Step 1: Add the failing e2e test**

Append a second test to `tests/test_discord_e2e_local.py` (reuse its module-level
stubs + keypair pattern). It signs an `aiuibuilder build "a todo app"` interaction,
mocks the tasks build POST + status GET and the Discord channel POST, and asserts the
build POST carried `X-User-Email` and no cron secret:

```python
@pytest.mark.asyncio
async def test_signed_aiuibuilder_build_reaches_start_build():
    import main as main_mod
    from config import settings
    from clients.discord import DiscordClient, DISCORD_API_BASE
    from clients.tasks import TasksClient
    from clients.openwebui import OpenWebUIClient
    from clients.n8n import N8NClient
    from handlers.commands import CommandRouter
    from handlers.discord_commands import DiscordCommandHandler

    sk = SigningKey.generate()
    original_public_key = settings.discord_public_key
    settings.discord_public_key = sk.verify_key.encode().hex()

    tasks_client = TasksClient(base_url=settings.tasks_url)
    router = CommandRouter(
        openwebui_client=OpenWebUIClient(base_url="http://noop", api_key=""),
        n8n_client=N8NClient(base_url="http://noop", api_key="", webhook_url="http://noop"),
        discord_user_email_map={"100": "e2e-test@local"},
        tasks_client=tasks_client,
    )
    discord_client = DiscordClient(application_id="test-app", bot_token="test-token")
    handler = DiscordCommandHandler(discord_client=discord_client, command_router=router)
    original_handler = main_mod.discord_command_handler
    main_mod.discord_command_handler = handler

    try:
        payload = {
            "type": 2, "id": "intx-2", "token": "intx-token-2",
            "data": {"name": "aiui", "options": [{
                "name": "aiuibuilder", "type": 1,
                "options": [{"name": "args", "type": 3, "value": 'build "a todo app"'}],
            }]},
            "member": {"user": {"id": "100", "username": "tester"}},
            "channel_id": "c1", "guild_id": "g1",
        }
        body = json.dumps(payload).encode()
        timestamp = "1234567890"
        sig = sk.sign(timestamp.encode() + body).signature.hex()

        transport = ASGITransport(app=main_mod.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            with respx.mock(assert_all_called=False) as mock:
                build_route = mock.post(
                    f"{settings.tasks_url}/api/aiuibuilder/build"
                ).mock(return_value=Response(201, json={
                    "task_id": "t1", "slug": "a-todo-app-a1b2", "status": "running"}))
                # status returns completed immediately so the watcher exits fast
                mock.get(
                    f"{settings.tasks_url}/api/aiuibuilder/build/t1"
                ).mock(return_value=Response(200, json={
                    "status": "completed", "slug": "a-todo-app-a1b2",
                    "preview_url": "https://x/p/", "error": None}))
                # intercept the eventual channel post (bot token)
                mock.post(f"{DISCORD_API_BASE}/channels/c1/messages").mock(
                    return_value=Response(200, json={"id": "m1"}))
                # intercept the deferred edit (followup webhook)
                mock.patch(
                    f"{DISCORD_API_BASE}/webhooks/test-app/intx-token-2/messages/@original"
                ).mock(return_value=Response(200, json={}))

                r = await client.post(
                    "/webhook/discord", content=body,
                    headers={
                        "Content-Type": "application/json",
                        "X-Signature-Ed25519": sig,
                        "X-Signature-Timestamp": timestamp,
                    },
                )
                assert r.status_code == 200, r.text
                assert r.json()["type"] == 5

                for _ in range(30):
                    await asyncio.sleep(0.01)
                    if build_route.called:
                        break
                assert build_route.called, "start_build must be called"
                req = build_route.calls.last.request
                assert req.headers.get("x-user-email") == "e2e-test@local"
                assert "x-cron-secret" not in {k.lower() for k in req.headers}
    finally:
        main_mod.discord_command_handler = original_handler
        settings.discord_public_key = original_public_key
```

- [ ] **Step 2: Run to verify it passes (feature already built in Tasks 4–8)**

Run: `cd webhook-handler && python -m pytest tests/test_discord_e2e_local.py -q`
Expected: PASS (2 passed). If it fails on the watcher posting to a non-mocked URL,
confirm all four respx routes above are registered.

- [ ] **Step 3: Run the FULL bot suite (regression gate)**

Run: `cd webhook-handler && python -m pytest tests/ -q`
Expected: PASS (all — was 41, now ~41 + new).

- [ ] **Step 4: Commit**

```bash
git add webhook-handler/tests/test_discord_e2e_local.py
git commit -m "test(bot): Layer-2 e2e — signed aiuibuilder build reaches start_build (X-User-Email only)"
```

---

## Task 10: live smoke + deploy + real Discord verification

**Files:**
- Modify: `scripts/e2e_backend_smoke.py`

- [ ] **Step 1: Extend the live smoke (auth/mount checks only — no real agent run)**

Append to `scripts/e2e_backend_smoke.py` `main()` (it already uses `c` + `EMAIL`/`BASE`):

```python
        print("\n=== 7) GET /api/aiuibuilder/build/<random> (mounted + owner-scoped) ===")
        import uuid as _uuid
        rid = str(_uuid.uuid4())
        r = await c.get(f"{BASE}/api/aiuibuilder/build/{rid}", headers={"X-User-Email": EMAIL})
        print(f"  status={r.status_code} (expect 404 — unknown id)")

        print("\n=== 8) same WITHOUT X-User-Email should 401 ===")
        r = await c.get(f"{BASE}/api/aiuibuilder/build/{rid}")
        print(f"  status={r.status_code} (expect 401)")
```

- [ ] **Step 2: Run the full local suites one last time (both green)**

```bash
cd webhook-handler && python -m pytest tests/ -q
cd ../mcp-servers/tasks && DATABASE_URL="postgresql+asyncpg://nope/nope" python -m pytest tests/test_routes_aiuibuilder.py -q
```
Expected: all PASS.

- [ ] **Step 3: Deploy to Hetzner (Workflow A — individual SCP, then rebuild the two services)**

```bash
SRV=root@46.224.193.25
DST=/root/proxy-server
scp mcp-servers/tasks/routes_aiuibuilder.py        $SRV:$DST/mcp-servers/tasks/routes_aiuibuilder.py
scp mcp-servers/tasks/main.py                      $SRV:$DST/mcp-servers/tasks/main.py
scp webhook-handler/clients/tasks.py               $SRV:$DST/webhook-handler/clients/tasks.py
scp webhook-handler/clients/discord.py             $SRV:$DST/webhook-handler/clients/discord.py
scp webhook-handler/handlers/commands.py           $SRV:$DST/webhook-handler/handlers/commands.py
scp webhook-handler/handlers/discord_commands.py   $SRV:$DST/webhook-handler/handlers/discord_commands.py
ssh $SRV "cd $DST && docker compose -f docker-compose.unified.yml up -d --build tasks webhook-handler"
```

- [ ] **Step 4: Health + live smoke on the server**

```bash
ssh root@46.224.193.25 "curl -sf http://localhost:8210/healthz && echo OK"
ssh root@46.224.193.25 "docker exec -i webhook-handler python - < /dev/stdin" < scripts/e2e_backend_smoke.py
```
Expected: `/healthz` OK; smoke step 7 → 404, step 8 → 401, earlier steps green.

- [ ] **Step 5: Real Discord verification (the true e2e)**

In Discord, run:
```
/aiui aiuibuilder build a tiny landing page that says hello world
```
Expected: bot replies "Building `<slug>` …"; within a few minutes a follow-up
appears in the channel: "`<slug>` is ready: https://ai-ui.coolestdomain.win/tasks/preview-app/<slug>/".
Then confirm `/aiui aiuibuilder list` shows the new app and `status <slug>` reports it.

- [ ] **Step 6: Commit + push**

```bash
git add scripts/e2e_backend_smoke.py
git commit -m "test(scripts): live smoke for /api/aiuibuilder/build mount + auth"
git push origin feat/vm-agent-flight-mcp
```

> **Do NOT push `.env` or any secrets.** Only the files listed above. `.env` stays on the server.

---

## Definition of Done

- [ ] `routes_aiuibuilder.py` mounted; `POST /build` (user-scoped, 1-at-a-time, 429 when busy) and `GET /build/{task_id}` (owner-scoped, 404 on miss/cross-user) live.
- [ ] Bot `build` action fires the build, acks immediately, and the watcher posts the preview link (or failure) to the channel.
- [ ] `X-User-Email` only end-to-end — no `X-Cron-Secret`, no admin header (asserted in tests).
- [ ] All local tests green (bot suite + tasks aiuibuilder suite). No regressions in existing aiuibuilder/list tests.
- [ ] Deployed; `/healthz` + live smoke green; one real Discord build produced a working preview link.
- [ ] Pushed to `feat/vm-agent-flight-mcp`. No secrets committed.
