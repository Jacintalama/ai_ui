"""Per-user knowledge graph ("Brain"). Phase 1: store + read.

Nodes are strictly per-user (scoped by the signed-in email). See
docs/superpowers/specs/2026-07-27-user-knowledge-graph-design.md and the
Phase 1 plan. Build-from-chats lives in this module too (added in Task 2).
"""
import os
import uuid

from fastapi import APIRouter, Depends

from auth import current_user, CurrentUser

router = APIRouter(prefix="/graph/mine")

DATABASE_URL = os.environ.get("DATABASE_URL", "")
MAX_NODES = 800  # cap per user to bound RAM/render cost on the small box


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


# --- endpoints ---------------------------------------------------------------
@router.get("/healthz")
async def healthz():
    return {"ok": True}


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
