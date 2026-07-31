# Files via Chat (Word/PDF + Drive) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Chat can produce real .docx and .pdf files (download button in chat) and optionally save them to the user's Google Drive.

**Architecture:** Pure markdown-to-document builders + a thin secret-gated
endpoint in the tasks service; a thin native OWUI tool calls it and renders
the Excel-Creator-style download button; Drive saves reuse mcp-gdrive's
`gdrive_create_file`, extended to accept binary content as base64.

**Tech Stack:** FastAPI, python-docx, reportlab, httpx, pytest, native Open WebUI tool.

Spec: `docs/superpowers/specs/2026-07-30-files-via-chat-design.md`

## Global Constraints

- Markdown input cap: 200,000 bytes UTF-8 (HTTP 413 above).
- Output cap: 5,000,000 bytes (HTTP 413 above).
- Secret gate: `X-Internal-Secret` vs env `INTERNAL_CALLBACK_SECRET` via
  `secrets.compare_digest`; missing config denies.
- Document content is never logged; log only format and byte sizes.
- No AI attribution in commits. Author: Ralph Benitez only.
- Tests run from `mcp-servers/tasks/`: `python -m pytest tests/<file> -q`.
- The generator must never raise on unknown markdown; degrade to paragraphs.

---

### Task 1: Markdown block parser (pure)

**Files:**
- Create: `mcp-servers/tasks/doc_builder.py`
- Test: `mcp-servers/tasks/tests/test_doc_builder.py`

**Interfaces:**
- Produces: `parse_blocks(md: str) -> list[dict]` with block shapes:
  `{"t":"h","level":1|2|3,"text":str}`, `{"t":"p","text":str}`,
  `{"t":"ul","items":[str]}`, `{"t":"ol","items":[str]}`,
  `{"t":"code","text":str}`, `{"t":"table","rows":[[str]]}`.
- Produces: `split_bold(text: str) -> list[tuple[str,bool]]` (segment, is_bold).

- [ ] **Step 1: Write the failing tests**

```python
"""Markdown subset -> document blocks -> docx/pdf bytes. Pure, no I/O."""
from doc_builder import parse_blocks, split_bold


def test_parse_headings_and_paragraphs():
    md = "# Title\n\nHello world.\nSame paragraph.\n\n## Section\nBody."
    b = parse_blocks(md)
    assert b[0] == {"t": "h", "level": 1, "text": "Title"}
    assert b[1] == {"t": "p", "text": "Hello world. Same paragraph."}
    assert b[2] == {"t": "h", "level": 2, "text": "Section"}
    assert b[3] == {"t": "p", "text": "Body."}


def test_parse_lists():
    md = "- one\n- two\n\n1. first\n2) second"
    b = parse_blocks(md)
    assert b[0] == {"t": "ul", "items": ["one", "two"]}
    assert b[1] == {"t": "ol", "items": ["first", "second"]}


def test_parse_code_fence_and_table():
    md = "```\nx = 1\ny = 2\n```\n\n| A | B |\n|---|---|\n| 1 | 2 |"
    b = parse_blocks(md)
    assert b[0] == {"t": "code", "text": "x = 1\ny = 2"}
    assert b[1] == {"t": "table", "rows": [["A", "B"], ["1", "2"]]}


def test_parse_never_raises_on_junk():
    assert parse_blocks("") == []
    assert parse_blocks("###### deep\n***\n> quote")  # no exception, some blocks


def test_split_bold():
    assert split_bold("a **b** c") == [("a ", False), ("b", True), (" c", False)]
    assert split_bold("plain") == [("plain", False)]
    assert split_bold("**all**") == [("all", True)]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_doc_builder.py -q`
Expected: FAIL (ImportError: no module doc_builder)

- [ ] **Step 3: Implement parser in `doc_builder.py`**

