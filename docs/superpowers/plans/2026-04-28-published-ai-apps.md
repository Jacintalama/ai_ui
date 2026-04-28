# Published AI Apps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish AI-built apps at `{slug}.ai-ui.coolestdomain.win` from stable snapshots, with backend support, on-demand startup, manual Republish, and clearer builder/user templates.

**Architecture:** Add a `tasks.published_apps` table and a snapshot service that copies `apps/<slug>/` into `published-apps/<slug>/current/`. Add a public runner/proxy in the tasks service that maps wildcard subdomains to published snapshots, starts backend/static apps on demand, and stops idle processes. Extend the preview UI with Publish, Republish, Unpublish, and Open Public App controls, then improve builder prompt templates so users understand preview vs public state.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy async, asyncpg, httpx, vanilla HTML/CSS/JS, Caddy, Docker Compose.

---

## Scope Check

The approved spec spans persistence, app snapshots, public routing, UI controls, and prompt/template wording. These are tightly coupled around one user outcome: publishing AI-built apps publicly. The work is split into small implementation tasks so each piece is independently testable before wiring the next layer.

## File Structure

Create or modify these files:

- `mcp-servers/tasks/migrations/003_published_apps.sql` - database table and indexes for published app state.
- `mcp-servers/tasks/models.py` - add `PublishedApp` ORM model.
- `mcp-servers/tasks/schemas.py` - add publish response schemas.
- `mcp-servers/tasks/publish_service.py` - slug validation, public URL construction, snapshot copy, publish state helpers.
- `mcp-servers/tasks/app_runtime.py` - shared command detection for Node, Python, and static apps.
- `mcp-servers/tasks/app_runner.py` - keep preview runner behavior, but call `app_runtime.resolve_command`.
- `mcp-servers/tasks/public_app_runner.py` - on-demand public process registry, port allocation, idle shutdown.
- `mcp-servers/tasks/routes_publish.py` - authenticated admin publish, republish, unpublish, and status APIs.
- `mcp-servers/tasks/routes_public.py` - unauthenticated wildcard-host public app proxy.
- `mcp-servers/tasks/main.py` - include new routers and start/stop public runner reaper.
- `mcp-servers/tasks/static/preview.html` - publish controls and status display.
- `mcp-servers/tasks/claude_executor.py` - clearer build, plan, verify, and enhance template wording.
- `Caddyfile` - wildcard app-subdomain route to the tasks service.
- `.env.example` - public app host suffix and port range configuration.
- Tests under `mcp-servers/tasks/tests/`.

## Shared Commands

Run task tests from the tasks service directory:

```powershell
cd mcp-servers/tasks
python -m pytest tests/<file>.py -v
```

The tests require `DATABASE_URL` for the local Postgres-backed test database, same as existing tasks tests.

---

### Task 1: Persistence Model and Schemas

**Files:**
- Create: `mcp-servers/tasks/migrations/003_published_apps.sql`
- Modify: `mcp-servers/tasks/models.py`
- Modify: `mcp-servers/tasks/schemas.py`
- Test: `mcp-servers/tasks/tests/test_published_app_model.py`

- [ ] **Step 1: Write the failing model test**

Create `mcp-servers/tasks/tests/test_published_app_model.py`:

```python
import uuid

from sqlalchemy import select

from models import PublishedApp, TaskItem


async def test_can_persist_published_app(db_session):
    source = TaskItem(
        meeting_id=uuid.uuid4(),
        action_type="BUILD",
        assignee_name="Ralph",
        assignee_email="ralph@aiui.com",
        description="source app",
        priority="NICE_TO_HAVE",
        status="completed",
        built_app_slug="meeting-notes",
    )
    db_session.add(source)
    await db_session.commit()
    await db_session.refresh(source)

    row = PublishedApp(
        slug="meeting-notes",
        source_task_id=source.id,
        snapshot_path="/workspace/ai_ui/published-apps/meeting-notes/current",
        status="published",
        public_url="https://meeting-notes.ai-ui.coolestdomain.win",
    )
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)

    loaded = (
        await db_session.execute(
            select(PublishedApp).where(PublishedApp.slug == "meeting-notes")
        )
    ).scalar_one()
    assert loaded.status == "published"
    assert loaded.source_task_id == source.id
    assert loaded.public_url == "https://meeting-notes.ai-ui.coolestdomain.win"
```

- [ ] **Step 2: Run the test to confirm it fails**

Run:

```powershell
cd mcp-servers/tasks
python -m pytest tests/test_published_app_model.py -v
```

Expected: FAIL with `ImportError: cannot import name 'PublishedApp'`.

- [ ] **Step 3: Add the migration**

Create `mcp-servers/tasks/migrations/003_published_apps.sql`:

```sql
CREATE TABLE IF NOT EXISTS tasks.published_apps (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug            TEXT NOT NULL UNIQUE,
    source_task_id  UUID NOT NULL REFERENCES tasks.items(id) ON DELETE CASCADE,
    snapshot_path   TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'published'
                      CHECK (status IN ('published','unpublished')),
    public_url      TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at    TIMESTAMPTZ,
    republished_at  TIMESTAMPTZ,
    unpublished_at  TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS published_apps_status_idx
    ON tasks.published_apps (status);

CREATE INDEX IF NOT EXISTS published_apps_source_task_idx
    ON tasks.published_apps (source_task_id);

CREATE OR REPLACE FUNCTION tasks._touch_published_apps_updated_at() RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS published_apps_touch_updated_at ON tasks.published_apps;
CREATE TRIGGER published_apps_touch_updated_at BEFORE UPDATE ON tasks.published_apps
    FOR EACH ROW EXECUTE FUNCTION tasks._touch_published_apps_updated_at();
```

- [ ] **Step 4: Add the ORM model**

Modify `mcp-servers/tasks/models.py`:

```python
class PublishedApp(Base):
    __tablename__ = "published_apps"
    __table_args__ = {"schema": "tasks"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug = Column(Text, nullable=False, unique=True)
    source_task_id = Column(UUID(as_uuid=True), ForeignKey("tasks.items.id"), nullable=False)
    snapshot_path = Column(Text, nullable=False)
    status = Column(Text, nullable=False, default="published")
    public_url = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    published_at = Column(DateTime(timezone=True), nullable=True)
    republished_at = Column(DateTime(timezone=True), nullable=True)
    unpublished_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow)
```

Keep the existing `TaskItem` and `TaskExecution` models unchanged.

- [ ] **Step 5: Add publish schemas**

Modify `mcp-servers/tasks/schemas.py`:

```python
class PublishStatusOut(BaseModel):
    slug: str
    status: Literal["not_published", "published", "unpublished"]
    public_url: str | None = None
    has_unpublished_changes: bool = False
    message: str
    published_at: datetime | None = None
    republished_at: datetime | None = None
    unpublished_at: datetime | None = None


class PublishActionOut(PublishStatusOut):
    snapshot_path: str | None = None
```

- [ ] **Step 6: Run the model test**

Run:

