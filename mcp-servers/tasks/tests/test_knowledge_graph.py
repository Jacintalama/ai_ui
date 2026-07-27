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


# --- Phase 3: denser build helpers (pure) ------------------------------------
from routes_knowledge_graph import (make_node, best_parent_id, attach_chats,
                                     source_branch)


def test_make_node_trims_and_defaults():
    n = make_node("u@x.com", "chat", "  Hello  ", "p1")
    assert n["kind"] == "chat" and n["label"] == "Hello" and n["parent_id"] == "p1"
    assert n["summary"] is None and n["id"]
    blank = make_node("u@x.com", "chat", "   ", None)
    assert blank["label"] == "(untitled)"


_TOPICS = [
    {"id": "t_email", "kind": "topic", "label": "Email Management", "summary": None},
    {"id": "t_crm", "kind": "topic", "label": "CRM Solutions", "summary": None},
    {"id": "s_gmail", "kind": "subtopic", "label": "Gmail Setup", "summary": "connecting gmail"},
]


def test_best_parent_matches_topic():
    assert best_parent_id("connect my gmail account", _TOPICS, "root") == "s_gmail"
    assert best_parent_id("which crm should I pick", _TOPICS, "root") == "t_crm"


def test_best_parent_falls_back_to_default():
    assert best_parent_id("totally unrelated xyzzy", _TOPICS, "root") == "root"
    assert best_parent_id("", _TOPICS, "root") == "root"


def test_attach_chats_assigns_parents_and_kind():
    chats = [
        {"title": "Gmail connection help", "snippet": "connect gmail"},
        {"title": "Best CRM tools", "snippet": "crm comparison"},
        {"title": "Random musing", "snippet": "xyzzy nothing"},
        {"title": "", "snippet": "skipped, no title"},
    ]
    out = attach_chats("u@x.com", "root", _TOPICS, chats)
    assert len(out) == 3                       # blank-title chat skipped
    assert all(n["kind"] == "chat" for n in out)
    by_label = {n["label"]: n["parent_id"] for n in out}
    assert by_label["Gmail connection help"] == "s_gmail"
    assert by_label["Best CRM tools"] == "t_crm"
    assert by_label["Random musing"] == "root"   # no match -> default


def test_source_branch_builds_hub_and_items():
    out = source_branch("u@x.com", "root", "Uploaded Files",
                        [{"label": "a.pdf"}, {"label": "b.docx"}, {"label": "  "}],
                        "document")
    assert out[0]["kind"] == "topic" and out[0]["label"] == "Uploaded Files"
    hub_id = out[0]["id"]
    items = out[1:]
    assert len(items) == 2                      # blank label dropped
    assert all(i["kind"] == "document" and i["parent_id"] == hub_id for i in items)


def test_source_branch_empty_makes_no_hub():
    assert source_branch("u@x.com", "root", "Saved Memories", [], "memory") == []


# --- Phase 4: accuracy helpers -----------------------------------------------
from routes_knowledge_graph import prettify_slug


def test_prettify_slug_strips_hash_and_titlecases():
    assert prettify_slug("create-me-a-shoe-website-fe02") == "Create Me A Shoe Website"
    assert prettify_slug("upload-c2f78c78") == "Upload"
    assert prettify_slug("ralph-portfolio") == "Ralph Portfolio"
    assert prettify_slug("crudsimple") == "Crudsimple"
    assert prettify_slug("") == "app"


# --- deleted-app accuracy: disk presence is truth ----------------------------
from routes_knowledge_graph import _app_exists


def test_app_exists_true_when_dir_present(tmp_path):
    (tmp_path / "my-app").mkdir()
    assert _app_exists("my-app", root=str(tmp_path)) is True


def test_app_exists_false_when_deleted(tmp_path):
    assert _app_exists("gone-app", root=str(tmp_path)) is False


def test_app_exists_fails_open_when_root_missing(tmp_path):
    # Apps root not mounted (local dev): cannot tell -> keep apps visible.
    assert _app_exists("any-app", root=str(tmp_path / "nope")) is True


def test_app_exists_blank_slug_false(tmp_path):
    assert _app_exists("", root=str(tmp_path)) is False