```python
"""Markdown subset -> blocks -> .docx / .pdf bytes.

Pure functions only; the routes layer does I/O. The subset: # ## ###
headings, paragraphs, -/* bullets, 1./1) numbered lists, **bold**, fenced
code, simple pipe tables. Anything else degrades to a paragraph; parsing
must never raise (spec: generation never errors on unknown markdown).
"""
import io
import re

_H_RE = re.compile(r"^(#{1,3})\s+(.*)$")
_UL_RE = re.compile(r"^[-*]\s+(.*)$")
_OL_RE = re.compile(r"^\d+[.)]\s+(.*)$")
_SEP_RE = re.compile(r"^\|?[\s:|-]+\|?$")


def parse_blocks(md: str) -> list:
    blocks, para, code, in_code = [], [], [], False

    def flush_para():
        if para:
            blocks.append({"t": "p", "text": " ".join(para)})
            para.clear()

    for raw in (md or "").splitlines():
        line = raw.rstrip()
        if line.strip().startswith("```"):
            if in_code:
                blocks.append({"t": "code", "text": "\n".join(code)})
                code.clear()
            else:
                flush_para()
            in_code = not in_code
            continue
        if in_code:
            code.append(raw)
            continue
        if not line.strip():
            flush_para()
            continue
        m = _H_RE.match(line)
        if m:
            flush_para()
            blocks.append({"t": "h", "level": len(m.group(1)),
                           "text": m.group(2).strip()})
            continue
        m = _UL_RE.match(line.strip())
        if m:
            flush_para()
            if blocks and blocks[-1]["t"] == "ul":
                blocks[-1]["items"].append(m.group(1).strip())
            else:
                blocks.append({"t": "ul", "items": [m.group(1).strip()]})
            continue
        m = _OL_RE.match(line.strip())
        if m:
            flush_para()
            if blocks and blocks[-1]["t"] == "ol":
                blocks[-1]["items"].append(m.group(1).strip())
            else:
                blocks.append({"t": "ol", "items": [m.group(1).strip()]})
            continue
        if line.strip().startswith("|") and "|" in line.strip()[1:]:
            if _SEP_RE.match(line.strip()):
                continue                      # |---|---| separator row
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            flush_para()
            if blocks and blocks[-1]["t"] == "table":
                blocks[-1]["rows"].append(cells)
            else:
                blocks.append({"t": "table", "rows": [cells]})
            continue
        para.append(line.strip())
    if in_code and code:                      # unclosed fence degrades to code
        blocks.append({"t": "code", "text": "\n".join(code)})
    flush_para()
    return blocks


def split_bold(text: str) -> list:
    """'a **b** c' -> [('a ', False), ('b', True), (' c', False)]."""
    out = []
    for i, seg in enumerate((text or "").split("**")):
        if seg:
            out.append((seg, i % 2 == 1))
    return out or [("", False)]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_doc_builder.py -q`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/doc_builder.py mcp-servers/tasks/tests/test_doc_builder.py
git commit -m "feat(files): markdown-subset block parser for document generation"
```

---

### Task 2: DOCX builder

**Files:**
- Modify: `mcp-servers/tasks/doc_builder.py` (append)
- Modify: `mcp-servers/tasks/requirements.txt` (add `python-docx`)
- Test: `mcp-servers/tasks/tests/test_doc_builder.py` (append)

**Interfaces:**
- Consumes: `parse_blocks`, `split_bold` (Task 1).
- Produces: `blocks_to_docx(title: str, blocks: list) -> bytes`.

- [ ] **Step 1: Install dep locally and add failing tests**

Run: `pip install python-docx` and append `python-docx` to
`mcp-servers/tasks/requirements.txt`.

