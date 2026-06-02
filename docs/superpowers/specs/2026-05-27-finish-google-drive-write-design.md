# Finish Google Drive (read verified + write/upload) — design

**Date:** 2026-05-27
**Branch:** feat/gdrive-gmail-connectors
**Author:** Ralph

## Summary

Complete the Google Drive connector for scheduled tasks. Drive read access is
already built (the scheduler points agents at `http://127.0.0.1:8017` with
`list/search/read/get_file_info` ops) but was never connected or exercised
end-to-end. This slice (a) verifies Drive read works end-to-end and (b) adds a
**write** capability — a scheduled agent can create files in the owner's Drive
(e.g. "save my email summary as a Google Doc"), behind a server-side rate cap.

This is the first sub-project of four agreed for the cron system; the others
(safety hardening, Google Calendar, more outputs/actions) are separate specs.

## Goals

- A scheduled agent can **read/search/read** the owner's Drive files (verify the
  existing path actually works once Drive is connected).
- A scheduled agent can **create** a file in the owner's Drive from text content,
  as a native Google Doc (default) or a plain text/markdown file.
- Drive write is **least-privilege**: the agent can only touch files it created;
  it can never read-modify-delete the owner's pre-existing documents.
- A **write cap** prevents an agent from spamming the owner's Drive.
- Connecting Drive is the existing button-driven OAuth flow, surfaced only when a
  task implies Drive (no change to that UX).

## Non-goals (this slice)

- Updating or deleting files (even app-created ones) — create-only MVP.
- A general "save the result to Drive" output destination wired into every task —
  that belongs to the "more outputs/actions" sub-project. Here, write is an
  agent-callable tool, used when the task text asks for it.
- DB-backed durable write quota — the cap is an in-process rolling counter for
  MVP (single host-local container). Durable quota is deferred to safety hardening.
- Generalizing the cap pattern to Gmail send — that is the safety-hardening
  sub-project (this slice only establishes the pattern for Drive).

## Existing building blocks (already on this branch / deployed)

- `mcp-servers/gdrive/main.py` — REST service, OAuth via signed state
  (`oauth_state.py`), encrypted token storage at the DB boundary
  (`crypto_utils.py`, `public.gdrive_tokens`), header-based `/auth/status`.
  Read routes: `gdrive_list_files`, `gdrive_search_files`, `gdrive_read_file`,
  `gdrive_get_file_info`, `gdrive_download/{id}`, `gdrive_upload_to_webui`.
- Host-local port `127.0.0.1:8017:8000` (docker-compose), reachable by the
  on-host scheduled agent.
- `mcp-servers/tasks/scheduler.py` — `_CONNECTOR_ACCESS["Google Drive"]` +
  `_connector_access_note(user_email)` injects connector instructions into the
  agent prompt when `gdrive_tokens` has a row for the owner.
- `webhook-handler/handlers/connector_intent.py` — `detect(text)` gates the
  schedule on `{gmail,drive,web}`; Drive keywords: `drive`, `google doc`,
  `spreadsheet`.
- `webhook-handler/clients/connectors.py` + `app_builder_panel` connect buttons
  (the OAuth UX, proven working for Gmail).

## Design

### 1. OAuth scope change (re-consent)

- `mcp-servers/gdrive/main.py` `SCOPES`:
  `https://www.googleapis.com/auth/drive.readonly`
  → `https://www.googleapis.com/auth/drive.readonly https://www.googleapis.com/auth/drive.file`
- Rationale: `drive.readonly` keeps full read of all files; `drive.file` grants
  write only to files the app creates. The agent cannot edit/delete pre-existing
  user files.
- No Drive token exists yet, so this is a clean first consent, not a forced
  re-consent / migration. No token-invalidation logic needed.

### 2. New write endpoint — `POST /gdrive_create_file`

- Request body:
  ```json
  {
    "name": "string (required)",
    "content": "string (required, the file body as text)",
    "mime_type": "doc | text | markdown (optional, default \"doc\")",
    "folder_id": "string (optional; create inside this folder)"
  }
  ```
- Behavior:
  - `mime_type="doc"` → create a native Google Doc: Drive `files.create`
    multipart with metadata `mimeType: application/vnd.google-apps.document`
    and media part `text/plain`; Drive converts plain text into a Doc.
    (Markdown/HTML rendering is out of scope — content lands as literal text;
    acceptable MVP.)
  - `mime_type="text"` → `text/plain` file.
  - `mime_type="markdown"` → `text/markdown` file.
  - `folder_id` (if given) sets `parents: [folder_id]`.
