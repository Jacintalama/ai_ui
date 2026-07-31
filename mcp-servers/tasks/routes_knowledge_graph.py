"""Per-user knowledge graph ("Brain"). Phase 1: store + read.

Nodes are strictly per-user (scoped by the signed-in email). See
docs/superpowers/specs/2026-07-27-user-knowledge-graph-design.md and the
Phase 1 plan. Build-from-chats lives in this module too (added in Task 2).
"""
import asyncio
import json
import os
import re
import time
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import graph_embeddings
from auth import current_user, CurrentUser

router = APIRouter(prefix="/graph/mine")

DATABASE_URL = os.environ.get("DATABASE_URL", "")
OPENAI_URL = os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
MAX_NODES = 800  # cap per user to bound RAM/render cost on the small box
MAX_CHATS = 30   # most-recent conversations to build from
CLUSTER_MODEL = os.environ.get("GRAPH_CLUSTER_MODEL", "gpt-4o")


def _first_sk(value: str) -> str:
    """OWUI may store several keys joined by ';'. Pick the first real sk- key."""
    for part in (value or "").split(";"):
        part = part.strip()
        if part.startswith("sk-"):
            return part
    return (value or "").strip()


# --- pure helpers (unit tested, no I/O) --------------------------------------
def cap_nodes(nodes: list, limit: int = MAX_NODES):
    """Return (capped_nodes, truncated). Preserves order, so roots/topics
    (inserted first) survive when a user's graph is huge."""
    if len(nodes) <= limit:
        return nodes, False
    return nodes[:limit], True


def build_links(nodes: list) -> list:
    """Turn parent_id references into {source, target} links. Roots (no
    parent) and dangling parents are skipped, so the graph never references a
    node that was capped away."""
    ids = {n["id"] for n in nodes}
    links = []
    for n in nodes:
        parent = n.get("parent_id")
        if parent and parent in ids:
            links.append({"source": parent, "target": n["id"]})
    return links


# --- retrieval / memory context (pure, unit tested) --------------------------
# Very common words carry no signal for matching a short chat message against
# node labels/summaries, so we drop them before scoring.
_STOPWORDS = {
    "the", "and", "for", "you", "your", "are", "was", "with", "can", "how",
    "what", "why", "who", "did", "does", "get", "got", "our", "out", "this",
    "that", "then", "them", "they", "have", "has", "had", "will", "would",
    "should", "could", "about", "into", "from", "please", "help", "want",
    "need", "make", "made", "let", "just", "like", "any", "all", "not",
}


def _tokens(text: str) -> set:
    """Lowercase alphanumeric words > 2 chars, minus stopwords."""
    return {
        w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
        if len(w) > 2 and w not in _STOPWORDS
    }


def rank_nodes_for_query(nodes: list, query: str, limit: int = 6) -> list:
    """Rank non-root nodes by keyword overlap with the query.

    Returns at most `limit` nodes that share >=1 keyword, most relevant first.
    Deterministic: ties break on label so the same query always yields the
    same order. Empty query or no overlap -> []."""
    qt = _tokens(query)
    if not qt:
        return []
    scored = []
    for n in nodes:
        if n.get("kind") == "root":
            continue
        nt = _tokens((n.get("label") or "") + " " + (n.get("summary") or ""))
        overlap = len(qt & nt)
        if overlap > 0:
            scored.append((overlap, n.get("label") or "", n))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [n for _, _, n in scored[:limit]]


COUNT_LABELS = (("apps", "App Builder apps"),
                ("crons", "scheduled automations (cron jobs)"),
                ("videos", "generated videos"),
                ("files", "uploaded files"),
                ("collections", "knowledge collections"),
                ("memories", "saved memories"),
                ("chats", "chats"))


def counts_line(counts) -> str:
    """One authoritative sentence of live totals, so 'how many X do I have'
    is answerable directly from memory instead of guessed at."""
    if not counts:
        return ""
    parts = [f"{counts.get(k, 0)} {lbl}" for k, lbl in COUNT_LABELS]
    return ("Live totals for this user on this platform right now "
            "(authoritative; when asked how many, use these exact numbers): "
            + ", ".join(parts) + ".")


def format_matched(matched: list, all_nodes: list = None,
                   max_children: int = 15) -> str:
    """Render matched nodes as the injected memory block. Matched source hubs
    (App Builder Apps, cron jobs, ...) expand into their actual item names so
    the model can enumerate them."""
    kids = {}
    for n in (all_nodes or []):
        p = n.get("parent_id")
        if p:
            kids.setdefault(p, []).append(n)
    lines = []
    for n in matched:
        lbl = (n.get("label") or "").strip()
        summ = (n.get("summary") or "").strip()
        line = f"- {lbl}: {summ}" if summ else f"- {lbl}"
        if lbl in RESERVED_HUBS:
            ch = kids.get(n.get("id") or "", [])
            if ch:
                names = [(c.get("label") or "").strip() for c in ch][:max_children]
                more = len(ch) - len(names)
                tail = f"; and {more} more" if more > 0 else ""
                line += f" [{len(ch)} items: " + "; ".join(names) + tail + "]"
        lines.append(line)
    return (
        "Background on this user, drawn from their personal knowledge graph "
        "of past conversations. Items relevant to their current message:\n"
        + "\n".join(lines)
        + "\nUse this as context about who they are and what they work on. "
        "Do not mention the knowledge graph unless they ask about it."
    )