```python
def test_docx_roundtrip():
    from docx import Document
    from doc_builder import blocks_to_docx
    blocks = parse_blocks(
        "# Report\n\nHello **bold** world.\n\n- a\n- b\n\n| X | Y |\n|--|--|\n| 1 | 2 |")
    data = blocks_to_docx("My Report", blocks)
    assert isinstance(data, bytes) and len(data) > 2000
    doc = Document(io.BytesIO(data))
    texts = [p.text for p in doc.paragraphs]
    assert "My Report" in texts          # title heading
    assert "Report" in texts             # h1 from markdown
    assert any("Hello" in t and "world." in t for t in texts)
    bold_runs = [r.text for p in doc.paragraphs for r in p.runs if r.bold]
    assert "bold" in bold_runs
    assert "a" in texts and "b" in texts
    assert doc.tables[0].cell(0, 0).text == "X"
    assert doc.tables[0].cell(1, 1).text == "2"


import io  # noqa: E402  (top of file if not already there)
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_doc_builder.py::test_docx_roundtrip -q`
Expected: FAIL (ImportError: blocks_to_docx)

- [ ] **Step 3: Implement**

```python
def blocks_to_docx(title: str, blocks: list) -> bytes:
    from docx import Document

    doc = Document()
    if (title or "").strip():
        doc.add_heading(title.strip(), level=0)
    for b in blocks:
        if b["t"] == "h":
            doc.add_heading(b["text"], level=b["level"])
        elif b["t"] == "p":
            p = doc.add_paragraph()
            for seg, bold in split_bold(b["text"]):
                p.add_run(seg).bold = bold
        elif b["t"] in ("ul", "ol"):
            style = "List Bullet" if b["t"] == "ul" else "List Number"
            for it in b["items"]:
                p = doc.add_paragraph(style=style)
                for seg, bold in split_bold(it):
                    p.add_run(seg).bold = bold
        elif b["t"] == "code":
            p = doc.add_paragraph()
            run = p.add_run(b["text"])
            run.font.name = "Courier New"
        elif b["t"] == "table" and b["rows"]:
            cols = max(len(r) for r in b["rows"])
            tbl = doc.add_table(rows=len(b["rows"]), cols=cols)
            tbl.style = "Table Grid"
            for ri, row in enumerate(b["rows"]):
                for ci, cell in enumerate(row):
                    tbl.cell(ri, ci).text = cell
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_doc_builder.py -q`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/doc_builder.py mcp-servers/tasks/tests/test_doc_builder.py mcp-servers/tasks/requirements.txt
git commit -m "feat(files): markdown blocks to .docx"
```

---

### Task 3: PDF builder

**Files:**
- Modify: `mcp-servers/tasks/doc_builder.py` (append)
- Modify: `mcp-servers/tasks/requirements.txt` (add `reportlab`)
- Test: `mcp-servers/tasks/tests/test_doc_builder.py` (append)

**Interfaces:**
- Consumes: `parse_blocks`, block shapes (Task 1).
- Produces: `blocks_to_pdf(title: str, blocks: list) -> bytes`.

- [ ] **Step 1: Install dep and add failing test**

Run: `pip install reportlab` and append `reportlab` to requirements.txt.

```python
def test_pdf_bytes():
    from doc_builder import blocks_to_pdf
    blocks = parse_blocks("# Report\n\nHello **bold** world.\n\n- a\n- b")
    data = blocks_to_pdf("My Report", blocks)
    assert data[:5] == b"%PDF-"
    assert len(data) > 1500
    assert b"/Page" in data


def test_pdf_escapes_markup():
    from doc_builder import blocks_to_pdf
    # < and & in user text must not break reportlab's mini-HTML parser
    data = blocks_to_pdf("t", parse_blocks("a < b & c **d**"))
    assert data[:5] == b"%PDF-"
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_doc_builder.py -k pdf -q`
Expected: FAIL (ImportError: blocks_to_pdf)

- [ ] **Step 3: Implement**

```python
def _pdf_rich(text: str) -> str:
    """Escape XML, then map **bold** to <b> for reportlab paragraphs."""
    from xml.sax.saxutils import escape
    parts = []
    for seg, bold in split_bold(text):
        seg = escape(seg)
        parts.append(f"<b>{seg}</b>" if bold else seg)
    return "".join(parts)


