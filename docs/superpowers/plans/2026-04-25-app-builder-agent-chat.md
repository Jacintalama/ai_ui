# App Builder Agent Chat Polish — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the in-preview Chat (Haiku, no edits) and Build (full agent, edits + commits) sidebar feel like a polished assistant: persistent history, retry on failure, clearer streaming, and `@filename` references that scope a chat answer to specific files.

**Architecture:**
- Chat history persisted server-side per (slug, user_email) so it survives reloads.
- Retry button on each failed AI bubble re-fires the request with the same prompt.
- `@filename` autocomplete in the prompt textarea, drawing from the existing `/api/tasks/{id}/files` data.

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy / vanilla JS / EventSource for streaming.

---

## File Structure

**Will create:**
- `mcp-servers/tasks/migrations/008_chat_history.sql` — `tasks.chat_history` table
- `mcp-servers/tasks/routes_chat_history.py` — `GET / POST /api/projects/{slug}/chat`
- `mcp-servers/tasks/tests/test_chat_history.py` — coverage

**Will modify:**
- `mcp-servers/tasks/models.py` — `ChatMessage` model
- `mcp-servers/tasks/main.py` — register router
- `mcp-servers/tasks/routes_tasks.py` — `/chat` endpoint persists messages
- `mcp-servers/tasks/static/preview.html` — load history on open, retry button, `@file` autocomplete

---

### Task 1: Migration + model for chat history

**Files:**
- Create: `mcp-servers/tasks/migrations/008_chat_history.sql`
- Modify: `mcp-servers/tasks/models.py`

- [ ] **Step 1: Migration**

```sql
-- Per-(slug, user) chat history. We keep at most ~100 messages per pair
-- (UI trims when loading; nothing on the DB side enforces this).

CREATE TABLE IF NOT EXISTS tasks.chat_history (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug         TEXT NOT NULL,
    user_email   TEXT NOT NULL,
    role         TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content      TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS chat_history_lookup_idx
    ON tasks.chat_history (slug, user_email, created_at DESC);
```

- [ ] **Step 2: Model**

Append to `models.py`:

```python
class ChatMessage(Base):
    __tablename__ = "chat_history"
    __table_args__ = {"schema": "tasks"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug = Column(Text, nullable=False)
    user_email = Column(Text, nullable=False)
    role = Column(Text, nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
```

- [ ] **Step 3: Apply on server**

```bash
scp -i ~/.ssh/aiui_safe mcp-servers/tasks/migrations/008_chat_history.sql mcp-servers/tasks/models.py root@46.224.193.25:/tmp/
ssh -i ~/.ssh/aiui_safe root@46.224.193.25 "cp /tmp/008_chat_history.sql /root/proxy-server/mcp-servers/tasks/migrations/ && cp /tmp/models.py /root/proxy-server/mcp-servers/tasks/ && docker cp /tmp/008_chat_history.sql tasks:/app/migrations/ && docker cp /tmp/models.py tasks:/app/ && docker restart tasks && sleep 4 && docker exec postgres psql \$(docker exec tasks printenv DATABASE_URL | sed 's|postgresql+asyncpg://|postgresql://|') -c '\\d tasks.chat_history'"
```

Expected: prints the table.

- [ ] **Step 4: Commit**

```bash
git add mcp-servers/tasks/migrations/008_chat_history.sql mcp-servers/tasks/models.py
git commit -m "feat(chat): persist chat history per (slug, user)"
```

---

### Task 2: Chat history endpoints

**Files:**
- Create: `mcp-servers/tasks/routes_chat_history.py`
- Create: `mcp-servers/tasks/tests/test_chat_history.py`
- Modify: `mcp-servers/tasks/main.py`

- [ ] **Step 1: Test first**

