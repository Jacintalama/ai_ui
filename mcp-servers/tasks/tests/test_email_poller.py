"""The looking half of the email trigger: what a tick does, and survives.

A poller is exactly the kind of thing that passes every test and never runs,
so these cover the behaviour that matters when it is live at 3am and nobody
is watching:

  * one person's revoked token must not stop everybody else's rules
  * a mailbox that cannot be read must NOT move the cursor, or the mail that
    arrived during the outage is lost for ever
  * a rule pointed at a deleted agent must not produce a failed run per
    email for ever
  * the cursor is written even when nothing fired, because a rule that has
    quietly stopped looking is indistinguishable from one nobody emailed

Everything goes through the module's seams, so no test needs a mailbox, an
agent or a model. The live checks (a real email, a real burst, a restart)
are done on the box, because that is the part this cannot prove.
"""
import asyncio

import pytest

import email_poller as ep
import email_trigger as et


def _rule(rid="r1", owner="owner@example.com", query="from:boss@example.com",
          after=1_000_000, seen=""):
    return {"id": rid, "user_email": owner, "name": "Chase leads",
            "agent_id": "a1", "instructions": "Deal with it.",
            "trigger": "email", "trigger_query": query, "deliver_to": "chat",
            "hook_token": "hk_x", "after_epoch": after, "seen_ids": seen}


def _msg(mid, epoch, subject="hello"):
    return {"id": mid, "thread_id": "t-" + mid, "from": "boss@example.com",
            "subject": subject, "date": "Wed, 29 Oct 2026 09:00:00 +0000",
            "snippet": "...", "internal_date": str(epoch * 1000)}


@pytest.fixture
def spy(monkeypatch):
    """Replaces every outward call and records what happened."""
    state = {"searched": [], "fired": [], "saved": [], "name": "Mia",
             "found": [], "search_error": None, "fire_error": None}

    async def search(owner, query):
        state["searched"].append((owner, query))
        if state["search_error"]:
            raise RuntimeError(state["search_error"])
        return state["found"]

    async def save(rid, owner, after, seen, error=""):
        state["saved"].append({"id": rid, "after": after,
                               "seen": list(seen), "error": error})

    async def agent_name(owner, agent_id):
        return state["name"]

    async def fire(automation, payload, name):
        if state["fire_error"]:
            raise RuntimeError(state["fire_error"])
        state["fired"].append((automation["id"], payload, name))

    monkeypatch.setattr(ep, "_search_seam", search)
    monkeypatch.setattr(ep, "_save_cursor_seam", save)
    monkeypatch.setattr(ep, "_agent_name_seam", agent_name)
    monkeypatch.setattr(ep, "_fire_seam", fire)
    return state


def _check(rule):
    return asyncio.run(ep.check_rule(rule))


# --- the ordinary case --------------------------------------------------------

def test_a_new_email_fires_the_rule(spy):
    spy["found"] = [_msg("m1", 1_000_100, subject="Invoice 42")]
    out = _check(_rule())
    assert out["fired"] == 1
    _rid, payload, name = spy["fired"][0]
    assert payload["subject"] == "Invoice 42"
    assert name == "Mia"


def test_the_rule_asks_gmail_for_its_own_query_and_window(spy):
    _check(_rule(query="from:boss@example.com is:unread", after=1_000_000))
    owner, query = spy["searched"][0]
    assert owner == "owner@example.com"
    assert query == "from:boss@example.com is:unread after:%d" % (
        1_000_000 - et.OVERLAP_SECONDS)


def test_the_cursor_moves_to_the_newest_message(spy):
    spy["found"] = [_msg("m1", 1_000_100), _msg("m2", 1_000_200)]
    _check(_rule())
    assert spy["saved"][-1]["after"] == 1_000_200


def test_what_fired_is_remembered_so_the_overlap_does_not_refire_it(spy):
    spy["found"] = [_msg("m1", 1_000_100)]
    _check(_rule())
    assert "m1" in spy["saved"][-1]["seen"]


def test_an_email_already_seen_does_not_fire_again(spy):
    """The overlap guarantees Gmail offers it a second time."""
    spy["found"] = [_msg("m1", 1_000_100)]
    out = _check(_rule(seen="m1"))
    assert out["fired"] == 0 and spy["fired"] == []


def test_the_oldest_email_is_fired_first(spy):
    spy["found"] = [_msg("new", 1_000_300), _msg("old", 1_000_100)]
    _check(_rule())
    assert [p["id"] for _r, p, _n in spy["fired"]] == ["old", "new"]


# --- nothing happened, which must still be recorded ----------------------------

def test_an_empty_mailbox_still_writes_the_cursor(spy):
    """A rule that has quietly stopped looking is indistinguishable from one
    nobody has emailed, unless checked_at keeps moving."""
    spy["found"] = []
    out = _check(_rule())
    assert out["fired"] == 0
    assert len(spy["saved"]) == 1, "the tick left no trace that it ran"
    assert spy["saved"][0]["error"] == ""


def test_an_empty_mailbox_does_not_move_the_cursor(spy):
    spy["found"] = []
    _check(_rule(after=1_000_000))
    assert spy["saved"][0]["after"] == 1_000_000


# --- a mailbox that cannot be read ---------------------------------------------

def test_a_mailbox_that_cannot_be_read_does_not_move_the_cursor(spy):
    """The most important failure case. Nothing was read, so nothing has
    been handled: moving the cursor would silently lose every email that
    arrived during the outage."""
    spy["search_error"] = ep.NOT_CONNECTED
    _check(_rule(after=1_000_000))
    assert spy["saved"][0]["after"] == 1_000_000
    assert ep.NOT_CONNECTED in spy["saved"][0]["error"]
    assert spy["fired"] == []


