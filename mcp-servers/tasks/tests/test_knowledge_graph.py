"""Phase 1, Task 1: pure helpers for the per-user knowledge graph.
No network/DB. Runs in the tasks container (fastapi/auth available)."""
import pytest

from routes_knowledge_graph import build_links, cap_nodes, MAX_NODES


def test_build_links_from_parent_ids():
    nodes = [
        {"id": "root", "parent_id": None},
        {"id": "topic", "parent_id": "root"},
        {"id": "leaf", "parent_id": "topic"},
    ]
    links = build_links(nodes)
    assert {"source": "root", "target": "topic"} in links
    assert {"source": "topic", "target": "leaf"} in links
    assert len(links) == 2  # root has no incoming link


def test_build_links_skips_dangling_parent():
    nodes = [{"id": "a", "parent_id": None}, {"id": "b", "parent_id": "gone"}]
    links = build_links(nodes)
    assert links == []  # parent 'gone' is not in the node set


def test_cap_nodes_truncates_and_flags():
    nodes = [{"id": str(i)} for i in range(MAX_NODES + 50)]
    capped, truncated = cap_nodes(nodes)
    assert truncated is True
    assert len(capped) == MAX_NODES


def test_cap_nodes_under_limit_untouched():
    nodes = [{"id": "1"}, {"id": "2"}]
    capped, truncated = cap_nodes(nodes)
    assert truncated is False
    assert capped == nodes


# --- Phase 2: retrieval / memory context (pure, unit tested) -----------------
from routes_knowledge_graph import rank_nodes_for_query, build_memory_context

_NODES = [
    {"id": "r", "kind": "root", "label": "My Knowledge", "summary": None, "parent_id": None},
    {"id": "t1", "kind": "topic", "label": "Email Management", "summary": None, "parent_id": "r"},
    {"id": "s1", "kind": "subtopic", "label": "Gmail Connection", "summary": "linking a Gmail account", "parent_id": "t1"},
    {"id": "t2", "kind": "topic", "label": "CRM Solutions", "summary": None, "parent_id": "r"},
    {"id": "l1", "kind": "leaf", "label": "Best CRM", "summary": "comparing CRM tools for sales", "parent_id": "t2"},
]


def test_rank_matches_by_keyword_overlap():
    hits = rank_nodes_for_query(_NODES, "how do I connect my gmail account", limit=6)
    labels = [n["label"] for n in hits]
    assert "Gmail Connection" in labels          # matches 'gmail' + 'connect'/'account'
    assert "My Knowledge" not in labels          # root never returned


def test_rank_empty_query_returns_nothing():
    assert rank_nodes_for_query(_NODES, "", limit=6) == []


def test_rank_no_match_returns_empty():
    assert rank_nodes_for_query(_NODES, "quantum astrophysics telescope", limit=6) == []


def test_rank_is_deterministic_and_capped():
    a = rank_nodes_for_query(_NODES, "crm gmail email", limit=2)
    b = rank_nodes_for_query(_NODES, "crm gmail email", limit=2)
    assert a == b
    assert len(a) <= 2


def test_build_context_uses_matches_when_present():
    ctx = build_memory_context(_NODES, "connect my gmail", limit=6)
    assert "Gmail Connection" in ctx
    assert ctx.strip() != ""


def test_build_context_falls_back_to_topic_profile():
    ctx = build_memory_context(_NODES, "totally unrelated query xyzzy", limit=6)
    # no keyword match -> profile of recurring topics
    assert "Email Management" in ctx and "CRM Solutions" in ctx


def test_build_context_empty_when_no_nodes():
    assert build_memory_context([], "anything", limit=6) == ""