```python
"""Tests for chat history endpoints."""
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from main import app
from models import ChatMessage, ProjectMember, TaskItem

OWNER_HDR = {"X-User-Email": "ralph@aiui.com", "X-User-Admin": "true"}


@pytest.fixture
def transport():
    return ASGITransport(app=app)


def _setup_member(db_session, slug="alpha", email="ralph@aiui.com", role="owner"):
    db_session.add(TaskItem(
        meeting_id=uuid.uuid4(), action_type="BUILD",
        assignee_name="Ralph", assignee_email=email,
        description="x", priority="IMPORTANT", status="completed",
        built_app_slug=slug,
    ))
    db_session.add(ProjectMember(slug=slug, user_email=email, role=role,
                                  added_by=email))


async def test_get_chat_history_empty(db_session, transport):
    _setup_member(db_session)
    await db_session.commit()
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/projects/alpha/chat", headers=OWNER_HDR)
    assert r.status_code == 200
    assert r.json() == []


async def test_post_then_get_chat_history(db_session, transport):
    _setup_member(db_session)
    await db_session.commit()
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/projects/alpha/chat", headers=OWNER_HDR,
                         json={"role": "user", "content": "hello"})
        assert r.status_code == 201
        r = await c.post("/api/projects/alpha/chat", headers=OWNER_HDR,
                         json={"role": "assistant", "content": "hi back"})
        assert r.status_code == 201

        r = await c.get("/api/projects/alpha/chat", headers=OWNER_HDR)
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) == 2
        assert rows[0]["role"] == "user" and rows[0]["content"] == "hello"
        assert rows[1]["role"] == "assistant"


async def test_chat_history_per_user_isolated(db_session, transport):
    _setup_member(db_session, email="ralph@aiui.com")
    _setup_member(db_session, email="bob@aiui.com", role="editor")
    await db_session.commit()
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/projects/alpha/chat", headers=OWNER_HDR,
                     json={"role": "user", "content": "ralph msg"})
        bob_hdr = {"X-User-Email": "bob@aiui.com", "X-User-Admin": "true"}
        await c.post("/api/projects/alpha/chat", headers=bob_hdr,
                     json={"role": "user", "content": "bob msg"})

        r = await c.get("/api/projects/alpha/chat", headers=OWNER_HDR)
        assert len(r.json()) == 1
        assert r.json()[0]["content"] == "ralph msg"

        r = await c.get("/api/projects/alpha/chat", headers=bob_hdr)
        assert len(r.json()) == 1
        assert r.json()[0]["content"] == "bob msg"
```

- [ ] **Step 2: Run, expect FAIL**

```bash
ssh -i ~/.ssh/aiui_safe root@46.224.193.25 "docker exec tasks pytest tests/test_chat_history.py -v"
```

Expected: all 3 fail (404 Not Found).

- [ ] **Step 3: Implement the router**

```python
# mcp-servers/tasks/routes_chat_history.py
"""Per-user chat history for a project (the in-preview Chat tab)."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from auth import AdminUser, current_admin
from db import session
from models import ChatMessage
from routes_projects import _require_role, _validate_slug

router = APIRouter(prefix="/api/projects")

MAX_MESSAGES = 200


class ChatMessageIn(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str = Field(min_length=1, max_length=20_000)


class ChatMessageOut(BaseModel):
    id: str
    role: str
    content: str
    created_at: str


@router.get("/{slug}/chat", response_model=list[ChatMessageOut])
async def list_chat(
    slug: str,
    limit: int = 100,
    user: AdminUser = Depends(current_admin),
):
    _validate_slug(slug)
    limit = max(1, min(limit, MAX_MESSAGES))
    async with session() as s:
        await _require_role(s, slug, user.email, "viewer")
        rows = (await s.execute(
            select(ChatMessage).where(
                ChatMessage.slug == slug,
                ChatMessage.user_email == user.email,
            )
            .order_by(ChatMessage.created_at.asc())
            .limit(limit)
        )).scalars().all()
    return [
        ChatMessageOut(
            id=str(m.id), role=m.role, content=m.content,
            created_at=m.created_at.isoformat() if m.created_at else "",
        )
        for m in rows
    ]


@router.post("/{slug}/chat", response_model=ChatMessageOut, status_code=201)
async def append_chat(
    slug: str,
    body: ChatMessageIn,
    user: AdminUser = Depends(current_admin),
):
    _validate_slug(slug)
    async with session() as s:
        await _require_role(s, slug, user.email, "viewer")
        msg = ChatMessage(
            slug=slug, user_email=user.email,
            role=body.role, content=body.content,
        )
        s.add(msg)
        await s.commit()
        await s.refresh(msg)
    return ChatMessageOut(
        id=str(msg.id), role=msg.role, content=msg.content,
        created_at=msg.created_at.isoformat() if msg.created_at else "",
    )


@router.delete("/{slug}/chat", status_code=204)
async def clear_chat(slug: str, user: AdminUser = Depends(current_admin)):
    """Clear my chat history for this project."""
    _validate_slug(slug)
    from sqlalchemy import delete as _del
    async with session() as s:
        await _require_role(s, slug, user.email, "viewer")
        await s.execute(_del(ChatMessage).where(
            ChatMessage.slug == slug,
            ChatMessage.user_email == user.email,
        ))
        await s.commit()
    return None
```

