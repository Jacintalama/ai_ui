# Discord App Builder — Publish — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a Discord user publish an app they built, via a **Publish** button on the bot's build-ready message — no web App Builder needed.

**Architecture:** Add a user-scoped (ownership-checked) publish endpoint to the tasks service by extracting the existing admin publish logic into a shared helper. On the webhook-handler side, the build-ready message gains a Publish button (+ Open-preview link); clicking it routes through the existing component-interaction dispatch to a new `run_panel_publish` that calls the new endpoint.

**Tech Stack:** Python 3, FastAPI, httpx, pytest + pytest-asyncio (`asyncio_mode = auto`), Discord HTTP API v10. webhook-handler tests run locally in `webhook-handler/.venv`; the tasks-service DB test needs PostgreSQL (runs in the tasks container / a test DB, not on the local Windows machine).

---

## File Structure

- **Modify** `mcp-servers/tasks/routes_projects.py` — extract `_publish_slug(s, slug, email, *, is_admin)`; admin `publish_app` calls it.
- **Modify** `mcp-servers/tasks/routes_aiuibuilder.py` — add user-scoped `POST /api/aiuibuilder/{slug}/publish`.
- **Create** `mcp-servers/tasks/tests/test_routes_aiuibuilder_publish.py` — DB-backed endpoint test (Postgres env).
- **Modify** `webhook-handler/handlers/app_builder_panel.py` — `build_ready_components`, `PUBLISH_PREFIX`, `is_publish_button`, `slug_from_publish_button`, `STYLE_LINK`.
- **Modify** `webhook-handler/clients/tasks.py` — `TasksClient.publish_app`.
- **Modify** `webhook-handler/handlers/commands.py` — `CommandContext.notify_channel_rich`; `run_panel_publish` + `_format_publish_error`; `_watch_build` completion uses the rich notifier.
- **Modify** `webhook-handler/handlers/discord_commands.py` — set `notify_channel_rich` in the slash + modal paths (via a small helper); dispatch `aiuibuild:publish:` in `_handle_message_component`.
- **Tests (local):** `tests/test_app_builder_panel.py`, `tests/test_tasks_client.py`, `tests/test_panel_build.py`, `tests/test_app_builder_interactions.py`.

**webhook-handler test command (from the `webhook-handler` dir):**
`& "C:\Users\Acer Philippines\Desktop\Lukas Project\ai_ui\webhook-handler\.venv\Scripts\python.exe" -m pytest -q`

---

## Task 1: Tasks service — user-scoped publish endpoint

**Files:**
- Modify: `mcp-servers/tasks/routes_projects.py` (extract helper from `publish_app`, ~lines 741-785)
- Modify: `mcp-servers/tasks/routes_aiuibuilder.py` (add route + imports)
- Test: `mcp-servers/tasks/tests/test_routes_aiuibuilder_publish.py` (Postgres env)

> **Note on running tests:** This task's test needs PostgreSQL (`db_session` truncates `tasks.*`). It runs inside the tasks container or against a dedicated test DB with `AIUI_TEST_DB=1` and a DB name containing `test`. It will NOT run on the local Windows machine. Implement it correctly; final verification is end-to-end after deploy (Task 6).

- [ ] **Step 1: Extract `_publish_slug` in `routes_projects.py`**

Replace the body of the existing admin route (currently `routes_projects.py` ~lines 741-785) so the route delegates to a new module-level helper. Add this helper immediately ABOVE the `@router.post("/{slug}/publish")` decorator:

