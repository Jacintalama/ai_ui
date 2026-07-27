"""Semantic embeddings for the per-user knowledge graph.

Gives /graph/mine/context real semantic retrieval: node texts and the user's
message are embedded (OpenAI text-embedding-3-small, 512 dims) and ranked by
cosine similarity, so "footwear shop page" finds the "Shoe Website" app even
with zero shared words.

Reliability structure (callers depend on this):
- Embeddings are CACHED by content hash in Postgres, so each distinct text is
  embedded once ever; repeat questions cost nothing.
- Any API/DB failure raises; the caller falls back to keyword ranking and the
  chat is never blocked (the OWUI filter fails open on top of that).

Pure helpers (text_key, cosine, rank_by_similarity, pick_missing) are unit
tested; `_call_embeddings` is the network seam tests monkeypatch.
"""
import hashlib
import math
import os

import httpx

EMBED_MODEL = os.environ.get("GRAPH_EMBED_MODEL", "text-embedding-3-small")
EMBED_DIM = 512            # plenty for ranking; 3x smaller to store than 1536
EMBED_URL = os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1").rstrip("/") + "/embeddings"
MAX_BATCH = 512            # texts per API call; graph is capped at 600 nodes
SIM_THRESHOLD = 0.30       # below this, a node is not relevant to the query


def _first_sk(value: str) -> str:
    """OWUI may store several keys joined by ';'. Pick the first real sk- key."""
    for part in (value or "").split(";"):
        part = part.strip()
        if part.startswith("sk-"):
            return part
    return (value or "").strip()


# --- pure helpers (unit tested, no I/O) --------------------------------------
def text_key(text: str) -> str:
    """Stable cache key for a text under the current model."""
    return hashlib.sha256(f"{EMBED_MODEL}:{text}".encode("utf-8")).hexdigest()


def cosine(a: list, b: list) -> float:
    """Cosine similarity; 0.0 for empty/zero vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def rank_by_similarity(query_vec: list, node_vecs: list, limit: int = 6,
                       threshold: float = SIM_THRESHOLD) -> list:
    """node_vecs = [(node, vec)]. Returns nodes scoring >= threshold, best
    first, capped at limit. Ties break on label for determinism."""
    scored = []
    for node, vec in node_vecs:
        s = cosine(query_vec, vec)
        if s >= threshold:
            scored.append((s, (node.get("label") or ""), node))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [n for _, _, n in scored[:limit]]


def pick_missing(texts: list, cached_keys: set) -> list:
    """Texts (deduped, order kept) whose key is not cached yet."""
    seen, out = set(), []
    for t in texts:
        k = text_key(t)
        if k in cached_keys or k in seen:
            continue
        seen.add(k)
        out.append(t)
    return out


# --- storage + API ------------------------------------------------------------
async def ensure_embed_table(conn) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_graph_embedding (
            text_key    text PRIMARY KEY,
            model       text NOT NULL,
            embedding   real[] NOT NULL,
            created_at  timestamptz NOT NULL DEFAULT now()
        )
        """
    )


async def _call_embeddings(texts: list) -> list:
    """One batch call -> list of vectors, same order as texts. Raises on any
    failure (missing key, HTTP error) so callers can fall back."""
    key = _first_sk(os.environ.get("OPENAI_API_KEY", ""))
    if not key:
        raise ValueError("no OpenAI key configured")
    payload = {"model": EMBED_MODEL, "input": texts, "dimensions": EMBED_DIM}
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(EMBED_URL, json=payload,
                              headers={"Authorization": f"Bearer {key}"})
    if r.status_code != 200:
        raise ValueError(f"embeddings error {r.status_code}: {r.text[:160]}")
    data = r.json()["data"]
    return [d["embedding"] for d in data]


async def get_embeddings(conn, texts: list) -> dict:
    """Return {text: vector} for every text, from cache plus at most one batch
    API call for the misses (new misses are cached). Overflow beyond MAX_BATCH
    is skipped this call and picked up next time."""
    texts = [t for t in texts if (t or "").strip()]
    if not texts:
        return {}
    keys = {t: text_key(t) for t in texts}
    rows = await conn.fetch(
        "SELECT text_key, embedding FROM knowledge_graph_embedding "
        "WHERE text_key = ANY($1::text[])", list(set(keys.values())))
    by_key = {r["text_key"]: list(r["embedding"]) for r in rows}
    missing = pick_missing(texts, set(by_key))[:MAX_BATCH]
    if missing:
        vecs = await _call_embeddings(missing)
        for t, v in zip(missing, vecs):
            k = keys[t]
            by_key[k] = v
            await conn.execute(
                "INSERT INTO knowledge_graph_embedding (text_key, model, embedding) "
                "VALUES ($1, $2, $3) ON CONFLICT (text_key) DO NOTHING",
                k, EMBED_MODEL, v)
    return {t: by_key[k] for t, k in keys.items() if k in by_key}