- Auth: owner-scoped via the existing `get_user_email(request)` (`x-user-email`
  header), same as the read routes.
- **Error handling:** the existing `drive_request()` helper is GET-only and
  raises `HTTPException` on non-200 — the create endpoint must NOT reuse it.
  It issues its own multipart POST and wraps it in try/except, returning
  `{"error": ...}` JSON (HTTP 200) on any failure, to honor the connector
  "return error JSON, never raise" convention the agent relies on.
- Success response: `{ "file_id": "...", "name": "...", "web_link": "https://..." }`
  (`webViewLink` from the create response).
- Failure: `{ "error": "..." }` (no token → `{"error":"Not connected"}`;
  Drive API error → caught and returned as error JSON; cap exceeded → see below).

### 3. Safety guardrail — write cap

- Server-side rolling rate limit in `mcp-servers/gdrive/main.py`:
  **max N file-creates per user per rolling hour**, default `N=20`, via env
  `GDRIVE_WRITE_CAP_PER_HOUR`.
- Implementation: in-process dict `{user_email: [timestamps]}`; on each create,
  prune entries older than 3600s, reject if `len >= N` with
  `{"error": "drive write cap reached (<N>/hour)"}` (the actual configured
  number interpolated, e.g. "20/hour") and HTTP 200 (so the agent
  reads the error JSON rather than treating it as a transport failure — matches
  the existing "never raise, return error JSON" convention).
- Counter is per-process and resets on container restart — acceptable for MVP
  (single host-local container). Durable quota deferred to safety hardening.

### 4. Agent wiring

- `scheduler.py` `_CONNECTOR_ACCESS["Google Drive"]` ops hint: append
  `/gdrive_create_file {"name":"...","content":"...","mime_type":"doc"}`
  so the agent knows how to write.
- `connector_intent.py` `_DRIVE`: add `save to drive`, `upload to drive` (the
  bare keyword `drive` already triggers the gate; this just improves recall).

### 5. Verification plan (the "finish" — requires the owner to connect once)

1. Deploy scope change + `/gdrive_create_file` + cap + wiring to the VPS
   (`mcp-gdrive` rebuild/`docker cp` + restart; scheduler `docker cp` + restart).
2. Owner triggers Drive connect in Discord, completes Google consent (now shows
   read + create-files). Confirm: row in `public.gdrive_tokens`, `/auth/status`
   on `127.0.0.1:8017` → `{"connected":true}`.
3. **Read** run-now task ("list my recent Drive files") → agent curls 8017 →
   reads → delivered to the owner's Discord thread.
4. **Write** run-now task ("create a Google Doc titled Test with 'hello'") →
   agent calls `/gdrive_create_file` → confirm the file appears in the owner's
   Drive (via `web_link`) and a confirmation is delivered.
5. Confirm the cap: the 21st create within an hour returns the cap error.

## Testing

TDD (write failing tests first) in `mcp-servers/gdrive/tests/`:

- `test_create_file_builds_google_doc_request` — `mime_type="doc"` produces a
  multipart `files.create` with `application/vnd.google-apps.document` metadata.
- `test_create_file_plain_and_markdown` — `text`/`markdown` map to the right
  media mime types.
- `test_create_file_folder_id_sets_parents` — `folder_id` adds `parents`.
- `test_create_file_no_token_returns_error` — missing token → `{"error":"Not connected"}`.
- `test_write_cap_blocks_after_limit` — N+1th create within the window returns the
  cap error; a create after the window passes (monkeypatch the clock).

Drive API calls are mocked at the HTTP boundary (httpx) — no live Google calls in
unit tests. End-to-end read/write is the manual run-now verification above.

## Deployment & risk

- Deploy per `reference_vps_connection.md`: `mcp-gdrive` needs a rebuild (code
  change) or `docker cp main.py` + restart; `tasks` gets `docker cp scheduler.py`
  + restart; `webhook-handler` gets `docker cp connector_intent.py` + restart.
- Commit on the VPS (LF), relay-push per `reference_git_push_relay_and_crlf.md`.
- Risk: low. `drive.file` bounds write blast radius to app-created files; the cap
  bounds volume; read scope is unchanged. Main user-visible change is the consent
  screen now requests file-create permission.