```python
async def _publish_slug(s, slug: str, email: str, *, is_admin: bool) -> PublishStatus:
    """Core publish logic, shared by the admin route and the user-scoped
    aiuibuilder route. Validates the slug, enforces project ownership
    (admins bypass via is_admin), verifies apps/<slug>/index.html exists, and
    idempotently inserts a PublishedApp row. Returns the publish status."""
    _validate_slug(slug)
    if not await _user_can_see_project(s, slug, email):
        raise HTTPException(status_code=403, detail="Not a member of this project")
    await _require_role(s, slug, email, "owner", is_admin=is_admin)

    index_path = os.path.join(REPO_ROOT, "apps", slug, "index.html")
    if not os.path.isfile(index_path):
        raise HTTPException(
            status_code=400,
            detail=f"apps/{slug}/index.html not found — only static apps with index.html are publishable today.",
        )

    existing = (
        await s.execute(select(PublishedApp).where(PublishedApp.slug == slug))
    ).scalar_one_or_none()
    if existing:
        return PublishStatus(
            published=True,
            public_url=_public_url_for(slug),
            published_at=existing.published_at.isoformat() if existing.published_at else None,
            published_by=existing.published_by,
        )
    row = PublishedApp(slug=slug, published_by=email, public_host=_public_host_for(slug))
    s.add(row)
    await s.commit()
    await s.refresh(row)
    return PublishStatus(
        published=True,
        public_url=_public_url_for(slug),
        published_at=row.published_at.isoformat() if row.published_at else None,
        published_by=row.published_by,
    )
```

Then replace the admin route body with:

```python
@router.post("/{slug}/publish", response_model=PublishStatus)
async def publish_app(slug: str, user: AdminUser = Depends(current_admin)):
    """Publish apps/<slug>/ at https://<slug>.ai-ui.coolestdomain.win/.

    Owner/admin only. The Caddy wildcard handler reverse-proxies the
    subdomain back into this service's /__public/<slug>/ static route.
    """
    async with session() as s:
        return await _publish_slug(s, slug, user.email, is_admin=user.is_admin)
```

(The `_validate_slug`, `_user_can_see_project`, `_require_role`, `_public_url_for`, `_public_host_for`, `PublishStatus`, `PublishedApp`, `REPO_ROOT`, `session`, `select`, `os`, `HTTPException` references all already exist in this module.)

- [ ] **Step 2: Add the user-scoped route in `routes_aiuibuilder.py`**

At the top of `mcp-servers/tasks/routes_aiuibuilder.py`, add this import near the other imports (after `from templates import is_valid_key`):

```python
from routes_projects import _publish_slug, PublishStatus
```

(No circular import: `routes_projects` does not import `routes_aiuibuilder`.)

Then add this route at the END of the file (after `get_build_status`):

```python
@router.post("/{slug}/publish", response_model=PublishStatus)
async def publish_built_app(slug: str, user: CurrentUser = Depends(current_user)):
    """User-scoped publish for a Discord-built app. Ownership-enforced (the
    builder is auto-added as owner on completion, and _require_role also treats
    the original build assignee as an implicit owner), so a normal user — not an
    admin — can publish their own app. Reuses the shared _publish_slug core."""
    async with session() as s:
        return await _publish_slug(s, slug, user.email, is_admin=False)
```

(`CurrentUser`, `current_user`, `session`, `APIRouter` `router` with prefix `/api/aiuibuilder` already exist in this module. Final path: `POST /api/aiuibuilder/{slug}/publish`.)

- [ ] **Step 3: Write the DB-backed test** `mcp-servers/tasks/tests/test_routes_aiuibuilder_publish.py`:

```python
"""User-scoped publish endpoint POST /api/aiuibuilder/{slug}/publish.

DB-backed (needs Postgres + the db_session fixture). Mirrors
test_publish_access_gate.py's harness.
"""
from cryptography.fernet import Fernet as _Fernet
_AIUI_TEST_KEY = _Fernet.generate_key().decode()

import os
os.environ.setdefault("AIUI_FERNET_KEY", _AIUI_TEST_KEY)

import uuid
import pytest
from httpx import ASGITransport, AsyncClient

import routes_projects
from main import app
from models import PublishedApp, TaskItem


@pytest.fixture
def transport():
    return ASGITransport(app=app)


def _stage_app(tmp_path, slug):
    d = tmp_path / "apps" / slug
    d.mkdir(parents=True)
    (d / "index.html").write_text("<html><body>app</body></html>")


async def _make_owner_task(db_session, slug, email):
    """Insert a completed BUILD task so `email` is the implicit owner of slug."""
    db_session.add(TaskItem(
        meeting_id=uuid.uuid4(), action_type="BUILD",
        assignee_name=email.split("@")[0], assignee_email=email,
        description="x", priority="NICE_TO_HAVE", status="completed",
        mode="ai", max_attempts=3, built_app_slug=slug,
    ))
    await db_session.commit()


async def test_owner_can_publish(db_session, transport, tmp_path, monkeypatch):
    monkeypatch.setattr(routes_projects, "REPO_ROOT", str(tmp_path))
    _stage_app(tmp_path, "alpha")
    await _make_owner_task(db_session, "alpha", "alice@x.com")

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/aiuibuilder/alpha/publish",
                         headers={"X-User-Email": "alice@x.com"})
    assert r.status_code == 200
    body = r.json()
    assert body["published"] is True
    assert body["public_url"] == "https://alpha.ai-ui.coolestdomain.win/"
    row = (await db_session.execute(
        __import__("sqlalchemy").select(PublishedApp).where(PublishedApp.slug == "alpha")
    )).scalar_one_or_none()
    assert row is not None


async def test_non_owner_rejected(db_session, transport, tmp_path, monkeypatch):
    monkeypatch.setattr(routes_projects, "REPO_ROOT", str(tmp_path))
    _stage_app(tmp_path, "alpha")
    await _make_owner_task(db_session, "alpha", "alice@x.com")

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/aiuibuilder/alpha/publish",
                         headers={"X-User-Email": "mallory@x.com"})
    assert r.status_code in (403, 404)
    assert "alpha.ai-ui" not in r.text


async def test_missing_index_html_400(db_session, transport, tmp_path, monkeypatch):
    monkeypatch.setattr(routes_projects, "REPO_ROOT", str(tmp_path))
    # No _stage_app → no index.html on disk.
    await _make_owner_task(db_session, "alpha", "alice@x.com")

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/aiuibuilder/alpha/publish",
                         headers={"X-User-Email": "alice@x.com"})
    assert r.status_code == 400


async def test_publish_is_idempotent(db_session, transport, tmp_path, monkeypatch):
    monkeypatch.setattr(routes_projects, "REPO_ROOT", str(tmp_path))
    _stage_app(tmp_path, "alpha")
    await _make_owner_task(db_session, "alpha", "alice@x.com")

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r1 = await c.post("/api/aiuibuilder/alpha/publish", headers={"X-User-Email": "alice@x.com"})
        r2 = await c.post("/api/aiuibuilder/alpha/publish", headers={"X-User-Email": "alice@x.com"})
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["public_url"] == r2.json()["public_url"]
```

- [ ] **Step 4: Run the test in a Postgres env** (tasks container or test DB):

Run: `AIUI_TEST_DB=1 DATABASE_URL=postgresql://.../...test... python -m pytest tests/test_routes_aiuibuilder_publish.py -v`
Expected: 4 passed. (Cannot run on the local Windows machine — no Postgres. If no test DB is available now, defer to the post-deploy end-to-end check in Task 6.)

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/routes_projects.py mcp-servers/tasks/routes_aiuibuilder.py mcp-servers/tasks/tests/test_routes_aiuibuilder_publish.py
git commit -m "feat(tasks): user-scoped publish endpoint for Discord app builds

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: webhook-handler — ready-message buttons (pure)

**Files:**
- Modify: `webhook-handler/handlers/app_builder_panel.py`
- Test: `webhook-handler/tests/test_app_builder_panel.py`

- [ ] **Step 1: Add failing tests** — append to `webhook-handler/tests/test_app_builder_panel.py`:

```python
from handlers.app_builder_panel import (
    build_ready_components, is_publish_button, slug_from_publish_button,
    PUBLISH_PREFIX, STYLE_SUCCESS, STYLE_LINK, ACTION_ROW, BUTTON,
)


def test_ready_components_has_publish_and_preview():
    rows = build_ready_components("portfolio-ab12", "https://x/preview/portfolio-ab12/")
    assert rows[0]["type"] == ACTION_ROW
    btns = rows[0]["components"]
    pub = btns[0]
    assert pub["custom_id"] == f"{PUBLISH_PREFIX}portfolio-ab12"
    assert pub["style"] == STYLE_SUCCESS
    link = btns[1]
    assert link["style"] == STYLE_LINK
    assert link["url"] == "https://x/preview/portfolio-ab12/"
    assert "custom_id" not in link  # link buttons must not carry a custom_id


def test_ready_components_without_preview_has_only_publish():
    rows = build_ready_components("slug-1", "")
    btns = rows[0]["components"]
    assert len(btns) == 1
    assert btns[0]["custom_id"] == f"{PUBLISH_PREFIX}slug-1"


def test_publish_button_parsers():
    assert is_publish_button(f"{PUBLISH_PREFIX}slug-1")
    assert not is_publish_button("aiuibuild:tpl:portfolio")
    assert slug_from_publish_button(f"{PUBLISH_PREFIX}slug-1") == "slug-1"
    import pytest
    with pytest.raises(ValueError):
        slug_from_publish_button("aiuibuild:tpl:x")
```

- [ ] **Step 2: Run, confirm fail** — `pytest tests/test_app_builder_panel.py -q` → ImportError on `build_ready_components`.

- [ ] **Step 3: Implement** — add to `webhook-handler/handlers/app_builder_panel.py` (after the existing style constants add `STYLE_LINK`, and append the new functions + prefix):

```python
STYLE_LINK = 5       # link button (opens a URL; carries `url`, not custom_id)
```

```python
PUBLISH_PREFIX = "aiuibuild:publish:"  # ready-msg button -> aiuibuild:publish:<slug>


def build_ready_components(slug: str, preview_url: str = "") -> list[dict]:
    """Action row for the build-ready message: a green Publish button, plus an
    'Open preview' link button when a preview_url is available. Link buttons
    carry `url` and must NOT carry a custom_id."""
    buttons: list[dict] = [
        {"type": BUTTON, "style": STYLE_SUCCESS, "label": "\U0001f7e2 Publish",
         "custom_id": f"{PUBLISH_PREFIX}{slug}"},
    ]
    if preview_url:
        buttons.append({"type": BUTTON, "style": STYLE_LINK,
                        "label": "\U0001f517 Open preview", "url": preview_url})
    return [{"type": ACTION_ROW, "components": buttons}]


def is_publish_button(custom_id: str) -> bool:
    return custom_id.startswith(PUBLISH_PREFIX)


def slug_from_publish_button(custom_id: str) -> str:
    """Publish-button custom_id -> slug. Raises ValueError if not a publish id."""
    if not is_publish_button(custom_id):
        raise ValueError(f"not a publish button custom_id: {custom_id!r}")
    return custom_id[len(PUBLISH_PREFIX):]
```

- [ ] **Step 4: Run, confirm pass** — `pytest tests/test_app_builder_panel.py -q` → all pass.

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/handlers/app_builder_panel.py webhook-handler/tests/test_app_builder_panel.py
git commit -m "feat(discord): build-ready Publish/Open-preview button builder

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: webhook-handler — `TasksClient.publish_app`

**Files:**
- Modify: `webhook-handler/clients/tasks.py`
- Test: `webhook-handler/tests/test_tasks_client.py`

- [ ] **Step 1: Add failing test** — append to `webhook-handler/tests/test_tasks_client.py`:

```python
@pytest.mark.asyncio
async def test_publish_app_posts_and_returns_status():
    import respx, httpx
    from clients.tasks import TasksClient
    client = TasksClient(base_url="http://tasks-test:8210")
    with respx.mock:
        route = respx.post("http://tasks-test:8210/api/aiuibuilder/portfolio-ab12/publish").mock(
            return_value=httpx.Response(200, json={
                "published": True,
                "public_url": "https://portfolio-ab12.ai-ui.coolestdomain.win/",
            })
        )
        out = await client.publish_app("alice@x.com", "portfolio-ab12")
    assert route.called
    assert route.calls[0].request.headers["X-User-Email"] == "alice@x.com"
    assert out["public_url"] == "https://portfolio-ab12.ai-ui.coolestdomain.win/"
```