def test_a_disconnected_account_is_said_in_our_own_words(spy):
    spy["search_error"] = ep.NOT_CONNECTED
    out = _check(_rule())
    assert out["error"] == ep.NOT_CONNECTED
    # Not the gmail service's own sentence, which carries a connect URL
    # written for a chat reply.
    assert "http" not in spy["saved"][0]["error"]


def test_a_failed_read_keeps_what_was_already_seen(spy):
    """Clearing it would make the overlap re-fire old mail once the mailbox
    came back."""
    spy["search_error"] = "gmail answered 500"
    _check(_rule(seen="m1,m2"))
    assert spy["saved"][0]["seen"] == ["m1", "m2"]


# --- a rule that can never work ------------------------------------------------

def test_a_rule_with_no_query_is_not_fired(spy):
    """Refused at creation, so this is a rule from before the check or one
    edited in the database by hand. An empty query matches every email the
    person has."""
    spy["found"] = [_msg("m1", 1_000_100)]
    out = _check(_rule(query=""))
    assert spy["fired"] == [] and out["error"] == "no query"
    assert spy["searched"] == [], "it asked Gmail for everything"


def test_a_deleted_agent_does_not_fail_once_per_email_for_ever(spy):
    """The cursor still advances. Otherwise every tick re-reads the same
    mail and records the same failure, until somebody notices."""
    spy["found"] = [_msg("m1", 1_000_100)]
    spy["name"] = None
    out = _check(_rule(after=1_000_000))
    assert out["error"] == "no agent" and spy["fired"] == []
    assert spy["saved"][0]["after"] == 1_000_100
    assert "no longer exists" in spy["saved"][0]["error"]


# --- the burst cap -------------------------------------------------------------

def test_a_flood_is_capped(spy):
    spy["found"] = [_msg("m%d" % i, 1_000_100 + i) for i in range(20)]
    out = _check(_rule())
    assert out["fired"] == et.BURST
    assert out["skipped"] == 20 - et.BURST


def test_a_capped_flood_still_advances_past_everything(spy):
    """Otherwise the same flood arrives again on the next tick, for ever."""
    spy["found"] = [_msg("m%d" % i, 1_000_100 + i) for i in range(20)]
    _check(_rule())
    assert spy["saved"][-1]["after"] == 1_000_100 + 19
    assert len(spy["saved"][-1]["seen"]) == 20


# --- one bad message must not strand the rest ----------------------------------

def test_a_firing_that_blows_up_does_not_stop_the_batch(spy, monkeypatch):
    """fire() swallows and records its own failures, so reaching this means
    something further out broke. The rest of the batch still runs."""
    spy["found"] = [_msg("m1", 1_000_100), _msg("m2", 1_000_200)]
    calls = []

    async def fire(automation, payload, name):
        calls.append(payload["id"])
        if payload["id"] == "m1":
            raise RuntimeError("the runner fell over")

    monkeypatch.setattr(ep, "_fire_seam", fire)
    out = _check(_rule())
    assert calls == ["m1", "m2"], "the second message was stranded"
    assert out["fired"] == 1


# --- the tick over everybody ----------------------------------------------------

def test_one_persons_broken_rule_does_not_stop_anybody_elses(monkeypatch, spy):
    """The reason every rule is wrapped on its own."""
    async def rules():
        return [_rule("bad", owner="a@example.com"),
                _rule("good", owner="b@example.com")]

    async def check(rule):
        if rule["id"] == "bad":
            raise RuntimeError("this rule is cursed")
        return {"fired": 1, "skipped": 0, "error": ""}

    monkeypatch.setattr(ep, "_rules_seam", rules)
    monkeypatch.setattr(ep, "check_rule", check)
    out = asyncio.run(ep.tick_once())
    assert out == {"rules": 2, "fired": 1}


def test_a_tick_that_cannot_list_its_rules_does_not_raise(monkeypatch):
    """It runs in a background task, so a raise here is a traceback nobody
    reads and a poller that never ticks again."""
    async def rules():
        raise RuntimeError("the database went away")

    monkeypatch.setattr(ep, "_rules_seam", rules)
    assert asyncio.run(ep.tick_once()) == {"rules": 0, "fired": 0}


def test_no_rules_is_not_an_error(monkeypatch):
    async def rules():
        return []

    monkeypatch.setattr(ep, "_rules_seam", rules)
    assert asyncio.run(ep.tick_once()) == {"rules": 0, "fired": 0}


# --- the shape of the thing -----------------------------------------------------

def test_the_poller_reads_mail_as_the_rules_owner(spy):
    """Not as anybody else, and never as a shared account. This is the
    invariant PR #49 and #50 made true enough to rely on."""
    _check(_rule(owner="someone@example.com"))
    assert spy["searched"][0][0] == "someone@example.com"


def test_a_tick_is_a_minute():
    """Faster is a webhook's job; slower and "when an email arrives" stops
    being a fair description of it."""
    assert ep.TICK_SECONDS == 60


def test_a_rule_with_no_cursor_at_all_does_not_read_the_whole_mailbox(spy):
    """The one mistake in this file that spends real money.

    The cursor is meant to start at the rule's creation time, which the
    _rules query does with a COALESCE and which is proven against a real
    database. This is the second line of defence for when it somehow is not:
    a zero would ask Gmail for everything and fire an agent turn per message
    in the mailbox's history.
    """
    spy["found"] = [_msg("m1", 1_000_100)]
    out = _check(_rule(after=0))
    assert spy["searched"] == [], "it asked Gmail for the whole mailbox"
    assert spy["fired"] == []
    assert out["error"] == "no cursor"
    # And it starts properly from now, rather than staying stuck at zero and
    # refusing for ever.
    assert spy["saved"][0]["after"] > 1_700_000_000
