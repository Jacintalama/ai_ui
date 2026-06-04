# Visual Editor deep link — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the bots' "Enhance" button with a "🎨 Visual Editor" deep link that opens the existing web editor (`preview.html`) scoped to the user's app, authenticated by a least-privilege capability — no web login required.

**Architecture:** A signed edit token (already exists) → a new tasks route `GET /tasks/edit/{slug}` verifies it, mints a single-task capability, and serves `preview.html` with that capability JSON-injected. The editor's API calls send the capability via `X-Edit-Capability`; editor endpoints accept it as a least-privilege replacement for `current_admin`, scoped to exactly one task. Bots just render a link button.

**Tech Stack:** Python (FastAPI tasks service, webhook-handler bots), pytest, HMAC over `OAUTH_STATE_SECRET`, vanilla JS (`preview.html`).

**Spec:** `docs/superpowers/specs/2026-06-04-visual-editor-deeplink-design.md`

**Constraint:** Build + test locally only. **Do NOT deploy** until the user says so (deploy order when approved: tasks service, then webhook-handler).

---

## File Structure

- Create `mcp-servers/tasks/edit_capability.py` — mint/verify single-task capability (HMAC, `edit_cap:` domain).
- Create `mcp-servers/tasks/tests/test_edit_capability.py`.
- Modify `mcp-servers/tasks/visual_edit_token.py` — add `edit_tok:` domain prefix (verify side).
- Modify `webhook-handler/handlers/visual_edit_token.py` — add `edit_tok:` domain prefix (sign side). Keep in lockstep.
- Modify `mcp-servers/tasks/main.py` (or the appropriate routes file) — add `GET /tasks/edit/{slug}`.
- Create `mcp-servers/tasks/tests/test_edit_route.py`.
- Modify `mcp-servers/tasks/routes_execution.py` — alt-auth dependency (`X-Edit-Capability` replaces `current_admin`, task-scoped); harden `cancel`.
- Modify `mcp-servers/tasks/tests/test_routes_execution*.py` (or add `test_edit_capability_auth.py`).
- Modify `mcp-servers/tasks/static/preview.html` — read injected edit context, send `X-Edit-Capability`.
- Modify `webhook-handler/handlers/app_builder_panel.py` + `slack_app_builder_panel.py` — Enhance → Visual Editor link; remove enhance modal/buttons.
- Modify `webhook-handler/handlers/discord_commands.py` + `slack_interactions.py` — drop enhance routing; remove dead `run_panel_enhance`/`enhance_app` (confirmed no other callers).

---

## Phase 1 — Capability module (pure, TDD)

### Task 1: `edit_capability.py`

**Files:**
- Create: `mcp-servers/tasks/edit_capability.py`
- Test: `mcp-servers/tasks/tests/test_edit_capability.py`

- [ ] **Step 1: Write failing tests**

```python
import importlib, os
def _mod(monkeypatch, secret="s3cr3t"):
    monkeypatch.setenv("OAUTH_STATE_SECRET", secret)
    import edit_capability; importlib.reload(edit_capability)
    return edit_capability

def test_roundtrip(monkeypatch):
    m = _mod(monkeypatch)
    cap = m.mint_capability("u@x.com", "my-app", "task-123", ttl=1800)
    got = m.verify_capability(cap)
    assert got == {"owner": "u@x.com", "slug": "my-app", "task_id": "task-123"}

def test_expired(monkeypatch):
    m = _mod(monkeypatch)
    cap = m.mint_capability("u@x.com", "my-app", "task-123", ttl=-1)
    assert m.verify_capability(cap) is None

def test_tampered(monkeypatch):
    m = _mod(monkeypatch)
    cap = m.mint_capability("u@x.com", "my-app", "task-123")
    assert m.verify_capability(cap[:-2] + ("AA" if not cap.endswith("AA") else "BB")) is None

def test_wrong_secret_rejects(monkeypatch):
    m = _mod(monkeypatch); cap = m.mint_capability("u@x.com", "a", "t")
    m2 = _mod(monkeypatch, secret="different"); assert m2.verify_capability(cap) is None

def test_no_secret_returns_none(monkeypatch):
    monkeypatch.setenv("OAUTH_STATE_SECRET", "")
    import edit_capability, importlib; importlib.reload(edit_capability)
    assert edit_capability.verify_capability("anything") is None

def test_not_confusable_with_edit_token(monkeypatch):
    # An edit_tok-domain string must NOT verify as a capability.
    m = _mod(monkeypatch)
    import hmac, hashlib, base64
    payload = b'{"owner":"u","slug":"a","task_id":"t","exp":9999999999}'
    sig = hmac.new(b"s3cr3t", b"edit_tok:" + payload, hashlib.sha256).digest()
    b = lambda x: base64.urlsafe_b64encode(x).decode().rstrip("=")
    assert m.verify_capability(b(payload) + "." + b(sig)) is None
```

