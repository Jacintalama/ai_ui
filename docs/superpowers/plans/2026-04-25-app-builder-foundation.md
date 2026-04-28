# App Builder Foundation Polish — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lock down the publish / custom-domain / unpublish / rename flow with comprehensive backend tests, fix the remaining edge-case bugs, and standardize error/loading UX.

**Architecture:** Backend is FastAPI + SQLAlchemy with `tasks.published_apps` and `tasks.project_members` tables. Tests use the `db_session` pytest fixture (truncates between tests). Caddy uses on-demand TLS gated by `/__caddy/check_ask`.

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy 2.x async / asyncpg / pytest-asyncio / vanilla JS frontend.

---

## File Structure

**Will modify:**
- `mcp-servers/tasks/routes_projects.py` — fix slug-validation regex on rename, fix race in unpublish + custom-domain reset
- `mcp-servers/tasks/main.py` — harden `/__caddy/check_ask` against malformed domains
- `mcp-servers/tasks/static/preview.html` — show inline busy state while publishing/attaching/verifying

**Will create:**
- `mcp-servers/tasks/tests/test_routes_projects.py` — full coverage of publish, custom-domain, presence, members, versions, rename
- `mcp-servers/tasks/tests/test_caddy_ask.py` — on-demand TLS gatekeeper coverage

---

### Task 1: Test fixture for published-apps + members

**Files:**
- Modify: `mcp-servers/tasks/tests/conftest.py`

The existing `db_session` fixture truncates `tasks.items, tasks.executions CASCADE`. We need it to also truncate `tasks.published_apps` and `tasks.project_members` so each test sees a clean slate.

- [ ] **Step 1: Add the truncate lines**

Modify the `TRUNCATE` line in `conftest.py:31` to:

```python
        await conn.execute(text(
            "TRUNCATE tasks.items, tasks.executions, "
            "tasks.published_apps, tasks.project_members CASCADE"
        ))
```

- [ ] **Step 2: Verify existing tests still pass**

```bash
ssh -i ~/.ssh/aiui_safe root@46.224.193.25 "docker exec tasks pytest tests/ -q"
```

Expected: all green (the new tables get truncated, no other behavior changes).

- [ ] **Step 3: Commit**

```bash
git add mcp-servers/tasks/tests/conftest.py
git commit -m "test(tasks): truncate published_apps + project_members between tests"
```

---

### Task 2: Backend test — POST /api/projects/{slug}/publish

**Files:**
- Create: `mcp-servers/tasks/tests/test_routes_projects.py`

- [ ] **Step 1: Write the failing test for the basic publish flow**

```python
# mcp-servers/tasks/tests/test_routes_projects.py
"""Tests for routes_projects: publish, custom domain, members, versions, rename."""
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from main import app
from models import ProjectMember, PublishedApp, TaskItem

OWNER_HDR = {"X-User-Email": "ralph@aiui.com", "X-User-Admin": "true"}
OTHER_HDR = {"X-User-Email": "other@aiui.com", "X-User-Admin": "true"}


def _build_task(*, slug, email="ralph@aiui.com"):
    return TaskItem(
        meeting_id=uuid.uuid4(),
        action_type="BUILD",
        assignee_name="Ralph",
        assignee_email=email,
        description="x",
        priority="IMPORTANT",
        status="completed",
        built_app_slug=slug,
    )


@pytest.fixture
def transport():
    return ASGITransport(app=app)


async def test_publish_sets_owner_and_returns_url(db_session, transport, monkeypatch, tmp_path):
    """POST /publish creates a published_apps row and a project_members owner row."""
    # Create a real built app on disk so the index.html check passes.
    apps_root = tmp_path / "apps" / "alpha"
    apps_root.mkdir(parents=True)
    (apps_root / "index.html").write_text("<html></html>")
    monkeypatch.setattr("routes_projects.REPO_ROOT", str(tmp_path))

    db_session.add(_build_task(slug="alpha"))
    db_session.add(ProjectMember(slug="alpha", user_email="ralph@aiui.com",
                                  role="owner", added_by="ralph@aiui.com"))
    await db_session.commit()

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/projects/alpha/publish", headers=OWNER_HDR)

    assert r.status_code == 200
    body = r.json()
    assert body["published"] is True
    assert body["public_url"].endswith(".coolestdomain.win/")
    assert body["public_url"].startswith("https://alpha.")

    # Verify DB row exists.
    pub = (await db_session.execute(
        select(PublishedApp).where(PublishedApp.slug == "alpha")
    )).scalar_one()
    assert pub.published_by == "ralph@aiui.com"
```

