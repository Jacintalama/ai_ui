# Visual Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a webpage that opens from a Discord button on the "Build ready" card, lets the user chat with the same enhance pipeline, and shows a live preview of the regenerated app on the right.

**Architecture:** Extends the existing `tasks` service. Discord side gets one new link button. The page is a thin SPA (HTML + JS) backed by three new HTTP routes (page, chat, status). Builds run as detached `asyncio` tasks tracked in an in-process job registry; the browser polls status at ~1Hz. Tokens are HMAC-SHA256 signed `owner:ts:slug` with a 30-min TTL — a new helper that does NOT touch the existing 2-purpose `oauth_state.py` in webhook-handler / gmail / gdrive.

**Tech Stack:** Python 3 / FastAPI (tasks service), Python 3 (webhook-handler, no FastAPI for this), pytest, vanilla JS in the browser, no new packages.

**Spec:** `docs/superpowers/specs/2026-05-28-visual-editor-design.md`

---

## Open questions resolved (locked here)

| Question | Resolution |
|---|---|
| Token TTL | 30 min (1800s). Constant inside the new `visual_edit_token.py`, NOT a change to `oauth_state.py`. |
| `oauth_state.py` slug-binding | Don't touch it. Create a separate `visual_edit_token.py` with its own `sign_edit_token` / `verify_edit_token` that HMACs `owner:ts:slug`. Same `OAUTH_STATE_SECRET` env var, different signing payload, so the two token types can never be cross-substituted. |
| `enhance_with_history` history format | `list[dict[{"role": "user" \| "assistant", "content": str}, ...]]`. The existing `claude_executor._format_conversation_history(history)` at line 626 uses different role names (`"ai"` vs everything-else → "Admin answered"), so we add a NEW formatter `_format_enhance_history(history)` for this flow rather than mutating the existing helper. |
| Enhance prompt history block | The `ENHANCE_PROMPT_TEMPLATE` (claude_executor.py:493) has no history slot today. We add a new `{conversation_history_block}` placeholder near the top (above `USER REQUEST:`) and pass `conversation_history` through `build_enhance_prompt`. |
| Atomic write/swap | The existing enhance path (`_create_and_spawn_enhance` at `routes_aiuibuilder.py:307`) spawns a Claude subprocess that edits `apps/<slug>/` in place — there's no temp-dir/rename today. v1 inherits this. Failure mode is documented in the spec's error table (the partial-edit case relies on Claude's own git commit step at the end of the prompt). |
| Sync vs fire-and-forget | `_create_and_spawn_enhance` returns a `task_id` immediately and runs the build via `asyncio.create_task(_run_execution(...))`. For visual-edit we need to AWAIT completion so the job registry can transition `applying → done`. We refactor the existing function into two halves: `_setup_enhance_task()` (DB rows + prompt build, returns `task_id, exec_id, prompt_text`) and the spawn step. Visual-edit calls setup, then `await _run_execution(...)` directly, then reads final status from the TaskItem row. |
| Chat input position | Bottom of the chat column, sticky. |

---

## File map (what gets created vs modified)

### webhook-handler (Discord side)

| Path | Status | Responsibility |
|---|---|---|
| `webhook-handler/handlers/visual_edit_token.py` | CREATE | `sign_edit_token(slug, owner) -> str` |
| `webhook-handler/handlers/app_builder_panel.py` | MODIFY (~line 160) | `build_ready_components` gains `owner` param + `Visual edit ↗` link button |
| `webhook-handler/handlers/discord_commands.py` | MODIFY (line 204 — the only caller) | Pass `owner` to `build_ready_components` |
| `webhook-handler/config.py` | MODIFY | Add `tasks_public_url: str = "https://ai-ui.coolestdomain.win"` (or reuse existing) |
| `webhook-handler/tests/test_visual_edit_token.py` | CREATE | Sign roundtrip, TTL, tamper |
| `webhook-handler/tests/test_build_ready_visual_edit_button.py` | CREATE | The 4th button is present with the right URL |

### tasks service

| Path | Status | Responsibility |
|---|---|---|
| `mcp-servers/tasks/visual_edit_token.py` | CREATE | `verify_edit_token(token, slug) -> owner_or_None` — verify only, no signing |
| `mcp-servers/tasks/visual_edit_jobs.py` | CREATE | `VisualEditJob` dataclass + in-memory registry + TTL reaper |
| `mcp-servers/tasks/routes_visual_edit.py` | CREATE | 3 routes: page, chat, status |
| `mcp-servers/tasks/claude_executor.py` | MODIFY | Add `enhance_with_history(slug, history, prompt) -> EnhanceResult` |
| `mcp-servers/tasks/main.py` | MODIFY | `include_router(visual_edit_router)` |
| `mcp-servers/tasks/static/visual-edit.html` | CREATE | SPA shell — narrow chat + preview iframe |
| `mcp-servers/tasks/static/visual-edit.js` | CREATE | Chat history, POST, poll, iframe reload |
| `mcp-servers/tasks/tests/test_visual_edit_token.py` | CREATE | Verify-side mirror of webhook-handler token test |
| `mcp-servers/tasks/tests/test_visual_edit_jobs.py` | CREATE | Registry behavior |
| `mcp-servers/tasks/tests/test_routes_visual_edit_auth.py` | CREATE | Page route 403 / 200 paths |
| `mcp-servers/tasks/tests/test_routes_visual_edit_chat.py` | CREATE | POST returns 202 + build_id, allocates job |
| `mcp-servers/tasks/tests/test_routes_visual_edit_status.py` | CREATE | GET status returns state, 404, 403 |
| `mcp-servers/tasks/tests/test_visual_edit_lifecycle.py` | CREATE | End-to-end with mocked Claude: happy / error / timeout |
| `mcp-servers/tasks/tests/test_claude_executor_enhance_history.py` | CREATE | `enhance_with_history` prepends history correctly |

---

## Task list

The plan has 8 phases. Each task is 2-5 min; each phase finishes with a green test + a commit.

### Phase 1: Token (slug-binding HMAC)

#### Task 1.1: Test for `sign_edit_token` / `verify_edit_token` roundtrip in webhook-handler

**Files:**
- Test: `webhook-handler/tests/test_visual_edit_token.py` (CREATE)
- Source (will be created in Task 1.2): `webhook-handler/handlers/visual_edit_token.py`

- [ ] **Step 1: Write the failing test**

```python
"""Visual-edit token: HMAC-SHA256 over owner:ts:slug with OAUTH_STATE_SECRET.
Format mirrors handlers.oauth_state but the signing payload includes slug, so
a token issued for slug A cannot be replayed against slug B.
"""
import os
import time
os.environ.setdefault("OAUTH_STATE_SECRET", "test-secret-123")

from handlers.visual_edit_token import (
    sign_edit_token, verify_edit_token, EDIT_TOKEN_TTL_SECONDS,
)


def test_sign_verify_roundtrip():
    tok = sign_edit_token("my-slug", "ralph@example.com")
    assert verify_edit_token(tok, "my-slug") == "ralph@example.com"


def test_wrong_slug_rejected():
    tok = sign_edit_token("slug-a", "ralph@example.com")
    assert verify_edit_token(tok, "slug-b") is None


def test_tampered_owner_rejected():
    tok = sign_edit_token("my-slug", "ralph@example.com")
    head, ts, sig = tok.split(".")
    # swap the owner segment for a different one — signature should fail
    import base64
    other = base64.urlsafe_b64encode(b"someone-else@example.com").decode().rstrip("=")
    bad = f"{other}.{ts}.{sig}"
    assert verify_edit_token(bad, "my-slug") is None


def test_expired_rejected(monkeypatch):
    tok = sign_edit_token("my-slug", "ralph@example.com")
    # advance time past the TTL
    monkeypatch.setattr("handlers.visual_edit_token.time.time",
                        lambda: time.time() + EDIT_TOKEN_TTL_SECONDS + 10)
    assert verify_edit_token(tok, "my-slug") is None


def test_malformed_returns_none():
    assert verify_edit_token("", "x") is None
    assert verify_edit_token("not.a.valid.token", "x") is None
    assert verify_edit_token("only-one-part", "x") is None


def test_ttl_is_30_minutes():
    assert EDIT_TOKEN_TTL_SECONDS == 1800
```

- [ ] **Step 2: Run test to verify it fails**

```
cd webhook-handler
OAUTH_STATE_SECRET=test-secret-123 python -m pytest tests/test_visual_edit_token.py -v
```
Expected: FAIL with `ModuleNotFoundError: handlers.visual_edit_token`

- [ ] **Step 3: Write `visual_edit_token.py`**

```python
"""Signed token for the visual editor URL. HMAC-SHA256 over "<owner>:<ts>:<slug>"
with OAUTH_STATE_SECRET, so a token issued for one slug cannot be replayed
against another. Format: <b64url(owner)>.<b64url(ts)>.<b64url(sig)>.

Two identical-purpose copies live in webhook-handler (sign) and tasks (verify).
Same OAUTH_STATE_SECRET; signing payload includes the slug, so these tokens
can never be cross-substituted with the connector oauth_state tokens.
"""
import base64
import hashlib
import hmac
import os
import time

_SECRET = os.environ.get("OAUTH_STATE_SECRET", "").encode()
EDIT_TOKEN_TTL_SECONDS = 1800  # 30 minutes


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _mac(owner: str, ts: str, slug: str) -> bytes:
    return hmac.new(_SECRET, f"{owner}:{ts}:{slug}".encode("utf-8"),
                    hashlib.sha256).digest()


def sign_edit_token(slug: str, owner: str) -> str:
    if not _SECRET:
        raise RuntimeError("OAUTH_STATE_SECRET is not set")
    ts = str(int(time.time()))
    return f"{_b64(owner.encode('utf-8'))}.{_b64(ts.encode('ascii'))}.{_b64(_mac(owner, ts, slug))}"


def verify_edit_token(token: str, slug: str) -> str | None:
    """Return the owner if the signature is valid AND not expired AND bound to
    this slug, else None."""
    if not _SECRET:
        return None
    parts = (token or "").split(".")
    if len(parts) != 3:
        return None
    owner_b64, ts_b64, sig_b64 = parts
    try:
        owner = _unb64(owner_b64).decode("utf-8")
        ts = _unb64(ts_b64).decode("ascii")
        sig = _unb64(sig_b64)
    except Exception:
        return None
    if not hmac.compare_digest(sig, _mac(owner, ts, slug)):
        return None
    try:
        if time.time() - int(ts) > EDIT_TOKEN_TTL_SECONDS:
            return None
    except ValueError:
        return None
    return owner
```

- [ ] **Step 4: Run test to verify it passes**

```
OAUTH_STATE_SECRET=test-secret-123 python -m pytest tests/test_visual_edit_token.py -v
```
Expected: PASS — 6 tests green.

- [ ] **Step 5: Commit**

```
git add webhook-handler/handlers/visual_edit_token.py webhook-handler/tests/test_visual_edit_token.py
git commit -m "feat(visual-edit): slug-bound signed token (sign+verify, 30-min TTL)"
```

#### Task 1.2: Mirror the verify side into the tasks service

**Files:**
- Create: `mcp-servers/tasks/visual_edit_token.py`
- Test: `mcp-servers/tasks/tests/test_visual_edit_token.py` (CREATE)

- [ ] **Step 1: Write the failing test** (verify-only — sign is webhook-handler's job, but our test cross-checks by importing both)

```python
"""Tasks-side verify mirror — must match webhook-handler's sign output."""
import os
import sys
os.environ.setdefault("OAUTH_STATE_SECRET", "test-secret-123")

# Import the webhook-handler signer to produce a real token for the test.
WEBHOOK_HANDLER = os.path.join(os.path.dirname(__file__), "..", "..", "..", "webhook-handler")
sys.path.insert(0, os.path.abspath(WEBHOOK_HANDLER))
from handlers.visual_edit_token import sign_edit_token  # noqa: E402

from visual_edit_token import verify_edit_token, EDIT_TOKEN_TTL_SECONDS  # noqa: E402


def test_cross_module_verify_matches_sign():
    tok = sign_edit_token("my-slug", "ralph@example.com")
    assert verify_edit_token(tok, "my-slug") == "ralph@example.com"


def test_wrong_slug_rejected():
    from handlers.visual_edit_token import sign_edit_token
    tok = sign_edit_token("slug-a", "ralph@example.com")
    assert verify_edit_token(tok, "slug-b") is None


def test_ttl_constants_match():
    """Both sides MUST have the same TTL or they'll disagree on expiry."""
    from handlers.visual_edit_token import EDIT_TOKEN_TTL_SECONDS as WH_TTL
    assert WH_TTL == EDIT_TOKEN_TTL_SECONDS == 1800
```

- [ ] **Step 2: Run — expect FAIL** (`ModuleNotFoundError: visual_edit_token`)

- [ ] **Step 3: Create `mcp-servers/tasks/visual_edit_token.py`**

```python
"""Tasks-side verifier for visual-edit URLs. Keep in sync with
webhook-handler/handlers/visual_edit_token.py — same secret + same HMAC
payload (owner:ts:slug), same TTL.
"""
import base64
import hashlib
import hmac
import os
import time

_SECRET = os.environ.get("OAUTH_STATE_SECRET", "").encode()
EDIT_TOKEN_TTL_SECONDS = 1800


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def verify_edit_token(token: str, slug: str) -> str | None:
    if not _SECRET:
        return None
    parts = (token or "").split(".")
    if len(parts) != 3:
        return None
    owner_b64, ts_b64, sig_b64 = parts
    try:
        owner = _unb64(owner_b64).decode("utf-8")
        ts = _unb64(ts_b64).decode("ascii")
        sig = _unb64(sig_b64)
    except Exception:
        return None
    expected = hmac.new(
        _SECRET, f"{owner}:{ts}:{slug}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        if time.time() - int(ts) > EDIT_TOKEN_TTL_SECONDS:
            return None
    except ValueError:
        return None
    return owner
```

- [ ] **Step 4: Run — expect PASS** (3 tests).
- [ ] **Step 5: Commit**

```
git add mcp-servers/tasks/visual_edit_token.py mcp-servers/tasks/tests/test_visual_edit_token.py
git commit -m "feat(visual-edit): tasks-side token verifier (mirrors webhook-handler signer)"
```

---

### Phase 2: Discord "Visual edit" link button

#### Task 2.1: `build_ready_components` gains `owner` param and a 4th link button

**Files:**
- Modify: `webhook-handler/handlers/app_builder_panel.py:160` (`build_ready_components`)
- Test: `webhook-handler/tests/test_build_ready_visual_edit_button.py` (CREATE)
- Config: `webhook-handler/config.py` — add `tasks_public_url` setting

- [ ] **Step 1: Write the failing test**

```python
"""Build-ready card now has a 4th button: a 'Visual edit' link with a
slug-bound signed token."""
import os
os.environ.setdefault("OAUTH_STATE_SECRET", "test-secret-123")

from handlers.app_builder_panel import build_ready_components
from handlers.visual_edit_token import verify_edit_token


def _flat(rows):
    return [c for row in rows for c in row["components"]]


def test_visual_edit_button_present():
    rows = build_ready_components("my-slug", "https://preview.example/x",
                                  owner="ralph@example.com")
    labels = [c.get("label", "") for c in _flat(rows)]
    assert any("Visual edit" in lbl for lbl in labels)


def test_visual_edit_url_carries_signed_slug_token():
    rows = build_ready_components("my-slug", "https://preview.example/x",
                                  owner="ralph@example.com")
    btn = next(c for c in _flat(rows) if "Visual edit" in c.get("label", ""))
    assert btn["style"] == 5  # LINK
    url = btn["url"]
    assert url.startswith("https://")
    assert "/tasks/edit/my-slug" in url
    # Extract ?token=... and verify it round-trips to the owner + slug.
    from urllib.parse import urlparse, parse_qs
    token = parse_qs(urlparse(url).query)["token"][0]
    assert verify_edit_token(token, "my-slug") == "ralph@example.com"


def test_owner_required():
    """Without an owner we cannot sign; the function must require it."""
    import pytest
    with pytest.raises(TypeError):
        build_ready_components("my-slug", "https://preview.example/x")
```

- [ ] **Step 2: Run — expect FAIL** (`build_ready_components` doesn't take `owner` yet).

- [ ] **Step 3: Add `tasks_public_url` to `config.py`**

Locate the existing `Settings` class in `webhook-handler/config.py`, add this field next to `gmail_public_url`/`gdrive_public_url`:

```python
tasks_public_url: str = "https://ai-ui.coolestdomain.win"
```

- [ ] **Step 4: Modify `build_ready_components`**

```python
def build_ready_components(slug: str, preview_url: str, *, owner: str) -> list[dict]:
    """Action row for the build-ready message: green Publish + blurple Enhance,
    plus an 'Open preview' link button, plus a 'Visual edit' link button that
    deep-links into the tasks service editor with a signed token."""
    from config import settings  # local import — avoid top-level cycle
    from handlers.visual_edit_token import sign_edit_token

    buttons: list[dict] = [
        _button("\U0001f7e2 Publish", f"{PUBLISH_PREFIX}{slug}", STYLE_SUCCESS),
        _button("✏️ Enhance", f"{ENHANCE_PREFIX}{slug}", STYLE_PRIMARY),
    ]
    if preview_url:
        buttons.append({"type": BUTTON, "style": STYLE_LINK,
                        "label": "\U0001f517 Open preview", "url": preview_url})

    token = sign_edit_token(slug, owner)
    edit_url = (
        f"{settings.tasks_public_url.rstrip('/')}/tasks/edit/{slug}?token={token}"
    )
    buttons.append({"type": BUTTON, "style": STYLE_LINK,
                    "label": "Visual edit", "url": edit_url})
    return [{"type": ACTION_ROW, "components": buttons}]
```

Note: existing emoji in Publish/Enhance labels stay for now — Discord's "no emoji" v2 rule only landed on the schedule/connections cards, not the App Builder card. (If Ralph wants those scrubbed too, that's a separate task.)

- [ ] **Step 5: Run — expect PASS** (3 tests).

- [ ] **Step 6: Commit**

```
git add webhook-handler/handlers/app_builder_panel.py webhook-handler/config.py webhook-handler/tests/test_build_ready_visual_edit_button.py
git commit -m "feat(visual-edit): add 'Visual edit' link button to Build-ready card"
```

#### Task 2.2: Thread `owner` through the single `build_ready_components` caller

**Files:**
- Modify: `webhook-handler/handlers/discord_commands.py:204` (the only caller — verified via grep)

- [ ] **Step 1: Confirm grep returns just one production call site**

```
cd webhook-handler
grep -rn "build_ready_components(" --include="*.py" handlers/
```
Expected: a single match at `handlers/discord_commands.py:204`, inside `_channel_notifiers` → `notify_channel_rich`. (Plus matches in `tests/` which we ignore for this task.) If you see additional production matches, audit them too.

- [ ] **Step 2: Resolve `owner` inside `_channel_notifiers` and pass it through**

The `_channel_notifiers` method (in `DiscordCommandHandler`) currently closes over `channel_id` only. We need to thread the `user_id` (or the resolved email) in too. The least-intrusive change is to make `_channel_notifiers` take `user_id` and resolve the email lazily inside `notify_channel_rich`:

Find the `_channel_notifiers` method signature and update it. Then update each call site (in `_handle_application_command`, `_handle_build_modal_submit`, `_handle_schedule_modal_submit`, etc.) to pass `user_id`. Inside `notify_channel_rich`, call `await self.router._resolve_email_auto(user_id)` to get the owner. Example:

```python
def _channel_notifiers(
    self, channel_id: str, user_id: str,
) -> tuple[Callable[[str], Awaitable[None]], Callable[[str, str, str], Awaitable[None]]]:
    ...
    async def notify_channel_rich(msg: str, slug: str, preview_url: str) -> None:
        owner = await self.router._resolve_email_auto(user_id)
        await self.discord.post_channel_message(
            channel_id, "", embeds=[build_ready_embed(slug, preview_url, msg)],
            components=build_ready_components(slug, preview_url, owner=owner),
        )
    return notify_channel, notify_channel_rich
```

- [ ] **Step 3: Run the full webhook-handler suite**

```
OAUTH_STATE_SECRET=test-secret-123 python -m pytest tests/ -q
```
Expected: all green (incl. existing + the 3 new tests).

- [ ] **Step 4: Commit**

```
git add -u webhook-handler/handlers/discord_commands.py
git commit -m "feat(visual-edit): pass owner through Build-ready render"
```

---

### Phase 3: Job registry

#### Task 3.1: `VisualEditJob` + in-memory registry with TTL reaper

**Files:**
- Create: `mcp-servers/tasks/visual_edit_jobs.py`
- Test: `mcp-servers/tasks/tests/test_visual_edit_jobs.py`

- [ ] **Step 1: Write the failing test**

```python
"""Job registry for the visual editor: allocate ids, track state, reap stale."""
import time

from visual_edit_jobs import (
    VisualEditJob, JobRegistry, JobState, JOB_TTL_SECONDS,
)


def test_allocate_returns_unique_ids():
    reg = JobRegistry()
    a = reg.allocate(slug="s", owner="o", prompt="hi")
    b = reg.allocate(slug="s", owner="o", prompt="hi")
    assert a != b
    assert reg.get(a) is not None
    assert reg.get(b) is not None


def test_initial_state_is_queued():
    reg = JobRegistry()
    bid = reg.allocate(slug="s", owner="o", prompt="hi")
    assert reg.get(bid).state == JobState.QUEUED


def test_set_state_transitions():
    reg = JobRegistry()
    bid = reg.allocate(slug="s", owner="o", prompt="hi")
    reg.set_state(bid, JobState.THINKING)
    reg.set_state(bid, JobState.APPLYING)
    reg.set_state(bid, JobState.DONE, preview_url="/tasks/preview-app/s/?v=1")
    job = reg.get(bid)
    assert job.state == JobState.DONE
    assert job.preview_url == "/tasks/preview-app/s/?v=1"


def test_set_state_error_carries_summary_and_detail():
    reg = JobRegistry()
    bid = reg.allocate(slug="s", owner="o", prompt="hi")
    reg.set_state(bid, JobState.ERROR,
                  error={"summary": "boom", "detail": "stack..."})
    assert reg.get(bid).state == JobState.ERROR
    assert reg.get(bid).error["summary"] == "boom"


def test_unknown_id_returns_none():
    reg = JobRegistry()
    assert reg.get("nope") is None


def test_reap_removes_old_jobs(monkeypatch):
    reg = JobRegistry()
    old = reg.allocate(slug="s", owner="o", prompt="hi")
    # advance time past TTL
    real_time = time.time()
    monkeypatch.setattr("visual_edit_jobs.time.time",
                        lambda: real_time + JOB_TTL_SECONDS + 5)
    reg.reap()
    assert reg.get(old) is None


def test_owner_is_preserved():
    reg = JobRegistry()
    bid = reg.allocate(slug="s", owner="ralph@x", prompt="hi")
    assert reg.get(bid).owner == "ralph@x"


def test_ttl_is_10_minutes():
    assert JOB_TTL_SECONDS == 600
```

- [ ] **Step 2: Run — expect FAIL** (`ModuleNotFoundError: visual_edit_jobs`).

- [ ] **Step 3: Write `visual_edit_jobs.py`**

```python
"""In-memory job registry for the visual-edit chat flow.

Each chat turn allocates a build_id, runs the enhance pipeline as a detached
asyncio task, and reports state through this registry. The browser polls the
status endpoint at ~1Hz until the state reaches done or error.

Process-local. Restart drops all in-flight jobs; that's acceptable for v1
because each job lives <= 5 min (enhance timeout) and the browser shows a
recoverable error if its build_id disappears.
"""
from __future__ import annotations

import enum
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional


JOB_TTL_SECONDS = 600  # entries older than this are reaped on each registry call


class JobState(str, enum.Enum):
    QUEUED = "queued"
    THINKING = "thinking"
    APPLYING = "applying"
    DONE = "done"
    ERROR = "error"


@dataclass
class VisualEditJob:
    build_id: str
    slug: str
    owner: str
    prompt: str
    state: JobState = JobState.QUEUED
    preview_url: Optional[str] = None
    error: Optional[dict] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class JobRegistry:
    """Thread-/task-safe enough for single-worker uvicorn use. Plain dict; if
    we ever run multiple workers we'd need a shared store (Redis) — out of
    scope for v1."""

    def __init__(self) -> None:
        self._jobs: dict[str, VisualEditJob] = {}

    def allocate(self, *, slug: str, owner: str, prompt: str) -> str:
        self.reap()
        build_id = f"b_{uuid.uuid4().hex[:12]}"
        self._jobs[build_id] = VisualEditJob(
            build_id=build_id, slug=slug, owner=owner, prompt=prompt,
        )
        return build_id

    def get(self, build_id: str) -> Optional[VisualEditJob]:
        return self._jobs.get(build_id)

    def set_state(self, build_id: str, state: JobState, *,
                  preview_url: Optional[str] = None,
                  error: Optional[dict] = None) -> None:
        job = self._jobs.get(build_id)
        if job is None:
            return
        job.state = state
        if preview_url is not None:
            job.preview_url = preview_url
        if error is not None:
            job.error = error
        job.updated_at = time.time()

    def reap(self) -> None:
        cutoff = time.time() - JOB_TTL_SECONDS
        stale = [bid for bid, j in self._jobs.items() if j.updated_at < cutoff]
        for bid in stale:
            del self._jobs[bid]


# Process-wide singleton for the running app to use.
REGISTRY = JobRegistry()
```

- [ ] **Step 4: Run — expect PASS** (8 tests).
- [ ] **Step 5: Commit**

```
git add mcp-servers/tasks/visual_edit_jobs.py mcp-servers/tasks/tests/test_visual_edit_jobs.py
git commit -m "feat(visual-edit): in-memory job registry with TTL reaper"
```

---

### Phase 4: History-aware enhance pipeline

This phase has 3 sub-tasks because the existing code base has more friction than the spec assumed: `build_enhance_prompt` has no history kwarg, `ENHANCE_PROMPT_TEMPLATE` has no history block, and `_create_and_spawn_enhance` is fire-and-forget (returns a task_id instead of awaiting the build). We add history support to the prompt, refactor the spawn helper into a setup/spawn pair so we can `await` directly, then write the new `enhance_with_history` entry point on top of those primitives.

#### Task 4.1: Add `_format_enhance_history` + history slot in `ENHANCE_PROMPT_TEMPLATE`

**Files:**
- Modify: `mcp-servers/tasks/claude_executor.py` — add helper + template placeholder + thread `conversation_history` through `build_enhance_prompt`
- Test: `mcp-servers/tasks/tests/test_claude_executor_enhance_history.py` (CREATE)

- [ ] **Step 1: Write the failing tests**

```python
"""History support for build_enhance_prompt:
  - empty list → empty string block (no template noise)
  - user/assistant turns render in plain text the LLM can parse
  - the helper does NOT mutate the existing _format_conversation_history
    (which uses different role names for clarify/tdd_execute prompts).
"""
from claude_executor import (
    _format_enhance_history,
    _format_conversation_history,
    build_enhance_prompt,
)


def test_empty_history_returns_empty_string():
    assert _format_enhance_history([]) == ""


def test_renders_user_and_assistant_turns():
    out = _format_enhance_history([
        {"role": "user", "content": "make the hero darker"},
        {"role": "assistant", "content": "Done."},
        {"role": "user", "content": "now bigger text"},
    ])
    assert "User: make the hero darker" in out
    assert "Assistant: Done." in out
    assert "User: now bigger text" in out
    # Should start with a CONVERSATION HISTORY: header so the LLM treats it
    # as context, not as part of the current request.
    assert out.startswith("CONVERSATION HISTORY:")


def test_existing_format_conversation_history_unchanged():
    """We add a NEW helper; the existing one (used by clarify/tdd_execute
    prompts) keeps its 'ai' / 'Admin answered' role mapping."""
    out = _format_conversation_history([
        {"role": "ai", "content": "what's the budget?"},
        {"role": "user", "content": "$50/month"},
    ])
    assert "AI asked: what's the budget?" in out
    assert "Admin answered: $50/month" in out


def test_build_enhance_prompt_includes_history_block():
    prompt = build_enhance_prompt(
        slug="my-app",
        user_request="now make buttons bigger",
        conversation_history=[
            {"role": "user", "content": "make hero darker"},
            {"role": "assistant", "content": "Done."},
        ],
    )
    assert "CONVERSATION HISTORY:" in prompt
    assert "make hero darker" in prompt
    assert "now make buttons bigger" in prompt  # current request still present


def test_build_enhance_prompt_no_history_no_block():
    prompt = build_enhance_prompt(slug="my-app", user_request="just one change")
    assert "CONVERSATION HISTORY:" not in prompt
    assert "just one change" in prompt
```

- [ ] **Step 2: Run — expect FAIL** on `_format_enhance_history` import.

- [ ] **Step 3: Add `_format_enhance_history` to `claude_executor.py`** (near `_format_conversation_history` at line ~626, so they live together):

```python
def _format_enhance_history(history: list[dict]) -> str:
    """Format chat history for the enhance prompt. Roles are 'user' or
    'assistant' (matching the visual-edit SPA's JSON). Returns an empty
    string when the list is empty so the template renders cleanly."""
    if not history:
        return ""
    lines = []
    for entry in history:
        role = "User" if entry.get("role") == "user" else "Assistant"
        content = (entry.get("content") or "").strip()
        if content:
            lines.append(f"  {role}: {content}")
    if not lines:
        return ""
    return "CONVERSATION HISTORY:\n" + "\n".join(lines)
```

- [ ] **Step 4: Add `{conversation_history_block}` placeholder to `ENHANCE_PROMPT_TEMPLATE`**

In `claude_executor.py`, find the line `ENHANCE_PROMPT_TEMPLATE = """You are enhancing an EXISTING app...` (line ~493). Insert the placeholder right BEFORE `USER REQUEST:` like this:

```text
APP LOCATION: /workspace/ai_ui/apps/{slug}/

{conversation_history_block}

USER REQUEST: {user_request}
```

- [ ] **Step 5: Thread `conversation_history` through `build_enhance_prompt`**

Modify the signature at `claude_executor.py:577`:

```python
def build_enhance_prompt(
    *,
    slug: str,
    user_request: str,
    attempt_count: int = 0,
    max_attempts: int = 3,
    error_context: str = "",
    supabase_url: str | None = None,
    has_db_uri: bool = False,
    user_email: str = "",
    attachments: list[str] | None = None,
    selection_block: str = "",
    conversation_history: list[dict] | None = None,
) -> str:
    ...existing err_block logic...
    body = ENHANCE_PROMPT_TEMPLATE.format(
        slug=slug,
        user_request=user_request,
        error_context_block=err_block,
        conversation_history_block=_format_enhance_history(conversation_history or []),
        supabase_block=_supabase_block(...),
    )
    ...existing selection_block / attachments logic...
```

- [ ] **Step 6: Run — expect PASS** (5 tests). Also run the existing enhance-prompt tests to make sure adding the placeholder didn't break them:

```
cd mcp-servers/tasks
python -m pytest tests/test_enhance_prompt.py tests/test_claude_executor_enhance_history.py -q
```

Expected: all green. If `test_enhance_prompt.py` fails because it does an exact string match on the prompt body, update those tests to allow the new (empty) history block.

- [ ] **Step 7: Commit**

```
git add mcp-servers/tasks/claude_executor.py mcp-servers/tasks/tests/test_claude_executor_enhance_history.py
git commit -m "feat(visual-edit): build_enhance_prompt grows conversation_history kwarg"
```

#### Task 4.2: Refactor `_create_and_spawn_enhance` into setup + spawn

**Files:**
- Modify: `mcp-servers/tasks/routes_aiuibuilder.py` — split the helper into `_setup_enhance_task` (returns the IDs + prompt) and the existing wrapper (which calls setup + spawns)
- Test: `mcp-servers/tasks/tests/test_enhance_endpoint.py` should still pass

This refactor is pure DRY — same behavior, different shape. No new behavior introduced.

- [ ] **Step 1: Read** `routes_aiuibuilder.py` from line 307 to ~380 to understand the existing body (DB lookup, role check, advisory lock, prompt build, asyncio.create_task spawn).

- [ ] **Step 2: Extract setup into a sibling**

Add a new helper above the existing function:

```python
async def _setup_enhance_task(
    email: str, slug: str, prompt: str, *,
    conversation_history: list[dict] | None = None,
) -> tuple[int, int, str]:
    """Create the TaskItem + TaskExecution rows for an enhance run, build the
    prompt (with optional history), and return (task_id, exec_id, prompt_text).
    Does NOT spawn the worker — caller chooses fire-and-forget vs await."""
    # ... lift the DB-rows + advisory-lock + prompt-build code from
    # _create_and_spawn_enhance verbatim, ending at the point where
    # _create_and_spawn_enhance currently calls asyncio.create_task.
    # Return (task_id, exec_id, prompt_text) instead of spawning.
```

Then change `_create_and_spawn_enhance` to call setup + spawn:

```python
async def _create_and_spawn_enhance(email: str, slug: str, prompt: str) -> tuple[str, str]:
    """Legacy fire-and-forget enhance: create rows + spawn worker, return task_id+slug
    immediately. Used by the Discord modal enhance flow."""
    from routes_execution import _RUNNING, _run_execution
    task_id, exec_id, prompt_text = await _setup_enhance_task(email, slug, prompt)
    _RUNNING[task_id] = {"task": None}
    bg = asyncio.create_task(_run_execution(task_id, exec_id, prompt_text))
    _RUNNING[task_id]["task"] = bg
    return str(task_id), slug
```

- [ ] **Step 3: Run the existing enhance tests**

```
cd mcp-servers/tasks
python -m pytest tests/test_enhance_endpoint.py -q
```
Expected: same number of tests pass as before (this is a no-behavior-change refactor).

- [ ] **Step 4: Commit**

```
git add mcp-servers/tasks/routes_aiuibuilder.py
git commit -m "refactor(enhance): split _create_and_spawn_enhance into setup + spawn"
```

#### Task 4.3: Add `enhance_with_history` as a public entry point

**Files:**
- Modify: `mcp-servers/tasks/routes_aiuibuilder.py` — add new function alongside `_create_and_spawn_enhance`
- Test: extend `tests/test_claude_executor_enhance_history.py` with an integration test (mocked subprocess)

This is the function the visual-edit job worker calls. Same setup as the legacy path, but awaits the worker and reads the final TaskItem status from the DB.

- [ ] **Step 1: Write the failing test**

```python
"""enhance_with_history wraps the setup helper + awaits _run_execution
so the visual-edit job worker can transition the job to DONE/ERROR based
on the final TaskItem.status."""
from unittest.mock import AsyncMock, patch
import pytest

from routes_aiuibuilder import enhance_with_history


@pytest.mark.asyncio
async def test_history_passed_to_setup(monkeypatch):
    captured: dict = {}

    async def fake_setup(email, slug, prompt, *, conversation_history=None):
        captured["history"] = conversation_history
        return (42, 7, "BUILT_PROMPT")

    fake_run = AsyncMock(return_value=None)

    monkeypatch.setattr("routes_aiuibuilder._setup_enhance_task", fake_setup)
    monkeypatch.setattr("routes_aiuibuilder._run_execution", fake_run)
    # Also patch the final-status DB read to a happy result.
    monkeypatch.setattr("routes_aiuibuilder._read_final_status",
                        AsyncMock(return_value={"status": "completed"}))

    result = await enhance_with_history(
        slug="my-app", history=[{"role": "user", "content": "hi"}],
        prompt="bigger text", owner_email="ralph@example.com",
    )
    assert captured["history"] == [{"role": "user", "content": "hi"}]
    assert result["status"] == "completed"
    fake_run.assert_awaited_once_with(42, 7, "BUILT_PROMPT")


@pytest.mark.asyncio
async def test_failed_status_propagates(monkeypatch):
    async def fake_setup(*a, **kw):
        return (42, 7, "PROMPT")
    monkeypatch.setattr("routes_aiuibuilder._setup_enhance_task", fake_setup)
    monkeypatch.setattr("routes_aiuibuilder._run_execution", AsyncMock(return_value=None))
    monkeypatch.setattr("routes_aiuibuilder._read_final_status",
                        AsyncMock(return_value={"status": "failed",
                                                "error": "git commit refused"}))
    result = await enhance_with_history(
        slug="my-app", history=[], prompt="x", owner_email="ralph@example.com",
    )
    assert result["status"] == "failed"
    assert "error" in result
```

- [ ] **Step 2: Run — expect FAIL** (`enhance_with_history` doesn't exist).

- [ ] **Step 3: Add `enhance_with_history` + `_read_final_status` to `routes_aiuibuilder.py`**

```python
async def _read_final_status(task_id: int) -> dict:
    """Read the TaskItem.status + last error after _run_execution returns."""
    async with session() as s:
        item = (await s.execute(
            select(TaskItem).where(TaskItem.id == task_id)
        )).scalar_one_or_none()
        if item is None:
            return {"status": "missing"}
        out = {"status": item.status or "unknown"}
        if item.status in ("failed", "errored"):
            out["error"] = (item.error_message or "")[:500]
        return out


async def enhance_with_history(
    *, slug: str, history: list[dict], prompt: str, owner_email: str,
) -> dict:
    """Synchronous (awaitable) enhance. Same pipeline as _create_and_spawn_enhance
    but blocks until the worker exits, then returns the final TaskItem status
    so the visual-edit job worker can flip its registry entry to DONE / ERROR.
    """
    from routes_execution import _RUNNING, _run_execution
    task_id, exec_id, prompt_text = await _setup_enhance_task(
        owner_email, slug, prompt, conversation_history=history,
    )
    _RUNNING[task_id] = {"task": None}
    bg = asyncio.create_task(_run_execution(task_id, exec_id, prompt_text))
    _RUNNING[task_id]["task"] = bg
    await bg  # block until worker completes
    return await _read_final_status(task_id)
```

Note the `_RUNNING` registry write — the existing enhance flow uses it to prevent concurrent enhances on the same task. Keep it consistent.

- [ ] **Step 4: Update `_setup_enhance_task` to call `build_enhance_prompt(..., conversation_history=conversation_history)`**

In `_setup_enhance_task` (the helper from Task 4.2), change the `build_enhance_prompt(...)` call to thread the new kwarg through:

```python
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
    conversation_history=conversation_history or [],
)
```

- [ ] **Step 5: Update the visual-edit route to import from `routes_aiuibuilder`**

In `routes_visual_edit.py`, change the import:

```python
# was:  from claude_executor import enhance_with_history
from routes_aiuibuilder import enhance_with_history
```

And update the patches in `tests/test_routes_visual_edit_chat.py` and `tests/test_visual_edit_lifecycle.py` accordingly.

- [ ] **Step 6: Run — expect PASS** (the 2 new tests + the existing route tests).

```
cd mcp-servers/tasks
python -m pytest tests/test_claude_executor_enhance_history.py tests/test_enhance_endpoint.py tests/test_routes_visual_edit_chat.py tests/test_visual_edit_lifecycle.py -q
```

- [ ] **Step 7: Commit**

```
git add mcp-servers/tasks/routes_aiuibuilder.py mcp-servers/tasks/routes_visual_edit.py mcp-servers/tasks/tests/test_claude_executor_enhance_history.py mcp-servers/tasks/tests/test_routes_visual_edit_chat.py mcp-servers/tasks/tests/test_visual_edit_lifecycle.py
git commit -m "feat(visual-edit): enhance_with_history — awaitable enhance with history"
```

---

### Phase 5: HTTP routes

#### Task 5.1: GET /tasks/edit/<slug> (auth + serve HTML)

**Files:**
- Create: `mcp-servers/tasks/routes_visual_edit.py`
- Test: `mcp-servers/tasks/tests/test_routes_visual_edit_auth.py`
- Stub static: `mcp-servers/tasks/static/visual-edit.html` — for now, a placeholder so the route has something to serve

- [ ] **Step 1: Create a 1-line stub HTML** so the route can return SOMETHING (the real SPA goes in Phase 6).

```html
<!-- mcp-servers/tasks/static/visual-edit.html -->
<!DOCTYPE html>
<html><body><div id="visual-edit-root">Loading…</div></body></html>
```

- [ ] **Step 2: Write the failing test**

```python
"""GET /tasks/edit/<slug>: requires a valid slug-bound signed token."""
import os
os.environ.setdefault("OAUTH_STATE_SECRET", "test-secret-123")
import sys
WEBHOOK_HANDLER = os.path.join(os.path.dirname(__file__), "..", "..", "..", "webhook-handler")
sys.path.insert(0, os.path.abspath(WEBHOOK_HANDLER))

import pytest
from fastapi.testclient import TestClient

from main import app
from handlers.visual_edit_token import sign_edit_token


@pytest.fixture
def client():
    return TestClient(app)


def test_missing_token_rejected(client):
    r = client.get("/tasks/edit/my-slug")
    assert r.status_code == 403


def test_bad_token_rejected(client):
    r = client.get("/tasks/edit/my-slug?token=garbage")
    assert r.status_code == 403


def test_wrong_slug_in_token_rejected(client):
    tok = sign_edit_token("slug-a", "ralph@example.com")
    r = client.get(f"/tasks/edit/slug-b?token={tok}")
    assert r.status_code == 403


def test_valid_token_serves_html(client):
    tok = sign_edit_token("my-slug", "ralph@example.com")
    r = client.get(f"/tasks/edit/my-slug?token={tok}")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "visual-edit-root" in r.text
```

- [ ] **Step 3: Run — expect FAIL** (route doesn't exist yet — likely 404).

- [ ] **Step 4: Implement the route**

```python
"""Visual editor routes — page, chat, status.

The page is a thin SPA served as static HTML; this module verifies the signed
URL token on every endpoint and orchestrates the chat → job → poll → preview
loop. See docs/superpowers/specs/2026-05-28-visual-editor-design.md.
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from visual_edit_token import verify_edit_token

logger = logging.getLogger(__name__)
router = APIRouter()

_STATIC = Path(__file__).parent / "static"


def _require_owner(slug: str, token: str) -> str:
    owner = verify_edit_token(token, slug)
    if owner is None:
        raise HTTPException(status_code=403, detail="invalid_or_expired_link")
    return owner


@router.get("/tasks/edit/{slug}", include_in_schema=False)
async def visual_edit_page(slug: str, token: str = Query("")):
    _require_owner(slug, token)
    html = (_STATIC / "visual-edit.html").read_text(encoding="utf-8")
    return HTMLResponse(html)
```

- [ ] **Step 5: Wire the router into `main.py`**

In `mcp-servers/tasks/main.py`, near the other `include_router` calls:

```python
from routes_visual_edit import router as visual_edit_router
app.include_router(visual_edit_router)
```

- [ ] **Step 6: Run — expect PASS** (4 tests).
- [ ] **Step 7: Commit**

```
git add mcp-servers/tasks/routes_visual_edit.py mcp-servers/tasks/main.py mcp-servers/tasks/static/visual-edit.html mcp-servers/tasks/tests/test_routes_visual_edit_auth.py
git commit -m "feat(visual-edit): GET /tasks/edit/<slug> page route (auth-gated)"
```

#### Task 5.2: POST /tasks/edit/<slug>/chat (allocate job, fire-and-forget build)

**Files:**
- Modify: `mcp-servers/tasks/routes_visual_edit.py`
- Test: `mcp-servers/tasks/tests/test_routes_visual_edit_chat.py`

- [ ] **Step 1: Write the failing test**

```python
"""POST /tasks/edit/<slug>/chat: allocate a build_id + kick off a build."""
import os
os.environ.setdefault("OAUTH_STATE_SECRET", "test-secret-123")
import sys
WEBHOOK_HANDLER = os.path.join(os.path.dirname(__file__), "..", "..", "..", "webhook-handler")
sys.path.insert(0, os.path.abspath(WEBHOOK_HANDLER))

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app
from handlers.visual_edit_token import sign_edit_token
from visual_edit_jobs import REGISTRY, JobState


@pytest.fixture
def client():
    REGISTRY._jobs.clear()
    return TestClient(app)


def test_chat_returns_build_id(client):
    tok = sign_edit_token("my-slug", "ralph@example.com")
    fake = AsyncMock(return_value=None)
    with patch("routes_visual_edit._run_chat_build", fake):
        r = client.post(
            f"/tasks/edit/my-slug/chat?token={tok}",
            json={"prompt": "make the hero darker", "history": []},
        )
    assert r.status_code == 202
    data = r.json()
    assert "build_id" in data
    assert data["build_id"].startswith("b_")


def test_chat_allocates_job_with_initial_state(client):
    tok = sign_edit_token("my-slug", "ralph@example.com")
    fake = AsyncMock(return_value=None)
    with patch("routes_visual_edit._run_chat_build", fake):
        r = client.post(
            f"/tasks/edit/my-slug/chat?token={tok}",
            json={"prompt": "hi", "history": []},
        )
    build_id = r.json()["build_id"]
    job = REGISTRY.get(build_id)
    assert job is not None
    assert job.state in (JobState.QUEUED, JobState.THINKING)
    assert job.slug == "my-slug"
    assert job.owner == "ralph@example.com"
    assert job.prompt == "hi"


def test_chat_rejects_bad_token(client):
    r = client.post(
        "/tasks/edit/my-slug/chat?token=garbage",
        json={"prompt": "hi", "history": []},
    )
    assert r.status_code == 403


def test_chat_rejects_wrong_slug(client):
    tok = sign_edit_token("slug-a", "ralph@example.com")
    r = client.post(
        f"/tasks/edit/slug-b/chat?token={tok}",
        json={"prompt": "hi", "history": []},
    )
    assert r.status_code == 403


def test_chat_empty_prompt_400(client):
    tok = sign_edit_token("my-slug", "ralph@example.com")
    r = client.post(
        f"/tasks/edit/my-slug/chat?token={tok}",
        json={"prompt": "", "history": []},
    )
    assert r.status_code == 400
```

- [ ] **Step 2: Run — expect FAIL**.

- [ ] **Step 3: Add the POST route + the build worker**

Append to `routes_visual_edit.py`:

```python
import asyncio

from pydantic import BaseModel, Field
from fastapi import status

from visual_edit_jobs import REGISTRY, JobState
from routes_aiuibuilder import enhance_with_history  # added in Phase 4.3


class ChatRequest(BaseModel):
    prompt: str
    history: list[dict] = Field(default_factory=list)


_BUILD_TIMEOUT_SECONDS = 300  # 5-min hard cap on a single chat-driven build


async def _run_chat_build(*, build_id: str, slug: str, owner: str,
                          prompt: str, history: list[dict]) -> None:
    """Background task: run the enhance pipeline and report state changes
    through the job registry. Never raises — all errors become job.error."""
    try:
        REGISTRY.set_state(build_id, JobState.THINKING)
        result = await asyncio.wait_for(
            enhance_with_history(
                slug=slug, history=history, prompt=prompt, owner_email=owner,
            ),
            timeout=_BUILD_TIMEOUT_SECONDS,
        )
        REGISTRY.set_state(build_id, JobState.APPLYING)
        # `result` is the EnhanceResult returned by enhance_with_history; in
        # practice the file write already happened inside that call, so this
        # state transition is informational only and we move straight to done.
        preview_url = f"/tasks/preview-app/{slug}/?v={build_id}"
        REGISTRY.set_state(build_id, JobState.DONE, preview_url=preview_url)
    except asyncio.TimeoutError:
        REGISTRY.set_state(build_id, JobState.ERROR, error={
            "summary": "Build took too long",
            "detail": f"Exceeded {_BUILD_TIMEOUT_SECONDS}s.",
        })
    except Exception as exc:  # noqa: BLE001
        logger.error("visual-edit build failed slug=%s: %s", slug, exc)
        REGISTRY.set_state(build_id, JobState.ERROR, error={
            "summary": "That edit didn't apply",
            "detail": str(exc)[:500],
        })


@router.post("/tasks/edit/{slug}/chat", status_code=status.HTTP_202_ACCEPTED)
async def visual_edit_chat(slug: str, body: ChatRequest, token: str = Query("")):
    owner = _require_owner(slug, token)
    prompt = (body.prompt or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="empty_prompt")
    build_id = REGISTRY.allocate(slug=slug, owner=owner, prompt=prompt)
    asyncio.create_task(_run_chat_build(
        build_id=build_id, slug=slug, owner=owner,
        prompt=prompt, history=body.history,
    ))
    return {"build_id": build_id}
```

- [ ] **Step 4: Run — expect PASS** (5 tests).
- [ ] **Step 5: Commit**

```
git add mcp-servers/tasks/routes_visual_edit.py mcp-servers/tasks/tests/test_routes_visual_edit_chat.py
git commit -m "feat(visual-edit): POST /chat allocates a build_id + runs enhance async"
```

#### Task 5.3: GET /tasks/edit/<slug>/chat/<build_id>/status

**Files:**
- Modify: `mcp-servers/tasks/routes_visual_edit.py`
- Test: `mcp-servers/tasks/tests/test_routes_visual_edit_status.py`

- [ ] **Step 1: Write the failing test**

```python
"""GET status: shape, 404 on unknown id, 403 on bad token."""
import os
os.environ.setdefault("OAUTH_STATE_SECRET", "test-secret-123")
import sys
WEBHOOK_HANDLER = os.path.join(os.path.dirname(__file__), "..", "..", "..", "webhook-handler")
sys.path.insert(0, os.path.abspath(WEBHOOK_HANDLER))

import pytest
from fastapi.testclient import TestClient

from main import app
from handlers.visual_edit_token import sign_edit_token
from visual_edit_jobs import REGISTRY, JobState


@pytest.fixture
def client():
    REGISTRY._jobs.clear()
    return TestClient(app)


def test_status_returns_job_state(client):
    tok = sign_edit_token("my-slug", "ralph@example.com")
    bid = REGISTRY.allocate(slug="my-slug", owner="ralph@example.com", prompt="x")
    REGISTRY.set_state(bid, JobState.THINKING)
    r = client.get(f"/tasks/edit/my-slug/chat/{bid}/status?token={tok}")
    assert r.status_code == 200
    assert r.json()["state"] == "thinking"


def test_status_done_includes_preview_url(client):
    tok = sign_edit_token("my-slug", "ralph@example.com")
    bid = REGISTRY.allocate(slug="my-slug", owner="ralph@example.com", prompt="x")
    REGISTRY.set_state(bid, JobState.DONE, preview_url="/p/?v=1")
    r = client.get(f"/tasks/edit/my-slug/chat/{bid}/status?token={tok}")
    body = r.json()
    assert body["state"] == "done"
    assert body["preview_url"] == "/p/?v=1"


def test_status_error_includes_error_dict(client):
    tok = sign_edit_token("my-slug", "ralph@example.com")
    bid = REGISTRY.allocate(slug="my-slug", owner="ralph@example.com", prompt="x")
    REGISTRY.set_state(bid, JobState.ERROR, error={"summary": "boom", "detail": "x"})
    r = client.get(f"/tasks/edit/my-slug/chat/{bid}/status?token={tok}")
    body = r.json()
    assert body["state"] == "error"
    assert body["error"]["summary"] == "boom"


def test_status_unknown_id_404(client):
    tok = sign_edit_token("my-slug", "ralph@example.com")
    r = client.get(f"/tasks/edit/my-slug/chat/b_doesnotexist/status?token={tok}")
    assert r.status_code == 404


def test_status_bad_token_403(client):
    bid = REGISTRY.allocate(slug="my-slug", owner="o", prompt="x")
    r = client.get(f"/tasks/edit/my-slug/chat/{bid}/status?token=garbage")
    assert r.status_code == 403
```

- [ ] **Step 2: Run — expect FAIL**.

- [ ] **Step 3: Add the GET status route**

```python
@router.get("/tasks/edit/{slug}/chat/{build_id}/status")
async def visual_edit_status(slug: str, build_id: str, token: str = Query("")):
    _require_owner(slug, token)
    job = REGISTRY.get(build_id)
    if job is None or job.slug != slug:
        raise HTTPException(status_code=404, detail="unknown_build_id")
    body: dict = {"state": job.state.value}
    if job.preview_url:
        body["preview_url"] = job.preview_url
    if job.error:
        body["error"] = job.error
    return body
```

- [ ] **Step 4: Run — expect PASS** (5 tests).
- [ ] **Step 5: Commit**

```
git add mcp-servers/tasks/routes_visual_edit.py mcp-servers/tasks/tests/test_routes_visual_edit_status.py
git commit -m "feat(visual-edit): GET /chat/<id>/status reports job state"
```

---

### Phase 6: SPA (HTML + JS)

#### Task 6.1: Replace the stub `visual-edit.html` with the real layout shell

**Files:**
- Modify: `mcp-servers/tasks/static/visual-edit.html`

No automated tests for the SPA layout in v1 (per spec — Playwright is v2). Just make it render correctly when opened.

- [ ] **Step 1: Write the full HTML**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AIUI · Visual edit</title>
  <style>
    :root {
      --aiui-cyan: #22d3ee;
      --bg: #0b0d10;
      --panel: #11151a;
      --border: #1f2a35;
      --text: #e5edf3;
      --muted: #7a8a98;
      --danger: #ef4444;
    }
    * { box-sizing: border-box; }
    html, body { margin: 0; height: 100%; background: var(--bg); color: var(--text);
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 14px; }
    body { display: grid; grid-template-columns: 32% 1fr; grid-template-rows: 1fr; height: 100vh; }
    #chat { border-right: 1px solid var(--border); display: flex; flex-direction: column; }
    #chat header { padding: 14px 16px; border-bottom: 1px solid var(--border);
      letter-spacing: 0.05em; color: var(--muted); text-transform: uppercase; font-size: 11px; }
    #chat header b { color: var(--aiui-cyan); font-weight: 600; }
    #messages { flex: 1; overflow-y: auto; padding: 14px 16px; display: flex; flex-direction: column; gap: 12px; }
    .msg { line-height: 1.5; white-space: pre-wrap; }
    .msg.user { color: var(--text); }
    .msg.user::before { content: "› "; color: var(--aiui-cyan); }
    .msg.assistant { color: var(--muted); }
    .msg.assistant::before { content: "◇ "; color: var(--aiui-cyan); }
    .pill { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px;
      letter-spacing: 0.04em; text-transform: uppercase; margin-left: 8px; }
    .pill.thinking, .pill.applying { background: rgba(34, 211, 238, 0.15); color: var(--aiui-cyan); }
    .pill.done { background: rgba(34, 211, 238, 0.2); color: var(--aiui-cyan); }
    .pill.error { background: rgba(239, 68, 68, 0.2); color: var(--danger); }
    form { padding: 12px 16px; border-top: 1px solid var(--border); display: flex; gap: 8px; }
    textarea { flex: 1; background: var(--panel); border: 1px solid var(--border); color: var(--text);
      padding: 8px 10px; border-radius: 4px; resize: none; min-height: 40px; max-height: 120px;
      font-family: inherit; font-size: inherit; }
    button { background: var(--aiui-cyan); color: #00111a; border: 0; padding: 8px 14px;
      font-weight: 600; cursor: pointer; border-radius: 4px; }
    button:disabled { opacity: 0.5; cursor: not-allowed; }
    #preview { display: flex; flex-direction: column; }
    #preview header { padding: 14px 16px; border-bottom: 1px solid var(--border);
      letter-spacing: 0.05em; color: var(--muted); text-transform: uppercase; font-size: 11px; }
    #preview iframe { flex: 1; border: 0; background: #fff; }
  </style>
</head>
<body>
  <section id="chat">
    <header><b>◇ AIUI</b> · Visual edit · <span id="slug-display"></span></header>
    <div id="messages"></div>
    <form id="chat-form">
      <textarea id="prompt" placeholder="describe a change…" rows="1" autofocus></textarea>
      <button type="submit" id="send">Send</button>
    </form>
  </section>
  <section id="preview">
    <header>Live preview</header>
    <iframe id="preview-frame" src=""></iframe>
  </section>
  <script src="/tasks/static/visual-edit.js"></script>
</body>
</html>
```

- [ ] **Step 2: Open it locally in a browser to confirm it renders** (no Python test).
- [ ] **Step 3: Commit**

```
git add mcp-servers/tasks/static/visual-edit.html
git commit -m "feat(visual-edit): SPA layout shell — narrow chat + preview iframe"
```

#### Task 6.2: `visual-edit.js` — chat logic

**Files:**
- Create: `mcp-servers/tasks/static/visual-edit.js`

- [ ] **Step 1: Write the JS**

```javascript
// Visual editor SPA — chat + poll + iframe reload.
// Stateless w.r.t. the server: full conversation history sent on every POST.
(() => {
  "use strict";

  // --- URL parsing ---
  // Page is served at /tasks/edit/<slug>?token=<tok>
  const path = location.pathname.split("/");
  const slug = path[path.length - 1] || path[path.length - 2];
  const token = new URLSearchParams(location.search).get("token") || "";

  // --- DOM ---
  const $messages = document.getElementById("messages");
  const $form = document.getElementById("chat-form");
  const $prompt = document.getElementById("prompt");
  const $send = document.getElementById("send");
  const $frame = document.getElementById("preview-frame");
  const $slug = document.getElementById("slug-display");

  $slug.textContent = slug;
  $frame.src = `/tasks/preview-app/${encodeURIComponent(slug)}/?v=0`;

  // --- State (in-memory only) ---
  const history = []; // [{role: "user" | "assistant", content: string}]

  // --- Render helpers ---
  function appendMessage(role, text, pill) {
    const div = document.createElement("div");
    div.className = `msg ${role}`;
    div.textContent = text;
    if (pill) {
      const span = document.createElement("span");
      span.className = `pill ${pill.state}`;
      span.textContent = pill.label;
      div.appendChild(span);
    }
    $messages.appendChild(div);
    $messages.scrollTop = $messages.scrollHeight;
    return div;
  }

  function setPill(div, state, label) {
    let pill = div.querySelector(".pill");
    if (!pill) {
      pill = document.createElement("span");
      div.appendChild(pill);
    }
    pill.className = `pill ${state}`;
    pill.textContent = label;
  }

  // --- Chat submit ---
  $form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = $prompt.value.trim();
    if (!text) return;
    $prompt.value = "";
    $send.disabled = true;

    appendMessage("user", text);
    history.push({ role: "user", content: text });

    const assistantDiv = appendMessage("assistant", "", { state: "thinking", label: "thinking" });

    let buildId;
    try {
      const r = await fetch(`/tasks/edit/${encodeURIComponent(slug)}/chat?token=${encodeURIComponent(token)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: text, history }),
      });
      if (!r.ok) {
        if (r.status === 403) {
          setPill(assistantDiv, "error", "link expired");
        } else {
          setPill(assistantDiv, "error", `error ${r.status}`);
        }
        $send.disabled = false;
        return;
      }
      buildId = (await r.json()).build_id;
    } catch (err) {
      setPill(assistantDiv, "error", "network error");
      $send.disabled = false;
      return;
    }

    // --- Poll status ---
    const poll = async () => {
      try {
        const r = await fetch(`/tasks/edit/${encodeURIComponent(slug)}/chat/${buildId}/status?token=${encodeURIComponent(token)}`);
        if (!r.ok) {
          setPill(assistantDiv, "error", `lost build (${r.status})`);
          $send.disabled = false;
          return;
        }
        const job = await r.json();
        if (job.state === "thinking" || job.state === "applying") {
          setPill(assistantDiv, job.state, job.state);
          setTimeout(poll, 1000);
          return;
        }
        if (job.state === "done") {
          setPill(assistantDiv, "done", "done");
          assistantDiv.textContent = "Updated.";
          history.push({ role: "assistant", content: "Updated." });
          // Reload iframe with cache-bust.
          $frame.src = job.preview_url;
          $send.disabled = false;
          return;
        }
        if (job.state === "error") {
          const sum = (job.error && job.error.summary) || "Build failed";
          setPill(assistantDiv, "error", "error");
          assistantDiv.textContent = sum;
          history.push({ role: "assistant", content: sum });
          $send.disabled = false;
          return;
        }
        setTimeout(poll, 1000);
      } catch (err) {
        setPill(assistantDiv, "error", "network error");
        $send.disabled = false;
      }
    };
    setTimeout(poll, 500);
  });

  // Enter submits, Shift+Enter inserts newline.
  $prompt.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      $form.requestSubmit();
    }
  });
})();
```

- [ ] **Step 2: Verify the static mount already exists** — `mcp-servers/tasks/main.py:117` already does `app.mount("/tasks/static", StaticFiles(directory="static"), name="static")`. So `<script src="/tasks/static/visual-edit.js"></script>` resolves out of the box. No `main.py` change needed for serving the JS.

- [ ] **Step 3: Smoke test locally**: run the tasks service, open `http://localhost:8210/tasks/edit/some-existing-slug?token=<test-token>`, confirm chat shell renders and clicking Send hits the chat endpoint (check network tab).

- [ ] **Step 4: Commit**

```
git add mcp-servers/tasks/static/visual-edit.js
git commit -m "feat(visual-edit): SPA client — chat history, poll, iframe reload"
```

---

### Phase 7: Lifecycle integration test

#### Task 7.1: End-to-end test with mocked enhance

**Files:**
- Create: `mcp-servers/tasks/tests/test_visual_edit_lifecycle.py`

- [ ] **Step 1: Write the test**

```python
"""End-to-end visual-edit lifecycle with a mocked enhance pipeline:
  - POST chat → poll → done (preview_url with cache-bust)
  - POST chat with failing fake → error pill in chat history
  - POST chat with hanging fake → timeout → error
"""
import asyncio
import os
os.environ.setdefault("OAUTH_STATE_SECRET", "test-secret-123")
import sys
WEBHOOK_HANDLER = os.path.join(os.path.dirname(__file__), "..", "..", "..", "webhook-handler")
sys.path.insert(0, os.path.abspath(WEBHOOK_HANDLER))

from unittest.mock import patch, AsyncMock

import pytest
from fastapi.testclient import TestClient

from main import app
from handlers.visual_edit_token import sign_edit_token
from visual_edit_jobs import REGISTRY, JobState


@pytest.fixture
def client():
    REGISTRY._jobs.clear()
    return TestClient(app)


def _wait_for_terminal_state(client, slug, build_id, token, timeout=3.0):
    """Poll the status endpoint until the job hits done|error."""
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/tasks/edit/{slug}/chat/{build_id}/status?token={token}")
        body = r.json()
        if body["state"] in ("done", "error"):
            return body
        time.sleep(0.05)
    pytest.fail(f"job did not reach terminal state within {timeout}s")


def test_lifecycle_happy_path(client):
    """Mocked enhance succeeds → job goes done with the expected preview_url."""
    tok = sign_edit_token("my-slug", "ralph@example.com")
    fake = AsyncMock(return_value="ok")  # the EnhanceResult is opaque to the route
    with patch("routes_visual_edit.enhance_with_history", fake):
        r = client.post(
            f"/tasks/edit/my-slug/chat?token={tok}",
            json={"prompt": "make hero darker", "history": []},
        )
        build_id = r.json()["build_id"]
        body = _wait_for_terminal_state(client, "my-slug", build_id, tok)
    assert body["state"] == "done"
    assert body["preview_url"] == f"/tasks/preview-app/my-slug/?v={build_id}"
    # The enhance was called with the right args.
    fake.assert_awaited_once()
    kwargs = fake.call_args.kwargs
    assert kwargs["slug"] == "my-slug"
    assert kwargs["prompt"] == "make hero darker"
    assert kwargs["history"] == []
    assert kwargs["owner_email"] == "ralph@example.com"


def test_lifecycle_error_path(client):
    """Mocked enhance raises → job goes error with a friendly summary."""
    tok = sign_edit_token("my-slug", "ralph@example.com")
    fake = AsyncMock(side_effect=RuntimeError("LLM exploded"))
    with patch("routes_visual_edit.enhance_with_history", fake):
        r = client.post(
            f"/tasks/edit/my-slug/chat?token={tok}",
            json={"prompt": "x", "history": []},
        )
        build_id = r.json()["build_id"]
        body = _wait_for_terminal_state(client, "my-slug", build_id, tok)
    assert body["state"] == "error"
    assert "didn't apply" in body["error"]["summary"].lower() or \
           "apply" in body["error"]["summary"].lower()


def test_lifecycle_timeout(client, monkeypatch):
    """Mocked enhance hangs → after the (short) timeout the job goes error."""
    # Patch the timeout constant down so we don't actually wait 5 min.
    monkeypatch.setattr("routes_visual_edit._BUILD_TIMEOUT_SECONDS", 0.1)
    tok = sign_edit_token("my-slug", "ralph@example.com")

    async def hanging(**kwargs):
        await asyncio.sleep(5)  # exceeds the 0.1s timeout

    with patch("routes_visual_edit.enhance_with_history", side_effect=hanging):
        r = client.post(
            f"/tasks/edit/my-slug/chat?token={tok}",
            json={"prompt": "x", "history": []},
        )
        build_id = r.json()["build_id"]
        body = _wait_for_terminal_state(client, "my-slug", build_id, tok, timeout=2.0)
    assert body["state"] == "error"
    assert "long" in body["error"]["summary"].lower()
```

- [ ] **Step 2: Run — expect PASS** (3 tests).
- [ ] **Step 3: Run the full tasks test suite** to make sure nothing else regressed.

```
cd mcp-servers/tasks
python -m pytest tests/ -q
```

- [ ] **Step 4: Commit**

```
git add mcp-servers/tasks/tests/test_visual_edit_lifecycle.py
git commit -m "test(visual-edit): end-to-end lifecycle (happy / error / timeout)"
```

---

### Phase 8: Deploy

#### Task 8.1: Deploy webhook-handler changes

- [ ] **Step 1: SCP the changed files**

```
scp -i $env:USERPROFILE\.ssh\aiui_vps "webhook-handler/handlers/visual_edit_token.py" "webhook-handler/handlers/app_builder_panel.py" "webhook-handler/config.py" "webhook-handler/handlers/discord_commands.py" root@46.224.193.25:/tmp/
```

- [ ] **Step 2: Move into the container + restart**

```
ssh -i $env:USERPROFILE\.ssh\aiui_vps root@46.224.193.25 "
  docker cp /tmp/visual_edit_token.py webhook-handler:/app/handlers/visual_edit_token.py &&
  docker cp /tmp/app_builder_panel.py webhook-handler:/app/handlers/app_builder_panel.py &&
  docker cp /tmp/config.py webhook-handler:/app/config.py &&
  docker cp /tmp/discord_commands.py webhook-handler:/app/handlers/discord_commands.py &&
  docker restart webhook-handler &&
  sleep 5 &&
  docker logs webhook-handler --tail 30 2>&1 | grep -iE 'ready on port|error'
"
```

Expected: `Webhook handler ready on port 8086`, no errors.

#### Task 8.2: Deploy tasks service changes

- [ ] **Step 1: SCP**

```
scp -i $env:USERPROFILE\.ssh\aiui_vps `
  "mcp-servers/tasks/visual_edit_token.py" `
  "mcp-servers/tasks/visual_edit_jobs.py" `
  "mcp-servers/tasks/routes_visual_edit.py" `
  "mcp-servers/tasks/claude_executor.py" `
  "mcp-servers/tasks/main.py" `
  "mcp-servers/tasks/static/visual-edit.html" `
  "mcp-servers/tasks/static/visual-edit.js" `
  root@46.224.193.25:/tmp/
```

- [ ] **Step 2: `docker cp` each into the `tasks` container + restart**

```
ssh -i $env:USERPROFILE\.ssh\aiui_vps root@46.224.193.25 "
  docker cp /tmp/visual_edit_token.py tasks:/app/visual_edit_token.py &&
  docker cp /tmp/visual_edit_jobs.py tasks:/app/visual_edit_jobs.py &&
  docker cp /tmp/routes_visual_edit.py tasks:/app/routes_visual_edit.py &&
  docker cp /tmp/claude_executor.py tasks:/app/claude_executor.py &&
  docker cp /tmp/main.py tasks:/app/main.py &&
  docker cp /tmp/visual-edit.html tasks:/app/static/visual-edit.html &&
  docker cp /tmp/visual-edit.js tasks:/app/static/visual-edit.js &&
  docker restart tasks &&
  sleep 5 &&
  docker logs tasks --tail 30 2>&1 | grep -iE 'application startup complete|error'
"
```

Expected: clean boot.

#### Task 8.3: Smoke test in Discord

- [ ] **Step 1: Build a new app via Discord** to get a fresh "Build ready" card.
- [ ] **Step 2: Confirm the 4th button "Visual edit" is present** on the card.
- [ ] **Step 3: Click it** — should open a new tab to `https://ai-ui.coolestdomain.win/tasks/edit/<slug>?token=...`.
- [ ] **Step 4: Verify the layout** — narrow chat on the left, preview iframe of the app on the right.
- [ ] **Step 5: Type a change** ("make the hero darker"), submit. Watch for `thinking → applying → done` pill transitions. Confirm the iframe refreshes and reflects the change.
- [ ] **Step 6: Try a follow-up** ("now make the buttons match") — confirm the LLM still has context (the regenerate keeps the darker hero).
- [ ] **Step 7: Try a bad-prompt error** ("dlskfjlksdjf adfsasd") — verify the chat shows a red pill with a sane error summary and the preview stays unchanged.
- [ ] **Step 8: Wait 31 min, then click the same Visual edit button again** — the OLD link should now show the expired-link error page (testing TTL).

If anything fails, capture the failure mode and add a fix-up commit.

---

## Done criteria

- All new tests green (~25 new test cases).
- Full webhook-handler suite + full tasks suite green (no regressions).
- `Visual edit` button live on every new Build-ready card.
- A real chat turn updates the preview iframe within 60s.
- Conversation context across turns survives within a session.
- 403 errors are surfaced to the user as actionable text, not silent failures.

## Out of scope (do NOT add to this plan)

The following are explicitly v2:
- Click-to-select visual element picker
- SSE / streaming LLM tokens
- Persistent conversation history (per slug + owner, in postgres)
- A "send updated preview to Discord" button
- Multi-tab collaboration / locking
- Playwright SPA tests
- Direct manipulation editor (drag, color picker, inline text)
