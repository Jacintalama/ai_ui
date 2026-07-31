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
    blocks, para, code = [], [], []
    in_code = False

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


def _pdf_rich(text: str) -> str:
    """Escape XML, then map **bold** to <b> for reportlab paragraphs."""
    from xml.sax.saxutils import escape
    parts = []
    for seg, bold in split_bold(text):
        seg = escape(seg)
        parts.append(f"<b>{seg}</b>" if bold else seg)
    return "".join(parts)


def blocks_to_pdf(title: str, blocks: list) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (ListFlowable, ListItem, Paragraph,
                                    Preformatted, SimpleDocTemplate, Spacer,
                                    Table, TableStyle)

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