def blocks_to_pdf(title: str, blocks: list) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (ListFlowable, ListItem, Paragraph,
                                    Preformatted, SimpleDocTemplate, Spacer,
                                    Table, TableStyle)
    from reportlab.lib import colors

    styles = getSampleStyleSheet()
    hmap = {1: "Heading1", 2: "Heading2", 3: "Heading3"}
    story = []
    if (title or "").strip():
        story += [Paragraph(_pdf_rich(title.strip()), styles["Title"]),
                  Spacer(1, 6 * mm)]
    for b in blocks:
        if b["t"] == "h":
            story.append(Paragraph(_pdf_rich(b["text"]), styles[hmap[b["level"]]]))
        elif b["t"] == "p":
            story.append(Paragraph(_pdf_rich(b["text"]), styles["BodyText"]))
        elif b["t"] in ("ul", "ol"):
            bt = "bullet" if b["t"] == "ul" else "1"
            story.append(ListFlowable(
                [ListItem(Paragraph(_pdf_rich(i), styles["BodyText"]))
                 for i in b["items"]],
                bulletType=bt))
        elif b["t"] == "code":
            story.append(Preformatted(b["text"], styles["Code"]))
        elif b["t"] == "table" and b["rows"]:
            t = Table(b["rows"], hAlign="LEFT")
            t.setStyle(TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ]))
            story.append(t)
        story.append(Spacer(1, 2 * mm))
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, title=title or "Document").build(story)
    return buf.getvalue()
```

- [ ] **Step 4: Run all builder tests**

Run: `python -m pytest tests/test_doc_builder.py -q`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/doc_builder.py mcp-servers/tasks/tests/test_doc_builder.py mcp-servers/tasks/requirements.txt
git commit -m "feat(files): markdown blocks to PDF"
```

---

### Task 4: /files/generate endpoint

**Files:**
- Create: `mcp-servers/tasks/routes_files.py`
- Modify: `mcp-servers/tasks/main.py` (two lines, next to the fusion router)
- Test: `mcp-servers/tasks/tests/test_routes_files.py`

**Interfaces:**
- Consumes: `parse_blocks`, `blocks_to_docx`, `blocks_to_pdf` (Tasks 1-3);
  `_require_internal` (existing, `routes_fusion.py`).
- Produces: `POST /files/generate` request
  `{"title", "markdown", "format": "docx"|"pdf"}` -> response
  `{"filename", "b64", "size", "mime"}`; pure helper
  `build_filename(title: str, fmt: str, now=None) -> str`.

- [ ] **Step 1: Failing tests for the filename helper and caps**

```python
"""/files/generate: pure pieces. Route wiring is verified on the server."""
from datetime import datetime

import pytest

from routes_files import MAX_MD_BYTES, MAX_OUT_BYTES, build_filename


def test_build_filename_sanitizes_and_stamps():
    ts = datetime(2026, 7, 31, 10, 5, 0)
    assert build_filename("Q3 Report: final!", "docx", now=ts) == \
        "Q3_Report__final__20260731_100500.docx"
    assert build_filename("x", "pdf", now=ts).endswith(".pdf")


def test_build_filename_empty_title_defaults():
    ts = datetime(2026, 7, 31, 10, 5, 0)
    assert build_filename("", "pdf", now=ts) == "document_20260731_100500.pdf"


def test_caps_are_spec_values():
    assert MAX_MD_BYTES == 200_000
    assert MAX_OUT_BYTES == 5_000_000
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_routes_files.py -q`
Expected: FAIL (ImportError routes_files)

- [ ] **Step 3: Implement `routes_files.py`**

