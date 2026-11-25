"""Figma: a design's link made into what Figma's REST API takes, and a
design's JSON made into something a model can build from.

Pure, like calendly_args and github_refs, so every rule is tested with no
vendor and no network (tests/test_figma_is_a_connector.py).

Read off Figma's REST API docs on 2026-11-25, and each of these matters:

- THERE IS NO WAY TO LIST SOMEBODY'S FILES. Figma says it is not possible
  to get a team id through the API, so every tool starts from a file's
  link, which a person copies out of Figma. The file key and the frame are
  both in that link (figma.com/design/<key>/<name>?node-id=1-2), and the
  frame is written 1-2 in a link but 1:2 in the API.
- READING A DESIGN IS RATIONED. Since 2025-11-17 the endpoints that read a
  design (file, nodes, images: Figma's "Tier 1") are capped by seat and
  plan: a file on the free Starter plan allows about 6 reads a MONTH, and a
  View or Collab seat about 20. A paid Full or Dev seat gets 10 to 20 a
  minute. So one read has to carry as much as it can, and the outline here
  is built to be read once.
- A FRAME'S JSON IS ENORMOUS: every node carries its geometry, paints,
  effects and constraints. What a build needs is the tree with names,
  sizes, auto-layout, colours, fonts and the words, so that is all the
  outline keeps, one line per layer.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

#: What a personal access token needs ticked. Figma's scope ids.
SCOPES = ("current_user:read", "file_content:read", "file_metadata:read",
          "file_comments:read", "file_comments:write")

#: The most of an outline handed to a model. A big frame is thousands of
#: layers; past this the answer says what was cut and how to ask for less.
MAX_OUTLINE_CHARS = 20_000

#: Frames listed per page in a file's outline.
MAX_FRAMES_PER_PAGE = 60

#: The longest piece of text kept from one text layer.
MAX_TEXT = 200

_KEY = re.compile(r"^[A-Za-z0-9]{10,64}$")
_NODE = re.compile(r"^I?\d+[:-]\d+(;\d+[:-]\d+)*$")
_FILE_KINDS = ("file", "design", "proto", "board", "slides", "make", "deck",
               "site")


def from_link(value: Any) -> Tuple[str, str]:
    """(file key, node id) out of a Figma link or a bare key. The node id is
    "" when the link names none. A branch link gives the branch's key,
    which is the file that branch's frames live in."""
    text = str(value or "").strip()
    if not text:
        return "", ""
    if _KEY.match(text):
        return text, ""
    url = urlparse(text if "://" in text else "https://" + text)
    if not url.netloc.lower().endswith("figma.com"):
        return "", ""
    parts = [p for p in url.path.split("/") if p]
    key = ""
    if len(parts) >= 2 and parts[0].lower() in _FILE_KINDS:
        key = parts[1]
        # figma.com/design/<key>/branch/<branch key>/<name>: the branch's
        # frames live in the branch's own file. Looked for anywhere after
        # the key, so a link with the name first reads the same.
        lowered = [x.lower() for x in parts]
        if "branch" in lowered[2:]:
            at = lowered.index("branch", 2)
            if at + 1 < len(parts):
                key = parts[at + 1]
    node = ""
    ids = parse_qs(url.query).get("node-id")
    if ids:
        node = node_id(ids[0])
    return (key if _KEY.match(key) else ""), node


def node_id(value: Any) -> str:
    """A node id as the API writes it: a link's 1-2 is the API's 1:2."""
    text = unquote(str(value or "").strip())
    if not _NODE.match(text):
        return ""
    return text.replace("-", ":")


def node_ids(value: Any) -> List[str]:
    """Several node ids, from a list, a comma string, or links."""
    items = value if isinstance(value, (list, tuple)) else \
        re.split(r"[,\s]+", str(value or ""))
    out: List[str] = []
    for item in items:
        item = str(item).strip()
        if not item:
            continue
        found = node_id(item) or from_link(item)[1]
        if found and found not in out:
            out.append(found)
    return out


# --- the outline ------------------------------------------------------------

def _hex(color: Dict[str, Any], opacity: Any = None) -> str:
    try:
        r, g, b = (round(float(color.get(k, 0)) * 255) for k in "rgb")
    except (TypeError, ValueError):
        return ""
    out = "#%02X%02X%02X" % (r, g, b)
    alpha = float(color.get("a", 1) or 0)
    if opacity is not None:
        try:
            alpha *= float(opacity)
        except (TypeError, ValueError):
            pass
    return out if alpha >= 0.995 else "%s %d%%" % (out, round(alpha * 100))