def topic_profile(nodes: list, limit: int = 6) -> str:
    """Light fallback: the user's recurring topics, when nothing matched."""
    topics = [n.get("label") or "" for n in nodes if n.get("kind") == "topic"]
    topics = [t for t in topics if t][:limit]
    if not topics:
        return ""
    return (
        "Background on this user, from their personal knowledge graph of "
        "past conversations. Recurring topics they care about: "
        + ", ".join(topics)
        + ". Use this as light context. Do not mention the knowledge graph "
        "unless they ask about it."
    )


def build_memory_context(nodes: list, query: str, limit: int = 6) -> str:
    """Keyword-ranked memory block (also the fallback when embeddings fail).

    If the query matches specific nodes, list those (label + summary). If not,
    fall back to a light profile of the user's recurring topics. Empty graph or
    nothing to say -> "" (the caller injects nothing)."""
    if not nodes:
        return ""
    matched = rank_nodes_for_query(nodes, query, limit)
    if matched:
        return format_matched(matched)
    return topic_profile(nodes, limit)


def node_text(n: dict) -> str:
    """The text a node is embedded under (label plus summary when present)."""
    lbl = (n.get("label") or "").strip()
    summ = (n.get("summary") or "").strip()
    return f"{lbl}: {summ}" if summ else lbl


async def semantic_rank(conn, nodes: list, query: str, limit: int = 6) -> list:
    """Rank non-root nodes against the query by embedding similarity.
    Raises on embedding failure so the caller can fall back to keywords."""
    cands = [n for n in nodes if n.get("kind") != "root"]
    texts = [node_text(n) for n in cands]
    vecs = await graph_embeddings.get_embeddings(conn, [query] + texts)
    qvec = vecs.get(query)
    if not qvec:
        raise ValueError("query embedding unavailable")
    pairs = [(n, vecs[t]) for n, t in zip(cands, texts) if t in vecs]
    return graph_embeddings.rank_by_similarity(qvec, pairs, limit=limit)


async def build_memory_context_smart(conn, nodes: list, query: str,
                                     limit: int = 6, counts=None):
    """Structured retrieval chain -> (context, mode).

    semantic (embeddings) -> keyword (on embedding failure) -> topic profile
    (nothing matched) -> "" (empty graph). `mode` names which tier answered,
    for observability. Every non-empty context opens with the live totals so
    quantitative questions get exact numbers."""
    if not nodes:
        return "", "none"
    matched, mode = [], "profile"
    qs = (query or "").strip()
    if qs:
        try:
            matched = await semantic_rank(conn, nodes, qs, limit)
            mode = "semantic"
        except Exception as e:
            print(f"[graph] semantic rank unavailable, keyword fallback: {e}",
                  flush=True)
            matched = rank_nodes_for_query(nodes, qs, limit)
            mode = "keyword"
    totals = counts_line(counts)
    if matched:
        body = format_matched(matched, all_nodes=nodes)
        return (totals + "\n" + body if totals else body), mode
    prof = topic_profile(nodes, limit)
    if prof:
        return (totals + "\n" + prof if totals else prof), "profile"
    return (totals, "profile") if totals else ("", "none")


# --- denser build: attach real items as nodes (pure, unit tested) -----------
def make_node(user_email: str, kind: str, label: str, parent_id, summary=None,
              url=None) -> dict:
    """One graph node with a fresh id. Labels are trimmed/capped; blank -> tag.
    `url` is the click-through target (None for pure grouping nodes)."""
    return {
        "id": str(uuid.uuid4()),
        "user_email": user_email,
        "kind": kind,
        "label": (label or "").strip()[:200] or "(untitled)",
        "summary": (summary or None),
        "parent_id": parent_id,
        "url": (url or None),
    }


def prettify_slug(slug: str) -> str:
    """App slug -> readable label: drop the trailing build hash and title-case.
    'create-me-a-shoe-website-fe02' -> 'Create Me A Shoe Website'."""
    s = (slug or "").strip()
    if not s:
        return "app"
    s = re.sub(r"[-_][0-9a-f]{4,8}$", "", s)   # trailing build hash
    s = s.replace("-", " ").replace("_", " ").strip()
    return " ".join(w.capitalize() for w in s.split()) or (slug or "app")