```powershell
cd mcp-servers/tasks
python -m pytest tests/test_published_app_model.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add mcp-servers/tasks/migrations/003_published_apps.sql `
        mcp-servers/tasks/models.py `
        mcp-servers/tasks/schemas.py `
        mcp-servers/tasks/tests/test_published_app_model.py
git commit -m "feat(tasks): add published app persistence"
```

---

### Task 2: Publish Service and Snapshot Copy

**Files:**
- Create: `mcp-servers/tasks/publish_service.py`
- Test: `mcp-servers/tasks/tests/test_publish_service.py`

- [ ] **Step 1: Write failing service tests**

Create `mcp-servers/tasks/tests/test_publish_service.py`:

```python
from pathlib import Path

import pytest

from publish_service import (
    RESERVED_SLUGS,
    build_public_url,
    copy_snapshot,
    editable_app_dir,
    snapshot_dir,
    validate_public_slug,
)


def test_validate_public_slug_accepts_project_slug():
    assert validate_public_slug("meeting-notes") == "meeting-notes"


@pytest.mark.parametrize("slug", ["api", "admin", "tasks", "n8n", "gdrive"])
def test_validate_public_slug_rejects_reserved_names(slug):
    assert slug in RESERVED_SLUGS
    with pytest.raises(ValueError, match="reserved"):
        validate_public_slug(slug)


@pytest.mark.parametrize("slug", ["Meeting Notes", "-bad", "bad-", "bad_slug", ""])
def test_validate_public_slug_rejects_invalid_format(slug):
    with pytest.raises(ValueError):
        validate_public_slug(slug)


def test_build_public_url_uses_configured_suffix(monkeypatch):
    monkeypatch.setenv("PUBLIC_APP_HOST_SUFFIX", "ai-ui.coolestdomain.win")
    assert build_public_url("meeting-notes") == "https://meeting-notes.ai-ui.coolestdomain.win"