def _paint(paints: Any) -> str:
    """The first visible paint, said briefly."""
    for p in paints if isinstance(paints, list) else []:
        if not isinstance(p, dict) or p.get("visible") is False:
            continue
        kind = str(p.get("type") or "")
        if kind == "SOLID" and isinstance(p.get("color"), dict):
            return _hex(p["color"], p.get("opacity"))
        if kind == "IMAGE":
            return "image"
        if kind.startswith("GRADIENT"):
            stops = [_hex(s.get("color") or {}) for s in p.get("gradientStops") or []
                     if isinstance(s, dict)]
            return "gradient " + " to ".join(s for s in stops[:3] if s)
    return ""


def _num(v: Any) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return ""
    return str(int(f)) if f == int(f) else ("%.1f" % f)


def describe(node: Dict[str, Any]) -> str:
    """One layer, in one line: kind, name, size, layout, paint, text."""
    kind = str(node.get("type") or "?")
    bits = [kind, '"%s"' % str(node.get("name") or "").replace('"', "'")]
    box = node.get("absoluteBoundingBox") or {}
    if isinstance(box, dict) and box.get("width") is not None:
        bits.append("%sx%s" % (_num(box.get("width")), _num(box.get("height"))))
    mode = node.get("layoutMode")
    if mode in ("HORIZONTAL", "VERTICAL"):
        layout = "row" if mode == "HORIZONTAL" else "column"
        if node.get("layoutWrap") == "WRAP":
            layout += " wrap"
        if node.get("itemSpacing"):
            layout += " gap " + _num(node["itemSpacing"])
        pads = [node.get("padding" + s) or 0 for s in
                ("Top", "Right", "Bottom", "Left")]
        if any(pads):
            layout += " pad " + " ".join(_num(p) for p in pads)
        align = node.get("primaryAxisAlignItems")
        if align and align != "MIN":
            layout += " justify " + str(align).lower()
        cross = node.get("counterAxisAlignItems")
        if cross and cross != "MIN":
            layout += " align " + str(cross).lower()
        bits.append(layout)
    if kind != "TEXT":
        fill = _paint(node.get("fills"))
        if fill:
            bits.append("fill " + fill)
    stroke = _paint(node.get("strokes"))
    if stroke and node.get("strokeWeight"):
        bits.append("border %s %s" % (_num(node["strokeWeight"]), stroke))
    if node.get("cornerRadius"):
        bits.append("radius " + _num(node["cornerRadius"]))
    if any(isinstance(e, dict) and e.get("visible") is not False
           and "SHADOW" in str(e.get("type")) for e in node.get("effects") or []):
        bits.append("shadow")
    if kind == "TEXT":
        words = " ".join(str(node.get("characters") or "").split())
        if len(words) > MAX_TEXT:
            words = words[:MAX_TEXT].rstrip() + "..."
        bits.append('text "%s"' % words.replace('"', "'"))
        style = node.get("style") or {}
        if isinstance(style, dict):
            font = " ".join(x for x in (
                str(style.get("fontFamily") or ""),
                _num(style.get("fontSize")) + (
                    "/" + _num(style["lineHeightPx"])
                    if style.get("lineHeightPx") else ""),
                _num(style.get("fontWeight"))) if x)
            if font:
                bits.append("font " + font)
            if style.get("textAlignHorizontal") not in (None, "LEFT"):
                bits.append("align " + str(style["textAlignHorizontal"]).lower())
        color = _paint(node.get("fills"))
        if color:
            bits.append("color " + color)
    bits.append("[%s]" % node.get("id", ""))
    return " ".join(b for b in bits if b)


def outline(node: Any, budget: int = MAX_OUTLINE_CHARS) -> str:
    """The layer tree under `node`, one line per visible layer, indented by
    depth, cut at `budget` characters with a line saying how much was left
    out and what to ask for instead."""
    if not isinstance(node, dict):
        return ""
    lines: List[str] = []
    used, cut = 0, 0
    stack = [(node, 0)]
    while stack:
        current, depth = stack.pop()
        if not isinstance(current, dict) or current.get("visible") is False:
            continue
        line = "  " * depth + describe(current)
        if used + len(line) + 1 > budget:
            cut += 1 + _count(current.get("children"))
            continue
        lines.append(line)
        used += len(line) + 1
        kids = current.get("children")
        if isinstance(kids, list):
            stack.extend((k, depth + 1) for k in reversed(kids))
    if cut:
        lines.append("... %d more layers were left out. Ask for one of the "
                     "frames above by its id for the rest." % cut)
    return "\n".join(lines)


def _count(children: Any) -> int:
    if not isinstance(children, list):
        return 0
    return sum(1 + _count(c.get("children")) for c in children
               if isinstance(c, dict))