# Hub labels the assembler generates live. Old builds may have stored these as
# topic nodes; we drop stale copies so they don't render twice.
RESERVED_HUBS = {"Uploaded Files", "Knowledge Collections", "App Builder Apps",
                 "Automations & Cron Jobs", "Saved Memories", "Generated Videos"}

def app_label(slug, description: str = "") -> str:
    """Label an App Builder card the way the page shows it: the slug (raw for
    sched-* so they stay distinguishable), or the task description when the
    build has no slug yet."""
    if slug:
        return slug if slug.startswith("sched-") else prettify_slug(slug)
    d = (description or "").strip()
    return d[:60] if d else "app"


def best_parent_id(text: str, candidates: list, default_id: str) -> str:
    """Pick the candidate node whose label+summary best overlaps `text` by
    keyword tokens. No overlap (or empty text) -> default_id. Deterministic:
    first candidate wins a tie because we only replace on a strictly higher
    score, and candidates are passed in a stable order."""
    it = _tokens(text)
    if not it:
        return default_id
    best_id, best = default_id, 0
    for c in candidates:
        ct = _tokens((c.get("label") or "") + " " + (c.get("summary") or ""))
        s = len(it & ct)
        if s > best:
            best, best_id = s, c["id"]
    return best_id


def attach_chats(user_email: str, root_id: str, topic_nodes: list, chats: list) -> list:
    """Attach each chat as a 'chat' node under its best-matching topic/subtopic
    (fallback: the root), giving topics many children (hub-and-spoke)."""
    cands = [n for n in topic_nodes if n.get("kind") in ("topic", "subtopic")]
    out = []
    for c in chats:
        title = (c.get("title") or "").strip()
        if not title:
            continue
        pid = best_parent_id(title + " " + (c.get("snippet") or ""), cands, root_id)
        out.append(make_node(user_email, "chat", title, pid,
                             (c.get("snippet") or "")[:300] or None,
                             url=(f"/c/{c['id']}" if c.get("id") else None)))
    return out


def source_branch(user_email: str, root_id: str, hub_label: str,
                  items: list, item_kind: str, hub_url: str = None) -> list:
    """Build a hub topic node under root plus one node per item. `items` =
    dicts with 'label' (and optional 'summary'/'url'). Empty -> [] (no empty
    hub). `hub_url` links the hub itself to its feature page."""
    items = [i for i in items if (i.get("label") or "").strip()]
    if not items:
        return []
    hub = make_node(user_email, "topic", hub_label, root_id, url=hub_url)
    out = [hub]
    for it in items:
        out.append(make_node(user_email, item_kind, it.get("label"),
                             hub["id"], it.get("summary"), url=it.get("url")))
    return out


# --- storage -----------------------------------------------------------------
async def _connect():
    import asyncpg
    return await asyncpg.connect(DATABASE_URL)


async def ensure_table(conn) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_graph_node (
            id          uuid PRIMARY KEY,
            user_email  text NOT NULL,
            kind        text NOT NULL,
            label       text NOT NULL,
            summary     text,
            parent_id   uuid,
            source_ref  text,
            created_at  timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS kgn_user_idx ON knowledge_graph_node(user_email)"
    )


# --- build pipeline (pure parts unit tested) --------------------------------
def parse_cluster_json(text: str) -> list:
    """Parse the LLM clustering output into a topics list. Strips code fences.
    Raises ValueError on empty/malformed output or a missing 'topics' list."""
    if not text or not text.strip():
        raise ValueError("empty cluster response")
    s = text.strip()
    s = re.sub(r"^```(?:json)?", "", s).strip()
    s = re.sub(r"```$", "", s).strip()
    data = json.loads(s)  # JSONDecodeError is a ValueError subclass
    topics = data.get("topics") if isinstance(data, dict) else None
    if not isinstance(topics, list):
        raise ValueError("response has no 'topics' list")
    return topics


def tree_to_nodes(user_email: str, topics: list, root_label: str = "My Knowledge") -> list:
    """Flatten a topics tree into node dicts (root -> topic -> subtopic -> leaf),
    each with a fresh id and a parent_id. Skips malformed/empty entries."""
    nodes = []
    root_id = str(uuid.uuid4())
    nodes.append({"id": root_id, "user_email": user_email, "kind": "root",
                  "label": root_label, "summary": None, "parent_id": None})
    for t in topics:
        if not isinstance(t, dict):
            continue
        t_label = (t.get("label") or "").strip()
        if not t_label:
            continue
        t_id = str(uuid.uuid4())
        nodes.append({"id": t_id, "user_email": user_email, "kind": "topic",
                      "label": t_label[:200], "summary": None, "parent_id": root_id})
        for st in (t.get("subtopics") or []):
            if not isinstance(st, dict):
                continue
            st_label = (st.get("label") or "").strip()
            if not st_label:
                continue
            st_id = str(uuid.uuid4())
            nodes.append({"id": st_id, "user_email": user_email, "kind": "subtopic",
                          "label": st_label[:200], "summary": None, "parent_id": t_id})
            for lf in (st.get("leaves") or []):
                if not isinstance(lf, dict):
                    continue
                lf_label = (lf.get("label") or "").strip()
                if not lf_label:
                    continue
                summary = (lf.get("summary") or "").strip()[:1000] or None
                nodes.append({"id": str(uuid.uuid4()), "user_email": user_email,
                              "kind": "leaf", "label": lf_label[:200],
                              "summary": summary, "parent_id": st_id})
    return nodes