def test_app_paths_are_under_workspace(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_WORKSPACE", str(tmp_path))
    assert editable_app_dir("demo") == tmp_path / "apps" / "demo"
    assert snapshot_dir("demo") == tmp_path / "published-apps" / "demo" / "current"


def test_copy_snapshot_excludes_generated_and_secret_files(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_WORKSPACE", str(tmp_path))
    src = tmp_path / "apps" / "demo"
    src.mkdir(parents=True)
    (src / "index.html").write_text("<h1>Demo</h1>")
    (src / ".env").write_text("SECRET=1")
    (src / "__pycache__").mkdir()
    (src / "__pycache__" / "x.pyc").write_text("cache")
    (src / "node_modules").mkdir()
    (src / "node_modules" / "pkg.js").write_text("module")

    dest = copy_snapshot("demo")

    assert dest == tmp_path / "published-apps" / "demo" / "current"
    assert (dest / "index.html").read_text() == "<h1>Demo</h1>"
    assert not (dest / ".env").exists()
    assert not (dest / "__pycache__").exists()
    assert not (dest / "node_modules").exists()
```

- [ ] **Step 2: Run the test to confirm it fails**

Run:

```powershell
cd mcp-servers/tasks
python -m pytest tests/test_publish_service.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'publish_service'`.

- [ ] **Step 3: Add the publish service**

Create `mcp-servers/tasks/publish_service.py`:

```python
"""Publish helpers for AI-built app snapshots."""
import os
import re
import shutil
from pathlib import Path

WORKSPACE = Path(os.environ.get("CLAUDE_WORKSPACE", "/workspace/ai_ui"))
PUBLIC_HOST_SUFFIX = os.environ.get("PUBLIC_APP_HOST_SUFFIX", "ai-ui.coolestdomain.win")

RESERVED_SLUGS = {
    "www",
    "api",
    "admin",
    "app",
    "tasks",
    "mcp",
    "grafana",
    "n8n",
    "auth",
    "webhook",
    "calendar",
    "gmail",
    "gdrive",
}

_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_EXCLUDED_NAMES = {".git", ".env", "node_modules", "__pycache__", ".pytest_cache"}


def _workspace() -> Path:
    return Path(os.environ.get("CLAUDE_WORKSPACE", str(WORKSPACE))).resolve()


def validate_public_slug(slug: str) -> str:
    normalized = (slug or "").strip().lower()
    if normalized in RESERVED_SLUGS:
        raise ValueError(f"'{normalized}' is reserved and cannot be published")
    if not _SLUG_RE.fullmatch(normalized):
        raise ValueError(
            "Slug must use lowercase letters, numbers, and hyphens, "
            "and cannot start or end with a hyphen"
        )
    return normalized


def build_public_url(slug: str) -> str:
    suffix = os.environ.get("PUBLIC_APP_HOST_SUFFIX", PUBLIC_HOST_SUFFIX).strip(".")
    return f"https://{validate_public_slug(slug)}.{suffix}"


def editable_app_dir(slug: str) -> Path:
    return _workspace() / "apps" / validate_public_slug(slug)


def snapshot_dir(slug: str) -> Path:
    return _workspace() / "published-apps" / validate_public_slug(slug) / "current"


def _ignore_snapshot_names(directory: str, names: list[str]) -> set[str]:
    ignored = set()
    for name in names:
        if name in _EXCLUDED_NAMES:
            ignored.add(name)
    return ignored


def copy_snapshot(slug: str) -> Path:
    src = editable_app_dir(slug)
    if not src.is_dir():
        raise FileNotFoundError(f"Editable app not found: apps/{slug}/")
    dest = snapshot_dir(slug)
    tmp = dest.parent / ".current-next"
    if tmp.exists():
        shutil.rmtree(tmp)
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, tmp, ignore=_ignore_snapshot_names)
    tmp.replace(dest)
    return dest
```

- [ ] **Step 4: Run the service tests**

Run:

```powershell
cd mcp-servers/tasks
python -m pytest tests/test_publish_service.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add mcp-servers/tasks/publish_service.py `
        mcp-servers/tasks/tests/test_publish_service.py
git commit -m "feat(tasks): add published app snapshot service"
```

---

### Task 3: Shared Runtime Detection

**Files:**
- Create: `mcp-servers/tasks/app_runtime.py`
- Modify: `mcp-servers/tasks/app_runner.py`
- Test: `mcp-servers/tasks/tests/test_app_runtime.py`

- [ ] **Step 1: Write failing runtime tests**

Create `mcp-servers/tasks/tests/test_app_runtime.py`:

```python
import json

from app_runtime import build_public_env, resolve_command


def test_resolve_command_static_site(tmp_path):
    app = tmp_path / "static-app"
    app.mkdir()
    (app / "index.html").write_text("<h1>Hello</h1>")
    kind, cmd = resolve_command(str(app), 9200)
    assert kind == "static"
    assert "npx --yes serve" in cmd
    assert "-l 9200" in cmd


def test_resolve_command_node_app(tmp_path):
    app = tmp_path / "node-app"
    app.mkdir()
    (app / "package.json").write_text(json.dumps({"scripts": {"start": "node server.js"}}))
    kind, cmd = resolve_command(str(app), 9201)
    assert kind == "node"
    assert "npm install" in cmd
    assert "PORT=9201 npm run start" in cmd


def test_resolve_command_python_app(tmp_path):
    app = tmp_path / "py-app"
    app.mkdir()
    (app / "server.py").write_text("print('hi')")
    kind, cmd = resolve_command(str(app), 9202)
    assert kind == "python"
    assert "PORT=9202 python3 server.py" in cmd


def test_public_env_drops_platform_secrets(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret")
    monkeypatch.setenv("DATABASE_URL", "postgresql://secret")
    monkeypatch.setenv("PATH", "/usr/bin")
    env = build_public_env(9203)
    assert env["PORT"] == "9203"
    assert env["PATH"] == "/usr/bin"
    assert "ANTHROPIC_API_KEY" not in env
    assert "DATABASE_URL" not in env
```

- [ ] **Step 2: Run the runtime tests to confirm they fail**

Run:

```powershell
cd mcp-servers/tasks
python -m pytest tests/test_app_runtime.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app_runtime'`.

- [ ] **Step 3: Create shared runtime module**

Create `mcp-servers/tasks/app_runtime.py` by moving command resolution logic out of `app_runner.py`:

```python
"""Shared app runtime command detection for preview and public apps."""
import json
import os
import shlex
from pathlib import Path

PYTHON_ENTRY_CANDIDATES = ("server.py", "main.py", "app.py")


def resolve_command(app_dir: str, port: int) -> tuple[str, str]:
    root = Path(app_dir)
    pkg_json_path = root / "package.json"
    requirements_path = root / "requirements.txt"
    python_entry = next((f for f in PYTHON_ENTRY_CANDIDATES if (root / f).is_file()), None)
    index_html = root / "index.html"

    if pkg_json_path.is_file():
        try:
            pkg = json.loads(pkg_json_path.read_text())
        except Exception:
            pkg = {}
        scripts: dict = pkg.get("scripts") or {}
        dev_cmd = scripts.get("dev") or ""
        start_cmd = scripts.get("start") or ""
        scripts_are_python = "python" in dev_cmd.lower() or "python" in start_cmd.lower()
        if not scripts_are_python and ("dev" in scripts or "start" in scripts):
            script_name = "dev" if "dev" in scripts else "start"
            return (
                "node",
                f"cd {shlex.quote(str(root))} && "
                f"npm install --silent --no-audit --no-fund && "
                f"PORT={port} npm run {script_name}",
            )

    if python_entry:
        parts = [f"cd {shlex.quote(str(root))}"]
        if requirements_path.is_file():
            parts.append("pip install -q -r requirements.txt")
        else:
            parts.append("(python3 -c 'import flask' 2>/dev/null || pip install -q flask)")
        parts.append(f"PORT={port} python3 {shlex.quote(python_entry)}")
        return ("python", " && ".join(parts))

    if index_html.is_file():
        return (
            "static",
            f"npx --yes serve -s {shlex.quote(str(root))} -l {port} --no-clipboard",
        )

    raise FileNotFoundError(
        f"Cannot determine how to run {root.name}/ - "
        "no runnable npm script, server.py/main.py/app.py, or index.html"
    )


def build_public_env(port: int) -> dict[str, str]:
    allowed = {}
    for key in ("PATH", "HOME", "NODE_PATH", "PYTHONPATH", "LANG", "LC_ALL"):
        if os.environ.get(key):
            allowed[key] = os.environ[key]
    allowed["PORT"] = str(port)
    allowed["NODE_ENV"] = "production"
    return allowed
```

- [ ] **Step 4: Modify preview runner to use the shared runtime**

Modify `mcp-servers/tasks/app_runner.py`:

```python
from app_runtime import resolve_command
```

Replace:

```python
kind, cmd = _resolve_command(app_dir, port)
```

with:

```python
kind, cmd = resolve_command(app_dir, port)
```

Then remove the now-duplicated local `_resolve_command`, `json`, `shlex`, and
`PYTHON_ENTRY_CANDIDATES` code from `app_runner.py`.

- [ ] **Step 5: Run runtime and existing preview-adjacent tests**

Run:

```powershell
cd mcp-servers/tasks
python -m pytest tests/test_app_runtime.py tests/test_routes_execution.py tests/test_slug_preservation.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add mcp-servers/tasks/app_runtime.py `
        mcp-servers/tasks/app_runner.py `
        mcp-servers/tasks/tests/test_app_runtime.py
git commit -m "refactor(tasks): share app runtime command detection"
```

---

### Task 4: Admin Publish API

**Files:**
- Create: `mcp-servers/tasks/routes_publish.py`
- Modify: `mcp-servers/tasks/main.py`
- Test: `mcp-servers/tasks/tests/test_routes_publish.py`

- [ ] **Step 1: Write failing route tests**

Create `mcp-servers/tasks/tests/test_routes_publish.py`:

```python
import uuid

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from main import app
from models import PublishedApp, TaskItem

HDR = {"X-User-Email": "ralph@aiui.com", "X-User-Admin": "true"}


def _build_task(slug="meeting-notes", email="ralph@aiui.com"):
    return TaskItem(
        meeting_id=uuid.uuid4(),
        action_type="BUILD",
        assignee_name="Ralph",
        assignee_email=email,
        description="build app",
        priority="NICE_TO_HAVE",
        status="completed",
        built_app_slug=slug,
    )


async def test_publish_status_not_published(db_session):
    item = _build_task()
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get(f"/api/tasks/{item.id}/publish/status", headers=HDR)
    assert r.status_code == 200
    assert r.json()["status"] == "not_published"


async def test_publish_rejects_task_without_slug(db_session):
    item = _build_task(slug=None)
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(f"/api/tasks/{item.id}/publish", headers=HDR)
    assert r.status_code == 400
    assert "built app" in r.json()["detail"].lower()


async def test_publish_rejects_reserved_slug(db_session):
    item = _build_task(slug="api")
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(f"/api/tasks/{item.id}/publish", headers=HDR)
    assert r.status_code == 400
    assert "reserved" in r.json()["detail"].lower()


async def test_publish_creates_record_and_snapshot(db_session, monkeypatch, tmp_path):
    import routes_publish

    item = _build_task()
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)

    app_dir = tmp_path / "apps" / "meeting-notes"
    app_dir.mkdir(parents=True)
    (app_dir / "index.html").write_text("<h1>Meeting Notes</h1>")
    monkeypatch.setenv("CLAUDE_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(routes_publish, "WORKSPACE", tmp_path, raising=False)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(f"/api/tasks/{item.id}/publish", headers=HDR)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "published"
    assert body["public_url"] == "https://meeting-notes.ai-ui.coolestdomain.win"
    assert (tmp_path / "published-apps" / "meeting-notes" / "current" / "index.html").exists()

    row = (await db_session.execute(select(PublishedApp))).scalar_one()
    assert row.slug == "meeting-notes"
    assert row.status == "published"


async def test_unpublish_marks_record_unpublished(db_session, monkeypatch, tmp_path):
    item = _build_task()
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)
    snap = tmp_path / "published-apps" / "meeting-notes" / "current"
    snap.mkdir(parents=True)
    row = PublishedApp(
        slug="meeting-notes",
        source_task_id=item.id,
        snapshot_path=str(snap),
        status="published",
        public_url="https://meeting-notes.ai-ui.coolestdomain.win",
    )
    db_session.add(row)
    await db_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(f"/api/tasks/{item.id}/unpublish", headers=HDR)

    assert r.status_code == 200
    assert r.json()["status"] == "unpublished"
```

- [ ] **Step 2: Run the route tests to confirm they fail**

Run:

```powershell
cd mcp-servers/tasks
python -m pytest tests/test_routes_publish.py -v
```

Expected: FAIL with 404 for publish routes.

- [ ] **Step 3: Add admin publish routes**

Create `mcp-servers/tasks/routes_publish.py`:

```python
"""Authenticated publish APIs for built apps."""
from datetime import datetime
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from auth import AdminUser, current_admin
from db import session
from models import PublishedApp, TaskItem
from publish_service import build_public_url, copy_snapshot, snapshot_dir, validate_public_slug
from schemas import PublishActionOut, PublishStatusOut

router = APIRouter(prefix="/api/tasks")
WORKSPACE = Path(__file__).resolve().parent
TEAM_EMAIL = "team@aiui.local"


async def _get_owned_build_task(s, task_id: UUID, email: str) -> TaskItem:
    item = (await s.execute(select(TaskItem).where(TaskItem.id == task_id))).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if item.assignee_email not in (email, TEAM_EMAIL):
        raise HTTPException(status_code=403, detail="Not your task")
    if item.action_type != "BUILD" or not item.built_app_slug:
        raise HTTPException(status_code=400, detail="Task has no built app to publish")
    return item


def _status_out(slug: str, row: PublishedApp | None) -> PublishStatusOut:
    if row is None:
        return PublishStatusOut(
            slug=slug,
            status="not_published",
            public_url=None,
            has_unpublished_changes=False,
            message="Not published",
        )
    status = "published" if row.status == "published" else "unpublished"
    message = (
        f"Published at {row.public_url.replace('https://', '')}"
        if row.status == "published"
        else "Unpublished"
    )
    return PublishStatusOut(
        slug=slug,
        status=status,
        public_url=row.public_url,
        has_unpublished_changes=False,
        message=message,
        published_at=row.published_at,
        republished_at=row.republished_at,
        unpublished_at=row.unpublished_at,
    )


@router.get("/{task_id}/publish/status", response_model=PublishStatusOut)
async def publish_status(task_id: UUID, user: AdminUser = Depends(current_admin)):
    async with session() as s:
        task = await _get_owned_build_task(s, task_id, user.email)
        slug = validate_public_slug(task.built_app_slug)
        row = (
            await s.execute(select(PublishedApp).where(PublishedApp.slug == slug))
        ).scalar_one_or_none()
    return _status_out(slug, row)


@router.post("/{task_id}/publish", response_model=PublishActionOut)
async def publish(task_id: UUID, user: AdminUser = Depends(current_admin)):
    return await _publish_or_republish(task_id, user, first_publish=True)


@router.post("/{task_id}/republish", response_model=PublishActionOut)
async def republish(task_id: UUID, user: AdminUser = Depends(current_admin)):
    return await _publish_or_republish(task_id, user, first_publish=False)


async def _publish_or_republish(task_id: UUID, user: AdminUser, *, first_publish: bool):
    async with session() as s:
        task = await _get_owned_build_task(s, task_id, user.email)
        try:
            slug = validate_public_slug(task.built_app_slug)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    try:
        dest = copy_snapshot(slug)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    public_url = build_public_url(slug)
    now = datetime.utcnow()
    async with session() as s:
        row = (
            await s.execute(select(PublishedApp).where(PublishedApp.slug == slug))
        ).scalar_one_or_none()
        if row is None:
            row = PublishedApp(
                slug=slug,
                source_task_id=task_id,
                snapshot_path=str(dest),
                status="published",
                public_url=public_url,
                published_at=now,
            )
            s.add(row)
        else:
            row.source_task_id = task_id
            row.snapshot_path = str(dest)
            row.status = "published"
            row.public_url = public_url
            if row.published_at is None:
                row.published_at = now
            if not first_publish:
                row.republished_at = now
            row.unpublished_at = None
        await s.commit()
        await s.refresh(row)

    message = (
        f"Published at {public_url.replace('https://', '')}"
        if first_publish
        else f"Republished at {public_url.replace('https://', '')}"
    )
    return PublishActionOut(
        slug=slug,
        status="published",
        public_url=public_url,
        has_unpublished_changes=False,
        message=message,
        published_at=row.published_at,
        republished_at=row.republished_at,
        unpublished_at=row.unpublished_at,
        snapshot_path=str(dest),
    )


@router.post("/{task_id}/unpublish", response_model=PublishStatusOut)
async def unpublish(task_id: UUID, user: AdminUser = Depends(current_admin)):
    async with session() as s:
        task = await _get_owned_build_task(s, task_id, user.email)
        slug = validate_public_slug(task.built_app_slug)
        row = (
            await s.execute(select(PublishedApp).where(PublishedApp.slug == slug))
        ).scalar_one_or_none()
        if row is None:
            return _status_out(slug, None)
        row.status = "unpublished"
        row.unpublished_at = datetime.utcnow()
        await s.commit()
        await s.refresh(row)
    return _status_out(slug, row)
```

- [ ] **Step 4: Register the publish router**

Modify `mcp-servers/tasks/main.py`:

```python
from routes_publish import router as publish_router
```

Add after the existing task routers:

```python
app.include_router(publish_router)
```

- [ ] **Step 5: Run publish route tests**

Run:

```powershell
cd mcp-servers/tasks
python -m pytest tests/test_routes_publish.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add mcp-servers/tasks/routes_publish.py `
        mcp-servers/tasks/main.py `
        mcp-servers/tasks/tests/test_routes_publish.py
git commit -m "feat(tasks): add publish management API"
```

---

### Task 5: Public App Runner

**Files:**
- Create: `mcp-servers/tasks/public_app_runner.py`
- Test: `mcp-servers/tasks/tests/test_public_app_runner.py`

- [ ] **Step 1: Write failing runner tests**

Create `mcp-servers/tasks/tests/test_public_app_runner.py`:

```python
import asyncio

import pytest

from public_app_runner import PublicAppRunner


async def test_runner_allocates_configured_port(monkeypatch, tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "index.html").write_text("<h1>Hello</h1>")

    runner = PublicAppRunner(port_start=9300, port_end=9300, idle_timeout_seconds=60)

    class FakeProc:
        pid = 123
        returncode = None

        async def wait(self):
            return 0

    async def fake_create(*args, **kwargs):
        return FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create)
    port = await runner.ensure_started("demo", str(app))
    assert port == 9300
    assert runner.status("demo")["running"] is True


async def test_runner_reuses_existing_process(monkeypatch, tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "index.html").write_text("<h1>Hello</h1>")
    runner = PublicAppRunner(port_start=9301, port_end=9302, idle_timeout_seconds=60)
    calls = 0

    class FakeProc:
        pid = 123
        returncode = None

        async def wait(self):
            return 0

    async def fake_create(*args, **kwargs):
        nonlocal calls
        calls += 1
        return FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create)
    first = await runner.ensure_started("demo", str(app))
    second = await runner.ensure_started("demo", str(app))
    assert first == second
    assert calls == 1


async def test_runner_reports_port_exhaustion(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "index.html").write_text("<h1>Hello</h1>")
    runner = PublicAppRunner(port_start=1, port_end=0, idle_timeout_seconds=60)
    with pytest.raises(RuntimeError, match="No public app ports available"):
        await runner.ensure_started("demo", str(app))
```

- [ ] **Step 2: Run the runner tests to confirm they fail**

Run:

```powershell
cd mcp-servers/tasks
python -m pytest tests/test_public_app_runner.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'public_app_runner'`.

- [ ] **Step 3: Create public app runner**

Create `mcp-servers/tasks/public_app_runner.py`:

```python
"""On-demand process runner for published app snapshots."""
import asyncio
import logging
import os
import time
from dataclasses import dataclass

from app_runtime import build_public_env, resolve_command

logger = logging.getLogger("tasks.public_app_runner")


@dataclass
class RunningPublicApp:
    slug: str
    snapshot_path: str
    port: int
    kind: str
    proc: asyncio.subprocess.Process
    started_at: float
    last_accessed_at: float


class PublicAppRunner:
    def __init__(
        self,
        *,
        port_start: int | None = None,
        port_end: int | None = None,
        idle_timeout_seconds: int | None = None,
    ):
        self.port_start = port_start or int(os.environ.get("PUBLIC_APP_PORT_START", "9200"))
        self.port_end = port_end or int(os.environ.get("PUBLIC_APP_PORT_END", "9299"))
        self.idle_timeout_seconds = idle_timeout_seconds or int(
            os.environ.get("PUBLIC_APP_IDLE_TIMEOUT_SECONDS", "1800")
        )
        self._running: dict[str, RunningPublicApp] = {}
        self._lock = asyncio.Lock()

    def _used_ports(self) -> set[int]:
        return {entry.port for entry in self._running.values()}

    def _allocate_port(self) -> int:
        used = self._used_ports()
        for port in range(self.port_start, self.port_end + 1):
            if port not in used:
                return port
        raise RuntimeError("No public app ports available")

    async def ensure_started(self, slug: str, snapshot_path: str) -> int:
        async with self._lock:
            current = self._running.get(slug)
            if current and current.proc.returncode is None and current.snapshot_path == snapshot_path:
                current.last_accessed_at = time.time()
                return current.port
            if current:
                await self.stop(slug)

            port = self._allocate_port()
            kind, cmd = resolve_command(snapshot_path, port)
            proc = await asyncio.create_subprocess_exec(
                "sh",
                "-c",
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
                env=build_public_env(port),
            )
            self._running[slug] = RunningPublicApp(
                slug=slug,
                snapshot_path=snapshot_path,
                port=port,
                kind=kind,
                proc=proc,
                started_at=time.time(),
                last_accessed_at=time.time(),
            )
            logger.info("Published app started: slug=%s kind=%s port=%s", slug, kind, port)
            return port

    async def stop(self, slug: str) -> None:
        entry = self._running.pop(slug, None)
        if not entry:
            return
        try:
            import signal
            import os as _os

            _os.killpg(_os.getpgid(entry.proc.pid), signal.SIGKILL)
            await entry.proc.wait()
        except (ProcessLookupError, PermissionError):
            pass
        logger.info("Published app stopped: slug=%s", slug)

    async def stop_all(self) -> None:
        for slug in list(self._running):
            await self.stop(slug)

    async def reap_idle(self) -> None:
        now = time.time()
        for slug, entry in list(self._running.items()):
            if entry.proc.returncode is not None:
                self._running.pop(slug, None)
            elif now - entry.last_accessed_at > self.idle_timeout_seconds:
                await self.stop(slug)

    def status(self, slug: str) -> dict:
        entry = self._running.get(slug)
        if not entry:
            return {"running": False}
        return {
            "running": entry.proc.returncode is None,
            "slug": slug,
            "port": entry.port,
            "kind": entry.kind,
            "pid": entry.proc.pid,
            "elapsed_seconds": int(time.time() - entry.started_at),
        }


public_runner = PublicAppRunner()
```

- [ ] **Step 4: Run the runner tests**

Run:

```powershell
cd mcp-servers/tasks
python -m pytest tests/test_public_app_runner.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add mcp-servers/tasks/public_app_runner.py `
        mcp-servers/tasks/tests/test_public_app_runner.py
git commit -m "feat(tasks): add on-demand public app runner"
```

---

### Task 6: Public Host Router and Proxy

**Files:**
- Create: `mcp-servers/tasks/routes_public.py`
- Modify: `mcp-servers/tasks/main.py`
- Test: `mcp-servers/tasks/tests/test_routes_public.py`

- [ ] **Step 1: Write failing public route tests**

Create `mcp-servers/tasks/tests/test_routes_public.py`:

```python
import uuid

from httpx import ASGITransport, AsyncClient

from main import app
from models import PublishedApp, TaskItem


async def test_public_route_returns_not_published_for_unknown_slug(db_session):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://meeting-notes.ai-ui.coolestdomain.win") as c:
        r = await c.get("/", headers={"host": "meeting-notes.ai-ui.coolestdomain.win"})
    assert r.status_code == 404
    assert "not published" in r.text.lower()


async def test_public_route_returns_not_published_for_unpublished_record(db_session, tmp_path):
    source = TaskItem(
        meeting_id=uuid.uuid4(),
        action_type="BUILD",
        assignee_name="Ralph",
        assignee_email="ralph@aiui.com",
        description="source",
        priority="NICE_TO_HAVE",
        status="completed",
        built_app_slug="meeting-notes",
    )
    db_session.add(source)
    await db_session.commit()
    await db_session.refresh(source)
    row = PublishedApp(
        slug="meeting-notes",
        source_task_id=source.id,
        snapshot_path=str(tmp_path),
        status="unpublished",
        public_url="https://meeting-notes.ai-ui.coolestdomain.win",
    )
    db_session.add(row)
    await db_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://meeting-notes.ai-ui.coolestdomain.win") as c:
        r = await c.get("/", headers={"host": "meeting-notes.ai-ui.coolestdomain.win"})
    assert r.status_code == 404
    assert "not published" in r.text.lower()


async def test_public_route_proxies_to_runner(db_session, monkeypatch, tmp_path):
    import routes_public

    source = TaskItem(
        meeting_id=uuid.uuid4(),
        action_type="BUILD",
        assignee_name="Ralph",
        assignee_email="ralph@aiui.com",
        description="source",
        priority="NICE_TO_HAVE",
        status="completed",
        built_app_slug="meeting-notes",
    )
    db_session.add(source)
    await db_session.commit()
    await db_session.refresh(source)
    row = PublishedApp(
        slug="meeting-notes",
        source_task_id=source.id,
        snapshot_path=str(tmp_path),
        status="published",
        public_url="https://meeting-notes.ai-ui.coolestdomain.win",
    )
    db_session.add(row)
    await db_session.commit()

    class FakeRunner:
        async def ensure_started(self, slug, snapshot_path):
            assert slug == "meeting-notes"
            assert snapshot_path == str(tmp_path)
            return 9999

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "text/plain"}
        content = b"proxied app"

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def request(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(routes_public, "public_runner", FakeRunner())
    monkeypatch.setattr(routes_public.httpx, "AsyncClient", FakeClient)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://meeting-notes.ai-ui.coolestdomain.win") as c:
        r = await c.get("/hello?x=1", headers={"host": "meeting-notes.ai-ui.coolestdomain.win"})

    assert r.status_code == 200
    assert r.text == "proxied app"
```

- [ ] **Step 2: Run tests to confirm they fail**

Run:

```powershell
cd mcp-servers/tasks
python -m pytest tests/test_routes_public.py -v
```

Expected: FAIL because `routes_public` is not registered.

- [ ] **Step 3: Add public router**

Create `mcp-servers/tasks/routes_public.py`:

```python
"""Unauthenticated public app host router."""
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Request, Response
from sqlalchemy import select

from db import session
from models import PublishedApp
from public_app_runner import public_runner
from publish_service import PUBLIC_HOST_SUFFIX, validate_public_slug

router = APIRouter()

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}


