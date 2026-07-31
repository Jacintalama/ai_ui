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