def file_outline(payload: Any) -> Any:
    """A file's pages and the frames on each, from GET /v1/files at depth 2."""
    if not isinstance(payload, dict) or not isinstance(payload.get("document"), dict):
        return payload
    pages = []
    for page in payload["document"].get("children") or []:
        if not isinstance(page, dict):
            continue
        kids = [k for k in page.get("children") or []
                if isinstance(k, dict) and k.get("visible") is not False]
        frames = []
        for k in kids[:MAX_FRAMES_PER_PAGE]:
            box = k.get("absoluteBoundingBox") or {}
            frames.append({"id": k.get("id"), "name": k.get("name"),
                           "type": k.get("type"),
                           "size": "%sx%s" % (_num(box.get("width")),
                                              _num(box.get("height")))
                           if isinstance(box, dict) and box else ""})
        entry = {"id": page.get("id"), "name": page.get("name"),
                 "frames": frames}
        if len(kids) > MAX_FRAMES_PER_PAGE:
            entry["more_frames"] = len(kids) - MAX_FRAMES_PER_PAGE
        pages.append(entry)
    return {"name": payload.get("name"),
            "last_modified": payload.get("lastModified"),
            "editor": payload.get("editorType"), "pages": pages}


def nodes_outline(payload: Any) -> Any:
    """Each asked-for frame as an outline, from GET /v1/files/:key/nodes.
    A frame the file does not have comes back null from Figma and is said
    to be missing rather than dropped."""
    if not isinstance(payload, dict) or not isinstance(payload.get("nodes"), dict):
        return payload
    out: Dict[str, Any] = {"file": payload.get("name"), "frames": []}
    budget = MAX_OUTLINE_CHARS
    for nid, entry in payload["nodes"].items():
        doc = entry.get("document") if isinstance(entry, dict) else None
        if not isinstance(doc, dict):
            out["frames"].append({"id": nid, "missing": True})
            continue
        text = outline(doc, budget=max(budget, 2_000))
        budget -= len(text)
        out["frames"].append({"id": nid, "name": doc.get("name"),
                              "outline": text})
    return out


def images(payload: Any) -> Any:
    """{node id: picture link}, saying which frames Figma could not draw.
    The links last 30 days."""
    if not isinstance(payload, dict) or not isinstance(payload.get("images"), dict):
        return payload
    drawn = {k: v for k, v in payload["images"].items() if v}
    failed = [k for k, v in payload["images"].items() if not v]
    out: Dict[str, Any] = {"images": drawn,
                           "note": "Picture links last 30 days."}
    if failed:
        out["could_not_draw"] = failed
    return out


def comments(payload: Any) -> Any:
    if isinstance(payload, dict) and isinstance(payload.get("comments"), list):
        rows = []
        for c in payload["comments"]:
            if not isinstance(c, dict):
                continue
            meta = c.get("client_meta") if isinstance(c.get("client_meta"), dict) else {}
            rows.append({"id": c.get("id"), "message": c.get("message"),
                         "by": (c.get("user") or {}).get("handle")
                         if isinstance(c.get("user"), dict) else None,
                         "at": c.get("created_at"),
                         "resolved": bool(c.get("resolved_at")),
                         "reply_to": c.get("parent_id") or None,
                         "on_frame": meta.get("node_id")})
        return rows
    return payload


def comment_body(args: Dict[str, Any]) -> Dict[str, Any]:
    message = str((args or {}).get("message") or "").strip()
    if not message:
        raise ValueError("Say what the comment says, in message.")
    body: Dict[str, Any] = {"message": message}
    reply = str((args or {}).get("reply_to") or "").strip()
    if reply:
        body["comment_id"] = reply
    return body


#: The tools whose path or query names frames.
NAMES_FRAMES = frozenset({"get_frame", "get_frame_image"})


async def prepare(tool_name: str, args: Dict[str, Any], get=None
                  ) -> Tuple[Dict[str, Any], Optional[str]]:
    """The file key and frame ids out of whatever the model was given.

    Reads nothing: everything needed is in the link.
    """
    args = dict(args or {})
    if "file" not in args and "file_key" not in args:
        return args, None
    key, node = from_link(args.get("file") or args.get("file_key"))
    if not key:
        return args, ("That is not a Figma file link. Copy the link from "
                      "Figma (Share, Copy link, or right-click a frame, Copy "
                      "link to selection) and paste it as it is.")
    args["file_key"] = key
    if tool_name in NAMES_FRAMES:
        ids = node_ids(args.get("frames")) or ([node] if node else [])
        if not ids:
            return args, ("Say which frame: paste a link to it (right-click "
                          "the frame in Figma, Copy link to selection), or "
                          "give its id from get_file.")
        args["ids"] = ",".join(ids[:10])
    return args, None
