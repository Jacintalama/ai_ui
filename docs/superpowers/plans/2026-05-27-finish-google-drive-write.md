# Finish Google Drive (read-verify + write/upload) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a scheduled agent create files in the owner's Google Drive (default: a native Google Doc) behind an hourly write cap, and verify Drive read+write works end-to-end.

**Architecture:** Add a `POST /gdrive_create_file` endpoint to the existing `mcp-gdrive` REST service (owner-scoped via `x-user-email`), broaden the OAuth scope to `drive.readonly drive.file`, guard writes with an in-process rolling rate cap, and point the scheduler's connector access-note at the new endpoint. The on-host scheduled agent calls it over the existing host-local port `127.0.0.1:8017`.

**Tech Stack:** Python, FastAPI, httpx (multipart/related upload), pydantic, pytest + `fastapi.testclient.TestClient`. Spec: `docs/superpowers/specs/2026-05-27-finish-google-drive-write-design.md`.

---

## Working environment & git workflow (READ FIRST)

- **Develop + TDD locally** on Windows for the **gdrive** service:
  `cd "mcp-servers/gdrive" && python -m pytest tests/ -v`. The `gdrive` tests set fake env vars at the top of each test file (`AIUI_FERNET_KEY`, `OAUTH_STATE_SECRET`, `GOOGLE_CLIENT_ID/SECRET`) — copy that preamble into the new test file. (Verified: the gdrive suite imports and runs clean locally — fastapi/httpx/pydantic/cryptography are installed.)
