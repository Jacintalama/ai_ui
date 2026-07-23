# Draft a new email via chat (Gmail) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an Open WebUI user ask the assistant, in chat, to draft a brand-new email, and have that draft appear in the user's own Gmail Drafts folder (never sent).

**Architecture:** Extend the existing Gmail MCP server with one new endpoint, `gmail_create_draft`. The MIME build is extracted into a stdlib-only helper (`draft_builder.py`) so it can be unit-tested offline. The endpoint reuses the server's existing per-user token lookup (`get_valid_token`), Gmail HTTP helper (`gmail_request`), and not-connected message. mcp-proxy already exposes the Gmail server to Open WebUI via OpenAPI and forwards the logged-in user's identity, so the new endpoint is picked up and identity-scoped automatically.

**Tech Stack:** Python, FastAPI, httpx, pydantic, stdlib `email` + `base64`, pytest. Runs in the `mcp-gmail` Docker container.

## Global Constraints

- Draft only. The AI never sends. (verbatim decision)
- New drafts only. Do NOT touch the existing `gmail_create_draft_reply` endpoint. (verbatim decision)
- Do NOT change Fusion, the free-model routing, or the Auto pipes.
- NEVER touch, overwrite, or commit `.env`.
- NEVER deploy local `mcp-servers/tasks/templates.py`.
- Type hints on all new function signatures. Use `httpx` and `async` for I/O (already the server's style).
- No secrets in source or commits. Never log or return the OAuth token.
- Commit messages: attribute to Ralph only. No AI co-author line. No em-dashes anywhere.
- Deploy per CLAUDE.md: commit first, push changed files to the VPS (one `scp` per file, never `scp -r`), rebuild the affected service, then run the live smoke.

---

### Task 1: Pure draft-builder helper + offline unit tests

Extract the MIME-to-raw build into a small, dependency-free module so its logic is testable without the FastAPI app (which raises at import unless `AIUI_FERNET_KEY` is set) and without network.

**Files:**
- Create: `mcp-servers/gmail/draft_builder.py`
- Create: `mcp-servers/gmail/tests/__init__.py` (empty)
- Test: `mcp-servers/gmail/tests/test_draft_builder.py`

**Interfaces:**
- Consumes: nothing (stdlib only).
- Produces: `build_draft_raw(to: str, subject: str, body: str, cc: str | None = None, bcc: str | None = None) -> str` returning a base64url-encoded MIME message string. Raises `ValueError` if `to` is empty/blank.

- [ ] **Step 1: Write the failing test**

Create `mcp-servers/gmail/tests/__init__.py` (empty file).

Create `mcp-servers/gmail/tests/test_draft_builder.py`:

```python
"""Offline unit tests for the Gmail draft MIME builder. No network, no env."""
import base64
import importlib.util
import pathlib
from email import message_from_bytes

import pytest

BUILDER_PATH = pathlib.Path(__file__).resolve().parents[1] / "draft_builder.py"


def _load():
    spec = importlib.util.spec_from_file_location("draft_builder", BUILDER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def mod():
    return _load()


def _decode(raw: str):
    # Gmail uses base64url; email libs need standard padding handling.
    return message_from_bytes(base64.urlsafe_b64decode(raw))


def test_builds_headers_and_body(mod):
    raw = mod.build_draft_raw("a@b.com", "Hi there", "Hello body")
    msg = _decode(raw)
    assert msg["To"] == "a@b.com"
    assert msg["Subject"] == "Hi there"
    assert "Hello body" in msg.get_payload(decode=True).decode("utf-8")


def test_includes_cc_and_bcc_when_given(mod):
    raw = mod.build_draft_raw("a@b.com", "s", "b", cc="c@d.com", bcc="e@f.com")
    msg = _decode(raw)
    assert msg["Cc"] == "c@d.com"
    assert msg["Bcc"] == "e@f.com"


def test_omits_cc_bcc_when_absent(mod):
    raw = mod.build_draft_raw("a@b.com", "s", "b")
    msg = _decode(raw)
    assert msg["Cc"] is None
    assert msg["Bcc"] is None


def test_empty_recipient_raises(mod):
    with pytest.raises(ValueError):
        mod.build_draft_raw("   ", "s", "b")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd mcp-servers/gmail && python -m pytest tests/test_draft_builder.py -v`
Expected: FAIL (module `draft_builder` / `build_draft_raw` does not exist yet).

- [ ] **Step 3: Write minimal implementation**

Create `mcp-servers/gmail/draft_builder.py`:

```python
"""Build a Gmail draft's base64url-encoded raw MIME message.

Stdlib only (email + base64) so it stays importable and testable without the
FastAPI app, the Fernet key, or network access.
"""
import base64
from email.mime.text import MIMEText


def build_draft_raw(
    to: str,
    subject: str,
    body: str,
    cc: str | None = None,
    bcc: str | None = None,
) -> str:
    """Return a base64url-encoded MIME message for a new (non-reply) draft.

    Raises ValueError if `to` is missing so a bad tool call fails loudly
    instead of creating a draft with no recipient.
    """
    if not to or not to.strip():
        raise ValueError("recipient (to) is required")
    msg = MIMEText(body or "", "plain")
    msg["To"] = to
    msg["Subject"] = subject or ""
    if cc:
        msg["Cc"] = cc
    if bcc:
        msg["Bcc"] = bcc
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd mcp-servers/gmail && python -m pytest tests/test_draft_builder.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/gmail/draft_builder.py mcp-servers/gmail/tests/__init__.py mcp-servers/gmail/tests/test_draft_builder.py
git commit -m "feat(gmail): add stdlib draft MIME builder with offline tests"
```

---

### Task 2: `gmail_create_draft` endpoint + input model

Add the new endpoint to the Gmail MCP server, wired to the helper from Task 1 and the server's existing token/HTTP helpers. Verified offline with a mocked TestClient (no network, dummy Fernet key).

**Files:**
- Modify: `mcp-servers/gmail/main.py` (add `CreateDraftInput` after `CreateDraftReplyInput` near line 389; add endpoint after `create_draft_reply`, near line 623)
- Test: `mcp-servers/gmail/tests/test_create_draft_endpoint.py`

**Interfaces:**
- Consumes: `build_draft_raw(...)` from Task 1; existing `get_user_email(request)`, `get_valid_token(user_email)`, `gmail_request(access_token, path, method=, json_body=)`, `NOT_CONNECTED_MSG`, `OAUTH_REDIRECT_URI` in `main.py`.
- Produces: `POST /gmail_create_draft` (operation_id `gmail_create_draft`) returning `{"success": True, "draft_id": str, "message": str}` on success, or `{"error": str}` when not connected.

- [ ] **Step 1: Write the failing test**

Create `mcp-servers/gmail/tests/test_create_draft_endpoint.py`:

```python
"""Offline endpoint test: not-connected path and drafts payload shape.
Sets a dummy Fernet key so main.py imports, and monkeypatches the token
lookup + Gmail HTTP call so no network is used."""
import os
import base64

import pytest
from fastapi.testclient import TestClient

# crypto_utils raises at import unless this is set. Dummy key, never used here.
os.environ.setdefault(
    "AIUI_FERNET_KEY",
    base64.urlsafe_b64encode(b"0" * 32).decode(),
)

import importlib.util
import pathlib

MAIN_PATH = pathlib.Path(__file__).resolve().parents[1] / "main.py"


def _load_main():
    spec = importlib.util.spec_from_file_location("gmail_main", MAIN_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def main():
    return _load_main()


def test_not_connected_returns_clear_error(main, monkeypatch):
    async def fake_token(_email):
        return None
    monkeypatch.setattr(main, "get_valid_token", fake_token)
    client = TestClient(main.app)
    r = client.post("/gmail_create_draft",
                    json={"to": "a@b.com", "subject": "s", "body": "b"},
                    headers={"X-User-Email": "u@x.com"})
    assert r.status_code == 200
    assert "error" in r.json()


def test_creates_draft_with_message_raw_payload(main, monkeypatch):
    captured = {}

    async def fake_token(_email):
        return "tok"

    async def fake_request(access_token, path, params=None, method="GET", json_body=None):
        captured["path"] = path
        captured["method"] = method
        captured["json_body"] = json_body
        return {"id": "draft123", "message": {"id": "msg1"}}

    monkeypatch.setattr(main, "get_valid_token", fake_token)
    monkeypatch.setattr(main, "gmail_request", fake_request)
    client = TestClient(main.app)
    r = client.post("/gmail_create_draft",
                    json={"to": "a@b.com", "subject": "Hi", "body": "Body"},
                    headers={"X-User-Email": "u@x.com"})
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True
    assert data["draft_id"] == "draft123"
    assert captured["path"] == "users/me/drafts"
    assert captured["method"] == "POST"
    # New drafts have no threadId; payload wraps a raw message.
    assert "raw" in captured["json_body"]["message"]
    assert "threadId" not in captured["json_body"]["message"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd mcp-servers/gmail && python -m pytest tests/test_create_draft_endpoint.py -v`
Expected: FAIL with 404 (route `/gmail_create_draft` not defined yet).

- [ ] **Step 3: Add the input model**

In `mcp-servers/gmail/main.py`, immediately after the `CreateDraftReplyInput` class (ends near line 389), add:

```python
class CreateDraftInput(BaseModel):
    to: str = Field(description="Recipient email address")
    subject: str = Field(description="Email subject")
    body: str = Field(description="Draft body text (plain text)")
    cc: Optional[str] = Field(default=None, description="CC recipients (comma-separated)")
    bcc: Optional[str] = Field(default=None, description="BCC recipients (comma-separated)")
```

- [ ] **Step 4: Add the import and the endpoint**

At the top of `mcp-servers/gmail/main.py`, in the local imports block (near line 15, beside `import crypto_utils`), add:

```python
from draft_builder import build_draft_raw
```

In `mcp-servers/gmail/main.py`, immediately after the `create_draft_reply` function (ends near line 623), add:

```python
@app.post("/gmail_create_draft", operation_id="gmail_create_draft", summary="Create a new draft email in Gmail")
async def create_draft(input: CreateDraftInput, request: Request):
    """Create a brand-new draft email (not a reply). Use this when the user asks to draft, compose, or write a new email to someone. The draft is saved in the user's Gmail Drafts folder and is NEVER sent; the user reviews and sends it themselves."""
    user_email = get_user_email(request)
    access_token = await get_valid_token(user_email)
    if not access_token:
        base = OAUTH_REDIRECT_URI.rsplit("/auth/", 1)[0]
        return {"error": NOT_CONNECTED_MSG.format(base_url=base, email=user_email)}

    try:
        raw = build_draft_raw(input.to, input.subject, input.body, input.cc, input.bcc)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    draft_body = {"message": {"raw": raw}}
    result = await gmail_request(access_token, "users/me/drafts", method="POST", json_body=draft_body)

    return {
        "success": True,
        "draft_id": result.get("id", ""),
        "to": input.to,
        "subject": input.subject,
        "message": "Draft created. Open Gmail to review and send it.",
    }
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd mcp-servers/gmail && python -m pytest tests/ -v`
Expected: PASS (all tests from Task 1 and Task 2).

- [ ] **Step 6: Commit**

```bash
git add mcp-servers/gmail/main.py mcp-servers/gmail/tests/test_create_draft_endpoint.py
git commit -m "feat(gmail): add gmail_create_draft endpoint for new-email drafts via chat"
```

---

### Task 3: Deploy to VPS, verify identity + live smoke

Ship the new endpoint and confirm end-to-end that a logged-in Open WebUI user, on a tool-capable model, can create a draft that lands in their own Gmail Drafts. This task has no unit test; its deliverable is a verified live smoke.

**Files:**
- No code changes (deploy + verification only). If the smoke reveals a broken identity or connect flow, stop and open a follow-up per "Known risks" in the spec; do not patch blindly here.

**Interfaces:**
- Consumes: the committed `main.py`, `draft_builder.py` from Tasks 1 and 2.
- Produces: a verified working `gmail_create_draft` in production.

- [ ] **Step 1: Confirm working tree is clean and pushed**

Run: `git status --short` (expected: no changes to tracked files under `mcp-servers/gmail/`).
Run: `git log --oneline -3` to confirm the Task 1 and Task 2 commits are present.

- [ ] **Step 2: Push the two changed files to the VPS (one scp each, never scp -r)**

```bash
scp -i ~/.ssh/aiui_vps -o IdentitiesOnly=yes mcp-servers/gmail/draft_builder.py root@46.224.193.25:/root/proxy-server/mcp-servers/gmail/draft_builder.py
scp -i ~/.ssh/aiui_vps -o IdentitiesOnly=yes mcp-servers/gmail/main.py root@46.224.193.25:/root/proxy-server/mcp-servers/gmail/main.py
```

- [ ] **Step 3: Rebuild the mcp-gmail service**

```bash
ssh -i ~/.ssh/aiui_vps -o IdentitiesOnly=yes root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --build mcp-gmail"
```
Expected: `mcp-gmail` rebuilds and reports healthy / `Up`.

- [ ] **Step 4: Confirm the new tool appears in the proxy's OpenAPI**

```bash
ssh -i ~/.ssh/aiui_vps -o IdentitiesOnly=yes root@46.224.193.25 "docker exec mcp-proxy sh -c 'curl -fsS http://localhost:8000/openapi.json' | grep -o gmail_create_draft | head -1"
```
Expected: prints `gmail_create_draft`. If empty, mcp-proxy may need a restart to re-aggregate: `docker compose -f docker-compose.unified.yml restart mcp-proxy`, then re-check.

- [ ] **Step 5: Verify identity path is live (not-connected returns cleanly per user)**

Sanity-check the endpoint is reachable and identity-scoped by calling it directly through the container with a test user header (expect the clean not-connected error, NOT a 500):

```bash
ssh -i ~/.ssh/aiui_vps -o IdentitiesOnly=yes root@46.224.193.25 "docker exec mcp-gmail sh -c 'curl -s -X POST http://localhost:8000/gmail_create_draft -H \"Content-Type: application/json\" -H \"X-User-Email: nobody@nowhere.test\" -d \"{\\\"to\\\":\\\"a@b.com\\\",\\\"subject\\\":\\\"s\\\",\\\"body\\\":\\\"b\\\"}\"'"
```
Expected: JSON containing an `error` with the connect instructions (proves the endpoint runs and is per-user token scoped).

- [ ] **Step 6: Live smoke in Open WebUI (go/no-go)**

In the Open WebUI browser UI, with a Gmail-connected account and a tool-capable (paid) model selected (e.g. GPT-5.5, tools enabled), send:

> draft an email to <your own address> with subject "AIUI test" saying hello

Expected: the assistant reports the draft was created, and a matching draft appears in that account's Gmail Drafts folder. Nothing is sent.

- [ ] **Step 7: Record the result**

If the smoke passes: note it (and update memory: the chat-agent roadmap email item is now shipped). If it fails at connect (OAuth) or identity, stop and open a follow-up referencing the spec's "Known risks"; do not improvise a fix in this task.

---

## Notes for the implementer

- The Gmail server's other tools already read `X-User-Email` and use `get_valid_token`; the new endpoint follows the exact same pattern, so if `gmail_list_emails` works for a user today, drafts will too.
- Free / non-tool-calling models will simply never call this tool. That is expected. Email via chat requires a tool-capable model.
- Do not enable sending and do not touch `gmail_create_draft_reply`.
