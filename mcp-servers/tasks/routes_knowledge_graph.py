"""Per-user knowledge graph ("Brain"). Phase 1: store + read.

Nodes are strictly per-user (scoped by the signed-in email). See
docs/superpowers/specs/2026-07-27-user-knowledge-graph-design.md and the
Phase 1 plan. Build-from-chats lives in this module too (added in Task 2).
"""
import json
import os
import re
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException

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


def build_memory_context(nodes: list, query: str, limit: int = 6) -> str:
    """Build a compact memory block to inject into a model's context.

    If the query matches specific nodes, list those (label + summary). If not,
    fall back to a light profile of the user's recurring topics. Empty graph or
    nothing to say -> "" (the caller injects nothing)."""
    if not nodes:
        return ""
    matched = rank_nodes_for_query(nodes, query, limit)
    if matched:
        lines = []
        for n in matched:
            lbl = (n.get("label") or "").strip()
            summ = (n.get("summary") or "").strip()
            lines.append(f"- {lbl}: {summ}" if summ else f"- {lbl}")
        return (
            "Background on this user, drawn from their personal knowledge graph "
            "of past conversations. Items relevant to their current message:\n"
            + "\n".join(lines)
            + "\nUse this as context about who they are and what they work on. "
            "Do not mention the knowledge graph unless they ask about it."
        )
    topics = [n.get("label") or "" for n in nodes if n.get("kind") == "topic"]
    topics = [t for t in topics if t][:limit]
    if topics:
        return (
            "Background on this user, from their personal knowledge graph of "
            "past conversations. Recurring topics they care about: "
            + ", ".join(topics)
            + ". Use this as light context. Do not mention the knowledge graph "
            "unless they ask about it."
        )
    return ""


# --- denser build: attach real items as nodes (pure, unit tested) -----------
def make_node(user_email: str, kind: str, label: str, parent_id, summary=None) -> dict:
    """One graph node with a fresh id. Labels are trimmed/capped; blank -> tag."""
    return {
        "id": str(uuid.uuid4()),
        "user_email": user_email,
        "kind": kind,
        "label": (label or "").strip()[:200] or "(untitled)",
        "summary": (summary or None),
        "parent_id": parent_id,
    }


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
                             (c.get("snippet") or "")[:300] or None))
    return out


def source_branch(user_email: str, root_id: str, hub_label: str,
                  items: list, item_kind: str) -> list:
    """Build a hub topic node under root plus one node per item. `items` =
    dicts with 'label' (and optional 'summary'). Empty -> [] (no empty hub)."""
    items = [i for i in items if (i.get("label") or "").strip()]
    if not items:
        return []
    hub = make_node(user_email, "topic", hub_label, root_id)
    out = [hub]
    for it in items:
        out.append(make_node(user_email, item_kind, it.get("label"),
                             hub["id"], it.get("summary")))
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
        'SELECT name, description FROM public."knowledge" WHERE user_id = $1 '
        'ORDER BY created_at DESC LIMIT $2', uid, limit)
    return [{"label": (r["name"] or "collection"),
             "summary": (r["description"] or None)} for r in rows]


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
        'SELECT title FROM public."chat" WHERE user_id = $1 '
        'ORDER BY updated_at DESC LIMIT $2', uid, limit)
    return [{"title": (r["title"] or ""), "snippet": ""} for r in rows]


async def _read_apps(conn, user_email: str, limit: int = 200) -> list:
    """App Builder apps the user created -> nodes. Excludes 'sched-*' slugs,
    which are scheduled-run artifacts, not real apps."""
    rows = await conn.fetch(
        "SELECT DISTINCT ON (built_app_slug) built_app_slug, description "
        "FROM tasks.items WHERE lower(assignee_email) = lower($1) "
        "AND built_app_slug IS NOT NULL AND built_app_slug NOT LIKE 'sched-%' "
        "ORDER BY built_app_slug, updated_at DESC LIMIT $2",
        user_email, limit)
    return [{"label": (r["built_app_slug"] or "app"),
             "summary": (r["description"] or None)} for r in rows]


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
        out.append({"label": (r["name"] or "automation"), "summary": summ})
    return out


# Kinds that make up the LLM "skeleton" we persist; everything else (chats,
# apps, files, cron jobs, ...) is assembled live so it stays current.
SKELETON_KINDS = ("root", "topic", "subtopic", "leaf")


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
                 "parent_id": str(r["parent_id"]) if r["parent_id"] else None}
                for r in srows]
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

    nodes = list(skeleton)
    nodes += attach_chats(user_email, root_id, skeleton, chats)
    nodes += source_branch(user_email, root_id, "App Builder Apps", apps, "app")
    nodes += source_branch(user_email, root_id, "Automations & Cron Jobs", crons, "cron")
    nodes += source_branch(user_email, root_id, "Uploaded Files", files, "document")
    nodes += source_branch(user_email, root_id, "Knowledge Collections", kbs, "document")
    nodes += source_branch(user_email, root_id, "Saved Memories", mems, "memory")
    counts = {"chats": len(chats), "apps": len(apps), "crons": len(crons),
              "files": len(files), "collections": len(kbs), "memories": len(mems)}
    return nodes, counts


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
        # Build ONLY re-derives the LLM topic skeleton from recent chats. The
        # items (chats/apps/cron jobs/files) are attached live on read, so they
        # never need a rebuild to stay current.
        chats = await _read_recent_chats(conn, user.email, limit=60)
        base = [{"id": str(uuid.uuid4()), "user_email": user.email,
                 "kind": "root", "label": "My Knowledge", "summary": None,
                 "parent_id": None}]
        corpus = "\n\n".join(f"# {c['title']}\n{c['snippet']}"
                             for c in chats[:40] if (c['title'] or c['snippet']))
        if corpus.strip():
            try:
                topics = parse_cluster_json(await _cluster_with_llm(corpus))
                base = tree_to_nodes(user.email, topics)
            except ValueError as e:
                raise HTTPException(status_code=502,
                                    detail=f"Could not organize your chats: {e}")
        skeleton, truncated = cap_nodes(base, 600)

        async with conn.transaction():
            await conn.execute("DELETE FROM knowledge_graph_node WHERE user_email = $1", user.email)
            for n in skeleton:
                await conn.execute(
                    "INSERT INTO knowledge_graph_node (id, user_email, kind, label, summary, parent_id) "
                    "VALUES ($1, $2, $3, $4, $5, $6)",
                    uuid.UUID(n["id"]), n["user_email"], n["kind"], n["label"],
                    n.get("summary"), uuid.UUID(n["parent_id"]) if n.get("parent_id") else None)

        # Report the full live picture (skeleton + attached items).
        nodes, counts = await _assemble_live(conn, user.email)
        topics = sum(1 for n in skeleton if n["kind"] == "topic")
        return {"built": True, "topics": topics, "nodes": len(nodes),
                "truncated": truncated, **counts}
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
    finally:
        await conn.close()
    capped, truncated = cap_nodes(nodes, 600)
    return {
        "nodes": capped,
        "links": build_links(capped),
        "count": len(nodes),
        "counts": counts,
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
        nodes, _counts = await _assemble_live(conn, user.email)
    finally:
        await conn.close()
    ctx = build_memory_context(nodes, q, limit)
    return {"context": ctx, "count": len(nodes), "used": bool(ctx)}