- **The `mcp-servers/tasks` suite does NOT run locally** and we deliberately add no tasks unit test here: its `tests/conftest.py` reads `os.environ["DATABASE_URL"]` at import time (KeyError without it) and `scheduler.py` imports `croniter` (not installed locally). The only tasks-side change in this plan is a one-line constant edit whose behavior is verified end-to-end in Task 6 — see Task 5.
- **Line endings:** `mcp-servers/gdrive/main.py`, `mcp-servers/tasks/scheduler.py` are stored **CRLF** in both local and VPS git. The `Edit` tool preserves CRLF when `old_string` is copied exactly. Do **not** rewrite whole files (that flips endings and churns the diff — see the thread-fix incident).
- **Deploy + commit (Task 6 only):** the live system is the VPS (`reference_vps_connection.md`). Re-apply the additive edits to the VPS copies (they're additive, so the same `Edit`/patch applies), `docker cp` into the `mcp-gdrive` and `tasks` containers, restart. Commit on branch `vps-snapshot-2026-05-27` (clean CRLF diff) authored as `thunder500 <ralphbenitez30@gmail.com>` (NO AI attribution), then relay-push per `reference_git_push_relay_and_crlf.md`. Do **not** commit to the local feat branch (committing these files locally drags in the large uncommitted working-tree feature diff).
- **TDD per task; deploy/commit batched in Task 6** (relay round-trips make per-step VPS commits impractical; locally we still go red→green→commit-intent per task and land them together on the VPS).

## File structure

| File | Responsibility | Action |
|---|---|---|
| `mcp-servers/gdrive/main.py` | Drive REST service: OAuth, read routes, **new** write route + cap | Modify |
| `mcp-servers/gdrive/tests/test_create_file.py` | Unit tests for metadata builder, cap, and the create endpoint | Create |
| `mcp-servers/tasks/scheduler.py` | `_CONNECTOR_ACCESS["Google Drive"]` ops hint → mention create_file | Modify (1 string) |

## Decisions / deviations from spec

- **`connector_intent.py` keyword change dropped (YAGNI).** The spec floated adding `"save to drive"` / `"upload to drive"`, but both contain the existing `"drive"` keyword and `"save ... google doc"` hits the existing `"google doc"` keyword — write phrases already gate Drive. No code change; no test needed. (If you disagree, it's a one-line tuple edit.)
- **MVP = create only** (no update/delete), per spec non-goals.

---

### Task 1: Broaden OAuth scope to allow writing app-created files

**Files:**
- Modify: `mcp-servers/gdrive/main.py` (the `SCOPES =` line, ~line 40)
- Test: `mcp-servers/gdrive/tests/test_create_file.py`

- [ ] **Step 1: Write the failing test**

Create `mcp-servers/gdrive/tests/test_create_file.py` with the env preamble, then:

```python
import os

os.environ.setdefault("AIUI_FERNET_KEY", "HUPF1Swo8jfVfpUOSqpga7Q1zbHA_33fh_j2X25Rbik=")
os.environ.setdefault("OAUTH_STATE_SECRET", "test-secret-123")
os.environ.setdefault("GOOGLE_CLIENT_ID", "x")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "x")

from fastapi.testclient import TestClient
import main


def test_scopes_include_readonly_and_file():
    assert "https://www.googleapis.com/auth/drive.readonly" in main.SCOPES
    assert "https://www.googleapis.com/auth/drive.file" in main.SCOPES
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "mcp-servers/gdrive" && python -m pytest tests/test_create_file.py::test_scopes_include_readonly_and_file -v`
Expected: FAIL — `drive.file` not in SCOPES.

- [ ] **Step 3: Write minimal implementation**

In `main.py`, change:
```python
SCOPES = "https://www.googleapis.com/auth/drive.readonly"
```
to:
```python
SCOPES = "https://www.googleapis.com/auth/drive.readonly https://www.googleapis.com/auth/drive.file"
```

- [ ] **Step 4: Run test to verify it passes**

Run: same command. Expected: PASS.

- [ ] **Step 5: Commit intent** (locally land in Task 6 on the VPS)

Note the change; do not push yet.

---

### Task 2: Pure helper `_build_create_metadata`

Maps the public `mime_type` ("doc"/"text"/"markdown") to Drive metadata + media content-type. Pure function → trivially testable, isolates the conversion decision.

**Files:**
- Modify: `mcp-servers/gdrive/main.py` (add near the other helpers, before the tool endpoints)
- Test: `mcp-servers/gdrive/tests/test_create_file.py`

- [ ] **Step 1: Write the failing tests**

Append:
```python
def test_build_metadata_doc_converts_to_google_doc():
    meta, media = main._build_create_metadata("Report", "doc", None)
    assert meta["name"] == "Report"
    assert meta["mimeType"] == "application/vnd.google-apps.document"
    assert media == "text/plain"
    assert "parents" not in meta


def test_build_metadata_text_and_markdown():
    meta_t, media_t = main._build_create_metadata("a", "text", None)
    assert meta_t["mimeType"] == "text/plain" and media_t == "text/plain"
    meta_m, media_m = main._build_create_metadata("b", "markdown", None)
    assert meta_m["mimeType"] == "text/markdown" and media_m == "text/markdown"


def test_build_metadata_folder_id_sets_parents():
    meta, _ = main._build_create_metadata("a", "doc", "FOLDER123")
    assert meta["parents"] == ["FOLDER123"]


def test_build_metadata_unknown_kind_defaults_to_doc():
    meta, _ = main._build_create_metadata("a", "bogus", None)
    assert meta["mimeType"] == "application/vnd.google-apps.document"
```

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/test_create_file.py -v -k build_metadata`
Expected: FAIL — `main._build_create_metadata` does not exist (AttributeError).

- [ ] **Step 3: Implement**

Add to `main.py` (helpers area):
```python
# mime kind -> (Drive file mimeType, media part Content-Type)
_CREATE_KINDS = {
    "doc": ("application/vnd.google-apps.document", "text/plain"),
    "text": ("text/plain", "text/plain"),
    "markdown": ("text/markdown", "text/markdown"),
}


def _build_create_metadata(name: str, mime_type: str, folder_id: Optional[str]):
    """Return (metadata, media_content_type) for a Drive files.create.
    Unknown mime_type falls back to 'doc' (native Google Doc)."""
    file_mime, media_mime = _CREATE_KINDS.get(mime_type, _CREATE_KINDS["doc"])
    metadata: dict = {"name": name, "mimeType": file_mime}
    if folder_id:
        metadata["parents"] = [folder_id]
    return metadata, media_mime
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_create_file.py -v -k build_metadata`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit intent**

---

### Task 3: Write cap `_check_write_cap` (rolling hourly, per user)

**Files:**
- Modify: `mcp-servers/gdrive/main.py` (add `import time`; add config + helper near config block)
- Test: `mcp-servers/gdrive/tests/test_create_file.py`

- [ ] **Step 1: Write the failing tests**

Append:
```python
def test_write_cap_allows_up_to_limit_then_blocks(monkeypatch):
    monkeypatch.setattr(main, "GDRIVE_WRITE_CAP_PER_HOUR", 3)
    main._write_log.clear()
    monkeypatch.setattr(main.time, "time", lambda: 1000.0)
    assert main._check_write_cap("u@x") is True
    assert main._check_write_cap("u@x") is True
    assert main._check_write_cap("u@x") is True
    assert main._check_write_cap("u@x") is False  # 4th within the hour


def test_write_cap_resets_after_window(monkeypatch):
    monkeypatch.setattr(main, "GDRIVE_WRITE_CAP_PER_HOUR", 1)
    main._write_log.clear()
    clock = {"t": 1000.0}
    monkeypatch.setattr(main.time, "time", lambda: clock["t"])
    assert main._check_write_cap("u@x") is True
    assert main._check_write_cap("u@x") is False
    clock["t"] += 3601  # advance past the rolling window
    assert main._check_write_cap("u@x") is True
```

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/test_create_file.py -v -k write_cap`
Expected: FAIL — `main._check_write_cap` / `main._write_log` / `main.GDRIVE_WRITE_CAP_PER_HOUR` missing.

- [ ] **Step 3: Implement**

Add `import time` to the imports block. Add near the Config block:
```python
GDRIVE_WRITE_CAP_PER_HOUR = int(os.getenv("GDRIVE_WRITE_CAP_PER_HOUR", "20"))
_write_log: dict = {}  # user_email -> list[float] create timestamps (this process)


def _check_write_cap(user_email: str) -> bool:
    """Record a create attempt; return True if under the hourly cap, else False.
    Rolling 1-hour window, per user, in-process (resets on restart)."""
    now = time.time()
    window = [t for t in _write_log.get(user_email, []) if now - t < 3600]
    if len(window) >= GDRIVE_WRITE_CAP_PER_HOUR:
        _write_log[user_email] = window
        return False
    window.append(now)
    _write_log[user_email] = window
    return True
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_create_file.py -v -k write_cap`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit intent**

---

### Task 4: `_drive_create` helper + `CreateFileInput` + `POST /gdrive_create_file`

**Files:**
- Modify: `mcp-servers/gdrive/main.py` (add `import uuid`; add model, upload URL, helper, endpoint)
- Test: `mcp-servers/gdrive/tests/test_create_file.py`

- [ ] **Step 1: Write the failing tests**

Append:
```python
def test_create_file_no_token_returns_error(monkeypatch):
    async def _none(email):
        return None
    monkeypatch.setattr(main, "get_valid_token", _none)
    main._write_log.clear()
    c = TestClient(main.app)
    r = c.post("/gdrive_create_file", json={"name": "X", "content": "hi"},
               headers={"x-user-email": "nobody@aiui.local"})
    assert r.status_code == 200
    assert "error" in r.json()


def test_create_file_maps_drive_response(monkeypatch):
    async def _tok(email):
        return "tok"
    async def _create(token, metadata, media, content):
        assert metadata["mimeType"] == "application/vnd.google-apps.document"
        assert content == "hi"
        return {"id": "F1", "name": "X", "webViewLink": "https://drive/F1"}
    monkeypatch.setattr(main, "get_valid_token", _tok)
    monkeypatch.setattr(main, "_drive_create", _create)
    main._write_log.clear()
    c = TestClient(main.app)
    r = c.post("/gdrive_create_file",
               json={"name": "X", "content": "hi", "mime_type": "doc"},
               headers={"x-user-email": "ralph@x"})
    assert r.json() == {"file_id": "F1", "name": "X", "web_link": "https://drive/F1"}


def test_create_file_cap_blocks_after_limit(monkeypatch):
    async def _tok(email):
        return "tok"
    async def _create(*a, **k):
        return {"id": "F", "name": "n", "webViewLink": "l"}
    monkeypatch.setattr(main, "get_valid_token", _tok)
    monkeypatch.setattr(main, "_drive_create", _create)
    monkeypatch.setattr(main, "GDRIVE_WRITE_CAP_PER_HOUR", 1)
    main._write_log.clear()
    c = TestClient(main.app)
    h = {"x-user-email": "capuser@x"}
    body = {"name": "a", "content": "b"}
    assert "file_id" in c.post("/gdrive_create_file", json=body, headers=h).json()
    assert "error" in c.post("/gdrive_create_file", json=body, headers=h).json()
```

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/test_create_file.py -v -k create_file`
Expected: FAIL — endpoint 404 / `main._drive_create` missing.

- [ ] **Step 3: Implement**

Add `import uuid` to imports. Add the model near the other `*Input` classes:
```python
class CreateFileInput(BaseModel):
    name: str
    content: str
    mime_type: str = "doc"           # doc | text | markdown
    folder_id: Optional[str] = None
```

Add the upload URL near the other Google URL constants:
```python
GOOGLE_UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"
```

Add the helper + endpoint in the tool-endpoints area:
```python
async def _drive_create(access_token: str, metadata: dict, media_mime: str,
                        content: str) -> dict:
    """multipart/related files.create. Returns created file JSON
    (id,name,webViewLink). Raises on non-2xx (caller wraps in try/except)."""
    boundary = "aiui_" + uuid.uuid4().hex
    body = (
        f"--{boundary}\r\n"
        "Content-Type: application/json; charset=UTF-8\r\n\r\n"
        f"{json.dumps(metadata)}\r\n"
        f"--{boundary}\r\n"
        f"Content-Type: {media_mime}; charset=UTF-8\r\n\r\n"
        f"{content}\r\n"
        f"--{boundary}--"
    ).encode("utf-8")
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            GOOGLE_UPLOAD_URL,
            params={"uploadType": "multipart", "fields": "id,name,webViewLink"},
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": f"multipart/related; boundary={boundary}",
            },
            content=body,
            timeout=30.0,
        )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"{resp.status_code} {resp.text[:300]}")
    return resp.json()