```python
"""Generate .docx/.pdf from a markdown subset. Internal-only (X-Internal-Secret,
same gate as fusion); consumed by the "Documents" native OWUI tool. Content is
never logged - the log line carries only format and byte sizes."""
import base64
import re
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from doc_builder import blocks_to_docx, blocks_to_pdf, parse_blocks
from routes_fusion import _require_internal

router = APIRouter(prefix="/files")

MAX_MD_BYTES = 200_000
MAX_OUT_BYTES = 5_000_000
MIMES = {
    "docx": ("application/vnd.openxmlformats-officedocument"
             ".wordprocessingml.document"),
    "pdf": "application/pdf",
}


def build_filename(title: str, fmt: str, now: datetime = None) -> str:
    base = re.sub(r"[^\w\-]", "_", (title or "").strip()) or "document"
    ts = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    return f"{base[:80]}_{ts}.{fmt}"


class GenerateBody(BaseModel):
    title: str = Field(default="", max_length=150)
    markdown: str = Field(min_length=1)
    format: Literal["docx", "pdf"]


@router.post("/generate")
async def generate_file(body: GenerateBody,
                        x_internal_secret: str = Header(default="")):
    _require_internal(x_internal_secret)
    if len(body.markdown.encode("utf-8")) > MAX_MD_BYTES:
        raise HTTPException(status_code=413,
                            detail="Document text is too long (200 KB max).")
    blocks = parse_blocks(body.markdown)
    try:
        data = (blocks_to_docx if body.format == "docx" else blocks_to_pdf)(
            body.title, blocks)
    except Exception as e:
        raise HTTPException(status_code=500,
                            detail=f"Could not build the {body.format}: {e}")
    if len(data) > MAX_OUT_BYTES:
        raise HTTPException(status_code=413,
                            detail="Generated file exceeds 5 MB.")
    print(f"[files] generated {body.format} "
          f"({len(body.markdown)} chars in, {len(data)} bytes out)", flush=True)
    return {"filename": build_filename(body.title, body.format),
            "b64": base64.b64encode(data).decode("ascii"),
            "size": len(data),
            "mime": MIMES[body.format]}
```

In `main.py`, next to `from routes_fusion import ...` add:

```python
from routes_files import router as files_router
```

and next to `app.include_router(fusion_router)`:

```python
app.include_router(files_router)   # /files - internal, secret-gated
```

(Find exact anchors with `grep -n "fusion" mcp-servers/tasks/main.py`.)

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_routes_files.py tests/test_doc_builder.py -q`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/routes_files.py mcp-servers/tasks/tests/test_routes_files.py mcp-servers/tasks/main.py
git commit -m "feat(files): internal /files/generate endpoint (docx/pdf)"
```

---

### Task 5: Binary uploads for gdrive_create_file

**Files:**
- Modify: `mcp-servers/gdrive/main.py` (CreateFileInput + body build)
- Create: `mcp-servers/gdrive/tests/__init__.py` (empty)
- Test: `mcp-servers/gdrive/tests/test_multipart.py`

**Interfaces:**
- Produces: `build_multipart(name: str, mime: str, payload: bytes, boundary: str) -> bytes`
  and `CreateFileInput.content_b64: str | None` (base64; wins over `content`).

- [ ] **Step 1: Failing test**

```python
"""Multipart body builder: must handle binary payloads byte-exactly."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from main import build_multipart


def test_build_multipart_binary_payload_intact():
    payload = b"%PDF-\x00\x01\xffbinary"
    body = build_multipart("a.pdf", "application/pdf", payload, "BND")
    assert payload in body                      # bytes not mangled
    assert b'{"name": "a.pdf"}' in body
    assert body.startswith(b"--BND\r\n")
    assert body.endswith(b"--BND--")
    assert b"Content-Type: application/pdf" in body
```

- [ ] **Step 2: Run to verify failure**

Run: `cd mcp-servers/gdrive && python -m pytest tests/test_multipart.py -q`
Expected: FAIL (ImportError build_multipart)

- [ ] **Step 3: Implement**

In `mcp-servers/gdrive/main.py`, extend the input model:

```python
class CreateFileInput(BaseModel):
    name: str = Field(description="File name, e.g. 'notes.txt' or 'summary.md'")
    content: str = Field(default="", description="Text content to write into the file")
    content_b64: str = Field(default="", description="Base64 content for binary files; wins over content")
    mime_type: str = Field(default="text/plain", description="MIME type (default text/plain)")
```

Add the pure builder (above the endpoint):

```python
def build_multipart(name: str, mime: str, payload: bytes, boundary: str) -> bytes:
    """Google Drive multipart/related upload body, safe for binary payloads."""
    meta = json.dumps({"name": name})
    head = (f"--{boundary}\r\n"
            "Content-Type: application/json; charset=UTF-8\r\n\r\n"
            f"{meta}\r\n"
            f"--{boundary}\r\n"
            f"Content-Type: {mime}\r\n\r\n").encode("utf-8")
    return head + payload + f"\r\n--{boundary}--".encode("utf-8")
```

Rewrite the body construction inside `create_file` (replace the current
f-string `body = (...)` block) with:

```python
    if input.content_b64:
        try:
            payload = base64.b64decode(input.content_b64)
        except Exception:
            return {"error": "content_b64 is not valid base64."}
    else:
        payload = input.content.encode("utf-8")
    body = build_multipart(input.name, input.mime_type, payload, boundary)
```

and change the httpx call's `content=body.encode("utf-8")` to `content=body`.
Add `import base64` to the imports if missing.

- [ ] **Step 4: Run test**

Run: `cd mcp-servers/gdrive && python -m pytest tests/test_multipart.py -q`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/gdrive/main.py mcp-servers/gdrive/tests/
git commit -m "feat(gdrive): binary file uploads via content_b64 on gdrive_create_file"
```

---

### Task 6: "Documents" native OWUI tool + installer

**Files:**
- Create: `open-webui-functions/documents_tool.py`
- Create: `scripts/insert_documents_tool.py`

**Interfaces:**
- Consumes: `POST {tasks_url}/files/generate` (Task 4 contract);
  `POST {gdrive_url}/gdrive_create_file` with
  `{"name","content_b64","mime_type"}` + `X-User-Email` header (Task 5).
- Produces: OWUI tool id `documents`, function
  `create_document(title, markdown, format="docx", save_to_drive=False)`.

- [ ] **Step 1: Write the tool**

```python
"""
title: Documents
author: AIUI Team
version: 0.1.0
description: Create real Word (.docx) or PDF files from chat and optionally save them to your Google Drive. Ask for any document, report, letter, or "export this conversation".
"""

# Native Open WebUI tool. The model writes the document content as markdown
# (headings, lists, **bold**, tables); generation happens in the tasks
# service so libraries survive OWUI upgrades. Download is a data: link
# (Excel Creator pattern). Drive save reuses the per-user mcp-gdrive OAuth.

import httpx
from pydantic import BaseModel, Field