def _chat_snippet(chat_val, max_chars: int = 600) -> str:
    """Pull a short text snippet from an OWUI chat JSON blob (defensive)."""
    try:
        data = chat_val if isinstance(chat_val, dict) else json.loads(chat_val)
    except Exception:
        return ""
    parts = []
    msgs = data.get("messages") if isinstance(data, dict) else None
    if isinstance(msgs, list):
        for m in msgs:
            if isinstance(m, dict) and isinstance(m.get("content"), str):
                parts.append(m["content"])
    return " ".join(parts)[:max_chars]


async def _read_recent_chats(conn, user_email: str, limit: int = MAX_CHATS) -> list:
    urow = await conn.fetchrow(
        'SELECT id FROM public."user" WHERE lower(email) = lower($1) LIMIT 1',
        user_email)
    if not urow:
        return []
    rows = await conn.fetch(
        'SELECT title, chat FROM public."chat" WHERE user_id = $1 '
        'ORDER BY updated_at DESC LIMIT $2',
        urow["id"], limit)
    return [{"title": (r["title"] or ""), "snippet": _chat_snippet(r["chat"])}
            for r in rows]


async def _user_id(conn, user_email: str):
    r = await conn.fetchrow(
        'SELECT id FROM public."user" WHERE lower(email) = lower($1) LIMIT 1',
        user_email)
    return r["id"] if r else None


async def _read_files(conn, uid, limit: int = 200) -> list:
    """Uploaded files -> Document nodes."""
    if not uid:
        return []
    rows = await conn.fetch(
        'SELECT filename FROM public."file" WHERE user_id = $1 '
        'ORDER BY created_at DESC LIMIT $2', uid, limit)
    return [{"label": (r["filename"] or "file")} for r in rows]


async def _read_knowledge(conn, uid, limit: int = 200) -> list:
    """Knowledge collections -> nodes (name + description)."""
    if not uid:
        return []
    rows = await conn.fetch(
        'SELECT id, name, description FROM public."knowledge" WHERE user_id = $1 '
        'ORDER BY created_at DESC LIMIT $2', uid, limit)
    return [{"label": (r["name"] or "collection"),
             "summary": (r["description"] or None),
             "url": f"/workspace/knowledge/{r['id']}"} for r in rows]


async def _read_memories(conn, uid, limit: int = 200) -> list:
    """Saved OWUI memories -> nodes. (Empty today; wired for when they exist.)"""
    if not uid:
        return []
    rows = await conn.fetch(
        'SELECT content FROM public."memory" WHERE user_id = $1 '
        'ORDER BY created_at DESC LIMIT $2', uid, limit)
    return [{"label": (r["content"] or "")[:80],
             "summary": (r["content"] or None)} for r in rows]


async def _read_chat_titles(conn, uid, limit: int = 200) -> list:
    """Fast title-only chat read for the live assembler (no JSON parse)."""
    if not uid:
        return []
    rows = await conn.fetch(
        'SELECT id, title FROM public."chat" WHERE user_id = $1 '
        'ORDER BY updated_at DESC LIMIT $2', uid, limit)
    return [{"title": (r["title"] or ""), "snippet": "", "id": str(r["id"])}
            for r in rows]


async def _read_apps(conn, user_email: str, limit: int = 200) -> list:
    """The user's App Builder cards, mirroring the page EXACTLY: same source
    query (routes_tasks is_project=true: BUILD tasks they own or are invited
    to, no team bucket, sched-* schedule artifacts excluded) AND the same
    dedup the page does client-side (one card per distinct built_app_slug,
    newest task wins; slugless builds stay individual). The limit matches the
    page's fetch window; if the page's rules change, change this with it."""
    rows = await conn.fetch(
        "SELECT DISTINCT ON (COALESCE(slug, rid)) slug, rid, description, status "
        "FROM ("
        "  SELECT built_app_slug AS slug, id::text AS rid, description, "
        "         status, created_at FROM tasks.items "
        "  WHERE action_type = 'BUILD' "
        "  AND (built_app_slug IS NULL OR built_app_slug NOT LIKE 'sched-%') "
        "  AND ("
        "    assignee_email = $1 OR built_app_slug IN ("
        "      SELECT slug FROM tasks.project_members WHERE user_email = $1)) "
        "  ORDER BY created_at DESC LIMIT $2"
        ") w ORDER BY COALESCE(slug, rid), created_at DESC",
        user_email, limit)
    out = []
    for r in rows:
        desc = (r["description"] or "").strip()
        summ = f"{r['status']}: {desc}"[:300] if desc else (r["slug"] or None)
        out.append({"label": app_label(r["slug"], desc), "summary": summ,
                    "url": f"/tasks/static/preview.html?task={r['rid']}&tab=preview"})
    return out