- [ ] **Step 2: Run, expect fail** — `cd mcp-servers/tasks && python -m pytest tests/test_edit_capability.py -q` → FAIL (no module).

- [ ] **Step 3: Implement**

```python
"""Single-task edit capability: HMAC over OAUTH_STATE_SECRET with an explicit
`edit_cap:` domain prefix so it can never be confused with edit tokens or
oauth_state tokens that share the same secret. Least privilege: authorizes edit
actions on exactly one task_id for one owner, short TTL."""
import base64, hashlib, hmac, json, os, time

_SECRET = os.environ.get("OAUTH_STATE_SECRET", "").encode()
EDIT_CAP_TTL_SECONDS = int(os.environ.get("EDIT_CAP_TTL_SECONDS", "1800"))
_DOMAIN = b"edit_cap:"

def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")

def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))

def mint_capability(owner: str, slug: str, task_id: str,
                    ttl: int = EDIT_CAP_TTL_SECONDS) -> str:
    if not _SECRET:
        raise RuntimeError("OAUTH_STATE_SECRET not set")
    payload = json.dumps(
        {"owner": owner, "slug": slug, "task_id": str(task_id),
         "exp": int(time.time()) + ttl},
        separators=(",", ":"), sort_keys=True).encode()
    sig = hmac.new(_SECRET, _DOMAIN + payload, hashlib.sha256).digest()
    return _b64(payload) + "." + _b64(sig)

def verify_capability(cap: str) -> dict | None:
    if not _SECRET:
        return None
    parts = (cap or "").split(".")
    if len(parts) != 2:
        return None
    try:
        payload, sig = _unb64(parts[0]), _unb64(parts[1])
    except Exception:
        return None
    if not hmac.compare_digest(
            sig, hmac.new(_SECRET, _DOMAIN + payload, hashlib.sha256).digest()):
        return None
    try:
        data = json.loads(payload)
    except Exception:
        return None
    if not isinstance(data, dict) or not all(
            k in data for k in ("owner", "slug", "task_id", "exp")):
        return None
    try:
        if int(time.time()) >= int(data["exp"]):
            return None
    except (TypeError, ValueError):
        return None
    return {"owner": data["owner"], "slug": data["slug"],
            "task_id": str(data["task_id"])}
```

- [ ] **Step 4: Run, expect pass.**
- [ ] **Step 5: Commit** — `git commit -m "feat(tasks): single-task edit capability (HMAC, edit_cap domain)"`

---

## Phase 2 — Domain-separate the existing edit token (MF-1)

> Both sides change together; this invalidates in-flight edit tokens (≤30 min) — acceptable. Deploy tasks + webhook-handler together when shipping.

### Task 2: add `edit_tok:` prefix to edit-token HMAC

**Files:**
- Modify: `mcp-servers/tasks/visual_edit_token.py` (verify side)
- Modify: `webhook-handler/handlers/visual_edit_token.py` (sign side)
- Test: existing `**/test_visual_edit_token.py` (both)

- [ ] **Step 1:** Update each test's expected HMAC input to `f"edit_tok:{owner}:{ts}:{slug}"`; run → FAIL.
- [ ] **Step 2:** In both files change the HMAC message from `f"{owner}:{ts}:{slug}"` to `f"edit_tok:{owner}:{ts}:{slug}"` (sign and verify). Add a cross-check test: a token signed without the prefix no longer verifies.
- [ ] **Step 3:** Run both test files → PASS.
- [ ] **Step 4: Commit** — `git commit -m "fix(security): domain-separate visual edit tokens (edit_tok prefix)"`

