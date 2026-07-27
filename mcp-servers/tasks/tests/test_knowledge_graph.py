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