(If `test_tasks_client.py` lacks `import pytest`, add it at the top.)

- [ ] **Step 2: Run, confirm fail** — `pytest tests/test_tasks_client.py -q` → `AttributeError: ... no attribute 'publish_app'`.

- [ ] **Step 3: Implement** — add this method to `TasksClient` in `webhook-handler/clients/tasks.py` (after `get_build_status`):

```python
    async def publish_app(self, user_email: str, slug: str) -> dict[str, Any]:
        resp = await self._request(
            "POST", f"/api/aiuibuilder/{slug}/publish", user_email,
        )
        return resp.json()
```

- [ ] **Step 4: Run, confirm pass** — `pytest tests/test_tasks_client.py -q` → all pass.

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/clients/tasks.py webhook-handler/tests/test_tasks_client.py
git commit -m "feat(discord): TasksClient.publish_app

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: webhook-handler — `run_panel_publish` + error mapping

**Files:**
- Modify: `webhook-handler/handlers/commands.py` (add 2 methods near `run_panel_build` / `_format_build_error`)
- Test: `webhook-handler/tests/test_panel_build.py`

- [ ] **Step 1: Add failing tests** — append to `webhook-handler/tests/test_panel_build.py`:

```python
@pytest.mark.asyncio
async def test_publish_unmapped_user_rejected():
    captured = []
    await _router({}, MagicMock()).run_panel_publish(_ctx("9", captured), "slug-1")
    assert any("isn't linked" in m for m in captured)


@pytest.mark.asyncio
async def test_publish_happy_path():
    captured = []
    tc = MagicMock()
    tc.publish_app = AsyncMock(return_value={
        "published": True, "public_url": "https://slug-1.ai-ui.coolestdomain.win/"})
    await _router({"100": "a@x.com"}, tc).run_panel_publish(_ctx("100", captured), "slug-1")
    tc.publish_app.assert_awaited_once_with("a@x.com", "slug-1")
    assert any("Published" in m and "https://slug-1.ai-ui.coolestdomain.win/" in m for m in captured)


@pytest.mark.asyncio
async def test_publish_non_owner_403():
    captured = []
    tc = MagicMock()
    tc.publish_app = AsyncMock(side_effect=TasksAPIError(403, "denied"))
    await _router({"100": "a@x.com"}, tc).run_panel_publish(_ctx("100", captured), "slug-1")
    assert any("owner" in m.lower() for m in captured)


@pytest.mark.asyncio
async def test_publish_no_index_400():
    captured = []
    tc = MagicMock()
    tc.publish_app = AsyncMock(side_effect=TasksAPIError(400, "no index"))
    await _router({"100": "a@x.com"}, tc).run_panel_publish(_ctx("100", captured), "slug-1")
    assert any("index.html" in m.lower() or "publishable" in m.lower() for m in captured)
```

- [ ] **Step 2: Run, confirm fail** — `pytest tests/test_panel_build.py -q` → `AttributeError: ... no attribute 'run_panel_publish'`.

- [ ] **Step 3: Implement** — in `webhook-handler/handlers/commands.py`, add these two methods immediately AFTER `run_panel_build` (before `_format_tasks_error`):

```python
    async def run_panel_publish(self, ctx: CommandContext, slug: str) -> None:
        """App Builder channel entry for the Publish button. Resolves the
        caller's email and publishes their built app, then posts the live URL.
        Ownership is enforced server-side (only the app's owner can publish)."""
        email = self._discord_user_email_map.get(ctx.user_id)
        if not email:
            await ctx.respond(
                "Your Discord account isn't linked. Ask Lukas to add you."
            )
            return
        try:
            result = await self._tasks_client.publish_app(email, slug)
        except TasksAPIError as e:
            await ctx.respond(self._format_publish_error(e))
            return
        url = (result.get("public_url") or "").strip()
        await ctx.respond(f"\U0001f389 Published! Live at {url}".rstrip())

    def _format_publish_error(self, e: TasksAPIError) -> str:
        """Publish-flavored error text."""
        if e.status == 0:
            return "Tasks service unreachable, try again."
        if e.status == 403:
            return "Only the app's owner can publish it."
        if e.status == 404:
            return "Project not found or not yours."
        if e.status in (400, 422):
            return "This app isn't publishable yet (it needs an index.html)."
        return f"Couldn't publish (error {e.status})."
```