---

## Phase 3 — `GET /tasks/edit/{slug}` route

### Task 3: serve the editor in edit mode

**Files:**
- Modify: `mcp-servers/tasks/main.py` (near the existing `/tasks/preview-app/{slug}` routes)
- Test: `mcp-servers/tasks/tests/test_edit_route.py`

Implementation discovery during this task: locate the slug→task lookup used by
`_require_role` (it keys off `TaskItem.built_app_slug`); reuse it to resolve the
task id and confirm `owner` owns it.

- [ ] **Step 1: Write failing tests** (use `ASGITransport`/`AsyncClient` like `test_schedule_result_endpoint.py`):
  - valid token → 200, body contains the resolved `task_id` and a capability seed; `Cache-Control: no-store`.
  - invalid/expired token → 403.
  - token valid but `slug` not owned by `owner` → 403/404.
  - injected values are JSON-encoded (assert the seed uses `JSON.parse`/quoted JSON, not raw interpolation).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3: Implement** route:

```python
@app.get("/tasks/edit/{slug}", include_in_schema=False)
async def tasks_edit(slug: str, token: str = ""):
    from visual_edit_token import verify_edit_token
    from edit_capability import mint_capability
    owner = verify_edit_token(token, slug)
    if not owner:
        raise HTTPException(status_code=403, detail="Invalid or expired edit link")
    task_id = await _resolve_task_id_for_owner(slug, owner)   # ownership-checked
    if not task_id:
        raise HTTPException(status_code=403, detail="App not found for this user")
    cap = mint_capability(owner, slug, str(task_id))
    html = _render_preview_edit_mode(task_id=str(task_id), cap=cap)  # JSON-encodes
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})
```

`_render_preview_edit_mode` reads `static/preview.html` and injects, before
`</head>`, a JSON-encoded seed (MF-5):

```python
seed = "<script>window.__EDIT_CTX__ = " + json.dumps(
    {"task_id": task_id, "cap": cap}) + ";</script>"
```

- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(tasks): GET /tasks/edit/{slug} serves editor with scoped capability"`

---

## Phase 4 — Editor endpoints accept the capability (least privilege)

### Task 4: capability auth dependency + per-endpoint task match

**Files:**
- Modify: `mcp-servers/tasks/routes_execution.py` (execute, answer, cancel, start_clarify, start_plan, review_plan, resume, task GET)
- Test: `mcp-servers/tasks/tests/test_edit_capability_auth.py`

- [ ] **Step 1: Write failing tests:**
  - capability for task A on `POST /{A}/execute` → authorized (200/expected), with NO admin headers.
  - same capability on `POST /{B}/execute` (different id) → 403.
  - expired capability → 403.
  - no capability + no admin headers → 401/403 (unchanged).
  - admin-header path still works unchanged.
  - `cancel`: capability for A cannot cancel B; admin path now also ownership-checked.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3: Implement** a dependency that **replaces** `current_admin` when `X-Edit-Capability` is present and valid:

```python
async def current_user_or_capability(task_id: UUID, request: Request):
    cap_hdr = request.headers.get("X-Edit-Capability", "")
    if cap_hdr:
        from edit_capability import verify_capability
        data = verify_capability(cap_hdr)
        if not data or data["task_id"] != str(task_id):
            raise HTTPException(status_code=403, detail="Invalid edit capability")
        # least-privilege principal scoped to this one task
        return _CapabilityPrincipal(email=data["owner"], slug=data["slug"],
                                    task_id=str(task_id))
    return await current_admin(request)   # unchanged web path
```

For each editor endpoint: swap `Depends(current_admin)` → `Depends(current_user_or_capability)`. When the principal is a capability, **skip** `_require_role` (the capability already binds owner+task); when it's an admin user, keep `_require_role("editor")`. Harden `cancel` so the admin path also verifies task ownership.

