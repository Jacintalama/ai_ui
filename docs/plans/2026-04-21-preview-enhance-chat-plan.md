# Preview Enhance-Chat Sidebar — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a Lovable-style chat sidebar to the preview page so admins can type enhancement prompts and watch the AI modify the existing app with phase labels showing progress.

**Architecture:** One new backend endpoint (`POST /api/tasks/enhance`) creates a new task per enhancement with `ENHANCE_PROMPT_TEMPLATE` context, skipping CLARIFY/PLAN and going straight to TDD EXECUTE → VERIFY. Frontend adds a right-side column to `preview.html` with chat bubbles, phase polling, and iframe auto-refresh on success. One-enhancement-at-a-time per app.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy async, Pydantic, vanilla HTML/CSS/JS (no build step), Claude CLI subprocess.

**Design:** See `docs/plans/2026-04-21-preview-enhance-chat-design.md`.

---

### Task 1: Add `EnhanceRequest` schema + `build_enhance_prompt()` helper

**Files:**
- Modify: `mcp-servers/tasks/schemas.py` (append at end)
- Modify: `mcp-servers/tasks/claude_executor.py` (append new template + builder)
- Test: `mcp-servers/tasks/tests/test_enhance_prompt.py` (create)

**Step 1: Write failing tests**

Create `mcp-servers/tasks/tests/test_enhance_prompt.py`:

```python
import pytest
from claude_executor import build_enhance_prompt, ENHANCE_PROMPT_TEMPLATE
from schemas import EnhanceRequest


def test_enhance_request_validates_non_empty_prompt():
    with pytest.raises(Exception):
        EnhanceRequest(source_task_id="00000000-0000-0000-0000-000000000001", prompt="")


def test_enhance_request_rejects_too_long_prompt():
    with pytest.raises(Exception):
        EnhanceRequest(
            source_task_id="00000000-0000-0000-0000-000000000001",
            prompt="x" * 2001,
        )


def test_build_enhance_prompt_includes_slug_and_user_request():
    out = build_enhance_prompt(
        slug="meeting-notes",
        user_request="add attendees field",
        attempt_count=0,
        max_attempts=3,
    )
    assert "apps/meeting-notes/" in out
    assert "add attendees field" in out


def test_build_enhance_prompt_forbids_stack_pivot():
    out = build_enhance_prompt(
        slug="todo-list",
        user_request="add dark mode",
        attempt_count=0,
        max_attempts=3,
    )
    # Must warn against replacing stack
    assert "preserve the existing tech stack" in out.lower()


def test_build_enhance_prompt_requires_tdd():
    out = build_enhance_prompt(
        slug="x",
        user_request="y",
        attempt_count=0,
        max_attempts=3,
    )
    assert "red-green-refactor" in out.lower() or "red" in out.lower()


def test_build_enhance_prompt_retry_context_appears_on_retry():
    out = build_enhance_prompt(
        slug="x",
        user_request="y",
        attempt_count=1,
        max_attempts=3,
        error_context="Previous test failed: missing import",
    )
    assert "Previous test failed: missing import" in out
    assert "1/3" in out or "attempt 1" in out.lower()
```

**Step 2: Run tests, confirm RED**

```bash
cd mcp-servers/tasks && python -m pytest tests/test_enhance_prompt.py -v
```

Expected: all 5 tests fail with `ImportError: cannot import name 'build_enhance_prompt'` / `EnhanceRequest`.

**Step 3: Add `EnhanceRequest` to `schemas.py`**

Append at end of `mcp-servers/tasks/schemas.py`:

```python
class EnhanceRequest(BaseModel):
    source_task_id: UUID
    prompt: str = Field(min_length=1, max_length=2000)
```

**Step 4: Add `ENHANCE_PROMPT_TEMPLATE` + `build_enhance_prompt()` to `claude_executor.py`**

Append at end of the prompt-template block in `claude_executor.py` (after `VERIFY_PROMPT_TEMPLATE`):