- [ ] **Step 4: Run, confirm pass** — `pytest tests/test_panel_build.py -q` → all pass.

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/handlers/commands.py webhook-handler/tests/test_panel_build.py
git commit -m "feat(discord): run_panel_publish + publish error mapping

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: webhook-handler — wire the Publish button end to end

**Files:**
- Modify: `webhook-handler/clients/discord.py` (`post_channel_message` gains `components`)
- Modify: `webhook-handler/handlers/commands.py` (`CommandContext.notify_channel_rich`; `_watch_build` completion)
- Modify: `webhook-handler/handlers/discord_commands.py` (set `notify_channel_rich`; dispatch publish button; copy in `open`/`help` is in commands.py — see Step 6)
- Test: `webhook-handler/tests/test_app_builder_interactions.py`

- [ ] **Step 1: Add failing test** — append to `webhook-handler/tests/test_app_builder_interactions.py`:

```python
from handlers.app_builder_panel import PUBLISH_PREFIX


@pytest.mark.asyncio
async def test_publish_button_routes_publish():
    captured = {}
    async def fake_pub(ctx, slug):
        captured.update(ctx=ctx, slug=slug)
    router = MagicMock(); router.run_panel_publish = fake_pub
    handler = _handler(router)
    payload = {
        "type": 3, "id": "i", "token": "tok",
        "data": {"custom_id": f"{PUBLISH_PREFIX}portfolio-ab12"},
        "member": {"user": {"id": "100", "username": "maya"}},
        "channel_id": "chan-1",
    }
    resp = await handler.handle_interaction(payload)
    assert resp["type"] == 5  # deferred ACK
    await asyncio.sleep(0)
    assert captured["slug"] == "portfolio-ab12"
    assert captured["ctx"].user_id == "100"
```

- [ ] **Step 2: Run, confirm fail** — `pytest tests/test_app_builder_interactions.py -q` → `test_publish_button_routes_publish` fails (the unknown-component branch returns `{"type": 6}`, and `run_panel_publish` is never called).

- [ ] **Step 3: `post_channel_message` accepts components** — in `webhook-handler/clients/discord.py`, replace the `post_channel_message` method signature/body so it optionally sends components:

```python
    async def post_channel_message(self, channel_id: str, content: str,
                                   components: list | None = None) -> bool:
        """Post a fresh message to a channel using the bot token.

        Unlike followup_message/edit_original (interaction token, 15-min TTL),
        this works indefinitely — used to report a build result that may finish
        after the interaction window closes. Optionally attaches message
        `components` (e.g. a Publish button). Requires the bot to have Send
        Messages in the channel. Never raises.
        """
        content = content[:2000]
        url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages"
        body: dict = {"content": content}
        if components:
            body["components"] = components
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    url,
                    headers={"Authorization": f"Bot {self.bot_token}"},
                    json=body,
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

- [ ] **Step 4: Add `notify_channel_rich` to `CommandContext`** — in `webhook-handler/handlers/commands.py`, add a field to the dataclass (after `notify_channel`):

```python
    notify_channel: Optional[Callable[[str], Awaitable[None]]] = None
    # (message, slug, preview_url) -> post a rich channel message (e.g. with a
    # Publish button). Set by the Discord layer; None on other platforms.
    notify_channel_rich: Optional[Callable[[str, str, str], Awaitable[None]]] = None
```

- [ ] **Step 5: `_watch_build` completion uses the rich notifier** — in `webhook-handler/handlers/commands.py`, replace the `if status == "completed":` block inside `_watch_build`:

```python
            if status == "completed":
                url = st.get("preview_url") or ""
                msg = f"`{slug}` is ready (preview): {url}".rstrip()
                if ctx.notify_channel_rich is not None:
                    try:
                        await ctx.notify_channel_rich(msg, slug, url)
                    except Exception as exc:  # noqa: BLE001
                        logger.error("watch_build rich notify failed task=%s: %s", task_id, exc)
                        await _notify(msg)
                else:
                    await _notify(msg)
                return