- [ ] **Step 4: Register router**

In `main.py`:

```python
from routes_chat_history import router as chat_history_router
# ...
app.include_router(chat_history_router)
```

- [ ] **Step 5: Run tests, expect 3 PASS**

```bash
scp -i ~/.ssh/aiui_safe mcp-servers/tasks/routes_chat_history.py mcp-servers/tasks/main.py mcp-servers/tasks/tests/test_chat_history.py root@46.224.193.25:/tmp/
ssh -i ~/.ssh/aiui_safe root@46.224.193.25 "cp /tmp/routes_chat_history.py /tmp/main.py /root/proxy-server/mcp-servers/tasks/ && cp /tmp/test_chat_history.py /root/proxy-server/mcp-servers/tasks/tests/ && docker cp /tmp/routes_chat_history.py tasks:/app/ && docker cp /tmp/main.py tasks:/app/ && docker cp /tmp/test_chat_history.py tasks:/app/tests/ && docker restart tasks && sleep 4 && docker exec tasks pytest tests/test_chat_history.py -v"
```

- [ ] **Step 6: Commit**

```bash
git add mcp-servers/tasks/routes_chat_history.py mcp-servers/tasks/main.py mcp-servers/tasks/tests/test_chat_history.py
git commit -m "feat(chat): persistent chat history endpoints"
```

---

### Task 3: Hook the existing /chat endpoint to also persist messages

**Files:**
- Modify: `mcp-servers/tasks/routes_tasks.py` — `chat` function (around line 483)

The current `/chat` endpoint takes a prompt + source_task_id and returns an answer. We want it to also save the user prompt + assistant reply to `chat_history` so reloads keep context.

- [ ] **Step 1: Modify the function to persist on the way through**

Find the existing `chat()` function. After receiving the Anthropic response and before returning it, add:

```python
    # Persist the round-trip. Failure here is non-fatal — chat still works.
    try:
        from models import ChatMessage as _CM
        from datetime import datetime as _dt
        async with session() as s2:
            s2.add(_CM(slug=source.built_app_slug, user_email=user.email,
                       role="user", content=body.prompt[:20_000]))
            s2.add(_CM(slug=source.built_app_slug, user_email=user.email,
                       role="assistant", content=reply_text[:20_000],
                       created_at=_dt.utcnow()))
            await s2.commit()
    except Exception:
        pass  # log but don't fail the request
```

- [ ] **Step 2: Smoke test live**

```bash
ssh -i ~/.ssh/aiui_safe root@46.224.193.25 "docker cp /root/proxy-server/mcp-servers/tasks/routes_tasks.py tasks:/app/routes_tasks.py && docker restart tasks && sleep 4"

# Send a chat message via the existing endpoint, then read history.
curl -s -X POST 'http://46.224.193.25:8210/api/tasks/chat' \
     -H 'X-User-Email: ralph@aiui.com' -H 'X-User-Admin: true' \
     -H 'Content-Type: application/json' \
     -d '{"source_task_id":"<existing task id>","prompt":"what does this app do?"}'
curl -s 'http://46.224.193.25:8210/api/projects/<slug>/chat' \
     -H 'X-User-Email: ralph@aiui.com' -H 'X-User-Admin: true'
```

Expected: the GET shows the user prompt + assistant reply.

- [ ] **Step 3: Commit**

```bash
git add mcp-servers/tasks/routes_tasks.py
git commit -m "feat(chat): persist /chat round-trips to chat_history"
```

---

### Task 4: Frontend — load chat history on preview open + Clear button

**Files:**
- Modify: `mcp-servers/tasks/static/preview.html` (the Enhance sidebar JS)

- [ ] **Step 1: Add a small fetch+render at sidebar init**

Find `loadEnhanceHistory` (around line 2790) and add a sibling function that loads chat-mode history. Append after the existing function:

```javascript
  async function loadChatHistory() {
    if (!slug) return;
    try {
      const token = localStorage.getItem("token");
      const r = await fetch(`/api/projects/${encodeURIComponent(slug)}/chat?limit=50`, {
        headers: token ? { Authorization: "Bearer " + token } : {},
        credentials: "include",
      });
      if (!r.ok) return;
      const rows = await r.json();
      if (!rows.length) return;
      // Remove the empty-state placeholder.
      const empty = document.getElementById("enhance-empty");
      if (empty) empty.remove();
      for (const m of rows) {
        if (m.role === "user") {
          renderChatBubble("user", m.content);
        } else if (m.role === "assistant") {
          renderChatBubble("ai", m.content);
        }
      }
      $log.scrollTop = $log.scrollHeight;
    } catch (_) {}
  }
```

- [ ] **Step 2: Call it from `loadFileTree` (the same place that fires `loadEnhanceHistory`)**

In `loadFileTree`, the slug is set right before `loadEnhanceHistory()`. Add `loadChatHistory();` next to it.

- [ ] **Step 3: Add a "Clear chat" button to the enhance sidebar**

Find the enhance-header markup (search for `class="title"><span class="spark">✨</span>Enhance`). Add a button right next to the collapse button:

```html
        <button id="enhance-clear" title="Clear chat history" type="button" style="background:transparent;border:0;color:var(--muted);cursor:pointer;padding:0 4px;font-size:12px;">🗑</button>
```

Wire it:

```javascript
  document.getElementById("enhance-clear")?.addEventListener("click", async () => {
    if (!slug) return;
    if (!confirm("Clear your chat history for this project?")) return;
    try {
      const token = localStorage.getItem("token");
      await fetch(`/api/projects/${encodeURIComponent(slug)}/chat`, {
        method: "DELETE",
        headers: token ? { Authorization: "Bearer " + token } : {},
        credentials: "include",
      });
      $log.innerHTML = '<div class="enhance-empty" id="enhance-empty"><div class="spark">✨</div><div class="hint">Chat history cleared.</div></div>';
    } catch (_) {}
  });
```

- [ ] **Step 4: Manual test**

1. Open preview, send a chat message
2. Reload page → message appears in history
3. Click 🗑 → confirms → chat clears

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/static/preview.html
git commit -m "feat(chat): load + clear persistent chat history in preview sidebar"
```

---

### Task 5: Retry button on failed chat/build messages

**Files:**
- Modify: `mcp-servers/tasks/static/preview.html`

When a chat fails (e.g. network error) or a build fails (already shows in bubble), show a small "↻ Retry" button.

- [ ] **Step 1: CSS for the retry button**

Add to existing CSS:

```css
.chat-retry-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 9px;
  margin-top: 6px;
  font-size: 11px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-2);
  cursor: pointer;
}
.chat-retry-btn:hover { background: var(--surface-3); color: var(--text); border-color: var(--accent); }
```

- [ ] **Step 2: Wrap submitChat to remember last prompt + add retry**

Find `submitChat` (around line 2575). After the catch block, modify to attach a retry button to the failing AI bubble:

```javascript
    } catch (e) {
      aiBubble.classList.remove("thinking");
      aiBubble.querySelector(".markdown").innerHTML =
        renderMarkdown("Chat failed: " + (e.message || String(e)));
      // Add retry button.
      const retry = document.createElement("button");
      retry.className = "chat-retry-btn";
      retry.type = "button";
      retry.innerHTML = "↻ Retry";
      retry.addEventListener("click", () => {
        retry.remove();
        aiBubble.remove();
        submitChat(text);  // closure captures the original prompt
      });
      aiBubble.appendChild(retry);
    }