@app.post("/gdrive_create_file", operation_id="gdrive_create_file",
          summary="Create a file in Google Drive")
async def create_file(input: CreateFileInput, request: Request):
    """Create a new file in the owner's Drive from text content. Default is a
    native Google Doc (mime_type='doc'); also 'text' or 'markdown'. The app can
    only modify files it created (drive.file scope). Returns the file's web link."""
    user_email = get_user_email(request)
    access_token = await get_valid_token(user_email)
    if not access_token:
        base = OAUTH_REDIRECT_URI.rsplit("/auth/", 1)[0]
        return {"error": NOT_CONNECTED_MSG.format(base_url=base, email=user_email)}
    if not _check_write_cap(user_email):
        return {"error": f"drive write cap reached ({GDRIVE_WRITE_CAP_PER_HOUR}/hour)"}
    if len(input.content.encode("utf-8")) > MAX_CONTENT_SIZE:
        return {"error": f"content too large (max {MAX_CONTENT_SIZE // (1024 * 1024)}MB)"}
    metadata, media_mime = _build_create_metadata(
        input.name, input.mime_type, input.folder_id)
    try:
        created = await _drive_create(access_token, metadata, media_mime, input.content)
    except Exception as e:  # noqa: BLE001
        return {"error": f"Drive create failed: {e}"}
    return {
        "file_id": created.get("id"),
        "name": created.get("name"),
        "web_link": created.get("webViewLink"),
    }
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_create_file.py -v`
Expected: PASS (all create_file + earlier tests). Then run the whole gdrive suite:
`python -m pytest tests/ -v` — expected: all green (no regressions in `test_auth_status.py` / `test_crypto_oauth.py`).

- [ ] **Step 5: Commit intent**

---

### Task 5: Advertise create_file in the scheduler's connector access-note

This is a one-line edit to a string constant. **No unit test** (see Working-environment note: the tasks suite can't run locally, and a substring assertion on a constant is low-value). Its real verification is the **end-to-end write** in Task 6 Step 5: the scheduled agent reads this exact hint and successfully calls `gdrive_create_file`. If the hint were missing/wrong, the agent wouldn't know the endpoint and the write would fail.

**Files:**
- Modify: `mcp-servers/tasks/scheduler.py` (`_CONNECTOR_ACCESS["Google Drive"]` ops string, ~line 91-95)

- [ ] **Step 1: Edit the Drive ops hint**

In `scheduler.py`, change the Drive ops string to append create_file (preserve the exact surrounding text so the diff stays one logical change):
```python
    "Google Drive": (
        "gdrive_tokens", "http://127.0.0.1:8017",
        "POST /gdrive_list_files {}, /gdrive_search_files {\"query\":\"...\"}, "
        "/gdrive_read_file {\"file_id\":\"...\"}, /gdrive_get_file_info {\"file_id\":\"...\"}, "
        "/gdrive_create_file {\"name\":\"...\",\"content\":\"...\",\"mime_type\":\"doc\"} "
        "(create a Google Doc/file from text)",
    ),
