"""Extract readable text from chat/build attachments (PDF, Word, plain text).

Pure and dependency-light so the App Builder chat can READ documents, not just
images:
  - PDF  -> pypdf (pure-python, light)
  - .docx -> zipfile + defusedxml (forbids DTD/entity-expansion bombs)
  - text  -> encoding-aware decode (UTF-16/UTF-8-BOM/cp1252, not UTF-8-only)

Used by the /chat and /enhance attachment loops in routes_tasks.py. Images keep
their existing base64-vision path there; this module never touches images.
"""
from __future__ import annotations

import io
import xml.etree.ElementTree as ET
import zipfile

try:
    # defusedxml forbids DTDs/entity definitions by default, closing the
    # billion-laughs hole regardless of the XML's encoding (UTF-16 etc.).
    from defusedxml.ElementTree import fromstring as _xml_fromstring
except ImportError:  # pragma: no cover - defusedxml is a declared dependency
    _xml_fromstring = ET.fromstring

MAX_DOC_CHARS = 20_000
# Refuse a .docx whose word/document.xml decompresses beyond this — a small
# upload can be a zip bomb that expands to gigabytes and OOMs the host.
MAX_DOCX_UNCOMPRESSED = 30 * 1024 * 1024
# Stop reading a PDF after this many pages (bounds CPU/memory on a hostile or
# huge document; the text is capped to MAX_DOC_CHARS regardless).
MAX_PDF_PAGES = 200

_PDF_MIME = {"application/pdf"}
_DOCX_MIME = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
_TEXT_MIME = {
    "text/plain", "text/markdown", "text/csv", "text/x-markdown",
    "application/json",
}
_TEXT_EXT = (".txt", ".md", ".markdown", ".csv", ".log", ".text", ".json")

_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def classify_document(declared_mime: str | None, head: bytes, filename: str | None) -> str | None:
    """Classify a NON-image attachment as 'pdf' | 'docx' | 'text' | None.

    Magic bytes win over the (spoofable) declared Content-Type. Plain text has
    no magic bytes, so it is recognised by a text/* MIME or a known extension.
    Images are intentionally NOT handled here — the caller's image sniff runs
    first; this returns None for them.
    """
    name = (filename or "").lower()
    declared = (declared_mime or "").lower()

    if head[:4] == b"%PDF" or declared in _PDF_MIME:
        return "pdf"
    # .docx is a zip; require a docx signal (name or MIME) so a bare zip of
    # something else isn't mis-read as a Word document.
    if head[:4] == b"PK\x03\x04" and (name.endswith(".docx") or declared in _DOCX_MIME):
        return "docx"
    if (declared in _TEXT_MIME or declared.startswith("text/")
            or name.endswith(_TEXT_EXT)):
        return "text"
    return None


def extract_text(data: bytes, kind: str, max_chars: int = MAX_DOC_CHARS) -> str:
    """Extract readable text for a document `kind`. Capped to max_chars and
    graceful: returns '' on anything unparseable (e.g. scanned/image-only PDF,
    corrupt file). The caller decides what to say when the result is empty."""
    if kind == "pdf":
        text = _extract_pdf(data, max_chars)
    elif kind == "docx":
        text = _extract_docx(data)
    elif kind == "text":
        text = _decode_text(data)
    else:
        text = ""

    text = text.strip()
    if not text:
        return ""
    if len(text) > max_chars:
        marker = "\n[... truncated]"
        text = text[: max(0, max_chars - len(marker))].rstrip() + marker
    return text


def _decode_text(data: bytes) -> str:
    """Decode a text file, honouring common Windows encodings (UTF-16/-BOM,
    UTF-8-BOM, cp1252) instead of mangling them via a hard-coded UTF-8."""
    if data[:3] == b"\xef\xbb\xbf":
        return data.decode("utf-8-sig", errors="replace")
    if data[:4] != b"\xff\xfe\x00\x00" and data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", errors="replace")  # BOM picks endianness + is stripped
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def _extract_pdf(data: bytes, max_chars: int = MAX_DOC_CHARS) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    try:
        reader = PdfReader(io.BytesIO(data))
        out: list[str] = []
        total = 0
        for page in reader.pages[:MAX_PDF_PAGES]:
            t = page.extract_text() or ""
            out.append(t)
            total += len(t)
            if total >= max_chars:  # enough text — stop before walking every page
                break
        return "\n".join(out)
    except Exception:
        return ""


def _extract_docx(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            info = z.getinfo("word/document.xml")
            if info.file_size > MAX_DOCX_UNCOMPRESSED:
                return ""  # decompression-bomb guard
            xml = z.read("word/document.xml")
        # A legit .docx never carries a DTD; a DOCTYPE/ENTITY is an
        # entity-expansion bomb (billion laughs) that the size guard misses.
        if b"<!DOCTYPE" in xml or b"<!ENTITY" in xml:
            return ""
        root = _xml_fromstring(xml)  # forbids DTDs in any encoding
    except Exception:
        return ""
    paragraphs: list[str] = []
    for p in root.iter(f"{_W_NS}p"):
        runs = [t.text for t in p.iter(f"{_W_NS}t") if t.text]
        if runs:
            paragraphs.append("".join(runs))
    return "\n".join(paragraphs)
