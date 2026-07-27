"""Phase 1, Task 2: build-from-chats pure helpers (parse + tree). No network.
Runs in the tasks container."""
import pytest

from routes_knowledge_graph import parse_cluster_json, tree_to_nodes


def test_parse_strips_code_fence_and_returns_topics():
    raw = '```json\n{"topics":[{"label":"Work","subtopics":[{"label":"Email","leaves":[{"label":"Invoices","summary":"about invoices"}]}]}]}\n```'
    topics = parse_cluster_json(raw)
    assert isinstance(topics, list)
    assert topics[0]["label"] == "Work"


def test_parse_malformed_raises():
    with pytest.raises(ValueError):
        parse_cluster_json("this is not json")


def test_parse_missing_topics_raises():
    with pytest.raises(ValueError):
        parse_cluster_json('{"something":"else"}')


def test_parse_empty_raises():
    with pytest.raises(ValueError):
        parse_cluster_json("   ")


def test_tree_to_nodes_shape_and_parents():
    topics = [
        {"label": "T1", "subtopics": [
            {"label": "S1", "leaves": [{"label": "L1", "summary": "s"}, {"bad": 1}]}
        ]},
        {"nolabel": 1},  # skipped
    ]
    nodes = tree_to_nodes("u@x.com", topics)
    kinds = [n["kind"] for n in nodes]
    assert kinds.count("root") == 1
    assert kinds.count("topic") == 1
    assert kinds.count("subtopic") == 1
    assert kinds.count("leaf") == 1  # the malformed leaf is skipped
    root = [n for n in nodes if n["kind"] == "root"][0]
    assert root["parent_id"] is None
    # every non-root points at a real node
    ids = {n["id"] for n in nodes}
    assert all(n["parent_id"] in ids for n in nodes if n["kind"] != "root")