async def _read_crons(conn, user_email: str, limit: int = 200) -> list:
    """Scheduled automations (cron jobs) the user created -> nodes."""
    rows = await conn.fetch(
        "SELECT name, cron_expr, prompt, enabled FROM tasks.schedules "
        "WHERE lower(user_email) = lower($1) ORDER BY created_at DESC LIMIT $2",
        user_email, limit)
    out = []
    for r in rows:
        state = "enabled" if r["enabled"] else "paused"
        summ = f"{r['cron_expr']} ({state}): {r['prompt'] or ''}".strip()
        out.append({"label": (r["name"] or "automation"), "summary": summ,
                    "url": "/cron-jobs"})
    return out


async def _read_videos(conn, user_email: str, limit: int = 200) -> list:
    """Videos the user generated -> nodes (title + status/prompt)."""
    rows = await conn.fetch(
        "SELECT id, title, prompt, status FROM tasks.video_jobs "
        "WHERE lower(user_email) = lower($1) ORDER BY created_at DESC LIMIT $2",
        user_email, limit)
    out = []
    for r in rows:
        label = (r["title"] or (r["prompt"] or "video")[:80])
        summ = f"{r['status'] or 'video'}: {r['prompt'] or ''}".strip()
        out.append({"label": label, "summary": summ,
                    "url": f"/video-generator?job={r['id']}"})
    return out


# Kinds that make up the LLM "skeleton" we persist: just the short topic
# labels. We deliberately DROP the LLM's full-sentence "leaf" summaries (the
# part most prone to paraphrase error); real items now hang under topics.
SKELETON_KINDS = ("root", "topic", "subtopic")


async def _assemble_live(conn, user_email: str):
    """Merge the stored topic skeleton with LIVE items read fresh each call, so
    the graph reflects what the user has right now (new/updated/deleted chats,
    apps, cron jobs, files) with no LLM rebuild. Returns (nodes, counts)."""
    uid = await _user_id(conn, user_email)
    srows = await conn.fetch(
        "SELECT id, kind, label, summary, parent_id FROM knowledge_graph_node "
        "WHERE user_email = $1 AND kind = ANY($2::text[]) ORDER BY created_at",
        user_email, list(SKELETON_KINDS))
    skeleton = [{"id": str(r["id"]), "user_email": user_email, "kind": r["kind"],
                 "label": r["label"], "summary": r["summary"],
                 "parent_id": str(r["parent_id"]) if r["parent_id"] else None,
                 "url": None}
                for r in srows]
    # Drop stale source-hub topics left by older builds (now generated live),
    # so hubs like "Uploaded Files" never render twice.
    skeleton = [n for n in skeleton
                if not (n["kind"] == "topic" and n["label"] in RESERVED_HUBS)]
    root = next((n for n in skeleton if n["kind"] == "root"), None)
    if root is None:
        root = {"id": str(uuid.uuid4()), "user_email": user_email, "kind": "root",
                "label": "My Knowledge", "summary": None, "parent_id": None}
        skeleton = [root] + skeleton
    root_id = root["id"]

    chats = await _read_chat_titles(conn, uid)
    files = await _read_files(conn, uid)
    kbs = await _read_knowledge(conn, uid)
    mems = await _read_memories(conn, uid)
    apps = await _read_apps(conn, user_email)
    crons = await _read_crons(conn, user_email)
    videos = await _read_videos(conn, user_email)

    nodes = list(skeleton)
    nodes += attach_chats(user_email, root_id, skeleton, chats)
    nodes += source_branch(user_email, root_id, "App Builder Apps", apps, "app",
                           hub_url="/Aiuibuilder")
    nodes += source_branch(user_email, root_id, "Automations & Cron Jobs", crons,
                           "cron", hub_url="/cron-jobs")
    nodes += source_branch(user_email, root_id, "Generated Videos", videos,
                           "video", hub_url="/video-generator")
    nodes += source_branch(user_email, root_id, "Uploaded Files", files, "document")
    nodes += source_branch(user_email, root_id, "Knowledge Collections", kbs,
                           "document", hub_url="/workspace/knowledge")
    nodes += source_branch(user_email, root_id, "Saved Memories", mems, "memory")
    counts = {"chats": len(chats), "apps": len(apps), "crons": len(crons),
              "videos": len(videos), "files": len(files),
              "collections": len(kbs), "memories": len(mems)}
    return nodes, counts