def _plain_page(title: str, detail: str, status_code: int) -> Response:
    html = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{title}</title>"
        "<style>body{font-family:system-ui;margin:0;min-height:100vh;display:grid;"
        "place-items:center;background:#f8fafc;color:#111827}"
        "main{max-width:520px;padding:32px;text-align:center}"
        "h1{font-size:28px;margin:0 0 12px}p{color:#4b5563;line-height:1.5}</style>"
        f"</head><body><main><h1>{title}</h1><p>{detail}</p></main></body></html>"
    )
    return Response(content=html, status_code=status_code, media_type="text/html")


def slug_from_host(host: str) -> str | None:
    hostname = (host or "").split(":", 1)[0].lower()
    suffix = PUBLIC_HOST_SUFFIX.strip(".").lower()
    if not hostname.endswith("." + suffix):
        return None
    raw = hostname[: -(len(suffix) + 1)]
    if "." in raw:
        return None
    try:
        return validate_public_slug(raw)
    except ValueError:
        return None


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"], include_in_schema=False)
async def public_app_proxy(path: str, request: Request):
    slug = slug_from_host(request.headers.get("host", ""))
    if not slug:
        return _plain_page("App not published", "This app URL is not published.", 404)

    async with session() as s:
        row = (
            await s.execute(select(PublishedApp).where(PublishedApp.slug == slug))
        ).scalar_one_or_none()
    if row is None or row.status != "published":
        return _plain_page("App not published", "This app is not public right now.", 404)

    try:
        port = await public_runner.ensure_started(row.slug, row.snapshot_path)
    except Exception:
        return _plain_page(
            "App failed to start",
            "The published app could not start. Ask an admin to check the app logs and republish.",
            502,
        )

    query = request.url.query
    target = f"http://127.0.0.1:{port}/{path}"
    if query:
        target = f"{target}?{query}"
    body = await request.body()
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS and key.lower() != "host"
    }
    headers["host"] = request.headers.get("host", "")
    headers["x-forwarded-host"] = request.headers.get("host", "")
    headers["x-forwarded-proto"] = request.url.scheme

    async with httpx.AsyncClient(timeout=60.0, follow_redirects=False) as client:
        upstream = await client.request(
            request.method,
            target,
            content=body,
            headers=headers,
        )
    response_headers = {
        key: value
        for key, value in upstream.headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
    }
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=response_headers,
    )