```

- [ ] **Step 6: Update `open`/`help` copy** — in `webhook-handler/handlers/commands.py`:

In `_handle_aiuibuilder`, the `open` branch currently replies (when not published):
```python
                    await ctx.respond(
                        f"`{slug}` is not published yet. Publish it from the App Builder UI first."
                    )
```
Replace with:
```python
                    await ctx.respond(
                        f"`{slug}` isn't published yet. Click **Publish** on its build "
                        "message, or rebuild it to get a fresh Publish button."
                    )
```

In `_handle_help`, change the aiuibuilder help line to mention publish:
```python
            "`/aiui aiuibuilder <build|templates|list|status|open>` — Build (optionally from a template) & manage your apps\n"
```
→
```python
            "`/aiui aiuibuilder <build|templates|list|status|open>` — Build, then **Publish** from the build message to go live\n"
```

- [ ] **Step 7: Set `notify_channel_rich` + dispatch the publish button** — in `webhook-handler/handlers/discord_commands.py`:

(a) Add the import to the existing `from handlers.app_builder_panel import (...)` block:
```python
    is_publish_button,
    slug_from_publish_button,
    build_ready_components,
```

(b) Add a helper method to `DiscordCommandHandler` (place it just above `_handle_message_component`):
```python
    def _channel_notifiers(self, channel_id: str):
        """Build the plain + rich channel notifiers for a ctx. The rich one
        posts a build-ready message with a Publish button. Both None-safe via
        the caller (only set when channel_id is truthy)."""
        async def notify_channel(msg: str) -> None:
            await self.discord.post_channel_message(channel_id, msg)

        async def notify_channel_rich(msg: str, slug: str, preview_url: str) -> None:
            await self.discord.post_channel_message(
                channel_id, msg, components=build_ready_components(slug, preview_url),
            )
        return notify_channel, notify_channel_rich
```

(c) In `_handle_application_command` and `_handle_modal_submit`, where the ctx is built, set BOTH notifiers. Replace the inline `notify_channel` closure + the `notify_channel=notify_channel if channel_id else None,` line in EACH of those methods with:
```python
        notify_channel, notify_channel_rich = self._channel_notifiers(channel_id)
```
and in the `CommandContext(...)` constructor add:
```python
            notify_channel=notify_channel if channel_id else None,
            notify_channel_rich=notify_channel_rich if channel_id else None,
```
(Remove the now-duplicate inline `async def notify_channel` definitions in those two methods.)

(d) In `_handle_message_component`, add a publish branch BEFORE the `is_panel_button` handling so publish buttons route to publish:
```python
        if is_publish_button(custom_id):
            return await self._handle_publish_component(payload, custom_id)
        if not is_panel_button(custom_id):
            logger.info(f"Ignoring unknown component custom_id: {custom_id}")
            return {"type": DEFERRED_UPDATE_MESSAGE}
        template_key = template_key_from_button(custom_id)
        logger.info(f"App Builder button clicked: template={template_key}")
        return {"type": MODAL, "data": build_modal_payload(template_key)}
```

(e) Add the publish-component handler method (place after `_handle_message_component`):
```python
    async def _handle_publish_component(self, payload: dict[str, Any], custom_id: str) -> dict[str, Any]:
        """A Publish button click. Route to run_panel_publish in the background,
        ACK deferred — mirrors the modal-submit pattern."""
        slug = slug_from_publish_button(custom_id)
        interaction_token = payload.get("token", "")
        member = payload.get("member", {})
        user = member.get("user", payload.get("user", {}))
        user_id = user.get("id", "")
        user_name = user.get("username", "unknown")
        channel_id = payload.get("channel_id", "")

        async def respond(msg: str) -> None:
            await self.discord.edit_original(
                interaction_token=interaction_token, content=msg,
            )

        ctx = CommandContext(
            user_id=user_id,
            user_name=user_name,
            channel_id=channel_id,
            raw_text=f"aiuibuilder publish {slug}",
            subcommand="aiuibuilder",
            arguments="",
            platform="discord",
            respond=respond,
            metadata={
                "interaction_id": payload.get("id", ""),
                "interaction_token": interaction_token,
                "guild_id": payload.get("guild_id", ""),
            },
        )
        asyncio.create_task(self.router.run_panel_publish(ctx, slug))
        return {"type": DEFERRED_CHANNEL_MESSAGE}