```

- [ ] **Step 2: Sanity-check syntax**

The tasks service can't import locally, so just confirm the file is still valid Python by eye (balanced quotes/parens). It will be compile-checked on the VPS in Task 6 Step 1 (`py_compile`) and exercised end-to-end in Step 5.

---

### Task 6: Deploy to VPS, verify end-to-end, commit + relay-push

**This task is manual/operational and requires the owner (Ralph) to complete the Google consent — the agent cannot click OAuth.**

- [ ] **Step 1: Re-apply the additive edits to the VPS copies (CRLF-preserving)**

For `mcp-servers/gdrive/main.py` and `mcp-servers/tasks/scheduler.py` on the VPS (`/root/proxy-server/...`): apply the same edits from Tasks 1-5 (they're additive). Use the `Edit` tool against the VPS files via a patch script (like the thread-fix `_patch_*.py`, written with `newline=""` / preserving CRLF) or targeted `sed`/python. Then:
```bash
ssh -i ~/.ssh/aiui_vps root@46.224.193.25 \
  "python3 -m py_compile /root/proxy-server/mcp-servers/gdrive/main.py \
   /root/proxy-server/mcp-servers/tasks/scheduler.py && echo COMPILE-OK"
```
Expected: `COMPILE-OK`.

- [ ] **Step 2: Deploy into the running containers + restart**
```bash
ssh -i ~/.ssh/aiui_vps root@46.224.193.25 "
  docker cp /root/proxy-server/mcp-servers/gdrive/main.py mcp-gdrive:/app/main.py &&
  docker cp /root/proxy-server/mcp-servers/tasks/scheduler.py tasks:/app/scheduler.py &&
  docker restart mcp-gdrive tasks && echo RESTARTED"