```

- [ ] **Step 4: Register public router after admin routers**

Modify `mcp-servers/tasks/main.py`:

```python
from routes_public import router as public_router
```

Register it after all specific routes, including `/health`. In `main.py`, keep
the health endpoint above the catch-all include, then add:

```python
app.include_router(public_router)
```

It must be the last route registered because it catches every path for
wildcard-host traffic. If it is registered before `/health`, it will intercept
`/health`.

- [ ] **Step 5: Run public route tests**

Run:

```powershell
cd mcp-servers/tasks
python -m pytest tests/test_routes_public.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add mcp-servers/tasks/routes_public.py `
        mcp-servers/tasks/main.py `
        mcp-servers/tasks/tests/test_routes_public.py
git commit -m "feat(tasks): route public app subdomains"
```

---

### Task 7: Public Runner Lifecycle and Configuration

**Files:**
- Modify: `mcp-servers/tasks/main.py`
- Modify: `docker-compose.unified.yml`
- Modify: `.env.example`
- Test: `mcp-servers/tasks/tests/test_public_app_runner.py`

- [ ] **Step 1: Add idle reaper test**

Append to `mcp-servers/tasks/tests/test_public_app_runner.py`:

```python
async def test_reap_idle_stops_stale_process(monkeypatch, tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "index.html").write_text("<h1>Hello</h1>")
    runner = PublicAppRunner(port_start=9305, port_end=9305, idle_timeout_seconds=0)
    killed = {"value": False}

    class FakeProc:
        pid = 123
        returncode = None

        async def wait(self):
            return 0

    async def fake_create(*args, **kwargs):
        return FakeProc()

    def fake_killpg(*args, **kwargs):
        killed["value"] = True

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create)
    monkeypatch.setattr("os.killpg", fake_killpg)
    await runner.ensure_started("demo", str(app))
    await runner.reap_idle()
    assert killed["value"] is True
    assert runner.status("demo")["running"] is False
