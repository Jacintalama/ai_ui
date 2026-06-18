"""Pure text extraction for chat/build document attachments (no DB, no API).

Lets the App Builder chat read PDF / Word / plain-text attachments, not just
images. PDF via pypdf; .docx via stdlib zip+xml; text by decode. (2026-06-18.)
"""
import io
import zipfile

from document_extract import classify_document, extract_text, MAX_DOC_CHARS


# --- fixtures (self-contained; no external files / generators) --------------

def _make_pdf(text: str) -> bytes:
    """A valid minimal one-page PDF with correct xref offsets + startxref."""
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        None,
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    stream = b"BT /F1 24 Tf 72 720 Td (" + text.encode("latin-1") + b") Tj ET"
    objs[3] = (b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n"
               + stream + b"\nendstream")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += str(i).encode() + b" 0 obj\n" + body + b"\nendobj\n"
    xref_pos = len(out)
    out += b"xref\n0 " + str(len(objs) + 1).encode() + b"\n0000000000 65535 f \n"
    for off in offsets:
        out += ("%010d 00000 n \n" % off).encode()
    out += (b"trailer\n<< /Root 1 0 R /Size " + str(len(objs) + 1).encode()
            + b" >>\nstartxref\n" + str(xref_pos).encode() + b"\n%%EOF\n")
    return bytes(out)


def _make_docx(paragraphs: list[str]) -> bytes:
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    doc = (f'<?xml version="1.0"?><w:document xmlns:w="{ns}">'
           f"<w:body>{body}</w:body></w:document>")
    return _make_docx_raw(doc)


def _make_docx_raw(document_xml: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", document_xml)
    return buf.getvalue()


# --- classify ---------------------------------------------------------------

def test_classify_pdf_by_magic_bytes():
    assert classify_document("application/octet-stream", b"%PDF-1.7\n...", "x") == "pdf"
    assert classify_document("application/pdf", b"%PDF-1.4", "report.pdf") == "pdf"


def test_classify_docx_requires_zip_and_docx_signal():
    zip_head = b"PK\x03\x04\x14\x00"
    assert classify_document(None, zip_head, "notes.docx") == "docx"
    docx_mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert classify_document(docx_mime, zip_head, "blob") == "docx"
    # a bare zip with no docx signal is NOT treated as a document
    assert classify_document("application/zip", zip_head, "archive.zip") is None


def test_classify_text_by_mime_or_extension():
    assert classify_document("text/plain", b"hello", "a.txt") == "text"
    assert classify_document("text/markdown", b"# hi", "README.md") == "text"
    assert classify_document(None, b"a,b,c", "data.csv") == "text"
    assert classify_document(None, b"plain", "notes.md") == "text"


def test_classify_rejects_images_and_junk():
    assert classify_document("image/png", b"\x89PNG\r\n\x1a\n", "x.png") is None
    assert classify_document("application/octet-stream", b"\x00\x01\x02\x03", "x.bin") is None


# --- extract ----------------------------------------------------------------

def test_extract_pdf_text():
    out = extract_text(_make_pdf("Hello PDF document"), "pdf")
    assert "Hello PDF document" in out


def test_extract_docx_joins_paragraphs():
    out = extract_text(_make_docx(["First para", "Second para"]), "docx")
    assert "First para" in out and "Second para" in out


def test_extract_text_decodes_utf8():
    assert extract_text("café — ok".encode("utf-8"), "text") == "café — ok"


def test_extract_text_handles_non_utf8_encodings():
    """Windows CSV/Notepad exports are often UTF-16, cp1252, or UTF-8-BOM —
    they must not silently garble into replacement chars."""
    assert extract_text(b"\xff\xfe" + "Héllo".encode("utf-16-le"), "text") == "Héllo"
    assert extract_text("café".encode("cp1252"), "text") == "café"
    assert extract_text(b"\xef\xbb\xbf" + b"hi", "text") == "hi"  # UTF-8 BOM stripped


def test_extract_docx_rejects_dtd_entity_bomb():
    """A 'billion laughs' DOCTYPE/ENTITY in document.xml passes the byte-size
    guard but expands during parsing — reject it outright (legit .docx never
    contains a DTD)."""
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    evil = (
        '<?xml version="1.0"?>'
        '<!DOCTYPE w:document [<!ENTITY lol "lololol">]>'
        f'<w:document xmlns:w="{ns}"><w:body>'
        '<w:p><w:r><w:t>&lol;</w:t></w:r></w:p></w:body></w:document>'
    )
    assert extract_text(_make_docx_raw(evil), "docx") == ""


def test_extract_docx_rejects_utf16_dtd_bomb():
    """A UTF-16-encoded document.xml hides the <!DOCTYPE marker behind null
    bytes, defeating a naive byte-scan — a real forbid-DTD parser must reject
    it regardless of encoding."""
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    evil = (
        '<?xml version="1.0" encoding="UTF-16"?>'
        '<!DOCTYPE w:document [<!ENTITY lol "lol">]>'
        f'<w:document xmlns:w="{ns}"><w:body>'
        '<w:p><w:r><w:t>&lol;</w:t></w:r></w:p></w:body></w:document>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", evil.encode("utf-16"))
    assert extract_text(buf.getvalue(), "docx") == ""


def test_extract_garbage_pdf_is_graceful():
    assert extract_text(b"not really a pdf", "pdf") == ""


def test_extract_empty_docx_is_graceful():
    assert extract_text(b"not a zip", "docx") == ""


def test_extract_truncates_oversized_text():
    out = extract_text(b"x" * (MAX_DOC_CHARS + 5000), "text")
    # Must NOT exceed the cap — the truncation marker has to fit WITHIN it, or
    # downstream attachment_text fields (max_length=20000) 422 on big docs.
    assert len(out) <= MAX_DOC_CHARS
    assert "truncated" in out.lower()


def test_extract_docx_refuses_decompression_bomb(monkeypatch):
    """A small .docx can decompress to gigabytes — guard the uncompressed size
    so a malicious upload can't OOM the host."""
    import document_extract as de
    monkeypatch.setattr(de, "MAX_DOCX_UNCOMPRESSED", 500)
    big = de.extract_text(_make_docx(["word " * 5000]), "docx")  # >500 B uncompressed
    assert big == ""
    # under the cap, a normal doc still extracts
    ok = de.extract_text(_make_docx(["hello world"]), "docx")
    assert "hello world" in ok