```

Same idea for `submitEnhance` — but builds restart via the existing 409-handling flow already, so for v1 we only add retry to chat.

- [ ] **Step 3: Manual test**

Block network temporarily (DevTools Network tab → Offline), send a chat, observe error + Retry button. Re-enable network, click Retry, message should retry successfully.

- [ ] **Step 4: Commit**

```bash
git add mcp-servers/tasks/static/preview.html
git commit -m "feat(chat): retry button on failed chat messages"
```

---

### Task 6: `@filename` autocomplete in the prompt textarea

**Files:**
- Modify: `mcp-servers/tasks/static/preview.html`

Typing `@` in the textarea opens a small dropdown of files. Selecting one inserts the filename. Lets the user say "explain @server.py" or "fix the bug in @public/index.html".

- [ ] **Step 1: CSS for the popup**

```css
.at-popup {
  position: absolute;
  background: var(--surface);
  border: 1px solid var(--border-2);
  border-radius: var(--radius);
  box-shadow: var(--shadow-md);
  padding: 4px;
  max-height: 220px;
  overflow-y: auto;
  z-index: 50;
  min-width: 240px;
  font-family: var(--font-mono);
  font-size: 11px;
}
.at-popup .at-item {
  padding: 5px 8px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.at-popup .at-item:hover, .at-popup .at-item.active {
  background: var(--accent-soft); color: var(--accent);
}
```

- [ ] **Step 2: JS — detect `@` then show suggestions**

Insert near the bottom of the IIFE, after `$prompt.addEventListener("keydown", ...)`:

```javascript
  // ── @filename autocomplete ──
  const $atPopup = (() => {
    const el = document.createElement("div");
    el.className = "at-popup";
    el.hidden = true;
    document.body.appendChild(el);
    return el;
  })();
  let _atActive = -1;
  let _atItems = [];

  function _atHide() { $atPopup.hidden = true; _atActive = -1; _atItems = []; }

  function _atUpdate() {
    const v = $prompt.value;
    const caret = $prompt.selectionStart;
    const before = v.slice(0, caret);
    const m = before.match(/@([^\s@]*)$/);
    if (!m) { _atHide(); return; }
    const q = m[1].toLowerCase();
    const matches = (files || [])
      .map((f) => f.path)
      .filter((p) => p.toLowerCase().includes(q))
      .slice(0, 8);
    if (!matches.length) { _atHide(); return; }
    _atItems = matches;
    _atActive = 0;
    $atPopup.innerHTML = matches.map((p, i) =>
      `<div class="at-item${i === 0 ? " active" : ""}" data-i="${i}">${escapeHtml(p)}</div>`
    ).join("");
    // Position the popup near the textarea.
    const r = $prompt.getBoundingClientRect();
    $atPopup.style.left = r.left + "px";
    $atPopup.style.top = (r.top - $atPopup.offsetHeight - 4) + "px";
    $atPopup.hidden = false;
  }

  function _atInsert(idx) {
    const path = _atItems[idx];
    if (!path) return;
    const v = $prompt.value;
    const caret = $prompt.selectionStart;
    const before = v.slice(0, caret).replace(/@([^\s@]*)$/, "@" + path + " ");
    const after = v.slice(caret);
    $prompt.value = before + after;
    $prompt.selectionStart = $prompt.selectionEnd = before.length;
    _atHide();
    $prompt.focus();
  }

  $prompt.addEventListener("input", _atUpdate);
  $prompt.addEventListener("keydown", (e) => {
    if ($atPopup.hidden || !_atItems.length) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      _atActive = (_atActive + 1) % _atItems.length;
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      _atActive = (_atActive - 1 + _atItems.length) % _atItems.length;
    } else if (e.key === "Enter" || e.key === "Tab") {
      e.preventDefault();
      _atInsert(_atActive);
      return;
    } else if (e.key === "Escape") {
      _atHide();
      return;
    } else {
      return;
    }
    // Update which row has .active.
    $atPopup.querySelectorAll(".at-item").forEach((el, i) => {
      el.classList.toggle("active", i === _atActive);
    });
  });
  $atPopup.addEventListener("click", (e) => {
    const el = e.target.closest(".at-item");
    if (el) _atInsert(parseInt(el.dataset.i, 10));
  });
  document.addEventListener("click", (e) => {
    if (e.target !== $prompt && !$atPopup.contains(e.target)) _atHide();
  });
```

- [ ] **Step 3: Manual test**

1. In the chat textarea type `explain @ind` → popup shows `index.html` etc.
2. Arrow down to choose, Enter → text becomes `explain public/index.html `
3. Type Escape → popup closes

- [ ] **Step 4: Commit**

```bash
git add mcp-servers/tasks/static/preview.html
git commit -m "feat(chat): @filename autocomplete in prompt textarea"
```

---

### Task 7: Self-review

- [ ] **Step 1: Run all tests**

```bash
ssh -i ~/.ssh/aiui_safe root@46.224.193.25 "docker exec tasks pytest tests/ -q"
```

Expected: all green.

- [ ] **Step 2: End-to-end manual test**

1. Open project preview → send 3 chat messages → reload → all 3 still there
2. Send message while offline → see Retry → reconnect → click Retry → succeeds
3. Type `@` + a few letters → popup → arrow down → Enter → filename inserted
4. Click 🗑 in enhance header → confirm → chat resets to empty state

- [ ] **Step 3: Final commit**

```bash
git add -A && git commit -m "chore(plan-agent-chat): e2e pass" || true
```
