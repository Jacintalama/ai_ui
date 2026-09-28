"""Does the free pool this platform is configured with still exist?

Measured on production 2026-09-28: AGENT_FREE_MODELS named three ids and
OpenRouter still served one of them. nex-agi/nex-n2.5-pro:free and
nex-agi/nex-n2.5-mini:free had been withdrawn, and nex-n2.5-pro had answered
26 real agent runs in the fortnight before that.

Nothing broke loudly, which is the problem. _fallback_pool already filters the
configured pool against the live catalogue, so a withdrawn id is dropped
rather than dialled. Drop two of three and what is left after the agent's own
base model is an empty list: the free agent has nowhere to fall back to and
the person is told "The free models are all busy right now" on the first
provider hiccup, having never reached a second model.

So the fallback did not fail. It quietly stopped existing, and nothing said
so. This module is what says so.
"""
import free_pool


LIVE = {
    "nvidia/nemotron-3-super-120b-a12b:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "cohere/north-mini-code:free",
    "openrouter/free",
}


# --- which configured ids are gone ------------------------------------------

def test_a_withdrawn_id_is_reported():
    gone = free_pool.stale(["nvidia/nemotron-3-super-120b-a12b:free",
                            "nex-agi/nex-n2.5-pro:free"], LIVE)
    assert gone == ["nex-agi/nex-n2.5-pro:free"]


def test_a_pool_that_is_all_live_reports_nothing():
    assert free_pool.stale(["cohere/north-mini-code:free"], LIVE) == []


def test_order_is_the_configured_order():
    """Read back the way it is written, so the answer lines up with the env
    var somebody is about to edit."""
    gone = free_pool.stale(["b:free", "a:free"], {"something-else:free"})
    assert gone == ["b:free", "a:free"]


def test_an_empty_catalogue_counts_as_unreadable():
    """A 200 listing nothing is not evidence that every model was withdrawn.
    agent_runner already treats an empty set as "do not filter", and the two
    must agree or this would report a pool the router is happily using."""
    assert free_pool.stale(["a:free"], set()) == []
    assert free_pool.usable(["a:free"], set()) == ["a:free"]


def test_an_unreadable_catalogue_reports_nothing_rather_than_everything():
    """None means the catalogue could not be read. Calling every id dead
    because OpenRouter was unreachable would page somebody at 3am over a
    network blip, and it is the same reasoning _available_free_ids already
    uses to decide not to filter."""
    assert free_pool.stale(["a:free", "b:free"], None) == []


# --- the thing that actually hurts: nothing left to fall back to ------------

def test_a_pool_with_nothing_live_has_no_fallback():
    assert free_pool.usable(["nex-agi/nex-n2.5-pro:free"], LIVE) == []


def test_usable_keeps_only_what_is_served():
    keep = free_pool.usable(["nvidia/nemotron-3-super-120b-a12b:free",
                             "nex-agi/nex-n2.5-mini:free",
                             "cohere/north-mini-code:free"], LIVE)
    assert keep == ["nvidia/nemotron-3-super-120b-a12b:free",
                    "cohere/north-mini-code:free"]


def test_an_unreadable_catalogue_leaves_the_pool_alone():
    pool = ["a:free", "b:free"]
    assert free_pool.usable(pool, None) == pool


# --- the report -------------------------------------------------------------

def test_the_report_names_what_is_configured_and_what_is_gone(monkeypatch):
    monkeypatch.setattr(free_pool, "CONFIGURED",
                        ["nvidia/nemotron-3-super-120b-a12b:free",
                         "nex-agi/nex-n2.5-pro:free"])
    report = free_pool.report(LIVE)
    assert report["configured"] == ["nvidia/nemotron-3-super-120b-a12b:free",
                                    "nex-agi/nex-n2.5-pro:free"]
    assert report["stale"] == ["nex-agi/nex-n2.5-pro:free"]
    assert report["usable"] == ["nvidia/nemotron-3-super-120b-a12b:free"]
    assert report["ok"] is False


def test_a_healthy_pool_reports_ok(monkeypatch):
    monkeypatch.setattr(free_pool, "CONFIGURED",
                        ["cohere/north-mini-code:free",
                         "nvidia/nemotron-3-ultra-550b-a55b:free"])
    assert free_pool.report(LIVE)["ok"] is True


def test_one_survivor_is_not_ok(monkeypatch):
    """One live id is not a pool. The survivor IS the agent's own base model
    in the usual case, so after excluding it there is nothing left, which is
    exactly the production state this module was written for."""
    monkeypatch.setattr(free_pool, "CONFIGURED",
                        ["cohere/north-mini-code:free", "gone-a:free",
                         "gone-b:free"])
    report = free_pool.report(LIVE)
    assert report["usable"] == ["cohere/north-mini-code:free"]
    assert report["ok"] is False


def test_an_unreadable_catalogue_is_not_a_verdict(monkeypatch):
    """Neither healthy nor broken: unknown. Saying ok would hide a real
    failure and saying broken would invent one."""
    monkeypatch.setattr(free_pool, "CONFIGURED", ["a:free"])
    report = free_pool.report(None)
    assert report["ok"] is None
    assert report["stale"] == []


def test_the_report_carries_a_sentence_somebody_can_act_on(monkeypatch):
    monkeypatch.setattr(free_pool, "CONFIGURED", ["live:free", "gone:free"])
    said = free_pool.report({"live:free"})["summary"]
    assert "gone:free" in said
    assert "AGENT_FREE_MODELS" in said