async def _rebuild_skeleton(conn, user_email: str) -> dict:
    """Re-derive the LLM topic skeleton from recent chats and store it
    (transactional replace). The one step that costs an LLM call; items are
    attached live on read so they never need this. Raises ValueError when the
    LLM/parse fails so callers choose their own error handling."""
    chats = await _read_recent_chats(conn, user_email, limit=60)
    base = [{"id": str(uuid.uuid4()), "user_email": user_email,
             "kind": "root", "label": "My Knowledge", "summary": None,
             "parent_id": None}]
    corpus = "\n\n".join(f"# {c['title']}\n{c['snippet']}"
                         for c in chats[:40] if (c['title'] or c['snippet']))
    if corpus.strip():
        topics = parse_cluster_json(await _cluster_with_llm(corpus))
        base = tree_to_nodes(user_email, topics)
    # Keep only short topic labels; drop the LLM's paraphrase leaves.
    base = [n for n in base if n["kind"] != "leaf"]
    skeleton, truncated = cap_nodes(base, 600)
    async with conn.transaction():
        await conn.execute("DELETE FROM knowledge_graph_node WHERE user_email = $1", user_email)
        for n in skeleton:
            await conn.execute(
                "INSERT INTO knowledge_graph_node (id, user_email, kind, label, summary, parent_id) "
                "VALUES ($1, $2, $3, $4, $5, $6)",
                uuid.UUID(n["id"]), n["user_email"], n["kind"], n["label"],
                n.get("summary"), uuid.UUID(n["parent_id"]) if n.get("parent_id") else None)
    return {"topics": sum(1 for n in skeleton if n["kind"] == "topic"),
            "truncated": truncated}


# --- automatic topic refresh -------------------------------------------------
# Topics re-analyze themselves so no user ever has to press Build: first use
# with enough chats triggers a build, and an existing skeleton refreshes once
# it is older than the threshold. Runs in the background (never blocks a
# request), at most one attempt per user per cooldown, and fails silently.
AUTO_REBUILD_HOURS = float(os.environ.get("GRAPH_AUTO_REBUILD_HOURS", "24"))
AUTO_REBUILD_MIN_CHATS = 3
AUTO_COOLDOWN_SEC = 3600
_AUTO_RUNNING = set()   # user_emails with a rebuild task in flight
_AUTO_LAST = {}         # user_email -> time.time() of the last attempt


def should_auto_rebuild(skeleton_topics: int, chats: int, age_hours,
                        threshold_hours: float = None) -> bool:
    """Pure decision. Rebuild when the user has enough chats but no topics yet
    (first use), no skeleton timestamp at all, or a skeleton older than the
    threshold. threshold <= 0 disables the feature."""
    th = AUTO_REBUILD_HOURS if threshold_hours is None else threshold_hours
    if th <= 0:
        return False
    if chats < AUTO_REBUILD_MIN_CHATS:
        return False
    if skeleton_topics == 0 or age_hours is None:
        return True
    return age_hours >= th


async def _skeleton_age_hours(conn, user_email: str):
    """Hours since this user's skeleton was stored (server clock); None if
    they have no stored nodes yet."""
    row = await conn.fetchrow(
        "SELECT EXTRACT(EPOCH FROM (now() - MAX(created_at))) / 3600.0 AS h "
        "FROM knowledge_graph_node WHERE user_email = $1", user_email)
    return float(row["h"]) if row and row["h"] is not None else None


async def _auto_rebuild(user_email: str) -> None:
    try:
        conn = await _connect()
        try:
            await ensure_table(conn)
            res = await _rebuild_skeleton(conn, user_email)
            print(f"[graph] auto-rebuilt topics for {user_email}: {res}",
                  flush=True)
        finally:
            await conn.close()
    except Exception as e:
        print(f"[graph] auto-rebuild failed for {user_email}: {e}", flush=True)
    finally:
        _AUTO_RUNNING.discard(user_email)


def _maybe_schedule_auto_build(user_email: str, nodes: list, counts: dict,
                               age_hours) -> bool:
    """Kick a background rebuild when warranted. Returns True if scheduled."""
    sk_topics = sum(1 for n in nodes
                    if n.get("kind") == "topic"
                    and n.get("label") not in RESERVED_HUBS)
    if not should_auto_rebuild(sk_topics, counts.get("chats", 0), age_hours):
        return False
    t = time.time()
    if user_email in _AUTO_RUNNING:
        return False
    if t - _AUTO_LAST.get(user_email, 0) < AUTO_COOLDOWN_SEC:
        return False
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False  # no loop (e.g. unit test) -> just skip, fail open
    _AUTO_LAST[user_email] = t
    _AUTO_RUNNING.add(user_email)
    loop.create_task(_auto_rebuild(user_email))
    return True


