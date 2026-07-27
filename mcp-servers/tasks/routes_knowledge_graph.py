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
        chats = await _read_recent_chats(conn, user.email)
        if not chats:
            return {"built": False, "reason": "No chats to build from yet.", "nodes": 0}
        corpus = "\n\n".join(f"# {c['title']}\n{c['snippet']}" for c in chats if (c['title'] or c['snippet']))
        if not corpus.strip():
            return {"built": False, "reason": "Your chats have no readable text yet.", "nodes": 0}
        try:
            raw = await _cluster_with_llm(corpus)
            topics = parse_cluster_json(raw)
        except ValueError as e:
            raise HTTPException(status_code=502, detail=f"Could not organize your chats: {e}")
        nodes, truncated = cap_nodes(tree_to_nodes(user.email, topics))
        async with conn.transaction():
            await conn.execute("DELETE FROM knowledge_graph_node WHERE user_email = $1", user.email)
            for n in nodes:
                await conn.execute(
                    "INSERT INTO knowledge_graph_node (id, user_email, kind, label, summary, parent_id) "
                    "VALUES ($1, $2, $3, $4, $5, $6)",
                    uuid.UUID(n["id"]), n["user_email"], n["kind"], n["label"],
                    n.get("summary"), uuid.UUID(n["parent_id"]) if n.get("parent_id") else None)
        return {"built": True, "nodes": len(nodes), "chats_used": len(chats), "truncated": truncated}
    finally:
        await conn.close()


@router.get("")
async def get_my_graph(user: CurrentUser = Depends(current_user)):
    """Return the signed-in user's knowledge graph as {nodes, links}."""
    conn = await _connect()
    try:
        await ensure_table(conn)
        rows = await conn.fetch(
            "SELECT id, kind, label, summary, parent_id "
            "FROM knowledge_graph_node WHERE user_email = $1 "
            "ORDER BY created_at",
            user.email,
        )
    finally:
        await conn.close()
    nodes = [
        {
            "id": str(r["id"]),
            "kind": r["kind"],
            "label": r["label"],
            "summary": r["summary"],
            "parent_id": str(r["parent_id"]) if r["parent_id"] else None,
        }
        for r in rows
    ]
    capped, truncated = cap_nodes(nodes)
    return {
        "nodes": capped,
        "links": build_links(capped),
        "count": len(nodes),
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
        rows = await conn.fetch(
            "SELECT kind, label, summary, parent_id "
            "FROM knowledge_graph_node WHERE user_email = $1 "
            "ORDER BY created_at",
            user.email,
        )
    finally:
        await conn.close()
    nodes = [
        {
            "kind": r["kind"],
            "label": r["label"],
            "summary": r["summary"],
            "parent_id": str(r["parent_id"]) if r["parent_id"] else None,
        }
        for r in rows
    ]
    ctx = build_memory_context(nodes, q, limit)
    return {"context": ctx, "count": len(nodes), "used": bool(ctx)}