```
Expected: `RESTARTED`. Then confirm both containers are healthy/up and port 8017 still answers (`curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8017/auth/status -H 'x-user-email: x'` → `200`).

- [ ] **Step 3: Owner connects Drive (consent now includes file-create)**

In Discord, create/edit a schedule whose text implies Drive (e.g. "every morning summarize my Google Drive files") so the **Connect Google Drive** button appears; complete Google consent. Verify:
```bash
ssh -i ~/.ssh/aiui_vps root@46.224.193.25 \
  "docker exec postgres psql -U openwebui -d openwebui -c \
   \"SELECT user_email, updated_at FROM public.gdrive_tokens;\""
```
Expected: one row for the owner's email. And `/auth/status` (header) → `{\"connected\":true}`.

- [ ] **Step 4: Verify READ end-to-end**

Run-now a schedule like "list my 5 most recent Google Drive files". Confirm the agent's result (delivered to the owner's Discord thread) lists real files. Spot-check the run row in the tasks DB shows `status=completed`.

- [ ] **Step 5: Verify WRITE end-to-end + cap**

Run-now a schedule like "create a Google Doc in my Drive titled 'AIUI test' with the text 'hello from cron'". Confirm:
- The agent reports a `web_link`; opening it shows the new Doc in the owner's Drive.
- (Optional) Temporarily set `GDRIVE_WRITE_CAP_PER_HOUR=1` in the mcp-gdrive env and confirm a second create within the hour returns the cap error, then restore the default.

- [ ] **Step 6: Commit on VPS + relay-push**

On the VPS, on branch `vps-snapshot-2026-05-27`, stage the two modified service files + the new gdrive test file (scp `test_create_file.py` to the VPS repo first, matching repo endings), then:
```bash
ssh -i ~/.ssh/aiui_vps root@46.224.193.25 'cd /root/proxy-server &&
  git add mcp-servers/gdrive/main.py mcp-servers/gdrive/tests/test_create_file.py \
          mcp-servers/tasks/scheduler.py &&
  git -c user.name="thunder500" -c user.email="ralphbenitez30@gmail.com" \
  commit -m "feat(gdrive): create-file write endpoint with hourly cap + drive.file scope"'
```
Verify the diff is small/clean (no CRLF whole-file churn — if `git diff --stat` shows ~all lines changed, the endings flipped; fix before committing). Then relay-push from local:
```bash
cd "C:/All/Work - Code/ai_ui"
GIT_SSH_COMMAND="ssh -i /c/Users/RYZENmsiPROddr4/.ssh/aiui_vps" \
  git fetch vps +vps-snapshot-2026-05-27:vps-snapshot-2026-05-27
git push origin vps-snapshot-2026-05-27:vps-snapshot-2026-05-27
```

- [ ] **Step 7: Final verification**

Confirm VPS working tree clean (`git status --short` → 0), `mcp-gdrive` + `tasks` containers healthy, and the create endpoint present in the running container:
`docker exec mcp-gdrive grep -c gdrive_create_file /app/main.py` → ≥ 1.

---

## Done when
- The `mcp-servers/gdrive` suite is green locally (the new `test_create_file.py` + existing tests). The scheduler one-line change is verified end-to-end, not by a local unit test.
- Owner has connected Drive; a run-now task has both **read** a real file and **created** a real Doc, delivered to Discord.
- The write cap returns an error past the limit.
- Changes committed on `vps-snapshot-2026-05-27` and pushed to origin; VPS tree clean.