class Tools:
    class Valves(BaseModel):
        tasks_url: str = Field(default="http://tasks:8210")
        gdrive_url: str = Field(default="http://mcp-gdrive:8000")
        internal_secret: str = Field(default="")
        timeout_seconds: int = Field(default=60)

    def __init__(self):
        self.valves = self.Valves()

    async def create_document(
        self,
        title: str,
        markdown: str,
        format: str = "docx",
        save_to_drive: bool = False,
        __user__: dict = {},
    ) -> str:
        """
        Create a Word (.docx) or PDF file from markdown content and give the
        user a download button. Use whenever the user asks for a document,
        report, letter, proposal, or to export this conversation as a file.
        Write the full document content yourself in the markdown argument
        (# headings, lists, **bold**, | tables |).

        :param title: Document title, used as the filename and heading.
        :param markdown: The complete document content as markdown.
        :param format: "docx" for Word or "pdf".
        :param save_to_drive: True when the user asks to save it to Google Drive.
        :return: HTML with a download button (and Drive link), or a plain error sentence.
        """
        fmt = "pdf" if str(format).lower().strip() == "pdf" else "docx"
        try:
            async with httpx.AsyncClient(timeout=self.valves.timeout_seconds) as c:
                r = await c.post(
                    f"{self.valves.tasks_url}/files/generate",
                    json={"title": title or "", "markdown": markdown, "format": fmt},
                    headers={"X-Internal-Secret": self.valves.internal_secret},
                )
        except Exception as e:
            return f"Sorry, the document service is unreachable: {e}"
        if r.status_code != 200:
            try:
                detail = r.json().get("detail", "")
            except Exception:
                detail = r.text[:120]
            return f"Sorry, the {fmt} could not be created. {detail}"
        d = r.json()
        label = "Word document" if fmt == "docx" else "PDF"
        kb = max(1, d["size"] // 1024)
        html = (
            '<div style="padding:18px;background:linear-gradient(135deg,#1e3a5f,#2d5a87);'
            'border-radius:12px;color:white;margin:10px 0;">'
            f'<h3 style="margin:0 0 8px 0;">{label} ready: {d["filename"]}</h3>'
            f'<p style="margin:0 0 12px 0;opacity:0.9;">{kb} KB</p>'
            f'<a href="data:{d["mime"]};base64,{d["b64"]}" download="{d["filename"]}" '
            'style="display:inline-block;padding:12px 24px;background:#4CAF50;color:white;'
            'text-decoration:none;border-radius:6px;font-weight:bold;">'
            f'Download {d["filename"]}</a>'
        )
        if save_to_drive:
            email = (__user__ or {}).get("email", "default@local")
            try:
                async with httpx.AsyncClient(timeout=self.valves.timeout_seconds) as c:
                    g = await c.post(
                        f"{self.valves.gdrive_url}/gdrive_create_file",
                        json={"name": d["filename"], "content_b64": d["b64"],
                              "mime_type": d["mime"]},
                        headers={"X-User-Email": email},
                    )
                gd = g.json()
            except Exception as e:
                gd = {"error": f"Google Drive is unreachable: {e}"}
            if gd.get("success"):
                html += (
                    f'<p style="margin:12px 0 0 0;">Saved to your Google Drive: '
                    f'<a href="{gd.get("link", "#")}" target="_blank" '
                    'style="color:#9ecbff;">open in Drive</a></p>'
                )
            else:
                # Not-connected message contains the connect URL; the frontend
                # turns it into the inline Connect button. Pass it through.
                html += ('<p style="margin:12px 0 0 0;">Drive save failed: '
                         f'{gd.get("error", "unknown error")}</p>')
        return html + "</div>"
```

- [ ] **Step 2: Syntax-check the tool**

Run: `python -c "import ast; ast.parse(open('open-webui-functions/documents_tool.py', encoding='utf-8').read()); print('OK')"`
Expected: OK

- [ ] **Step 3: Write the installer**

`scripts/insert_documents_tool.py` (runs ON THE SERVER; uses the OWUI API so
OWUI itself parses the content into tool specs):

```python
"""Install/refresh the "Documents" tool via the OWUI API.

Run on the server:
  OPENWEBUI_API_KEY=sk-... python3 scripts/insert_documents_tool.py
Reads the tool source from open-webui-functions/documents_tool.py, creates or
updates tool id `documents`, then writes its valves (internal secret comes
from the tasks env, never from this file). OWUI computes the function specs
from the content during create/update.
"""
import json
import os
import sys
import urllib.request

BASE = os.environ.get("OPENWEBUI_URL", "http://localhost:3000")
KEY = os.environ.get("OPENWEBUI_API_KEY", "")
SECRET = os.environ.get("INTERNAL_CALLBACK_SECRET", "")
if not KEY:
    sys.exit("OPENWEBUI_API_KEY is required")

src = open(os.path.join(os.path.dirname(__file__), "..",
                        "open-webui-functions", "documents_tool.py"),
           encoding="utf-8").read()


def call(path, payload=None, method="POST"):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Authorization": f"Bearer {KEY}",
                 "Content-Type": "application/json"},
        method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or "{}")


