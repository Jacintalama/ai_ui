"""Semantic retrieval for the knowledge graph: pure helpers + the structured
fallback chain (semantic -> keyword -> profile). No network/DB; the embedding
call is monkeypatched at the module seam. Runs in the tasks container."""
import pytest

import graph_embeddings as ge
import routes_knowledge_graph as rkg


# --- pure helpers ------------------------------------------------------------
def test_cosine_identity_orthogonal_zero():
    assert ge.cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert ge.cosine([1, 0], [0, 1]) == pytest.approx(0.0)
    assert ge.cosine([0, 0], [1, 1]) == 0.0
    assert ge.cosine([], [1]) == 0.0
    assert ge.cosine([1, 2], [1, 2, 3]) == 0.0  # length mismatch -> no match


def test_cosine_scale_invariant():
    assert ge.cosine([1, 2, 3], [2, 4, 6]) == pytest.approx(1.0)


def test_text_key_stable_and_distinct():
    assert ge.text_key("hello") == ge.text_key("hello")
    assert ge.text_key("hello") != ge.text_key("world")


def test_rank_by_similarity_threshold_order_limit():
    q = [1.0, 0.0]
    a = {"label": "close"}
    b = {"label": "closer"}
    c = {"label": "far"}
    pairs = [(c, [0.0, 1.0]),          # sim 0.0 -> cut by threshold
             (a, [0.9, 0.44]),         # sim ~0.90
             (b, [1.0, 0.05])]         # sim ~0.999
    out = ge.rank_by_similarity(q, pairs, limit=6, threshold=0.30)
    assert [n["label"] for n in out] == ["closer", "close"]
    assert ge.rank_by_similarity(q, pairs, limit=1, threshold=0.30)[0]["label"] == "closer"


def test_rank_tie_breaks_on_label():
    q = [1.0, 0.0]
    pairs = [({"label": "beta"}, [1.0, 0.0]), ({"label": "alpha"}, [1.0, 0.0])]
    out = ge.rank_by_similarity(q, pairs, limit=2, threshold=0.30)
    assert [n["label"] for n in out] == ["alpha", "beta"]


def test_pick_missing_dedupes_and_skips_cached():
    cached = {ge.text_key("a")}
    assert ge.pick_missing(["a", "b", "b", "c"], cached) == ["b", "c"]


# --- the structured chain: semantic -> keyword -> profile --------------------
_NODES = [
    {"id": "r", "kind": "root", "label": "My Knowledge", "summary": None},
    {"id": "t", "kind": "topic", "label": "Email Management", "summary": None},
    {"id": "a", "kind": "app", "label": "Shoe Website", "summary": "create-me-a-shoe-website"},
]


async def test_smart_uses_semantic_when_available(monkeypatch):
    async def fake_rank(conn, nodes, query, limit=6):
        return [n for n in nodes if n["kind"] == "app"]
    monkeypatch.setattr(rkg, "semantic_rank", fake_rank)
    ctx, mode = await rkg.build_memory_context_smart(None, _NODES, "footwear shop")
    assert mode == "semantic" and "Shoe Website" in ctx


async def test_smart_falls_back_to_keyword_on_embedding_failure(monkeypatch):
    async def broken(conn, nodes, query, limit=6):
        raise ValueError("no OpenAI key configured")
    monkeypatch.setattr(rkg, "semantic_rank", broken)
    ctx, mode = await rkg.build_memory_context_smart(None, _NODES, "email management")
    assert mode == "keyword" and "Email Management" in ctx


async def test_smart_profile_when_nothing_matches(monkeypatch):
    async def empty(conn, nodes, query, limit=6):
        return []
    monkeypatch.setattr(rkg, "semantic_rank", empty)
    ctx, mode = await rkg.build_memory_context_smart(None, _NODES, "xyzzy")
    assert mode == "profile" and "Email Management" in ctx