```

- [ ] **Step 8: Run the targeted tests** — `pytest tests/test_app_builder_interactions.py tests/test_discord_notify_wiring.py -q` → all pass (the publish dispatch test passes; existing slash/modal wiring still green — note `test_discord_notify_wiring.py` checks `notify_channel`, which is still set).

- [ ] **Step 9: Run the FULL local suite** — `pytest -q` from `webhook-handler/` → all green (was 94; expect 94 + new tests).

- [ ] **Step 10: Commit**

```bash
git add webhook-handler/clients/discord.py webhook-handler/handlers/commands.py webhook-handler/handlers/discord_commands.py webhook-handler/tests/test_app_builder_interactions.py
git commit -m "feat(discord): Publish button on build-ready message, wired end to end

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Full verification

**Files:** none (verification only)

- [ ] **Step 1: Local webhook-handler suite green** — from `webhook-handler/`: `& "...\.venv\Scripts\python.exe" -m pytest -q`. Expected: all pass, no regressions.
- [ ] **Step 2: Tasks tests** — if a Postgres test DB is available, run `tests/test_routes_aiuibuilder_publish.py` there (Task 1 Step 4). Otherwise note it's deferred to the post-deploy end-to-end check.
- [ ] **Step 3: Fix any reds** with the systematic-debugging skill before proceeding. Don't weaken tests to pass.
- [ ] **Step 4: Final commit** (only if Step 3 changed anything):

```bash
git add -A
git commit -m "test(discord): green publish-from-Discord suite"
```

---

## Deployment (after merge)

Two services change, so deploy is two-part (per `CLAUDE.md`):
1. **tasks (backend):** `ORCH_HOST=46.224.193.25 ./scripts/deploy_orchestrator.sh` (it watches `mcp-servers/`). NEVER deploy local `templates.py`.
2. **webhook-handler (Discord bot):** one `scp` per changed file (`clients/discord.py`, `clients/tasks.py`, `handlers/app_builder_panel.py`, `handlers/commands.py`, `handlers/discord_commands.py`), then `docker compose -f docker-compose.unified.yml up -d --build webhook-handler`.

Verify: `curl -fsS https://ai-ui.coolestdomain.win/tasks/healthz`; bot `Up`; then run a real build in `#app-builder` and click **Publish** → confirm it goes live at `https://<slug>.ai-ui.coolestdomain.win/`. This live click is the authoritative test of the tasks publish endpoint (since its DB test can't run on the local machine).

---

## Self-Review Notes

- **Spec coverage:** user-scoped endpoint via shared `_publish_slug` (Task 1); `TasksClient.publish_app` (Task 3); pure `build_ready_components` + parsers (Task 2); ready message carries buttons via `notify_channel_rich` (Task 5 Steps 4-5); publish-button dispatch + `run_panel_publish` (Tasks 4, 5); copy updates (Task 5 Step 6); errors (Task 4 `_format_publish_error`); tests across both services (Tasks 1-5); deploy two-part (Deployment section). Out-of-scope items (chat, unpublish, domains) intentionally absent. ✔
- **Type/name consistency:** `PUBLISH_PREFIX`, `build_ready_components(slug, preview_url)`, `is_publish_button`, `slug_from_publish_button`, `STYLE_LINK`, `TasksClient.publish_app(user_email, slug)`, `run_panel_publish(ctx, slug)`, `_format_publish_error`, `notify_channel_rich(msg, slug, preview_url)`, `_channel_notifiers`, `_handle_publish_component`, `_publish_slug(s, slug, email, *, is_admin)` — consistent across tasks. ✔
- **No placeholders:** every step has concrete code/commands. ✔
