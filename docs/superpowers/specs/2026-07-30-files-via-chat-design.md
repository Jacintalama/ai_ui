# Files via chat: Word + PDF creation with optional save to Drive

Date: 2026-07-30
Status: approved (design discussion in session; Ralph picked Word + PDF,
download button + Drive on request, chat export included)

## Goal

A user asks in chat for a document ("write me a proposal as a Word file",
"turn this conversation into a PDF") and gets the real file back in the chat
as a download button. If they ask, the file is also saved to their connected
Google Drive. No setup beyond the existing one-click Google connect.

## What exists already (reused, not rebuilt)

- **Excel Creator** native tool proves the delivery UX: generate bytes, return
  a styled download button using a base64 `data:` link. No storage, no TTL.
- **mcp-gdrive** service has per-user Google OAuth and a `gdrive_create_file`
  endpoint. The OAuth scopes already include `drive.file` (write access to
  app-created files), so existing connections need no re-consent.
- **Gmail/Drive native-tool pattern**: OWUI injects the signed-in user via
  `__user__`; the tool calls a backend service with that identity; a
  "not connected" reply renders the inline Connect button via
  integrations-ui.js.

## Scope

In v1:
- Formats: Word (.docx) and PDF.
- Delivery: download button in chat; `save_to_drive` flag additionally uploads
  to the user's Drive and returns the Drive link.
- Chat export: no special function. The model already holds the conversation
  and writes it into the `markdown` argument.

Out of v1: PowerPoint, templates/branding, editing existing files, auto-save
without being asked, per-folder Drive placement.

## Architecture

Two small pieces:

1. **`mcp-servers/tasks/routes_files.py`** (new): `POST /files/generate`,
   internal-only (tasks:8210 is not routed publicly; additionally gated by the
   `X-Internal-Secret` header against `INTERNAL_CALLBACK_SECRET`, compared
   with `secrets.compare_digest`, exactly the fusion endpoint pattern:
   missing config denies rather than opens).
   - Request: `{"title": str, "markdown": str, "format": "docx"|"pdf"}`
   - Response: `{"filename": str, "b64": str, "size": int, "mime": str}`
   - Caps: markdown <= 200 KB (413 above), output <= 5 MB (413 above).
   - Filename: sanitized title (`[^\w\-]` -> `_`) + timestamp + extension.
   - Generation: `python-docx` for Word, `reportlab` (platypus) for PDF. Both
     pure Python, added to `mcp-servers/tasks/requirements.txt`.
   - Never logs document content; log line carries only format and sizes.

2. **`open-webui-functions/documents_tool.py`** (new native tool, installed
   into the OWUI `tool` table by `scripts/insert_documents_tool.py`, same
   docker-run psycopg2 pattern as the knowledge-graph filter installer):
   - One function:
     `create_document(title, markdown, format="docx", save_to_drive=False)`.
   - Valves: `tasks_url` (default `http://tasks:8210`), `gdrive_url`
     (default `http://mcp-gdrive:8000`), `internal_secret`, `timeout_seconds`.
   - Flow: call tasks -> on success render the Excel-style download button
     (data: URI, correct mime). If `save_to_drive`, also POST the bytes to
     `gdrive_create_file` with the user's email; append the Drive link to the
     reply, or the existing inline-connect message if the user has not
     connected Google Drive.
   - "Save that to my Drive" after the fact: the model calls the function
     again with the same content and `save_to_drive=true` (regeneration is
     cheap; the tool stays stateless).

## Markdown subset

Headings `#`..`###`, paragraphs, `-`/`*` bullets, `1.` numbered lists, bold
`**text**`, simple pipe tables, fenced code blocks rendered monospace.
Everything else degrades to plain paragraph text; the generator must never
error on unknown markdown.

## Error handling

Every leg returns a readable sentence to the chat, never a stack trace:
- Generation failure or cap exceeded: the endpoint's `detail` string.
- Drive not connected: the gdrive service's connect message (frontend renders
  the button).
- Drive upload failure: file still delivered as download; the reply notes the
  Drive save failed and why, in one sentence.

## Testing and verification

- TDD on pure builders in `tests/test_files_generate.py`: markdown parsing to
  an intermediate block list; docx bytes read back with `python-docx` and
  asserted (headings, list items, bold run, table cell); PDF asserted for
  `%PDF` magic, non-trivial size, and page presence; cap enforcement raises.
- Endpoint smoke in the prod container after deploy (httpx against
  localhost:8210 with the secret).
- Real-chat proof on prod: create one docx and one pdf from chat, click-check
  the button markup in the response, and one real save to Ralph's Drive.

## Deployment notes

- `requirements.txt` change means a tasks image rebuild.
- Tool install is a DB insert (idempotent upsert); OWUI restart not required
  for tools, but verify the tool lists in the chat tools picker.
- Secret: the installer writes the tool's `internal_secret` valve from the
  server's `INTERNAL_CALLBACK_SECRET` (already in the tasks environment for
  fusion); never hardcoded in the tool source or committed anywhere.