async def test_smart_empty_graph_returns_none():
    ctx, mode = await rkg.build_memory_context_smart(None, [], "anything")
    assert ctx == "" and mode == "none"


async def test_smart_no_query_gives_profile():
    ctx, mode = await rkg.build_memory_context_smart(None, _NODES, "   ")
    assert mode == "profile" and "Email Management" in ctx


# --- quantitative memory: counts line + hub expansion ------------------------
from routes_knowledge_graph import counts_line, format_matched

_COUNTS = {"chats": 35, "apps": 21, "crons": 4, "videos": 0,
           "files": 26, "collections": 7, "memories": 0}


def test_counts_line_has_exact_numbers():
    line = counts_line(_COUNTS)
    assert "21 App Builder apps" in line
    assert "4 scheduled automations (cron jobs)" in line
    assert "35 chats" in line
    assert "authoritative" in line


def test_counts_line_empty_when_no_counts():
    assert counts_line(None) == ""
    assert counts_line({}) == ""


def test_hub_expansion_lists_children():
    hub = {"id": "h1", "kind": "topic", "label": "App Builder Apps", "summary": None}
    kids = [{"id": f"a{i}", "kind": "app", "label": f"App {i}", "parent_id": "h1"}
            for i in range(3)]
    ctx = format_matched([hub], all_nodes=[hub] + kids)
    assert "[3 items: App 0; App 1; App 2]" in ctx


def test_hub_expansion_caps_and_counts_overflow():
    hub = {"id": "h1", "kind": "topic", "label": "App Builder Apps", "summary": None}
    kids = [{"id": f"a{i}", "kind": "app", "label": f"App {i}", "parent_id": "h1"}
            for i in range(20)]
    ctx = format_matched([hub], all_nodes=[hub] + kids, max_children=15)
    assert "[20 items:" in ctx and "and 5 more" in ctx


def test_non_hub_nodes_do_not_expand():
    topic = {"id": "t1", "kind": "topic", "label": "Email Management", "summary": None}
    kids = [{"id": "c1", "kind": "chat", "label": "A chat", "parent_id": "t1"}]
    ctx = format_matched([topic], all_nodes=[topic] + kids)
    assert "[1 items" not in ctx


async def test_smart_context_opens_with_totals(monkeypatch):
    import routes_knowledge_graph as rkg
    async def fake_rank(conn, nodes, query, limit=6):
        return [n for n in nodes if n["kind"] == "topic"]
    monkeypatch.setattr(rkg, "semantic_rank", fake_rank)
    nodes = [{"id": "r", "kind": "root", "label": "My Knowledge", "summary": None},
             {"id": "t", "kind": "topic", "label": "Email Management", "summary": None}]
    ctx, mode = await rkg.build_memory_context_smart(None, nodes, "how many apps",
                                                     counts=_COUNTS)
    assert ctx.startswith("Live totals")
    assert "21 App Builder apps" in ctx and mode == "semantic"


# --- automatic topic refresh: pure decision ----------------------------------
from routes_knowledge_graph import should_auto_rebuild


def test_auto_rebuild_first_use_with_enough_chats():
    assert should_auto_rebuild(0, 5, None, threshold_hours=24) is True


def test_auto_rebuild_not_for_users_with_few_chats():
    assert should_auto_rebuild(0, 2, None, threshold_hours=24) is False


def test_auto_rebuild_when_skeleton_stale():
    assert should_auto_rebuild(6, 30, 30.0, threshold_hours=24) is True


def test_auto_rebuild_not_when_fresh():
    assert should_auto_rebuild(6, 30, 2.0, threshold_hours=24) is False


def test_auto_rebuild_when_topics_but_no_timestamp():
    assert should_auto_rebuild(6, 30, None, threshold_hours=24) is True


def test_auto_rebuild_disabled_by_zero_threshold():
    assert should_auto_rebuild(0, 30, None, threshold_hours=0) is False