```

- [ ] **Step 2: Run the updated runner tests**

Run:

```powershell
cd mcp-servers/tasks
python -m pytest tests/test_public_app_runner.py -v
```

Expected: PASS after Task 5 implementation.

- [ ] **Step 3: Start and stop reaper in FastAPI lifespan**

Modify `mcp-servers/tasks/main.py`:

```python
import asyncio
```

Import:

```python
from public_app_runner import public_runner
```

Update lifespan:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    logger.info("DB initialized")
    stop_event = asyncio.Event()

    async def _reaper_loop():
        while not stop_event.is_set():
            await public_runner.reap_idle()
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=30.0)
            except asyncio.TimeoutError:
                pass

    reaper_task = asyncio.create_task(_reaper_loop())
    try:
        yield
    finally:
        stop_event.set()
        reaper_task.cancel()
        await public_runner.stop_all()
```

- [ ] **Step 4: Add environment configuration**

Modify the `tasks` service environment in `docker-compose.unified.yml`:

```yaml
      - PUBLIC_APP_HOST_SUFFIX=${PUBLIC_APP_HOST_SUFFIX:-ai-ui.coolestdomain.win}
      - PUBLIC_APP_PORT_START=${PUBLIC_APP_PORT_START:-9200}
      - PUBLIC_APP_PORT_END=${PUBLIC_APP_PORT_END:-9299}
      - PUBLIC_APP_IDLE_TIMEOUT_SECONDS=${PUBLIC_APP_IDLE_TIMEOUT_SECONDS:-1800}
```

Modify `.env.example` near the Tasks section:

```dotenv
# Public app publishing
PUBLIC_APP_HOST_SUFFIX=ai-ui.coolestdomain.win
PUBLIC_APP_PORT_START=9200
PUBLIC_APP_PORT_END=9299
PUBLIC_APP_IDLE_TIMEOUT_SECONDS=1800
```