# --- model write-back ---------------------------------------------------------
MEMORY_MAX_CHARS = 500
MEMORY_MIN_CHARS = 3


def clean_memory_content(content: str) -> str:
    """Normalize a fact before storing it as an OWUI memory: collapse all
    whitespace runs, trim, cap at MEMORY_MAX_CHARS. Empty or trivially short
    input raises ValueError (the endpoint turns it into a 422)."""
    out = " ".join((content or "").split())[:MEMORY_MAX_CHARS]
    if len(out) < MEMORY_MIN_CHARS:
        raise ValueError("memory content is empty or too short")
    return out


# --- nightly prebuild ---------------------------------------------------------
# Rebuild every user's topic skeleton while they sleep, so the first graph
# load (and the AI-memory injection) never waits on the LLM. Reuses the same
# should_auto_rebuild decision as the on-demand path; users with fresh
# skeletons or too few chats are skipped. Hour is UTC; 18 = 2am Manila.
# Set GRAPH_PREBUILD_UTC_HOUR=-1 to disable the loop.
PREBUILD_UTC_HOUR = float(os.environ.get("GRAPH_PREBUILD_UTC_HOUR", "18"))


def seconds_until_utc_hour(now_ts: float, hour: float) -> float:
    """Seconds from `now_ts` (epoch) to the next occurrence of `hour` UTC.
    Exactly at the hour -> a full day (the current run is already firing)."""
    day = 86400.0
    delta = ((hour % 24.0) * 3600.0 - now_ts % day) % day
    return delta or day


async def prebuild_pass() -> dict:
    """One sweep over all users: rebuild stale/missing skeletons sequentially
    (one LLM call at a time — the box is small). Per-user failures are logged
    and skipped; the sweep itself never raises."""
    conn = await _connect()
    try:
        await ensure_table(conn)
        rows = await conn.fetch(
            'SELECT email FROM public."user" WHERE email IS NOT NULL')
        emails = sorted({(r["email"] or "").strip().lower()
                         for r in rows if r["email"]})
    finally:
        await conn.close()
    checked, rebuilt = 0, 0
    for email in emails:
        checked += 1
        try:
            conn = await _connect()
            try:
                uid = await _user_id(conn, email)
                chats = (await conn.fetchval(
                    'SELECT COUNT(*) FROM public."chat" WHERE user_id = $1',
                    uid)) if uid else 0
                topics = await conn.fetchval(
                    "SELECT COUNT(*) FROM knowledge_graph_node "
                    "WHERE user_email = $1 AND kind = 'topic' "
                    "AND NOT (label = ANY($2::text[]))",
                    email, list(RESERVED_HUBS))
                age = await _skeleton_age_hours(conn, email)
            finally:
                await conn.close()
            if not should_auto_rebuild(topics or 0, chats or 0, age):
                continue
            if email in _AUTO_RUNNING:
                continue
            _AUTO_RUNNING.add(email)
            _AUTO_LAST[email] = time.time()
            await _auto_rebuild(email)   # clears _AUTO_RUNNING in its finally
            rebuilt += 1
            await asyncio.sleep(2)       # pace the LLM calls
        except Exception as e:
            print(f"[graph] prebuild skipped {email}: {e}", flush=True)
    print(f"[graph] nightly prebuild done: {rebuilt}/{checked} users rebuilt",
          flush=True)
    return {"checked": checked, "rebuilt": rebuilt}


async def _prebuild_loop() -> None:
    while True:
        await asyncio.sleep(seconds_until_utc_hour(time.time(), PREBUILD_UTC_HOUR))
        try:
            await prebuild_pass()
        except Exception as e:
            print(f"[graph] nightly prebuild failed: {e}", flush=True)


def start_nightly_prebuild() -> bool:
    """Spawn the nightly loop (called from main's lifespan). Fail-open: any
    problem just means no prebuild, never a boot failure."""
    if PREBUILD_UTC_HOUR < 0 or AUTO_REBUILD_HOURS <= 0:
        return False
    try:
        asyncio.get_running_loop().create_task(_prebuild_loop())
        return True
    except RuntimeError:
        return False