```python
ENHANCE_PROMPT_TEMPLATE = """You are enhancing an EXISTING app from the AIUI decision engine.

APP LOCATION: /workspace/ai_ui/apps/{slug}/

USER REQUEST: {user_request}

RULES — READ CAREFULLY:
  1. You are MODIFYING existing code, not creating a new app from scratch.
  2. READ the existing files first (index.html, server.py, etc.) before
     changing anything. Understand the current structure before you touch it.
  3. Make the SMALLEST change that satisfies the request. Do not refactor.
  4. PRESERVE THE EXISTING TECH STACK. If the app is Python/Flask/sqlite3,
     stay there — do not switch to Node/Prisma or vice versa.
  5. Preserve existing features. The user is ADDING to the app, not replacing
     it.
  6. Do NOT delete the existing database file (apps/{slug}/data/*.db).
     If you change the schema, write a migration that ALTERs the existing
     table instead.
  7. Keep tests passing. If there's a tests/ folder or test file, update it
     if your change breaks existing tests.

You MUST follow Red-Green-Refactor for the change itself:
  RED:   Write a test (or update an existing one) that proves the new
         behavior. Run it. Confirm it fails.
  GREEN: Make the minimal change. Run the test. Confirm it passes.
  COMMIT: Stage only the files you changed. One commit with clear message.

{error_context_block}

When done successfully:
  COMPLETED: <one-sentence summary of what changed> (commit <sha>)

If you cannot proceed:
  NEEDS_INPUT: <what you need>
  FAILED: <what went wrong>
"""


def build_enhance_prompt(
    *,
    slug: str,
    user_request: str,
    attempt_count: int = 0,
    max_attempts: int = 3,
    error_context: str = "",
) -> str:
    if error_context:
        err_block = (
            f"PREVIOUS ATTEMPT ({attempt_count}/{max_attempts}) FAILED:\n"
            f"{error_context}\n"
            "Fix the issues above. Do NOT repeat the same mistake."
        )
    else:
        err_block = ""
    return ENHANCE_PROMPT_TEMPLATE.format(
        slug=slug,
        user_request=user_request,
        error_context_block=err_block,
    )
```

**Step 5: Run tests, confirm GREEN**

```bash
cd mcp-servers/tasks && python -m pytest tests/test_enhance_prompt.py -v
```

Expected: `5 passed`.

**Step 6: Commit**

```bash
git add mcp-servers/tasks/schemas.py \
        mcp-servers/tasks/claude_executor.py \
        mcp-servers/tasks/tests/test_enhance_prompt.py
git commit -m "feat(tasks): ENHANCE_PROMPT_TEMPLATE + build_enhance_prompt + EnhanceRequest schema"
```

---

### Task 2: Add `POST /api/tasks/enhance` endpoint

**Files:**
- Modify: `mcp-servers/tasks/routes_tasks.py` (append new route)
- Test: `mcp-servers/tasks/tests/test_enhance_endpoint.py` (create)

**Step 1: Write failing tests**

Create `mcp-servers/tasks/tests/test_enhance_endpoint.py`:

```python
import pytest
import uuid
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)
ADMIN_HEADERS = {
    "X-User-Email": "test@aiui.local",
    "X-User-Admin": "true",
}


def _insert_source(db_conn, slug="meeting-notes", action_type="BUILD"):
    """Seed a completed BUILD task with built_app_slug into the test DB."""
    tid = uuid.uuid4()
    db_conn.execute(
        """INSERT INTO tasks.items
           (id, meeting_id, action_type, assignee_name, assignee_email,
            description, priority, status, built_app_slug)
           VALUES (:id, :mid, :at, 'test', 'test@aiui.local',
                   'Seed', 'NICE_TO_HAVE', 'completed', :slug)""",
        {"id": tid, "mid": uuid.uuid4(), "at": action_type, "slug": slug},
    )
    return tid


def test_enhance_rejects_missing_source():
    r = client.post(
        "/api/tasks/enhance",
        json={"source_task_id": str(uuid.uuid4()), "prompt": "x"},
        headers=ADMIN_HEADERS,
    )
    assert r.status_code == 404


def test_enhance_rejects_research_source(seeded_research_task):
    r = client.post(
        "/api/tasks/enhance",
        json={"source_task_id": str(seeded_research_task), "prompt": "x"},
        headers=ADMIN_HEADERS,
    )
    assert r.status_code == 400
    assert "BUILD" in r.json()["detail"]


def test_enhance_rejects_source_without_slug(seeded_build_no_slug):
    r = client.post(
        "/api/tasks/enhance",
        json={"source_task_id": str(seeded_build_no_slug), "prompt": "x"},
        headers=ADMIN_HEADERS,
    )
    assert r.status_code == 400


def test_enhance_returns_202_and_new_task(seeded_build_task):
    r = client.post(
        "/api/tasks/enhance",
        json={"source_task_id": str(seeded_build_task), "prompt": "add feature X"},
        headers=ADMIN_HEADERS,
    )
    assert r.status_code == 202
    body = r.json()
    assert body["id"] != str(seeded_build_task)
    assert body["action_type"] == "BUILD"
    assert body["built_app_slug"] == "meeting-notes"
    assert body["plan_status"] == "approved"
    assert "add feature X" in body["description"]


def test_enhance_rejects_concurrent(seeded_build_task, seeded_in_flight_enhance):
    r = client.post(
        "/api/tasks/enhance",
        json={"source_task_id": str(seeded_build_task), "prompt": "x"},
        headers=ADMIN_HEADERS,
    )
    assert r.status_code == 409


def test_enhance_requires_auth():
    r = client.post(
        "/api/tasks/enhance",
        json={"source_task_id": str(uuid.uuid4()), "prompt": "x"},
    )
    assert r.status_code == 401
```