- [ ] **Step 5: Run smoke import test**

Run:

```powershell
cd mcp-servers/tasks
python -m pytest tests/test_public_app_runner.py tests/test_routes_public.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add mcp-servers/tasks/main.py `
        docker-compose.unified.yml `
        .env.example `
        mcp-servers/tasks/tests/test_public_app_runner.py
git commit -m "feat(tasks): manage public app runner lifecycle"
```

---

### Task 8: Caddy Wildcard Subdomain Route

**Files:**
- Modify: `Caddyfile`
- Test: manual `caddy validate` if Caddy is available

- [ ] **Step 1: Add wildcard route block**

Add a new site block before the existing `:80` catch-all block if production uses host-based routing, or add a host matcher near the top of the `:80` block if this deployment terminates TLS at Cloudflare and forwards all HTTP to Caddy.

For the current `:80` Caddyfile shape, add this near the top of the `:80` block after health checks and before gateway/admin handles:

```caddyfile
	# ---------------------------------------------------------------------------
	# Public AI-built apps
	# ---------------------------------------------------------------------------
	@publishedApps {
		host *.ai-ui.coolestdomain.win
		not host ai-ui.coolestdomain.win
	}
	handle @publishedApps {
		reverse_proxy tasks:8210
	}
```

The `not host ai-ui.coolestdomain.win` line keeps the main platform host on the existing routes.

- [ ] **Step 2: Validate Caddy syntax**

Run if Caddy is installed locally:

```powershell
caddy validate --config Caddyfile
```

Expected: `Valid configuration`.

If Caddy is not installed locally, validate inside the container during deployment:

```powershell
docker compose -f docker-compose.unified.yml exec caddy caddy validate --config /etc/caddy/Caddyfile
```

Expected: `Valid configuration`.

- [ ] **Step 3: Commit**

```powershell
git add Caddyfile
git commit -m "feat(caddy): route public app subdomains"
```

---

### Task 9: Preview UI Publish Controls

**Files:**
- Modify: `mcp-servers/tasks/static/preview.html`
- Test: manual browser verification

- [ ] **Step 1: Add publish controls in the topbar**

In `mcp-servers/tasks/static/preview.html`, add these controls inside `<div class="topbar-right">` before the Run button:

```html
    <div class="publish-chip" id="publish-chip" data-state="loading" title="Public app publish status">
      <span class="dot"></span>
      <span id="publish-label">Checking publish status...</span>
    </div>
    <button class="btn btn-ghost" id="btn-publish" disabled>Publish</button>
    <button class="btn btn-ghost" id="btn-republish" hidden disabled>Republish</button>
    <button class="btn btn-ghost" id="btn-unpublish" hidden disabled>Unpublish</button>
    <a class="btn btn-ghost" id="btn-open-public" href="#" target="_blank" rel="noopener" hidden>Open Public App</a>
```

- [ ] **Step 2: Add minimal CSS for publish controls**

Add near existing status chip styles:

```css
    .publish-chip {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      height: 30px;
      padding: 0 10px;
      border: 1px solid var(--border);
      border-radius: 6px;
      color: var(--muted);
      font-size: 12px;
      background: var(--surface-2);
      max-width: 320px;
      overflow: hidden;
      white-space: nowrap;
      text-overflow: ellipsis;
    }
    .publish-chip .dot {
      width: 7px;
      height: 7px;
      border-radius: 999px;
      background: var(--muted);
      flex: 0 0 auto;
    }
    .publish-chip[data-state="published"] .dot { background: var(--success); }
    .publish-chip[data-state="unpublished"] .dot,
    .publish-chip[data-state="not_published"] .dot { background: var(--warning); }
    .publish-chip[data-state="error"] .dot { background: var(--danger); }
```

- [ ] **Step 3: Add DOM references and state**

Near existing DOM refs:

```javascript
  let publishState = null;

  const $publishChip = document.getElementById("publish-chip");
  const $publishLabel = document.getElementById("publish-label");
  const $btnPublish = document.getElementById("btn-publish");
  const $btnRepublish = document.getElementById("btn-republish");
  const $btnUnpublish = document.getElementById("btn-unpublish");
  const $btnOpenPublic = document.getElementById("btn-open-public");
```

- [ ] **Step 4: Add publish status functions**

Add after `apiFetch` helper:

```javascript
  function renderPublishState(state) {
    publishState = state;
    const status = (state && state.status) || "not_published";
    $publishChip.dataset.state = status;
    $publishLabel.textContent = state && state.message ? state.message : "Not published";

    const isPublished = status === "published";
    const isUnpublished = status === "unpublished";
    const isNotPublished = status === "not_published";

    $btnPublish.hidden = !isNotPublished && !isUnpublished;
    $btnRepublish.hidden = !isPublished;
    $btnUnpublish.hidden = !isPublished;
    $btnOpenPublic.hidden = !state || !state.public_url;

    $btnPublish.disabled = false;
    $btnRepublish.disabled = false;
    $btnUnpublish.disabled = false;
    if (state && state.public_url) {
      $btnOpenPublic.href = state.public_url;
    }
  }

  async function loadPublishStatus() {
    try {
      const state = await apiFetch("GET", "/" + taskId + "/publish/status");
      renderPublishState(state);
    } catch (e) {
      $publishChip.dataset.state = "error";
      $publishLabel.textContent = "Publish status unavailable";
      toast("Could not load publish status: " + e.message, "error", 5000);
    }
  }

  async function runPublishAction(action) {
    const label = action === "republish" ? "Republish" : action === "unpublish" ? "Unpublish" : "Publish";
    if (action === "republish") {
      const ok = confirm("Republish will replace what public users see with the current preview version.");
      if (!ok) return;
    }
    $btnPublish.disabled = true;
    $btnRepublish.disabled = true;
    $btnUnpublish.disabled = true;
    try {
      const state = await apiFetch("POST", "/" + taskId + "/" + action);
      renderPublishState(state);
      toast(state.message || (label + " complete"), "success", 5000);
    } catch (e) {
      toast(label + " failed: " + e.message, "error", 7000);
    } finally {
      $btnPublish.disabled = false;
      $btnRepublish.disabled = false;
      $btnUnpublish.disabled = false;
    }
  }
```

- [ ] **Step 5: Wire button events and initial load**

Add near existing event listeners:

```javascript
  $btnPublish.addEventListener("click", function () { runPublishAction("publish"); });
  $btnRepublish.addEventListener("click", function () { runPublishAction("republish"); });
  $btnUnpublish.addEventListener("click", function () { runPublishAction("unpublish"); });
```

Call after `loadFileTree()` starts during initialization:

```javascript
  loadPublishStatus();
