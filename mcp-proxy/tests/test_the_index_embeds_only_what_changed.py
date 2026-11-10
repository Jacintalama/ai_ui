"""The proxy re-embedded every tool on every start, in one batch (2026-11-10).

Measured on production that day: the container held about 1,060 MB of its
1,200 MB limit, and 987 MB of it was the heap of `uvicorn main:app`. The
FastMCP process beside it, which never loads the search model, was 56 MB.
Each start ran `model.embed(texts)` over all 336 tool texts at fastembed's
default batch of 256. Reproduced with the server's library versions and the
336 stored texts: 617 MB peak at that batch, 243 MB in batches of 32, and the
memory is kept afterwards.

The vectors were already in the table. So a start now embeds only the tools
whose text is new or changed, in small batches, and a start where nothing
changed does not load the model at all.
"""
import pytest

import tool_embeddings as te
from tool_embeddings import EMBED_BATCH, needing_embedding, text_hash, tool_text


# --- the pure parts -------------------------------------------------------------

def test_the_text_is_what_was_always_embedded():
    """Changing this would silently re-embed everything once, and would make
    stored vectors disagree with the text they were made from."""
    info = {"original_name": "create_task", "description": "Create a task",
            "tenant_name": "ClickUp (your account)"}
    assert tool_text("my-clickup_create_task", info) == (
        "create_task - Create a task (server: ClickUp (your account))")


def test_the_text_falls_back_as_it_did():
    assert tool_text("x_ping", {"tenant_id": "x"}) == "x_ping -  (server: x)"


def test_an_unchanged_tool_is_not_embedded_again():
    texts = {"a": "a - x (server: s)", "b": "b - y (server: s)"}
    stored = {"a": text_hash(texts["a"]), "b": text_hash(texts["b"])}
    assert needing_embedding(texts, stored) == []


def test_a_new_a_changed_and_an_unhashed_tool_are_embedded():
    """`d` is a row written before the hash existed: the first start after
    this deploy embeds it once, and never again."""
    texts = {"a": "a - x", "b": "b - changed", "c": "c - new", "d": "d - old row"}
    stored = {"a": text_hash("a - x"), "b": text_hash("b - before"), "d": None}
    assert needing_embedding(texts, stored) == ["b", "c", "d"]


def test_batches_are_small():
    assert 1 <= EMBED_BATCH <= 32


# --- through store_tool_embeddings ----------------------------------------------

class _Conn:
    def __init__(self, rows):
        self.rows = rows
        self.sql = []

    async def execute(self, sql, *args):
        self.sql.append((" ".join(sql.split()), args))
        return "OK"

    async def fetch(self, sql, *args):
        self.sql.append((" ".join(sql.split()), args))
        return self.rows


class _Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def __init__(self, rows=()):
        self.conn = _Conn(list(rows))

    def acquire(self):
        return _Acquire(self.conn)


TOOLS = {
    "my-clickup_create_task": {"original_name": "create_task",
                               "description": "Create a task",
                               "tenant_id": "my-clickup",
                               "tenant_name": "ClickUp (your account)"},
    "github_search": {"original_name": "search", "description": "Search code",
                      "tenant_id": "github", "tenant_name": "GitHub"},
}


def _hashes_of(tools):
    return [{"tool_name": n, "text_hash": text_hash(tool_text(n, i))}
            for n, i in tools.items()]


def _writes(pool):
    return [(sql, args) for sql, args in pool.conn.sql
            if sql.startswith("INSERT INTO mcp_proxy.tool_embeddings")]


async def test_a_start_where_nothing_changed_never_loads_the_model(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("the model was loaded with nothing to embed")
    monkeypatch.setattr(te, "get_embedding_model", refuse)
    monkeypatch.setattr(te, "generate_embeddings_batch", refuse)

    pool = _Pool(_hashes_of(TOOLS))
    assert await te.store_tool_embeddings(pool, TOOLS) == 2
    # Metadata still kept current, without touching the vectors.
    writes = _writes(pool)
    assert len(writes) == 2
    assert all("embedding" not in sql.split("DO UPDATE SET", 1)[1] for sql, _ in writes)


async def test_only_the_changed_tool_is_embedded_and_its_hash_is_written(monkeypatch):
    asked = []

    def fake_batch(texts):
        asked.append(list(texts))
        return [[0.1] * te.EMBEDDING_DIM for _ in texts]
    monkeypatch.setattr(te, "generate_embeddings_batch", fake_batch)

    rows = _hashes_of(TOOLS)
    rows[1]["text_hash"] = text_hash("search - old words (server: GitHub)")
    pool = _Pool(rows)
    await te.store_tool_embeddings(pool, TOOLS)

    assert asked == [["search - Search code (server: GitHub)"]]
    with_vector = [args for sql, args in _writes(pool) if "::vector" in sql]
    assert len(with_vector) == 1
    assert with_vector[0][0] == "github_search"
    assert text_hash("search - Search code (server: GitHub)") in with_vector[0]


async def test_the_hash_column_is_added_to_an_existing_table():
    pool = _Pool()
    await te.ensure_embeddings_table(pool)
    assert any("ADD COLUMN IF NOT EXISTS text_hash" in sql for sql, _ in pool.conn.sql)


def test_the_model_is_asked_in_small_batches(monkeypatch):
    seen = {}

    class _Vec(list):
        def tolist(self):
            return list(self)

    class _Model:
        def embed(self, texts, batch_size=256, **kw):
            seen["batch_size"] = batch_size
            return [_Vec([0.0]) for _ in texts]

    monkeypatch.setattr(te, "get_embedding_model", lambda: _Model())
    assert te.generate_embeddings_batch(["a", "b"]) == [[0.0], [0.0]]
    assert seen["batch_size"] == EMBED_BATCH