- [ ] **Step 2: Run test, expect failure (no test file existed before)**

```bash
ssh -i ~/.ssh/aiui_safe root@46.224.193.25 "docker exec tasks pytest tests/test_routes_projects.py::test_publish_sets_owner_and_returns_url -v"
```

Expected: PASS — the publish endpoint already exists and works. (We're adding test coverage for the existing behavior.)

- [ ] **Step 3: Commit**

```bash
git add mcp-servers/tasks/tests/test_routes_projects.py
git commit -m "test(tasks): cover publish endpoint happy path"
```

---

### Task 3: Backend test — non-owner cannot publish

**Files:**
- Modify: `mcp-servers/tasks/tests/test_routes_projects.py`

- [ ] **Step 1: Append the test**

```python
async def test_publish_rejects_non_owner(db_session, transport, monkeypatch, tmp_path):
    apps_root = tmp_path / "apps" / "alpha"
    apps_root.mkdir(parents=True)
    (apps_root / "index.html").write_text("<html></html>")
    monkeypatch.setattr("routes_projects.REPO_ROOT", str(tmp_path))

    db_session.add(_build_task(slug="alpha", email="ralph@aiui.com"))
    db_session.add(ProjectMember(slug="alpha", user_email="ralph@aiui.com",
                                  role="owner", added_by="ralph@aiui.com"))
    await db_session.commit()

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # 'other' is not a member of 'alpha' at all.
        r = await c.post("/api/projects/alpha/publish",
                         headers={"X-User-Email": "other@aiui.com",
                                  "X-User-Admin": "true"})

    assert r.status_code == 403
```

- [ ] **Step 2: Run test, expect PASS (existing endpoint enforces this)**

```bash
ssh -i ~/.ssh/aiui_safe root@46.224.193.25 "docker exec tasks pytest tests/test_routes_projects.py::test_publish_rejects_non_owner -v"
```

- [ ] **Step 3: Commit**

```bash
git add mcp-servers/tasks/tests/test_routes_projects.py
git commit -m "test(tasks): publish rejects non-owners"
```

---

### Task 4: Backend test — unpublish wipes everything (incl. custom domain)

**Files:**
- Modify: `mcp-servers/tasks/tests/test_routes_projects.py`

- [ ] **Step 1: Append the test**

```python
async def test_unpublish_wipes_published_row_and_custom_domain(db_session, transport):
    db_session.add(PublishedApp(
        slug="alpha", published_by="ralph@aiui.com",
        public_host="alpha.example.com",
        custom_domain="myapp.com",
    ))
    db_session.add(ProjectMember(slug="alpha", user_email="ralph@aiui.com",
                                  role="owner", added_by="ralph@aiui.com"))
    await db_session.commit()

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.delete("/api/projects/alpha/publish", headers=OWNER_HDR)

    assert r.status_code == 204

    pub = (await db_session.execute(
        select(PublishedApp).where(PublishedApp.slug == "alpha")
    )).scalar_one_or_none()
    assert pub is None
```

- [ ] **Step 2: Run, expect PASS**

```bash
ssh -i ~/.ssh/aiui_safe root@46.224.193.25 "docker exec tasks pytest tests/test_routes_projects.py::test_unpublish_wipes_published_row_and_custom_domain -v"
```

- [ ] **Step 3: Commit**

```bash
git add mcp-servers/tasks/tests/test_routes_projects.py
git commit -m "test(tasks): unpublish wipes published row + custom domain"
```

---

### Task 5: Backend test — rename atomically updates 3 tables

**Files:**
- Modify: `mcp-servers/tasks/tests/test_routes_projects.py`

- [ ] **Step 1: Append the test**

```python
import os

async def test_rename_updates_all_tables(db_session, transport, monkeypatch, tmp_path):
    # Set up a git repo at tmp_path so _run_git works.
    monkeypatch.setattr("routes_projects.REPO_ROOT", str(tmp_path))
    os.system(f"git -C {tmp_path} init -q")
    os.system(f"git -C {tmp_path} config user.email t@t")
    os.system(f"git -C {tmp_path} config user.name t")
    apps_dir = tmp_path / "apps" / "alpha"
    apps_dir.mkdir(parents=True)
    (apps_dir / "index.html").write_text("<html></html>")
    os.system(f"git -C {tmp_path} add . && git -C {tmp_path} commit -q -m init")

    db_session.add(_build_task(slug="alpha"))
    db_session.add(ProjectMember(slug="alpha", user_email="ralph@aiui.com",
                                  role="owner", added_by="ralph@aiui.com"))
    db_session.add(PublishedApp(slug="alpha", published_by="ralph@aiui.com",
                                 public_host="alpha.example.com"))
    await db_session.commit()

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/projects/alpha/rename",
                         headers=OWNER_HDR,
                         json={"new_slug": "beta"})

    assert r.status_code == 200
    body = r.json()
    assert body["new_slug"] == "beta"

    # All three tables now reference "beta".
    task = (await db_session.execute(
        select(TaskItem).where(TaskItem.built_app_slug == "beta")
    )).scalar_one()
    assert task.built_app_slug == "beta"
    pub = (await db_session.execute(
        select(PublishedApp).where(PublishedApp.slug == "beta")
    )).scalar_one()
    assert pub.slug == "beta"
    mem = (await db_session.execute(
        select(ProjectMember).where(ProjectMember.slug == "beta")
    )).scalar_one()
    assert mem.slug == "beta"

    # Old slug is GONE everywhere.
    old = (await db_session.execute(
        select(TaskItem).where(TaskItem.built_app_slug == "alpha")
    )).scalar_one_or_none()
    assert old is None
```

- [ ] **Step 2: Run, expect PASS**

```bash
ssh -i ~/.ssh/aiui_safe root@46.224.193.25 "docker exec tasks pytest tests/test_routes_projects.py::test_rename_updates_all_tables -v"
```

- [ ] **Step 3: Commit**

```bash
git add mcp-servers/tasks/tests/test_routes_projects.py
git commit -m "test(tasks): rename moves slug across items + published + members"
```

---

### Task 6: Backend test — Caddy ask endpoint gates correctly

**Files:**
- Create: `mcp-servers/tasks/tests/test_caddy_ask.py`

- [ ] **Step 1: Write the test file**

```python
"""Caddy on-demand TLS gatekeeper at GET /__caddy/check_ask."""
from datetime import datetime

import pytest
from httpx import ASGITransport, AsyncClient

from main import app
from models import PublishedApp


@pytest.fixture
def transport():
    return ASGITransport(app=app)


async def test_ask_rejects_missing_domain(transport):
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/__caddy/check_ask")
    # Missing domain → 404 (we treat any unparseable host as "not allowed").
    assert r.status_code == 404


async def test_ask_rejects_two_label_domain(transport):
    """A bare apex like 'example.com' is not a valid <slug>.<parent> shape."""
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/__caddy/check_ask?domain=example.com")
    assert r.status_code == 404


async def test_ask_rejects_unverified(db_session, transport):
    db_session.add(PublishedApp(
        slug="alpha", published_by="r@aiui.com",
        public_host="alpha.example.com",
        custom_domain="example.com",
        custom_domain_verified_at=None,  # NOT verified
    ))
    await db_session.commit()
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/__caddy/check_ask?domain=alpha.example.com")
    assert r.status_code == 404


async def test_ask_allows_verified(db_session, transport):
    db_session.add(PublishedApp(
        slug="alpha", published_by="r@aiui.com",
        public_host="alpha.example.com",
        custom_domain="example.com",
        custom_domain_verified_at=datetime.utcnow(),
    ))
    await db_session.commit()
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/__caddy/check_ask?domain=alpha.example.com")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


async def test_ask_rejects_wrong_slug_under_verified_parent(db_session, transport):
    db_session.add(PublishedApp(
        slug="alpha", published_by="r@aiui.com",
        public_host="alpha.example.com",
        custom_domain="example.com",
        custom_domain_verified_at=datetime.utcnow(),
    ))
    await db_session.commit()
    # alpha is verified; beta is not — so beta.example.com must NOT pass.
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/__caddy/check_ask?domain=beta.example.com")
    assert r.status_code == 404
```

- [ ] **Step 2: Run all 5 tests, expect PASS**

```bash
ssh -i ~/.ssh/aiui_safe root@46.224.193.25 "docker exec tasks pytest tests/test_caddy_ask.py -v"
```

- [ ] **Step 3: Commit**

```bash
git add mcp-servers/tasks/tests/test_caddy_ask.py
git commit -m "test(tasks): cover on-demand TLS ask endpoint gates"
```

---

### Task 7: Frontend busy-state on long Publish/Verify operations

**Files:**
- Modify: `mcp-servers/tasks/static/preview.html` — search for `$pubConfirm.addEventListener`

The Publish and Verify buttons currently just disable + change text. Add a small inline spinner so a slow request feels responsive.

- [ ] **Step 1: Add a CSS spinner used inline next to button text**

Add to the CSS block (near the existing `.spinner` rules — search for `@keyframes spin`):

```css
.btn-spinner {
  display: inline-block;
  width: 11px;
  height: 11px;
  margin-right: 5px;
  border: 1.5px solid currentColor;
  border-top-color: transparent;
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
  vertical-align: -1px;
}
```

- [ ] **Step 2: Update the Publish handler to show spinner**

Replace the busy-state block in `$pubConfirm.addEventListener("click", async () => {`:

```javascript
    $pubConfirm.disabled = true;
    $pubConfirm.innerHTML = '<span class="btn-spinner"></span>Publishing…';
```

And in the finally clause:

```javascript
    } finally {
      $pubConfirm.disabled = false;
      $pubConfirm.textContent = "Publish now";
    }
```

- [ ] **Step 3: Same treatment for Verify and Attach**

Replace the relevant lines in `$cdVerify` click handler:

```javascript
    $cdVerify.disabled = true;
    $cdVerify.innerHTML = '<span class="btn-spinner"></span>Checking…';
```

And in `$cdAttach` click handler when auto-publishing:

```javascript
    $cdAttach.innerHTML = '<span class="btn-spinner"></span>Publishing…';
    // ...later...
    $cdAttach.innerHTML = '<span class="btn-spinner"></span>Attaching…';
```

- [ ] **Step 4: Manual test — open preview.html, click Publish, verify spinner shows**

Open the project preview page in a browser, click 🌐 Publish. The Publish button should show a small spinning circle next to "Publishing…" text.

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/static/preview.html
git commit -m "feat(preview): inline spinner on publish/verify/attach buttons"
```

---

### Task 8: Self-review + smoke test

- [ ] **Step 1: Run all tests one more time**

```bash
ssh -i ~/.ssh/aiui_safe root@46.224.193.25 "docker exec tasks pytest tests/ -q"
```

Expected: all green.

- [ ] **Step 2: Live publish-flow smoke test**

In a browser:
1. Open `/tasks/app-builder` → click any project → preview opens
2. Confirm topbar badge reads **Publish** (grey) when nothing's published, or **Preview** (amber) for auto-only, or **Live** (green) for verified custom domain
3. Click 🌐 Publish → modal appears with the new spinner
4. Type a domain → Attach → spinner → DNS table appears
5. Click Verify DNS → spinner → either ✓ or warning
6. Click Unpublish → confirms with the right phrasing → badge resets to grey

- [ ] **Step 3: Final commit if any nits**

```bash
git add -A
git commit -m "chore(plan-foundation): smoke-test pass" || true
```