```

Also call `loadPublishStatus()` after a completed enhancement so Republish state refreshes.

- [ ] **Step 6: Manual browser check**

Start the local demo stack or deployed stack. Open:

```text
/tasks/static/preview.html?task=<completed-build-task-id>
```

Expected:

- Never-published app shows `Not published` and `Publish`.
- Publish changes status to `Published at <slug>.ai-ui.coolestdomain.win`.
- Open Public App link appears.
- Published app shows Republish and Unpublish.
- Unpublish changes status to Unpublished.

- [ ] **Step 7: Commit**

```powershell
git add mcp-servers/tasks/static/preview.html
git commit -m "feat(preview): add public publish controls"
```

---

### Task 10: Builder Communication and Generated App Guidance

**Files:**
- Modify: `mcp-servers/tasks/claude_executor.py`
- Test: `mcp-servers/tasks/tests/test_builder_templates.py`

- [ ] **Step 1: Write failing template tests**

Create `mcp-servers/tasks/tests/test_builder_templates.py`:

```python
from claude_executor import (
    build_enhance_prompt,
    build_plan_prompt,
    build_tdd_execute_prompt,
)


def test_enhance_prompt_explains_republish():
    prompt = build_enhance_prompt(slug="meeting-notes", user_request="add search")
    assert "Public users will not see it until you click Republish" in prompt


def test_plan_prompt_requires_plain_language_summary():
    prompt = build_plan_prompt(
        description="Build a meeting notes app",
        action_type="BUILD",
        priority="NICE_TO_HAVE",
        requirements="web app",
    )
    assert "What the app will do" in prompt
    assert "technical details" in prompt.lower()


def test_tdd_prompt_requires_user_facing_generated_app_copy():
    prompt = build_tdd_execute_prompt(
        description="Build a simple app",
        action_type="BUILD",
        priority="NICE_TO_HAVE",
        meeting_title="x",
        meeting_date="",
        plan="plan",
        conversation_history=[],
    )
    assert "clear page title" in prompt.lower()
    assert "empty state" in prompt.lower()
    assert "relative API paths" in prompt
```

- [ ] **Step 2: Run tests to confirm they fail**

Run:

```powershell
cd mcp-servers/tasks
python -m pytest tests/test_builder_templates.py -v
```

Expected: FAIL because the required phrases are missing.

- [ ] **Step 3: Improve `PLAN_PROMPT_TEMPLATE`**

In `mcp-servers/tasks/claude_executor.py`, change the plan sections so the first section starts with plain language:

```text
## 1. WHAT THE APP WILL DO
- Plain-language summary for the admin
- Main screens or views users will see
- What the user can click, create, edit, delete, or search
- Success criteria in user-facing terms

## 2. TECHNICAL DETAILS
- Architecture: files to create, components, data flow
- Exact file paths under apps/<slug>/ (e.g. apps/notes-organizer/index.html)
- Dependencies (if any - prefer zero-dep vanilla JS for simple apps)
- Runtime assumptions for preview and public publishing
```

Keep the existing test and implementation sections, but rename them consistently:

```text
## 3. TEST SPECIFICATIONS
## 4. IMPLEMENTATION STEPS
```

- [ ] **Step 4: Improve `TDD_EXECUTE_PROMPT_TEMPLATE` generated app guidance**

Add this block after the existing scope rules:

```text
GENERATED APP UX RULES:
  1. Use a clear page title and obvious primary action button.
  2. Add helpful empty states for empty lists and missing search results.
  3. Label form fields clearly. Do not use developer-only labels.
  4. Show plain error messages users can act on. Never expose stack traces in
     the browser.
  5. Confirm destructive actions such as delete.
  6. Use relative API paths so the app works in preview and when published at
     {slug}.ai-ui.coolestdomain.win.
  7. Do not show developer-only text such as sample, debug, placeholder, or
     lorem ipsum in the finished app.
```

If `{slug}` is not available in this template, write:

```text
     the public app subdomain.
```

instead of using `{slug}`.

- [ ] **Step 5: Improve `ENHANCE_PROMPT_TEMPLATE` completion instruction**

Add this exact sentence inside the successful `COMPLETED:` format instructions:

```text
Include this sentence when the app has a public version:
"This is updated in preview. Public users will not see it until you click Republish."
```

Also update the example completion block to include:

```text
This is updated in preview. Public users will not see it until you click Republish.
```

- [ ] **Step 6: Run template tests**

Run:

```powershell
cd mcp-servers/tasks
python -m pytest tests/test_builder_templates.py tests/test_enhance_prompt.py tests/test_claude_executor.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add mcp-servers/tasks/claude_executor.py `
        mcp-servers/tasks/tests/test_builder_templates.py
git commit -m "feat(tasks): clarify builder and app templates"
```

---

### Task 11: End-to-End Verification

**Files:**
- No source changes expected unless verification finds defects.

- [ ] **Step 1: Run focused test suite**

Run:

```powershell
cd mcp-servers/tasks
python -m pytest `
  tests/test_published_app_model.py `
  tests/test_publish_service.py `
  tests/test_app_runtime.py `
  tests/test_routes_publish.py `
  tests/test_public_app_runner.py `
  tests/test_routes_public.py `
  tests/test_builder_templates.py `
  tests/test_enhance_prompt.py `
  tests/test_slug_preservation.py `
  -v
```

Expected: PASS.

- [ ] **Step 2: Run all tasks service tests**

Run:

```powershell
cd mcp-servers/tasks
python -m pytest tests -v
```

Expected: PASS.

- [ ] **Step 3: Validate Caddy configuration**

Run one of these, depending on environment:

```powershell
caddy validate --config Caddyfile
```

or:

```powershell
docker compose -f docker-compose.unified.yml exec caddy caddy validate --config /etc/caddy/Caddyfile
```

Expected: valid configuration.

- [ ] **Step 4: Manual static app smoke test**

Use an existing completed static BUILD task or seed one manually with an `apps/<slug>/index.html` folder.

Check:

- Preview page shows Publish.
- Publish creates `published-apps/<slug>/current/index.html`.
- `https://<slug>.ai-ui.coolestdomain.win` opens the static app.
- Unpublish returns the friendly not-published page.

- [ ] **Step 5: Manual backend app smoke test**

Use the meeting-notes style backend app.

Check:

- Publish creates snapshot without `node_modules`.
- First public request starts the Node app on a 9200-range port.
- Public app can call its relative API paths.
- After enhancement, public app does not change before Republish.
- Republish updates the snapshot and public URL.

- [ ] **Step 6: Final status**

Do not claim completion until all commands above have either passed or the exact blocker is recorded.

---

## Self-Review Notes

Spec coverage:

- Public `{slug}.ai-ui.coolestdomain.win` routing: Tasks 6 and 8.
- Snapshot publish layer: Tasks 2 and 4.
- Backend app support: Tasks 3, 5, and 6.
- On-demand start with idle shutdown: Tasks 5 and 7.
- Publish, Republish, Unpublish UI: Task 9.
- Builder communication and generated app guidance: Task 10.
- Verification for static and backend apps: Task 11.

Type consistency:

- `PublishedApp.slug`, `PublishedApp.snapshot_path`, `PublishStatusOut.status`, and `PublishActionOut.snapshot_path` are used consistently across tasks.
- Routes use `/api/tasks/{task_id}/publish/status`, `/publish`, `/republish`, and `/unpublish`.
- Public runner exposes `ensure_started(slug, snapshot_path)`, `status(slug)`, `reap_idle()`, and `stop_all()`.