body = {"id": "documents", "name": "Documents", "content": src,
        "meta": {"description": "Create Word/PDF files from chat, save to Drive"},
        "access_control": None}
status, out = call("/api/v1/tools/create", body)
if status != 200:
    status, out = call("/api/v1/tools/id/documents/update", body)
print("tool upsert:", status)

valves = {"tasks_url": "http://tasks:8210",
          "gdrive_url": "http://mcp-gdrive:8000",
          "internal_secret": SECRET, "timeout_seconds": 60}
status, out = call("/api/v1/tools/id/documents/valves/update", valves)
print("valves:", status)
```

- [ ] **Step 4: Syntax-check the installer**

Run: `python -c "import ast; ast.parse(open('scripts/insert_documents_tool.py', encoding='utf-8').read()); print('OK')"`
Expected: OK

- [ ] **Step 5: Commit**

```bash
git add open-webui-functions/documents_tool.py scripts/insert_documents_tool.py
git commit -m "feat(files): Documents native tool (Word/PDF via chat) + installer"
```

---

### Task 7: Deploy and end-to-end verification on prod

**Files:** none new. Server: `root@46.224.193.25`, `/root/proxy-server/`.

- [ ] **Step 1: scp changed files, CRLF-strip, rebuild tasks AND mcp-gdrive**

One scp per file (never `scp -r`): `doc_builder.py`, `routes_files.py`,
`main.py`, `requirements.txt`, both tests, `mcp-servers/gdrive/main.py`,
`mcp-servers/gdrive/tests/*`, `open-webui-functions/documents_tool.py`,
`scripts/insert_documents_tool.py`. Then on the server
`sed -i 's/\r$//'` each, and:

```bash
docker compose -f docker-compose.unified.yml up -d --build tasks mcp-gdrive
```

- [ ] **Step 2: Container tests + endpoint smoke**

```bash
docker exec tasks sh -lc 'cd /app && python -m pytest tests/test_doc_builder.py tests/test_routes_files.py -q'
# expect: 11 passed
docker exec tasks python - <<'PY'
import httpx, os, base64
r = httpx.post("http://localhost:8210/files/generate",
               json={"title": "Smoke", "markdown": "# Hi\n\n- a\n- b", "format": "pdf"},
               headers={"X-Internal-Secret": os.environ["INTERNAL_CALLBACK_SECRET"]})
print(r.status_code, r.json()["filename"], r.json()["size"])
assert base64.b64decode(r.json()["b64"])[:5] == b"%PDF-"
r2 = httpx.post("http://localhost:8210/files/generate",
                json={"title": "x", "markdown": "y", "format": "docx"},
                headers={"X-Internal-Secret": "wrong"})
print("bad secret ->", r2.status_code)   # expect 403
PY
```

- [ ] **Step 3: Install the tool**

```bash
cd /root/proxy-server && OPENWEBUI_API_KEY=<from server env> \
  INTERNAL_CALLBACK_SECRET=<from tasks env> python3 scripts/insert_documents_tool.py
# expect: tool upsert: 200 / valves: 200
```

Verify: tool row exists (`SELECT id, name FROM public.tool`) and specs are
non-empty.

- [ ] **Step 4: Real-chat proof**

In a chat with the Documents tool enabled: "make me a short Word doc titled
Test Doc with a heading and two bullets" -> download button appears, file
opens in Word. Then "make it a PDF and save it to my Drive" -> PDF button +
"Saved to your Google Drive" link that opens. Check tasks logs for
`[files] generated` lines and zero content logging.

- [ ] **Step 5: Push, stamp, memory**

```bash
git push origin main
# update /root/proxy-server/.deploy-state with the new sha (JSON!)
```

Update `MEMORY.md` + the roadmap memory file with the outcome.
