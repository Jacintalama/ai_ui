"""Project file/dependency graph for the Tests tab.

Walks `apps/<slug>/` and parses files with fast regex (no AST) to surface
which file references which. The frontend renders the result as a layered
SVG bubble graph. See `docs/2026-04-27-feature-graph.md` and the spec in
the PR description for the wire format.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException

from auth import AdminUser, current_admin, current_admin_or_capability_for_slug
from db import session
from routes_projects import _require_role, _user_can_see_project, _validate_slug

router = APIRouter(prefix="/api/projects")

REPO_ROOT = os.environ.get("CLAUDE_WORKSPACE", "/workspace/ai_ui")
APPS_DIR = os.path.join(REPO_ROOT, "apps")

# Hard cap on files walked per request — keeps regex parsing bounded even
# if a future build dumps hundreds of generated files into the app dir.
MAX_FILES_WALKED = 200

# Skip these directories anywhere in the tree.
_SKIP_DIRS = frozenset({
    "node_modules", "__pycache__", ".git", "data", ".next",
    ".cache", "dist", "build", ".venv", "venv",
})

# Map file extensions to node "type" buckets.
_EXT_TO_TYPE: dict[str, str] = {
    ".html": "html",
    ".htm":  "html",
    ".css":  "css",
    ".js":   "js",
    ".mjs":  "js",
    ".sql":  "sql",
}

# Patterns ----------------------------------------------------------------
_HTML_SCRIPT_RE = re.compile(r'<script[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)
_HTML_LINK_RE = re.compile(r'<link[^>]+href=["\']([^"\']+)["\']', re.IGNORECASE)

# JS imports — covers `import x from "..."`, `import "..."`, and dynamic
# `import("...")`. Captures group 1 = the module specifier.
_JS_IMPORT_RE = re.compile(
    r"""(?:^|\s|;)
        import
        (?:\s+[\w*{}\s,]+\s+from)?
        \s*
        ["']([^"']+)["']
    """,
    re.VERBOSE | re.MULTILINE,
)
_JS_DYNAMIC_IMPORT_RE = re.compile(r"""import\s*\(\s*["']([^"']+)["']\s*\)""")
_JS_FETCH_RE = re.compile(r"""fetch\s*\(\s*["'](/api/[^"']+)["']""")
# Anything mentioning supabase OR a createClient(SUPABASE_URL, ...) call.
_JS_SUPABASE_RE = re.compile(r"""(?:createClient\s*\(\s*[A-Za-z_$][\w$]*\s*,|supabase)""", re.IGNORECASE)

_CSS_IMPORT_RE = re.compile(r"""@import\s+url\(\s*["']?([^"')]+)["']?\s*\)""", re.IGNORECASE)


def _is_external_url(spec: str) -> bool:
    """True iff the spec looks like a remote URL or protocol-relative URL."""
    s = spec.strip().lower()
    return (
        s.startswith("http://")
        or s.startswith("https://")
        or s.startswith("//")
        or s.startswith("data:")
    )


def _cdn_label(url: str) -> str:
    """Short label for a CDN URL, e.g. 'cdn.tailwindcss.com' → 'Tailwind CDN'."""
    u = url.lower()
    if "tailwindcss.com" in u or "tailwind" in u:
        return "Tailwind CDN"
    if "supabase" in u:
        return "Supabase"
    if "jsdelivr.net" in u:
        return "jsDelivr CDN"
    if "unpkg.com" in u:
        return "unpkg CDN"
    if "fonts.googleapis.com" in u or "fonts.gstatic.com" in u:
        return "Google Fonts"
    if "cdnjs.cloudflare.com" in u:
        return "cdnjs"
    # Strip protocol + path, return host
    host = re.sub(r"^https?://", "", url, flags=re.IGNORECASE).split("/")[0]
    return host or "external"


def _normalize_relative(base_dir: str, app_root: str, spec: str) -> str | None:
    """Resolve a relative module specifier to a forward-slash app-relative path.

    base_dir / spec are file-system paths. Returns the path relative to
    app_root with forward slashes, or None if the result escapes app_root.
    """
    if _is_external_url(spec):
        return None
    if spec.startswith("/"):
        # Absolute server path — treat as escape (we only graph in-tree files).
        return None
    target = os.path.normpath(os.path.join(base_dir, spec))
    try:
        rel = os.path.relpath(target, app_root)
    except ValueError:
        return None
    if rel.startswith(".."):
        return None
    return rel.replace(os.sep, "/")


@dataclass(frozen=True)
class _Node:
    id: str
    type: str
    label: str


def _label_for(rel_path: str) -> str:
    """Human label for a node id (file path)."""
    # Show the deepest-2 segments (e.g. 'lib/supabase.js') for files in nested
    # dirs; just the basename for top-level.
    parts = rel_path.split("/")
    if len(parts) <= 2:
        return parts[-1]
    return "/".join(parts[-2:])


def _walk_app_dir(app_root: str) -> list[str]:
    """Return up-to-MAX_FILES_WALKED app-relative file paths inside app_root."""
    found: list[str] = []
    if not os.path.isdir(app_root):
        return found
    for dirpath, dirnames, filenames in os.walk(app_root):
        # Mutate dirnames in place to skip excluded subtrees.
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            try:
                rel = os.path.relpath(full, app_root).replace(os.sep, "/")
            except ValueError:
                continue
            found.append(rel)
            if len(found) >= MAX_FILES_WALKED:
                return found
    return found


def _read_text(path: str, max_bytes: int = 200_000) -> str:
    """Read a file as text, capped to max_bytes. Returns '' on any error."""
    try:
        with open(path, "rb") as f:
            data = f.read(max_bytes)
        return data.decode("utf-8", errors="replace")
    except OSError:
        return ""


def _build_graph(app_root: str) -> dict:
    """Walk app_root, parse files, return {nodes, edges} dict.

    Nodes are deduped by id; edges are deduped by (from, to, kind).
    """
    nodes: dict[str, _Node] = {}
    edges: list[dict] = []
    seen_edges: set[tuple[str, str, str]] = set()

    def add_node(node_id: str, ntype: str, label: str) -> None:
        if node_id not in nodes:
            nodes[node_id] = _Node(id=node_id, type=ntype, label=label)

    def add_edge(src: str, dst: str, kind: str) -> None:
        key = (src, dst, kind)
        if key in seen_edges:
            return
        seen_edges.add(key)
        edges.append({"from": src, "to": dst, "kind": kind})

    files = _walk_app_dir(app_root)

    # First pass: register every walked file as a node so later cross-refs
    # have something to link to.
    for rel in files:
        ext = os.path.splitext(rel)[1].lower()
        ntype = _EXT_TO_TYPE.get(ext)
        if ntype is None:
            continue
        add_node(rel, ntype, _label_for(rel))

    # Second pass: parse and emit edges.
    for rel in files:
        ext = os.path.splitext(rel)[1].lower()
        ntype = _EXT_TO_TYPE.get(ext)
        if ntype is None:
            continue
        full = os.path.join(app_root, rel)
        text = _read_text(full)
        if not text:
            continue
        base_dir = os.path.dirname(full)

        if ntype == "html":
            for m in _HTML_SCRIPT_RE.finditer(text):
                spec = m.group(1)
                if _is_external_url(spec):
                    ext_id = "@cdn:" + _cdn_label(spec)
                    add_node(ext_id, "external", _cdn_label(spec))
                    add_edge(rel, ext_id, "external")
                else:
                    target = _normalize_relative(base_dir, app_root, spec)
                    if target:
                        # Make sure the target node exists (may not have been
                        # walked if it's a missing file — show as broken-ish
                        # leaf with type js by extension guess).
                        if target not in nodes:
                            t_ext = os.path.splitext(target)[1].lower()
                            t_type = _EXT_TO_TYPE.get(t_ext, "js")
                            add_node(target, t_type, _label_for(target))
                        add_edge(rel, target, "script")
            for m in _HTML_LINK_RE.finditer(text):
                spec = m.group(1)
                if _is_external_url(spec):
                    ext_id = "@cdn:" + _cdn_label(spec)
                    add_node(ext_id, "external", _cdn_label(spec))
                    add_edge(rel, ext_id, "external")
                else:
                    target = _normalize_relative(base_dir, app_root, spec)
                    if target:
                        if target not in nodes:
                            t_ext = os.path.splitext(target)[1].lower()
                            t_type = _EXT_TO_TYPE.get(t_ext, "css")
                            add_node(target, t_type, _label_for(target))
                        add_edge(rel, target, "stylesheet")

        elif ntype == "js":
            for m in _JS_IMPORT_RE.finditer(text):
                spec = m.group(1)
                if _is_external_url(spec):
                    ext_id = "@cdn:" + _cdn_label(spec)
                    add_node(ext_id, "external", _cdn_label(spec))
                    add_edge(rel, ext_id, "external")
                else:
                    target = _normalize_relative(base_dir, app_root, spec)
                    if target:
                        if target not in nodes:
                            t_ext = os.path.splitext(target)[1].lower()
                            t_type = _EXT_TO_TYPE.get(t_ext, "js")
                            add_node(target, t_type, _label_for(target))
                        add_edge(rel, target, "import")
            for m in _JS_DYNAMIC_IMPORT_RE.finditer(text):
                spec = m.group(1)
                if _is_external_url(spec):
                    ext_id = "@cdn:" + _cdn_label(spec)
                    add_node(ext_id, "external", _cdn_label(spec))
                    add_edge(rel, ext_id, "external")
                else:
                    target = _normalize_relative(base_dir, app_root, spec)
                    if target:
                        if target not in nodes:
                            t_ext = os.path.splitext(target)[1].lower()
                            t_type = _EXT_TO_TYPE.get(t_ext, "js")
                            add_node(target, t_type, _label_for(target))
                        add_edge(rel, target, "import")
            for m in _JS_FETCH_RE.finditer(text):
                api_path = m.group(1)
                api_id = "@api:" + api_path
                add_node(api_id, "api", api_path)
                add_edge(rel, api_id, "api")
            if _JS_SUPABASE_RE.search(text):
                add_node("@supabase", "external", "Supabase")
                add_edge(rel, "@supabase", "external")

        elif ntype == "css":
            for m in _CSS_IMPORT_RE.finditer(text):
                spec = m.group(1)
                if _is_external_url(spec):
                    ext_id = "@cdn:" + _cdn_label(spec)
                    add_node(ext_id, "external", _cdn_label(spec))
                    add_edge(rel, ext_id, "external")
                else:
                    target = _normalize_relative(base_dir, app_root, spec)
                    if target:
                        if target not in nodes:
                            t_ext = os.path.splitext(target)[1].lower()
                            t_type = _EXT_TO_TYPE.get(t_ext, "css")
                            add_node(target, t_type, _label_for(target))
                        add_edge(rel, target, "import")
        # SQL: just a node, no outgoing edges.

    return {
        "nodes": [
            {"id": n.id, "type": n.type, "label": n.label}
            for n in nodes.values()
        ],
        "edges": edges,
    }


@router.get("/{slug}/graph")
async def get_project_graph(slug: str, user: AdminUser = Depends(current_admin_or_capability_for_slug)) -> dict:
    """Return a {nodes, edges} graph of the project's file structure."""
    _validate_slug(slug)
    async with session() as s:
        if not await _user_can_see_project(s, slug, user.email):
            raise HTTPException(status_code=403, detail="Not a member of this project")
        await _require_role(s, slug, user.email, "viewer", is_admin=user.is_admin)

    app_root = os.path.join(APPS_DIR, slug)
    return _build_graph(app_root)
