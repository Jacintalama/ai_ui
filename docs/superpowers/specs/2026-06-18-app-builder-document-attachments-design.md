# App Builder chat: read PDF / Word / text attachments

**Date:** 2026-06-18
**Status:** approved (design)

## Problem

In the App Builder web chat (Enhance panel), attaching a PDF or Word document
does nothing useful — only images are read. In code, both attachment consumers
reject non-images:

- `mcp-servers/tasks/routes_tasks.py:69` — `ALLOWED_MIME` is images only
  (`png/jpeg/webp/gif`).
- `routes_tasks.py:55-67` — `_sniff_image_mime` returns `None` for non-images,
  so a spoofed Content-Type is also caught (`test_attachment_helpers.py:59`
  locks in that `%PDF` is rejected).
- `static/preview.html:2865` — the file input `accept=` allows images only.

A PDF/Word therefore fails with HTTP 400 before anything reads it.

Two consumers share that allowlist:

1. **`/api/tasks/chat`** (line 1040) — the conversational assistant. Calls the
   Anthropic Messages API (haiku) directly; images become base64 `image`
   blocks on the latest user message. Ephemeral (not persisted).
2. **`/api/tasks/enhance`** (line 695) — the build path. Writes attachments to
   `apps/<slug>/.attachments/<task_id>/` and lists their paths in the build
   prompt for the agent (`claude` CLI) to `Read`
   (`claude_executor.build_enhance_prompt(attachments=...)`).

No PDF/Word library exists anywhere in the repo.

## Approach — uniform server-side text extraction

Add a small, pure, dependency-light module `mcp-servers/tasks/document_extract.py`:

- `classify_document(declared_mime, head, filename) -> 'pdf'|'docx'|'text'|None`
  — magic bytes win over the (spoofable) declared MIME; plain text has no magic
  bytes so it is recognised by `text/*` MIME or a known extension.
- `extract_text(data, kind, max_chars=20000) -> str` — capped, graceful: a
  scanned/image-only PDF or unparseable file returns `""` and the caller adds a
  short "no extractable text" note.
- **PDF** via `pypdf` (one new dependency — pure-python, light). **`.docx`** via
  stdlib `zipfile` + `xml.etree` (zero new deps — join `<w:t>` runs per
  paragraph). **`.txt/.md/.csv`** decode as UTF-8 (`errors="replace"`).

### Wiring (images stay byte-for-byte identical — existing tests pass)

- **`/chat`** loop (1108-1131): if the declared MIME is an image, keep the exact
  existing image-block path. Otherwise `classify_document(...)`; on a doc,
  append a `text` block `"[Attached file: <name>]\n<text>"` to the user
  message; on `None`, HTTP 400 (message now lists PDF/Word/text too).
- **`/enhance`** loop (748-778 + disk write 865-886): images unchanged. For a
  doc, write the original bytes to `.attachments/` (as today) AND an extracted
  `.txt` sidecar, and list the sidecar in `attachment_rel_paths` so the build
  agent reads plain text. Rename the prompt section "Attached images" →
  "Attached files" (`claude_executor.build_enhance_prompt`).
- **Frontend**: widen `static/preview.html` attach `accept=` to add
  `application/pdf,.pdf,.docx,.txt,.md,.csv`.

### Limits / safety

- Keep the existing 5 MB/file and 5-file caps; both endpoints are admin-only.
- Cap extracted text at ~20k chars (protects the 3.8 GB host and the prompt
  budget); truncation is marked.
- Image-only PDFs: extraction yields nothing → graceful note, no crash.

## Testing

- `document_extract.py` is pure → full unit coverage locally: classify
  (pdf/docx/text/junk/image), extract for pdf (fixture)/docx (stdlib-built
  zip)/text/empty/oversized/garbage.
- Existing image attachment tests (`test_attachment_helpers.py`) stay green —
  the image branch is unchanged.
- `build_enhance_prompt` "Attached files" wording gets a test.
- `/chat` and `/enhance` themselves need Postgres + the Anthropic API, so they
  are verified by import + the pure-helper tests + the prompt-wording test;
  full route verification happens via the container test runner at deploy time.

## Out of scope

- The drag-and-drop project-import path (`upload_validation.py`) — a different
  feature; not the place for chat document understanding.
- Legacy `.doc` (binary) and OCR of scanned PDFs.