(Note: the seeded_* fixtures need to be added to the existing `conftest.py` or created inline with raw SQL; if the tests package already uses a fixture pattern, match it — check `mcp-servers/tasks/tests/` for prior test files to follow conventions.)

**Step 2: Run tests, confirm RED**

```bash
cd mcp-servers/tasks && python -m pytest tests/test_enhance_endpoint.py -v
```

Expected: all fail with 404 (route doesn't exist yet).

**Step 3: Add the endpoint to `routes_tasks.py`**

Append to `mcp-servers/tasks/routes_tasks.py`:

```python
# Near the top of the file, add to imports:
# from schemas import EnhanceRequest
# from claude_executor import build_enhance_prompt
# import asyncio
# from models import TaskExecution
# from routes_execution import _run_execution, _RUNNING

@router.post("/enhance", response_model=TaskOut, status_code=202)
async def enhance(
    body: EnhanceRequest,
    user: AdminUser = Depends(current_admin),
):
    """Create a new task that modifies an existing built app.
    Skips CLARIFY/PLAN, goes straight to TDD EXECUTE with ENHANCE_PROMPT_TEMPLATE.
    """
    from schemas import EnhanceRequest  # local to avoid circulars if needed
    from claude_executor import build_enhance_prompt
    from models import TaskExecution
    from routes_execution import _run_execution, _RUNNING
    import asyncio

    async with session() as s:
        # 1. Validate source
        source = (await s.execute(
            select(TaskItem).where(TaskItem.id == body.source_task_id)
        )).scalar_one_or_none()
        if source is None:
            raise HTTPException(status_code=404, detail="Source task not found")
        if source.action_type != "BUILD":
            raise HTTPException(status_code=400, detail="Can only enhance BUILD tasks")
        if not source.built_app_slug:
            raise HTTPException(
                status_code=400,
                detail="Source task has no built_app_slug — nothing to enhance",
            )

        # 2. Reject concurrent enhancements on same app
        in_flight = (await s.execute(
            select(TaskItem).where(
                TaskItem.built_app_slug == source.built_app_slug,
                TaskItem.status.in_(["running", "planning", "awaiting_input"]),
            )
        )).scalar_one_or_none()
        if in_flight:
            raise HTTPException(
                status_code=409,
                detail=f"Another enhancement is already in progress for apps/{source.built_app_slug}/",
            )

        # 3. Create new enhancement task
        new_task = TaskItem(
            meeting_id=uuid.uuid4(),
            action_type="BUILD",
            assignee_name=user.email.split("@")[0],
            assignee_email=user.email,
            description=f"Enhance apps/{source.built_app_slug}/: {body.prompt.strip()[:400]}",
            priority="NICE_TO_HAVE",
            status="running",
            mode="ai",
            max_attempts=max(source.max_attempts, 1),
            built_app_slug=source.built_app_slug,
            plan_status="approved",
        )
        s.add(new_task)
        await s.commit()
        await s.refresh(new_task)

        execution = TaskExecution(task_id=new_task.id, status="running", log="")
        s.add(execution)
        await s.commit()
        await s.refresh(execution)

    # 4. Fire background execution with ENHANCE prompt
    prompt = build_enhance_prompt(
        slug=source.built_app_slug,
        user_request=body.prompt.strip(),
        attempt_count=0,
        max_attempts=new_task.max_attempts,
    )
    _RUNNING[new_task.id] = {"task": None, "proc": None}
    bg = asyncio.create_task(_run_execution(new_task.id, execution.id, prompt))
    _RUNNING[new_task.id]["task"] = bg

    return new_task
```

**Step 4: Run tests, confirm GREEN**

```bash
cd mcp-servers/tasks && python -m pytest tests/test_enhance_endpoint.py -v
```

Expected: `6 passed`.

**Step 5: Commit**

```bash
git add mcp-servers/tasks/routes_tasks.py mcp-servers/tasks/tests/test_enhance_endpoint.py
git commit -m "feat(tasks): POST /api/tasks/enhance — create enhancement task with ENHANCE prompt"
```

---

### Task 3: Add `slug` filter to `GET /api/tasks`

**Files:**
- Modify: `mcp-servers/tasks/routes_tasks.py:37-57` (the `list_tasks` endpoint)
- Test: `mcp-servers/tasks/tests/test_slug_filter.py` (create)

**Step 1: Write failing test**

Create `mcp-servers/tasks/tests/test_slug_filter.py`:

```python
import uuid
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)
HDR = {"X-User-Email": "test@aiui.local", "X-User-Admin": "true"}


def test_list_tasks_filters_by_slug(seed_two_slugs):
    """seed_two_slugs creates 2 completed tasks — one with slug='alpha',
    one with slug='beta'. Both assigned to test@aiui.local."""
    r = client.get("/api/tasks?status=done&slug=alpha", headers=HDR)
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["built_app_slug"] == "alpha"


def test_list_tasks_no_slug_returns_all(seed_two_slugs):
    r = client.get("/api/tasks?status=done", headers=HDR)
    assert r.status_code == 200
    assert len(r.json()) >= 2


def test_list_tasks_unknown_slug_returns_empty(seed_two_slugs):
    r = client.get("/api/tasks?status=done&slug=nonexistent", headers=HDR)
    assert r.status_code == 200
    assert r.json() == []
```

**Step 2: Run tests, confirm RED**

```bash
cd mcp-servers/tasks && python -m pytest tests/test_slug_filter.py -v
```

Expected: `test_list_tasks_filters_by_slug` fails because all 2 tasks return (filter not applied).

**Step 3: Add filter**

Modify `mcp-servers/tasks/routes_tasks.py` `list_tasks` (currently line 37):

```python
@router.get("", response_model=list[TaskOut])
async def list_tasks(
    status: str = "pending",
    slug: str | None = None,                         # NEW parameter
    limit: int = 50,
    user: AdminUser = Depends(current_admin),
):
    if status not in STATUS_BY_TAB:
        raise HTTPException(status_code=400, detail="Invalid status filter")

    async with session() as s:
        q = (
            select(TaskItem)
            .where(
                TaskItem.assignee_email.in_([user.email, TEAM_EMAIL]),
                TaskItem.status.in_(STATUS_BY_TAB[status]),
            )
            .order_by(TaskItem.created_at.desc())
            .limit(limit)
        )
        if slug:                                      # NEW: apply slug filter
            q = q.where(TaskItem.built_app_slug == slug)
        rows = (await s.execute(q)).scalars().all()
    return rows
```

**Step 4: Run tests, confirm GREEN**

```bash
cd mcp-servers/tasks && python -m pytest tests/test_slug_filter.py -v
```

Expected: `3 passed`.

**Step 5: Commit**

```bash
git add mcp-servers/tasks/routes_tasks.py mcp-servers/tasks/tests/test_slug_filter.py
git commit -m "feat(tasks): add optional ?slug= filter to GET /api/tasks"
```

---

### Task 4: Preview page — layout restructure (add 3rd column)

**Files:**
- Modify: `mcp-servers/tasks/static/preview.html` (CSS + DOM)

**Step 1: Update CSS for 3-column flex layout**

In `<style>` block around line 85, replace the `.main` rule:

```css
/* ── Main layout: file tree | content | enhance chat ── */
.main {
  display: flex;
  flex: 1;
  overflow: hidden;
}

/* ── Enhance chat sidebar (right) ── */
.sidebar-enhance {
  width: 340px;
  min-width: 280px;
  max-width: 420px;
  border-left: 1px solid #2a2a2a;
  background: #0f0f0f;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  overflow: hidden;
  transition: width 0.2s;
}
.sidebar-enhance.collapsed {
  width: 40px;
  min-width: 40px;
}
.sidebar-enhance.collapsed .enhance-log,
.sidebar-enhance.collapsed .enhance-input {
  display: none;
}
.enhance-header {
  padding: 10px 14px;
  font-size: 11px;
  font-weight: 700;
  color: #888;
  text-transform: uppercase;
  border-bottom: 1px solid #2a2a2a;
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: #0a0a0a;
}
.enhance-header button {
  background: transparent;
  border: 0;
  color: #888;
  font-size: 14px;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 4px;
}
.enhance-header button:hover {
  background: #1a1a1a;
  color: #fff;
}
.enhance-log {
  flex: 1;
  overflow-y: auto;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.enhance-bubble {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12.5px;
}
.enhance-bubble .who {
  font-size: 10.5px;
  color: #888;
  font-weight: 600;
}
.enhance-bubble.user .body {
  background: #1a1a1a;
  border: 1px solid #2a2a2a;
  border-radius: 8px;
  padding: 8px 10px;
  color: #e5e5e5;
  white-space: pre-wrap;
}
.enhance-bubble.ai .body {
  background: #0a0a0a;
  border: 1px solid #2a2a2a;
  border-left: 3px solid #3b82f6;
  border-radius: 8px;
  padding: 8px 10px;
  color: #d1d5db;
}
.enhance-bubble.ai.done .body {
  border-left-color: #22c55e;
}
.enhance-bubble.ai.failed .body {
  border-left-color: #ef4444;
  color: #fca5a5;
}
.enhance-bubble .phase {
  font-weight: 600;
  color: #fcd34d;
}
.enhance-bubble.done .phase { color: #86efac; }
.enhance-bubble.failed .phase { color: #fca5a5; }
.enhance-bubble .detail {
  margin-top: 4px;
  color: #888;
  font-size: 11.5px;
  white-space: pre-wrap;
}
.enhance-bubble .commit {
  display: inline-block;
  margin-top: 4px;
  padding: 1px 6px;
  background: #1e3a8a;
  color: #dbeafe;
  border-radius: 3px;
  font-family: Consolas, Menlo, monospace;
  font-size: 10.5px;
}
.enhance-input {
  border-top: 1px solid #2a2a2a;
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  background: #0a0a0a;
}
.enhance-input textarea {
  background: #000;
  color: #fff;
  border: 1px solid #2a2a2a;
  border-radius: 6px;
  padding: 8px 10px;
  font-size: 12.5px;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  resize: vertical;
  min-height: 64px;
  outline: none;
}
.enhance-input textarea:focus {
  border-color: #3b82f6;
}
.enhance-input button {
  align-self: flex-end;
  background: #3b82f6;
  color: #fff;
  border: 0;
  padding: 7px 16px;
  border-radius: 6px;
  cursor: pointer;
  font-weight: 600;
  font-size: 12.5px;
}
.enhance-input button:disabled {
  background: #374151;
  cursor: not-allowed;
  opacity: 0.5;
}
.enhance-input .warn {
  color: #f59e0b;
  font-size: 10.5px;
}

/* Collapse sidebar below 1100px */
@media (max-width: 1100px) {
  .sidebar-enhance { display: none; }
}
```

**Step 2: Add DOM for the sidebar**

Modify the `.main` block (around line 391) to append the sidebar AFTER the content div:

```html
<!-- Main layout -->
<div class="main">
  <!-- (existing) file tree sidebar -->
  <div class="sidebar"> ... </div>

  <!-- (existing) content pane -->
  <div class="content"> ... </div>

  <!-- NEW: enhance chat sidebar -->
  <aside id="enhance-sidebar" class="sidebar-enhance">
    <div class="enhance-header">
      <span>✨ Enhance</span>
      <button id="enhance-collapse" title="Collapse">🗕</button>
    </div>
    <div class="enhance-log" id="enhance-log">
      <div style="color:#555;font-size:11.5px;text-align:center;padding:20px;">
        Type a change below to get started.
      </div>
    </div>
    <div class="enhance-input">
      <textarea id="enhance-prompt"
                placeholder="Type what you want to change..."
                maxlength="2000"
                rows="3"></textarea>
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <span class="warn" id="enhance-warn"></span>
        <button id="enhance-send">Send</button>
      </div>
    </div>
  </aside>
</div>
```

**Step 3: Manual check in browser**

Open `/tasks/static/preview.html?task=<any-task-id>` in the browser. Expected:
- Old layout still works (file tree + content)
- New sidebar appears on the right showing "✨ Enhance" header and a textarea + Send button
- Viewport < 1100px hides the sidebar (collapse responsive rule)

**Step 4: Commit**

```bash
git add mcp-servers/tasks/static/preview.html
git commit -m "feat(preview): add enhance-chat sidebar DOM + CSS (3-column layout)"
```

---

### Task 5: Preview page — chat logic (send, poll, render bubbles)

**Files:**
- Modify: `mcp-servers/tasks/static/preview.html` (JS block)

**Step 1: Add the chat module at the bottom of the existing IIFE**

Inside the `(function () { ... })();` IIFE in `preview.html`, before the closing `})();`, add:

```javascript
// ═══════════════════════════════════════════════════════════════════════
// ENHANCE CHAT SIDEBAR
// ═══════════════════════════════════════════════════════════════════════

const $log = document.getElementById("enhance-log");
const $prompt = document.getElementById("enhance-prompt");
const $send = document.getElementById("enhance-send");
const $warn = document.getElementById("enhance-warn");
const $collapse = document.getElementById("enhance-collapse");
const $sidebar = document.getElementById("enhance-sidebar");

const ENHANCE_STATE_KEY = "aiui-enhance-collapsed";
const activeBubbles = new Map();  // taskId → { bubbleEl, pollTimer }

// Collapse persistence
if (localStorage.getItem(ENHANCE_STATE_KEY) === "true") {
  $sidebar.classList.add("collapsed");
}
$collapse.addEventListener("click", () => {
  $sidebar.classList.toggle("collapsed");
  localStorage.setItem(ENHANCE_STATE_KEY, $sidebar.classList.contains("collapsed"));
});

function renderBubble(kind, content, opts = {}) {
  const el = document.createElement("div");
  el.className = `enhance-bubble ${kind}`;
  if (opts.taskId) el.dataset.taskId = opts.taskId;
  el.innerHTML = `
    <span class="who">${kind === "user" ? "💬 You" : "🤖 AI"}</span>
    <div class="body">
      ${kind === "ai" ? '<span class="phase">⏳ Queued</span>' : ""}
      <div class="content"></div>
      <div class="detail"></div>
    </div>
  `;
  el.querySelector(".content").textContent = content || "";
  $log.appendChild(el);
  $log.scrollTop = $log.scrollHeight;
  return el;
}

function extractCommitSha(resultText) {
  if (!resultText) return null;
  const m = resultText.match(/commit\s+([a-f0-9]{7,40})/i);
  return m ? m[1].substring(0, 7) : null;
}

function derivePhase(task, latestExec) {
  const log = (latestExec && latestExec.log) || "";
  const attempt = task.attempt_count;
  const max = task.max_attempts;
  if (task.status === "completed") return { label: "✓ Done", terminal: true };
  if (task.status === "failed")    return { label: "✗ Failed", terminal: true };
  if (task.status === "awaiting_input") return { label: "❓ Needs input", terminal: false };
  if (task.status === "running") {
    if (attempt > 0) return { label: `🔄 Retrying (${attempt}/${max})…`, terminal: false };
    if (log.includes("--- VERIFY STEP ---")) return { label: "✅ Verifying…", terminal: false };
    return { label: "⚡ Building…", terminal: false };
  }
  return { label: "⏳ Queued", terminal: false };
}

function updateAiBubble(bubbleEl, task, latestExec) {
  const phase = derivePhase(task, latestExec);
  const phaseEl = bubbleEl.querySelector(".phase");
  const detailEl = bubbleEl.querySelector(".detail");
  phaseEl.textContent = phase.label;
  if (task.status === "completed") {
    bubbleEl.classList.add("done");
    const sha = extractCommitSha(task.result);
    const summary = (task.result || "").replace(/\s*\(commit [a-f0-9]+\)\s*$/i, "").trim();
    detailEl.innerHTML = escapeHtml(summary) +
      (sha ? ` <span class="commit">commit ${sha}</span>` : "");
    refreshPreviewIframeIfVisible();
  } else if (task.status === "failed") {
    bubbleEl.classList.add("failed");
    detailEl.textContent = task.result || "Enhancement failed";
  }
  return phase;
}

function refreshPreviewIframeIfVisible() {
  if (activeTab !== "preview") return;
  const iframe = document.querySelector('#panel-preview iframe');
  if (!iframe) return;
  const url = new URL(iframe.src, window.location.origin);
  url.searchParams.set("t", Date.now());
  iframe.src = url.toString();
}

async function pollEnhance(taskId, bubbleEl) {
  try {
    const [task, execs] = await Promise.all([
      apiFetch("GET", `/${taskId}`),
      apiFetch("GET", `/${taskId}/executions`),
    ]);
    const latestExec = execs && execs.length ? execs[0] : null;
    const phase = updateAiBubble(bubbleEl, task, latestExec);
    if (phase.terminal) {
      stopPolling(taskId);
      setSendDisabled(false);
    }
  } catch (e) {
    console.warn("[enhance] poll error", e);
  }
}

function startPolling(taskId, bubbleEl) {
  if (activeBubbles.has(taskId)) return;
  const timer = setInterval(() => pollEnhance(taskId, bubbleEl), 2000);
  activeBubbles.set(taskId, { bubbleEl, pollTimer: timer });
  pollEnhance(taskId, bubbleEl);  // fire immediately
}

function stopPolling(taskId) {
  const entry = activeBubbles.get(taskId);
  if (!entry) return;
  clearInterval(entry.pollTimer);
  activeBubbles.delete(taskId);
}

function setSendDisabled(disabled) {
  $send.disabled = disabled;
  $prompt.disabled = disabled;
  $warn.textContent = disabled ? "Enhancement in progress…" : "";
}

async function submitEnhance() {
  const text = $prompt.value.trim();
  if (!text) return;
  if (!sourceTaskId) {
    $warn.textContent = "No source task — reload the page";
    return;
  }
  setSendDisabled(true);
  const userBubble = renderBubble("user", text);
  const aiBubble = renderBubble("ai", "", { taskId: "pending" });
  $prompt.value = "";

  try {
    const resp = await apiFetch("POST", "/enhance", {
      source_task_id: sourceTaskId,
      prompt: text,
    });
    aiBubble.dataset.taskId = resp.id;
    startPolling(resp.id, aiBubble);
  } catch (e) {
    aiBubble.classList.add("failed");
    aiBubble.querySelector(".phase").textContent = "✗ Failed";
    aiBubble.querySelector(".detail").textContent = e.message || String(e);
    setSendDisabled(false);
  }
}

$send.addEventListener("click", submitEnhance);
$prompt.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    submitEnhance();
  }
});

// Load enhancement history on page mount (after slug is known)
async function loadEnhanceHistory() {
  if (!slug) return;
  try {
    const history = await apiFetch("GET", `?status=done&slug=${encodeURIComponent(slug)}&limit=20`);
    // Sort chronological (oldest first so newest at bottom)
    const sorted = (history || []).sort((a, b) =>
      new Date(a.created_at) - new Date(b.created_at)
    );
    // Remove placeholder
    $log.innerHTML = "";
    for (const t of sorted) {
      // Skip the source task itself
      if (t.id === sourceTaskId) continue;
      const userMsg = (t.description || "").replace(/^Enhance apps\/[^\/]+\/:\s*/i, "");
      renderBubble("user", userMsg, { taskId: t.id });
      const aiBubble = renderBubble("ai", "", { taskId: t.id });
      updateAiBubble(aiBubble, t, null);
    }
    if ($log.children.length === 0) {
      $log.innerHTML = '<div style="color:#555;font-size:11.5px;text-align:center;padding:20px;">Type a change below to get started.</div>';
    }
  } catch (e) {
    console.warn("[enhance] history load failed", e);
  }
}
```

**Step 2: Hook `sourceTaskId` into the existing init**

Find where `taskId` is loaded from URL in the existing code (`const taskId = params.get("task")`). Add near the top of the IIFE:

```javascript
const sourceTaskId = taskId;   // alias used by enhance chat — clearer intent
```

And in `loadFileTree()` after `slug = data.slug || "";` has been set, call:

```javascript
loadEnhanceHistory();
```

**Step 3: Manual test in browser**

1. Hard refresh preview page for `meeting-notes` task
2. Type "add attendees field" → hit Enter
3. Observe: user bubble appears instantly, AI bubble shows "⏳ Queued" then "⚡ Building…"
4. Wait ~60s, phase becomes "✓ Done — commit <sha>"
5. Iframe on Preview tab auto-refreshes
6. Reload page → both bubbles appear in history, collapsed at top

**Step 4: Commit**

```bash
git add mcp-servers/tasks/static/preview.html
git commit -m "feat(preview): enhance-chat JS — send, poll, phase labels, iframe auto-refresh"
```

---

### Task 6: Deploy to Hetzner + verify via Playwright

**Step 1: Deploy**

```bash
scp mcp-servers/tasks/schemas.py              root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/
scp mcp-servers/tasks/claude_executor.py      root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/
scp mcp-servers/tasks/routes_tasks.py         root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/
scp mcp-servers/tasks/static/preview.html     root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/static/

ssh root@46.224.193.25 "docker cp /root/proxy-server/mcp-servers/tasks/schemas.py tasks:/app/schemas.py \
 && docker cp /root/proxy-server/mcp-servers/tasks/claude_executor.py tasks:/app/claude_executor.py \
 && docker cp /root/proxy-server/mcp-servers/tasks/routes_tasks.py tasks:/app/routes_tasks.py \
 && docker cp /root/proxy-server/mcp-servers/tasks/static/preview.html tasks:/app/static/preview.html \
 && docker restart tasks"
```

**Step 2: Wait for health check**

```bash
ssh root@46.224.193.25 "until docker exec tasks curl -sf http://localhost:8210/health > /dev/null 2>&1; do sleep 2; done && echo READY"
```

**Step 3: API smoke test**

```bash
ssh root@46.224.193.25 "docker exec tasks curl -s -X POST http://localhost:8210/api/tasks/enhance \
  -H 'X-User-Email: alamajacintg04@gmail.com' -H 'X-User-Admin: true' \
  -H 'Content-Type: application/json' \
  -d '{\"source_task_id\":\"16737bca-f408-455e-ba3a-165d44b0a445\",\"prompt\":\"add a simple footer saying Made by AI\"}'"
```

Expected: HTTP 202 with new task JSON (new UUID, action_type=BUILD, built_app_slug=meeting-notes, plan_status=approved).

**Step 4: Browser E2E via Playwright**

Use the same test harness as `playwright-final-proof.js` but:
1. Log in
2. Navigate to `preview.html?task=16737bca-...`
3. Wait for sidebar to load
4. Type into `#enhance-prompt` → click `#enhance-send`
5. Wait for `#enhance-log .enhance-bubble.ai.done` (max 120s)
6. Screenshot final state

Check: screenshot shows ✓ Done bubble, commit SHA present, preview iframe on Preview tab has refreshed.

**Step 5: Commit the Playwright test script**

```bash
# Save to repo tests/ folder for future regression runs
mkdir -p docs/plans/screenshots
cp /tmp/aiui-enhance-done.png docs/plans/screenshots/2026-04-21-enhance-done.png
git add docs/plans/screenshots/
git commit -m "test(preview): enhance-chat E2E screenshot evidence"
```

---

### Task 7: Memory update + roadmap commit

**Step 1: Update project memory**

Update `C:\Users\alama\.claude\projects\C--Users-alama-Desktop-Lukas-Work-IO\memory\project_decision_engine_roadmap.md` to note:
- Phase C enhance-chat: implemented + deployed
- New endpoint `POST /api/tasks/enhance`
- New prompt template `ENHANCE_PROMPT_TEMPLATE`

No git commit needed for memory files (they live in the user's home dir).

**Step 2: Done — nothing else to commit unless followups surface.**

---

## Skills referenced

- `@superpowers:executing-plans` — to execute this plan task-by-task
- `@superpowers:test-driven-development` — for Tasks 1, 2, 3 (RED → GREEN)
- `@superpowers:verification-before-completion` — before claiming any task done
- `@superpowers:systematic-debugging` — if deploy or E2E test fails