- [ ] **Step 4:** Run → PASS, plus full tasks suite green.
- [ ] **Step 5: Commit** — `git commit -m "feat(tasks): editor endpoints accept task-scoped edit capability"`

---

## Phase 5 — preview.html edit mode

### Task 5: use injected context + send capability header

**Files:** Modify `mcp-servers/tasks/static/preview.html`

- [ ] **Step 1:** In the bootstrap, if `window.__EDIT_CTX__` exists, set `taskId = __EDIT_CTX__.task_id` and store the capability.
- [ ] **Step 2:** In `apiFetch`, if a capability is present, add header `X-Edit-Capability: <cap>` (in addition to / instead of the `Authorization` bearer). On `401/403`, show "this edit session expired — reopen Visual Editor from the bot".
- [ ] **Step 3:** Manual smoke (local): load `/tasks/edit/<slug>?token=<minted>`; Select an element, Send, confirm `/{taskId}/execute` is called with the header (browser devtools) and the edit applies.
- [ ] **Step 4: Commit** — `git commit -m "feat(editor): preview.html edit mode via injected capability"`

---

## Phase 6 — Bots: Enhance → Visual Editor

### Task 6: Discord

**Files:** Modify `webhook-handler/handlers/app_builder_panel.py`, `discord_commands.py`; tests in `webhook-handler/tests/`.

- [ ] **Step 1:** Update builder tests: `build_ready_attachment`/`build_published_attachment`/apps-list render a **link** button labeled "🎨 Visual Editor" with url `…/tasks/edit/{slug}?token=…` (use `sign_edit_token`), and no longer emit `ENHANCE_PREFIX`. Run → FAIL.
- [ ] **Step 2:** Implement: replace the Enhance buttons with link buttons (`STYLE_LINK` + url via `sign_edit_token(slug, owner)`); the builders that need `owner` already receive it (others get it threaded in). Remove `is_enhance_button` routing + the enhance-modal open in `_handle_message_component`.
- [ ] **Step 3:** Run webhook-handler suite → PASS.
- [ ] **Step 4: Commit** — `git commit -m "feat(discord): Visual Editor link replaces Enhance"`

### Task 7: Slack

**Files:** Modify `webhook-handler/handlers/slack_app_builder_panel.py`, `slack_interactions.py`; tests.

- [ ] **Step 1:** Update tests: apps-list/ready/published render a `_link_button("🎨 Visual Editor", url)`; remove `ENHANCE_PREFIX` from the action loop and the `is_enhance_modal` submit branch. Run → FAIL.
- [ ] **Step 2:** Implement the swap + routing removal.
- [ ] **Step 3:** Run suite → PASS.
- [ ] **Step 4: Commit** — `git commit -m "feat(slack): Visual Editor link replaces Enhance"`

### Task 8: remove dead enhance path

**Files:** `webhook-handler/handlers/commands.py` (`run_panel_enhance`, `_format_enhance_error`), tasks client `enhance_app`, related tests.

- [ ] **Step 1:** Grep to re-confirm zero remaining callers of `run_panel_enhance`/`enhance_app`.
- [ ] **Step 2:** Remove them + their tests (or keep if any caller surfaced; document).
- [ ] **Step 3:** Full webhook-handler suite → PASS.
- [ ] **Step 4: Commit** — `git commit -m "chore: remove orphaned enhance handler"`

---

## Phase 7 — Verify (no deploy)

- [ ] Full suites green: `mcp-servers/tasks` and `webhook-handler`.
- [ ] Manual local smoke of the edit deep link (Phase 5 Step 3).
- [ ] Security spot-check: capability for task A rejected on task B; expired token → 403; missing `OAUTH_STATE_SECRET` → fail closed.
- [ ] Stop. Report to user with a deploy checklist (tasks first, then webhook-handler). **Do not deploy until told.**

---

## Notes
- DRY/YAGNI/TDD, frequent commits.
- Keep `edit_capability.py` and both `visual_edit_token.py` files in lockstep on the secret + domain prefixes.
- Branch: `feat/visual-editor-deeplink` (spec already committed here).
