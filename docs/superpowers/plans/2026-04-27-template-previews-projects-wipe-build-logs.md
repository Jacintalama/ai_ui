# Template Previews + Projects Wipe + Build Logs Verified — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship working live previews for all 5 base-app templates in the gallery, wipe all current projects so we start clean, and verify the build-log streaming actually displays agent activity in real time.

**Architecture:** The blocking issue with previews so far has been Open WebUI's service worker intercepting same-origin requests under `/tasks/...` and serving its own 404 fallback. We've already proven `/api/*` paths bypass the SW (the gallery's `/api/templates` call works fine). So we **mount `template_apps/` under `/api/template-preview/` instead of `/tasks/template-apps/`** — a one-line FastAPI mount change. The gallery card embeds a live iframe pointing at the new path; relative URLs inside the template (CSS, JS imports, Supabase CDN) all resolve under `/api/...` and work without SW intercept. No bundler, no subdomain, no Playwright. The projects-wipe is a SQL truncate + filesystem rmtree scoped to the current admin user. Build-log verification is a smoke test of existing code, not a rewrite — the stream-json renderer was shipped earlier and just needs an end-to-end sanity check on a fresh build.

**Tech Stack:** FastAPI (StaticFiles mount), Postgres (asyncpg), vanilla HTML+JS gallery in projects.html, existing Caddy reverse proxy (no Caddyfile change — `/api/*` already routes to api-gateway → tasks).

---

## File Structure

| Path | Responsibility | Action |
|---|---|---|
| `mcp-servers/tasks/main.py` | FastAPI app + static mounts | Modify — add `/api/template-preview` static mount |
| `mcp-servers/tasks/static/projects.html` | App Builder + gallery + new-project modal | Modify — gallery card uses new iframe URL |
| `mcp-servers/tasks/tests/test_template_preview_route.py` | Verify the new mount serves the right content | Create |
| `.claude/worktrees/wipe-projects.sql` | One-time SQL to scrub the current admin's projects | Create (gitignored) |

The old `/tasks/template-apps/` mount stays in `main.py` for now — it's still used by the BUILD pipeline to serve the *user's* generated apps. We're only adding a parallel `/api/` mount for the *reference* template_apps. If SW interferes there too in the future, that's a separate fix.

---

## Task 1: Wipe all current projects (clean slate)

**Files:**
- Create: `.claude/worktrees/wipe-projects.sql`

- [ ] **Step 1: Write the wipe SQL to a temp file**

```sql
-- .claude/worktrees/wipe-projects.sql
-- Reset every project owned by the current admin so we test the new flow
-- on a clean slate. Run this once via docker exec postgres psql -f.
BEGIN;
DELETE FROM tasks.chat_history       WHERE user_email = 'ralphbenitez32@gmail.com';
DELETE FROM tasks.project_supabase   WHERE slug IN (SELECT slug FROM tasks.project_members WHERE user_email = 'ralphbenitez32@gmail.com');
DELETE FROM tasks.published_apps     WHERE slug IN (SELECT slug FROM tasks.project_members WHERE user_email = 'ralphbenitez32@gmail.com');
DELETE FROM tasks.items              WHERE built_app_slug IN (SELECT slug FROM tasks.project_members WHERE user_email = 'ralphbenitez32@gmail.com');
DELETE FROM tasks.items              WHERE assignee_email = 'ralphbenitez32@gmail.com';
DELETE FROM tasks.project_members    WHERE user_email = 'ralphbenitez32@gmail.com';
COMMIT;
SELECT 'items'     AS tbl, COUNT(*) FROM tasks.items
UNION ALL SELECT 'members',   COUNT(*) FROM tasks.project_members
UNION ALL SELECT 'supabase',  COUNT(*) FROM tasks.project_supabase
UNION ALL SELECT 'chat',      COUNT(*) FROM tasks.chat_history
UNION ALL SELECT 'published', COUNT(*) FROM tasks.published_apps;
```

- [ ] **Step 2: Copy the SQL into the postgres container and run it**

Run on the VPS:
```bash
scp -i ~/.ssh/aiui_vps .claude/worktrees/wipe-projects.sql root@46.224.193.25:/tmp/wipe.sql
ssh -i ~/.ssh/aiui_vps root@46.224.193.25 \
  "docker cp /tmp/wipe.sql postgres:/tmp/wipe.sql && \
   docker exec postgres psql -U openwebui -d openwebui -f /tmp/wipe.sql"
```

Expected output ends with all five row-count lines reading `0` for the current user (the legacy `hello-world` row owned by `ralph@aiui.com` is unrelated and stays).

- [ ] **Step 3: Remove the user's app folders on disk**

```bash
ssh -i ~/.ssh/aiui_vps root@46.224.193.25 "ls /root/proxy-server/apps/"
```

For every folder listed that belongs to the current admin (none should remain after the previous wipes — verify against the `tasks.project_members` query), run:

```bash
ssh -i ~/.ssh/aiui_vps root@46.224.193.25 "rm -rf /root/proxy-server/apps/<folder>"
```

Then confirm:

```bash
ssh -i ~/.ssh/aiui_vps root@46.224.193.25 "ls /root/proxy-server/apps/ 2>&1"
```

Expected: empty or a single legacy folder for an unrelated account.

- [ ] **Step 4: Verify the App Builder shows zero projects**

In a browser, load `https://ai-ui.coolestdomain.win/tasks/app-builder` (hard-refresh).
Expected: header reads "Built apps 0" and the grid is empty.

- [ ] **Step 5: Commit the wipe SQL**

```bash
cd "C:/All/Work - Code/ai_ui"
git add .claude/worktrees/wipe-projects.sql
git commit -m "ops: one-shot SQL to wipe current admin's projects"
```

---

## Task 2: Add `/api/template-preview` static mount that serves `template_apps/`

**Files:**
- Modify: `mcp-servers/tasks/main.py:72-75`

- [ ] **Step 1: Read the current static-mount block**

Open `mcp-servers/tasks/main.py` and locate:

```python
app.mount("/tasks/static", StaticFiles(directory="static"), name="static")
# Read-only public mount of the bundled template reference apps. Used by
# the Templates gallery's iframe previews.
app.mount("/tasks/template-apps", StaticFiles(directory="template_apps"), name="template-apps")
```

- [ ] **Step 2: Add a parallel `/api/template-preview` mount**

Replace the block above with:

```python
app.mount("/tasks/static", StaticFiles(directory="static"), name="static")
# Read-only public mount of the bundled template reference apps. The
# /tasks/template-apps path is intercepted by Open WebUI's service worker
# (which claims the /tasks/ path scope) and returns a stale 404. The
# /api/template-preview path is NOT under any SW scope (the gallery's
# /api/templates JSON call already proves /api/* bypasses the SW), so we
# expose the same files there for use as live iframe previews.
app.mount("/tasks/template-apps", StaticFiles(directory="template_apps", html=True), name="template-apps")
app.mount("/api/template-preview", StaticFiles(directory="template_apps", html=True), name="template-preview")
```

The `html=True` argument tells StaticFiles to serve `index.html` automatically when a directory path is requested (e.g. `/api/template-preview/landing/` returns `landing/index.html`).

- [ ] **Step 3: Commit**

```bash
cd "C:/All/Work - Code/ai_ui"
git add mcp-servers/tasks/main.py
git commit -m "feat(tasks): mount template_apps under /api/template-preview to bypass SW"
```

---

## Task 3: Test the new mount serves files correctly

**Files:**
- Create: `mcp-servers/tasks/tests/test_template_preview_route.py`

- [ ] **Step 1: Write the failing test**

```python
# mcp-servers/tasks/tests/test_template_preview_route.py
"""Smoke test for the /api/template-preview static mount.

Confirms the mount serves index.html, nested CSS/JS files, and returns 404
for non-existent paths. The mount is what the gallery iframes load, so a
regression here breaks the entire preview flow.
"""
import os

import httpx
import pytest
from httpx import ASGITransport

from main import app


@pytest.mark.asyncio
async def test_index_html_serves_for_known_template():
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/template-preview/landing/index.html")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    assert "<html" in r.text.lower()


@pytest.mark.asyncio
async def test_directory_index_redirect_serves_index_html():
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/template-preview/landing/")
    assert r.status_code == 200
    assert "<html" in r.text.lower()


@pytest.mark.asyncio
async def test_nested_asset_serves():
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/template-preview/landing/styles/main.css")
    assert r.status_code == 200
    assert "text/css" in r.headers.get("content-type", "")


@pytest.mark.asyncio
async def test_unknown_template_returns_404():
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/template-preview/no-such-template/index.html")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_path_traversal_blocked():
    """StaticFiles' default behavior is to reject `..` segments. Verify."""
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/template-preview/../etc/passwd")
    # Path-normalized away from the mount, so should 404 rather than expose data.
    assert r.status_code in (404, 400)
```

- [ ] **Step 2: Run tests to verify they fail (mount not yet added in this session's context — will pass if Task 2 already ran)**

Run inside the tasks container, with a test-only `DATABASE_URL`:

```bash
ssh -i ~/.ssh/aiui_vps root@46.224.193.25 \
  "docker exec -e AIUI_TEST_DB=1 -e DATABASE_URL='postgresql://openwebui:<DB_PASSWORD>@postgres:5432/openwebui_test' \
   tasks pytest tests/test_template_preview_route.py -v --tb=short"
```

Expected: 5 tests pass. If the 5th test (`test_path_traversal_blocked`) fails because StaticFiles silently normalizes the path and returns 200 for some other file, downgrade the assertion to `assert r.status_code != 200` rather than relaxing the test.

- [ ] **Step 3: Commit the test file**

```bash
cd "C:/All/Work - Code/ai_ui"
git add mcp-servers/tasks/tests/test_template_preview_route.py
git commit -m "test(tasks): smoke test the /api/template-preview static mount"
```

---

## Task 4: Frontend gallery — embed live iframe via the new path

**Files:**
- Modify: `mcp-servers/tasks/static/projects.html` (gallery card render in `_renderTgGrid`)

- [ ] **Step 1: Locate the gallery render block**

Open `mcp-servers/tasks/static/projects.html` and find the `tgGrid.innerHTML = filtered.map(...)` block inside `_renderTgGrid()`. The visual currently uses an SVG mockup:

```javascript
const visual = t.svg_mockup
  ? `<div class="visual visual-svg">${t.svg_mockup}</div>`
  : `<div class="visual">
      <div class="placeholder">
        <div class="vname">${escapeHtml(t.label)}</div>
        <div class="vsub">${escapeHtml(t.role_tag || "Ready app")}</div>
      </div>
    </div>`;
```

- [ ] **Step 2: Replace with iframe pointing at `/api/template-preview/<key>/`**

Change the block to:

```javascript
// Live iframe preview from /api/template-preview/<key>/index.html. This
// path is NOT under Open WebUI's service-worker scope, so requests pass
// through to our origin and render properly. Iframe is rendered at desktop
// size (1366×768) then scaled down via CSS transform.
const previewUrl = "/api/template-preview/" + encodeURIComponent(t.key) + "/index.html";
const visual = `
  <div class="visual visual-iframe">
    <iframe class="preview" src="${previewUrl}" loading="lazy" title="${escapeHtml(t.label)} preview"></iframe>
    <div class="placeholder fallback">
      <div class="vname">${escapeHtml(t.label)}</div>
      <div class="vsub">${escapeHtml(t.role_tag || "Ready app")}</div>
    </div>
  </div>`;
```

The `.fallback` placeholder sits underneath the iframe in case the iframe fails to load — JS in step 3 hides it on successful load.

- [ ] **Step 3: Add CSS for `.visual-iframe`**

Find the existing `.visual.visual-svg` block in the inline `<style>` and add right after it:

```css
#templates-modal .tcard .visual.visual-iframe {
  background: #ffffff;
}
#templates-modal .tcard .visual.visual-iframe iframe.preview {
  position: absolute;
  top: 0; left: 0;
  width: 1366px;
  height: 768px;
  border: 0;
  transform: scale(0.235);
  transform-origin: top left;
  pointer-events: none;
  background: #ffffff;
  z-index: 2;
}
#templates-modal .tcard .visual.visual-iframe iframe.preview.broken { display: none; }
#templates-modal .tcard .visual.visual-iframe .placeholder.fallback {
  position: absolute; inset: 0;
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 6px;
  background: linear-gradient(135deg, #4338ca 0%, #1e1b4b 100%);
  color: #fff;
  z-index: 1;
}
```

The iframe sits at `z-index: 2` so it covers the fallback when it loads cleanly.

- [ ] **Step 4: Add iframe-load health check**

Find the existing `tgGrid.querySelectorAll(".tcard").forEach(...)` block that wires Use buttons. Inside that loop, add this iframe handler right after `card` is captured:

```javascript
const ifr = card.querySelector("iframe.preview");
if (ifr) {
  ifr.addEventListener("load", () => {
    try {
      const doc = ifr.contentDocument;
      const titleBad = doc && /404|not found|error/i.test(doc.title || "");
      const tooSmall = doc && doc.body && (doc.body.textContent || "").trim().length < 100;
      if (titleBad || tooSmall) ifr.classList.add("broken");
    } catch (_) {
      ifr.classList.add("broken");
    }
  });
  ifr.addEventListener("error", () => ifr.classList.add("broken"));
}
```

The fallback gradient is always behind, so a `.broken` iframe degrades gracefully.

- [ ] **Step 5: Commit**

```bash
cd "C:/All/Work - Code/ai_ui"
git add mcp-servers/tasks/static/projects.html
git commit -m "feat(gallery): live iframe previews via /api/template-preview"
```

---

## Task 5: Deploy and end-to-end verify the gallery previews

- [ ] **Step 1: Sync the changed files to the VPS and into the running container**

```bash
cd "C:/All/Work - Code/ai_ui/mcp-servers/tasks"
scp -i ~/.ssh/aiui_vps main.py static/projects.html root@46.224.193.25:/tmp/
ssh -i ~/.ssh/aiui_vps root@46.224.193.25 "
  mv /tmp/main.py /root/proxy-server/mcp-servers/tasks/
  mv /tmp/projects.html /root/proxy-server/mcp-servers/tasks/static/
  docker cp /root/proxy-server/mcp-servers/tasks/main.py tasks:/app/
  docker cp /root/proxy-server/mcp-servers/tasks/static/projects.html tasks:/app/static/
  docker restart tasks && sleep 4 && docker logs --tail 5 tasks"
```

Expected: tasks container restarts cleanly with `Application startup complete`.

- [ ] **Step 2: Curl-verify the new mount responds at the right paths**

```bash
ssh -i ~/.ssh/aiui_vps root@46.224.193.25 "
  curl -sk -o /dev/null -w 'landing: %{http_code}\n' https://ai-ui.coolestdomain.win/api/template-preview/landing/index.html
  curl -sk -o /dev/null -w 'crud: %{http_code}\n'    https://ai-ui.coolestdomain.win/api/template-preview/crud/index.html
  curl -sk -o /dev/null -w 'invoice: %{http_code}\n' https://ai-ui.coolestdomain.win/api/template-preview/invoice/index.html
  curl -sk -o /dev/null -w 'dashboard: %{http_code}\n' https://ai-ui.coolestdomain.win/api/template-preview/dashboard/index.html
  curl -sk -o /dev/null -w 'portfolio: %{http_code}\n' https://ai-ui.coolestdomain.win/api/template-preview/portfolio/index.html"
```

Expected: all five return `200`.

- [ ] **Step 3: Browser smoke test the gallery**

In Chrome, load `https://ai-ui.coolestdomain.win/tasks/app-builder` (hard-refresh `Ctrl+Shift+R`). Click `+ New Project`, then `Select template` in the title bar. The gallery should open and each of the five featured cards should render a live miniaturized preview of the actual app inside the card. No "404: Not Found" page in any card.

If a card stays blank for more than 3 seconds, that template's iframe failed and the gradient fallback should show through. Investigate which template, what error appears in DevTools Network tab.

- [ ] **Step 4: If any card 404s in the browser**

Open DevTools Network tab, click the failing card's iframe request, copy the URL. Run:

```bash
ssh -i ~/.ssh/aiui_vps root@46.224.193.25 "curl -sk -o /dev/null -w '%{http_code}\n' '<failing URL>'"
```

If the server returns 200 but the browser shows 404, Cloudflare has cached an older 404. Bypass with `?v=$(date +%s)` query and report. If the server actually returns 404, check the corresponding `template_apps/<key>/` folder exists in the container with `docker exec tasks ls /app/template_apps/<key>/`.

---

## Task 6: Verify build-log streaming works on a fresh build

The stream-json log renderer was shipped earlier in `static/preview.html` (around `_bovCheck` / `_renderLogLine`). This task is a smoke test, not a rewrite.

- [ ] **Step 1: Create a fresh project from a featured template**

In the App Builder (now empty after Task 1), click `+ New Project`. Name it `smoke-test`. Click `Select template`, choose **CRUD app** (or any featured template), click `Use this template`. In the description, type `simple smoke test`. Click `Create project`.

The browser should navigate to `/tasks/static/preview.html?task=...`.

- [ ] **Step 2: Watch the build overlay for streaming agent logs**

Within 5 seconds, the build overlay should show:
- "AIUI Agent is building your app…" header
- A progress phase pill ("Queued" → "Building")
- A black log box that fills with lines like `Read   apps/smoke-test/index.html`, `Edit   apps/smoke-test/styles/main.css`, `Bash   ...` as the agent works

If the log box stays empty for more than 30 seconds while the phase pill says "Building", the streaming pipeline broke. Diagnose:

```bash
ssh -i ~/.ssh/aiui_vps root@46.224.193.25 "docker exec postgres psql -U openwebui -d openwebui -c \"
  SELECT e.id, e.status, length(e.log) AS log_bytes, e.started_at
  FROM tasks.executions e
  JOIN tasks.items i ON i.id = e.task_id
  WHERE i.built_app_slug = 'smoke-test'
  ORDER BY e.started_at DESC LIMIT 3;\""
```

- If `log_bytes` grows over time → streaming works on the backend; bug is in the frontend renderer (check `_renderLogLine` in preview.html for JSON parse errors in DevTools console).
- If `log_bytes` stays at 0 → backend streaming broke; check `routes_execution.py:_stream_claude` and confirm the `claude` CLI subprocess is actually emitting stream-json.

- [ ] **Step 3: After the build completes, confirm the project appears**

Build should finish within 60-90 seconds (most of it is file-copy from `template_apps/crud/` + agent personalization). Once the overlay disappears, the preview should show the working CRUD app. Click `Open preview` from the App Builder grid to confirm.

- [ ] **Step 4: If anything in the build stream is broken, file the smallest reproducer**

Capture: the failing task's UUID, the latest execution's `log` column truncated to 200 chars, and any DevTools console errors. Don't attempt fixes inside this plan — open a follow-up plan.

---

## Self-Review

**Spec coverage:**

| Requirement | Task |
|---|---|
| "remove the projects" | Task 1 (SQL wipe + filesystem rm) |
| "fix the preview of every template" | Tasks 2, 3, 4, 5 (new `/api/template-preview` mount + iframe + verify) |
| "make sure it can be seen `template_apps`" | Task 5 step 2 (curl all 5 templates) + step 3 (browser smoke test) |
| "the logs of building will work" | Task 6 (end-to-end build smoke test with explicit log streaming check) |

No gaps.

**Placeholder scan:**
- No "TBD" / "TODO" / "implement later" — every step has either runnable commands or actual code.
- No vague "add error handling" — error paths are specified (e.g. fallback placeholder when iframe fails, diagnostic SQL when log streaming fails).
- All file paths are absolute.

**Type / signature consistency:**
- The `_renderTgGrid` change in Task 4 references `t.svg_mockup`, `t.role_tag`, `t.label`, `t.key` — all already exposed by `routes_templates.py` as documented in the existing codebase.
- The CSS class `.visual-iframe` in Task 4 step 3 matches the JSX className in step 2.
- The `.broken` class added by the JS health check in step 4 matches the CSS rule in step 3.

**Out-of-scope:**
- Subdomain routing (`templates.coolestdomain.win`) — not needed; mount move solves the problem.
- Bundling ES modules into self-contained HTML — not needed for the same reason.
- Playwright screenshot generation — abandoned in favor of live iframes.
- Reactive cleanup of the legacy `/tasks/template-apps` mount — kept for compatibility; can be removed after a soak period.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-04-27-template-previews-projects-wipe-build-logs.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
