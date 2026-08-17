"""Which conversations get to shape the Brain.

The graph clusters your chats into topics, and it could only ever read a
handful of them. It took the 30 most recently touched, which is a proxy for
"the ones that matter" and a bad one: measured on Ralph's own account, 64
conversations, 24 of them substantial and 6 trivial. Under recency ordering,
34 of the 64 contributed nothing but a title, and which 34 got dropped was
decided by whatever he happened to open last. Two chats literally titled "hi"
outranked a fortnight of real work.

So selection is by substance, with a recent slice kept so the graph still
feels live. Pure function, no database, because the rule is the thing worth
pinning and it is the one part that has nothing to do with SQL.
"""
import os

os.environ.setdefault("AIUI_FERNET_KEY",
                      "hUZ3RkVvY0JmS3FnWlp4TXcyN0RkNTZWc1RCQzNKS1E=")

import routes_knowledge_graph as kg


def chat(cid, size, title="t"):
    """A candidate as the metadata query returns it: newest first."""
    return {"id": cid, "title": title, "size": size}


def ids(chosen):
    return [c["id"] for c in chosen]


def test_a_substantial_chat_beats_a_newer_trivial_one():
    """The whole point. "hi" from today must not displace a real conversation
    from last week."""
    pool = [chat("hi-today", 300), chat("hi-yesterday", 320),
            chat("real-old", 40000), chat("also-real", 30000)]
    got = ids(kg.choose_chats(pool, limit=2, recent=0))
    assert got == ["real-old", "also-real"]


def test_the_newest_are_always_kept():
    """Substance alone would make the graph feel frozen: a big conversation
    from March would outrank everything you did this morning, forever."""
    pool = [chat("today", 3000), chat("yesterday", 2500),
            chat("huge-in-march", 90000)]
    got = ids(kg.choose_chats(pool, limit=3, recent=2))
    assert "today" in got and "yesterday" in got and "huge-in-march" in got


def test_the_recent_slice_cannot_eat_the_whole_budget():
    pool = [chat(f"c{i}", 5000) for i in range(20)]
    got = kg.choose_chats(pool, limit=5, recent=3)
    assert len(got) == 5


def test_a_trivial_chat_never_takes_a_slot():
    """Below the floor it contributes nothing but noise to the clustering,
    and it costs a slot a real conversation could have used."""
    pool = [chat("greeting", 200), chat("real", 20000)]
    got = ids(kg.choose_chats(pool, limit=5, recent=5, floor=1500))
    assert got == ["real"]


def test_everything_trivial_still_returns_something():
    """A brand new account has nothing substantial yet. Returning empty would
    give it no graph at all, which is worse than a thin one."""
    pool = [chat("a", 200), chat("b", 300)]
    got = ids(kg.choose_chats(pool, limit=5, recent=2, floor=1500))
    assert got, "a new user would get no topics at all"


def test_no_chat_is_chosen_twice():
    """The recent slice and the substance fill overlap by construction: the
    newest chat is often also the biggest."""
    pool = [chat("big-and-new", 90000), chat("b", 20000), chat("c", 19000)]
    got = ids(kg.choose_chats(pool, limit=3, recent=2))
    assert len(got) == len(set(got)) == 3


def test_the_order_stays_newest_first():
    """The corpus is truncated downstream, so whatever leads it matters."""
    pool = [chat("new", 5000), chat("mid", 90000), chat("old", 40000)]
    got = ids(kg.choose_chats(pool, limit=3, recent=1))
    assert got[0] == "new"


def test_an_empty_account_is_not_an_error():
    assert kg.choose_chats([], limit=5, recent=2) == []


# --- how much of each chat is read -------------------------------------

def test_a_chosen_chat_is_read_more_deeply_than_before():
    """600 characters of an 8000-character conversation is 7% of it. The
    budget is shared, so this is bounded, not unbounded."""
    assert kg.snippet_budget(30) > 600


def test_the_total_read_is_bounded_across_every_reachable_size():
    """The constraint on a 3.8GB box is total text, not a count of chats.

    Only up to MAX_CHATS, because that is all that can occur: choose_chats
    caps what it returns, and the floor under a single snippet (MIN_SNIPPET,
    so a snippet is never uselessly small) would otherwise win past it. The
    cap is what makes the budget hold, so it is asserted below rather than
    assumed here.
    """
    for n in range(1, kg.MAX_CHATS + 1):
        assert kg.snippet_budget(n) * n <= kg.SNIPPET_BUDGET + kg.MAX_SNIPPET, n


def test_the_number_of_chats_is_itself_capped():
    """What keeps the budget above honest. Without this the per-chat floor
    would multiply out past the total on a big account."""
    pool = [chat(f"c{i}", 20000) for i in range(500)]
    assert len(kg.choose_chats(pool)) <= kg.MAX_CHATS


def test_one_chat_does_not_get_the_entire_budget():
    """Otherwise a single long conversation becomes the whole corpus and the
    clustering has nothing to compare it against."""
    assert kg.snippet_budget(1) <= kg.MAX_SNIPPET