async def _cluster_with_llm(corpus: str) -> str:
    key = _first_sk(os.environ.get("OPENAI_API_KEY", ""))
    if not key:
        raise ValueError("no OpenAI key configured")
    sys = (
        "You organize a user's content into a compact knowledge tree. Return "
        "ONLY JSON, no prose, in this exact shape: "
        '{"topics":[{"label":"...","subtopics":[{"label":"...","leaves":['
        '{"label":"...","summary":"..."}]}]}]}. Use 3-8 topics, each with 2-6 '
        "subtopics, each with 1-6 leaves. Labels are short (a few words); "
        "summaries are one sentence."
    )
    payload = {
        "model": CLUSTER_MODEL,
        "temperature": 0,
        "messages": [{"role": "system", "content": sys},
                     {"role": "user", "content": corpus[:12000]}],
    }
    async with httpx.AsyncClient(timeout=90) as client:
        r = await client.post(OPENAI_URL, json=payload,
                              headers={"Authorization": f"Bearer {key}"})
    if r.status_code != 200:
        raise ValueError(f"LLM error {r.status_code}: {r.text[:160]}")
    return r.json()["choices"][0]["message"].get("content") or ""


# --- endpoints ---------------------------------------------------------------
@router.get("/healthz")
async def healthz():
    return {"ok": True}


@router.post("/build")
async def build_my_graph(user: CurrentUser = Depends(current_user)):
    """Rebuild the signed-in user's knowledge graph from their recent chats."""
    conn = await _connect()
    try:
        await ensure_table(conn)
        try:
            built = await _rebuild_skeleton(conn, user.email)
        except ValueError as e:
            raise HTTPException(status_code=502,
                                detail=f"Could not organize your chats: {e}")
        # Report the full live picture (skeleton + attached items).
        nodes, counts = await _assemble_live(conn, user.email)
        return {"built": True, "nodes": len(nodes), **built, **counts}
    finally:
        await conn.close()


@router.get("")
async def get_my_graph(user: CurrentUser = Depends(current_user)):
    """Return the signed-in user's knowledge graph as {nodes, links}, assembled
    live (stored topic skeleton + current chats/apps/cron jobs/files)."""
    conn = await _connect()
    try:
        await ensure_table(conn)
        nodes, counts = await _assemble_live(conn, user.email)
        age = await _skeleton_age_hours(conn, user.email)
    finally:
        await conn.close()
    auto = _maybe_schedule_auto_build(user.email, nodes, counts, age)
    capped, truncated = cap_nodes(nodes, 600)
    return {
        "nodes": capped,
        "links": build_links(capped),
        "count": len(nodes),
        "counts": counts,
        "auto_refresh": auto,
        "truncated": truncated,
    }


@router.get("/context")
async def my_graph_context(
    q: str = "",
    limit: int = 6,
    user: CurrentUser = Depends(current_user),
):
    """Compact memory block for the signed-in user, relevant to query `q`.

    Consumed by the global OWUI memory filter (inlet) so every model gets the
    user's own knowledge-graph context injected at chat time. Strictly
    per-user; returns {"context": "", ...} when there is nothing to inject."""
    conn = await _connect()
    try:
        await ensure_table(conn)
        await graph_embeddings.ensure_embed_table(conn)
        nodes, counts = await _assemble_live(conn, user.email)
        ctx, mode = await build_memory_context_smart(conn, nodes, q, limit,
                                                     counts=counts)
        age = await _skeleton_age_hours(conn, user.email)
    finally:
        await conn.close()
    _maybe_schedule_auto_build(user.email, nodes, counts, age)
    return {"context": ctx, "count": len(nodes), "used": bool(ctx),
            "mode": mode}


@router.post("/prebuild")
async def run_prebuild(user: CurrentUser = Depends(current_user)):
    """Admin-only manual trigger of the nightly sweep (also how it's verified
    without waiting for the scheduled hour)."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admins only.")
    return await prebuild_pass()


class RememberBody(BaseModel):
    content: str


@router.post("/memory")
async def remember_memory(body: RememberBody,
                          user: CurrentUser = Depends(current_user)):
    """Store a fact as a real OWUI memory for the signed-in user (called by
    the "Remember" native tool). One insert lights up all three surfaces that
    already read public.memory live: the Brain graph's Saved Memories hub,
    the per-chat AI-memory injection, and OWUI's Settings > Personalization
    memories page."""
    try:
        content = clean_memory_content(body.content)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    conn = await _connect()
    try:
        uid = await _user_id(conn, user.email)
        if not uid:
            raise HTTPException(status_code=404, detail="Unknown user.")
        now = int(time.time())
        mem_id = str(uuid.uuid4())
        await conn.execute(
            'INSERT INTO public."memory" (id, user_id, content, created_at, '
            "updated_at) VALUES ($1, $2, $3, $4, $5)",
            mem_id, uid, content, now, now)
        total = await conn.fetchval(
            'SELECT COUNT(*) FROM public."memory" WHERE user_id = $1', uid)
    finally:
        await conn.close()
    print(f"[graph] memory saved for {user.email} ({len(content)} chars)",
          flush=True)
    return {"saved": True, "id": mem_id, "content": content,
            "total_memories": total}
