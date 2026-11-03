"""The looking half of the Trello trigger: what a tick does, and survives.

A poller is exactly the kind of thing that passes every test and never
runs, so these cover the behaviour that matters when it is live at 3am and
nobody is watching, and they are the same four the email poller paid for:

  * one person's rejected Trello token must not stop everybody else's rules
  * a list that cannot be read must NOT move the cursor, or every card that
    changed during the outage is lost
  * a rule pointed at a deleted agent must not produce a failed run per
    card for ever
  * the cursor is written even when nothing fired, because a rule that has
    quietly stopped looking is indistinguishable from one nobody has
    touched

Everything goes through the module's seams, so no test needs a board, an
agent or a model. The live checks (a real card, a real burst, a restart)
are done on the box, because that is the part this cannot prove.
"""
from datetime import datetime, timezone

import pytest

import trello_poller as tp
import trello_trigger as T

LIST_ID = "6ae472c14cc1b6e65b622e10"
NOW = 1_762_000_000


def _rule(rid="r1", owner="owner@example.com", list_id=LIST_ID,
          after=NOW, seen=""):
    return {"id": rid, "user_email": owner, "name": "Watch Review",
            "agent_id": "a1", "instructions": "Summarise it.",
            "trigger": "trello", "trigger_query": list_id,
            "deliver_to": "chat", "hook_token": "hk_x",
            "after_epoch": after, "seen_marks": seen}


def _card(cid, epoch):
    when = datetime.fromtimestamp(epoch, timezone.utc)
    return {"id": cid, "name": "Card " + cid, "url": "https://trello.com/c/" + cid,
            "due": None, "desc": "", "idList": LIST_ID, "idBoard": "b" * 24,
            "dateLastActivity": when.strftime("%Y-%m-%dT%H:%M:%S.000Z")}


@pytest.fixture
def spy(monkeypatch):
    """Replaces every outward call and records what happened."""
    state = {"read": [], "fired": [], "saved": [], "name": "Mia",
             "found": [], "read_error": None, "fire_error": None}

    async def cards(owner, list_id):
        state["read"].append((owner, list_id))
        if state["read_error"]:
            raise RuntimeError(state["read_error"])
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

    monkeypatch.setattr(tp, "_cards_seam", cards)
    monkeypatch.setattr(tp, "_save_cursor_seam", save)
    monkeypatch.setattr(tp, "_agent_name_seam", agent_name)
    monkeypatch.setattr(tp, "_fire_seam", fire)
    return state


# --- the ordinary tick --------------------------------------------------------

async def test_a_changed_card_fires_the_rule_once(spy):
    spy["found"] = [_card("c1", NOW + 30)]
    out = await tp.check_rule(_rule())
    assert out["fired"] == 1
    assert spy["fired"][0][0] == "r1"
    assert spy["fired"][0][1]["id"] == "c1"
    assert spy["fired"][0][2] == "Mia"


async def test_the_cursor_is_written_even_when_nothing_fired(spy):
    """A rule that has quietly stopped looking must be distinguishable from
    one nobody has touched, and checked_at is the only thing that says so."""
    spy["found"] = []
    out = await tp.check_rule(_rule())
    assert out["fired"] == 0
    assert len(spy["saved"]) == 1
    assert spy["saved"][0]["error"] == ""


async def test_the_cursor_is_written_after_firing_not_before(spy):
    """Read, decide, fire, then write. The other order loses the whole
    batch if the process dies mid-fire."""
    spy["found"] = [_card("c1", NOW + 30)]
    await tp.check_rule(_rule())
    assert spy["saved"][-1]["after"] == NOW + 30
    assert T.mark("c1", NOW + 30) in spy["saved"][-1]["seen"]


# --- the things that go wrong -------------------------------------------------

async def test_a_list_that_cannot_be_read_does_not_move_the_cursor(spy):
    """Nothing was read, so nothing has been handled. Moving it here loses
    every card that changed during the outage."""
    spy["read_error"] = "Trello answered 500"
    out = await tp.check_rule(_rule(after=NOW))
    assert out["fired"] == 0
    assert spy["saved"][0]["after"] == NOW
    assert spy["saved"][0]["error"] == "Trello answered 500"
    assert spy["fired"] == []


async def test_a_rejected_token_is_recorded_where_the_person_can_see_it(spy):
    spy["read_error"] = tp.REJECTED
    await tp.check_rule(_rule())
    assert "Reconnect" in spy["saved"][0]["error"]


async def test_a_deleted_agent_stops_the_rule_without_stopping_the_cursor(spy):
    """Otherwise every tick for ever re-reads the same cards and records
    the same failure."""
    spy["found"] = [_card("c1", NOW + 30)]
    spy["name"] = None
    out = await tp.check_rule(_rule())
    assert out["fired"] == 0
    assert spy["fired"] == []
    assert spy["saved"][0]["after"] == NOW + 30
    assert "agent" in spy["saved"][0]["error"]


async def test_one_card_that_will_not_fire_does_not_strand_the_others(spy):
    """fire() swallows its own failures, so reaching the handler means
    something further out broke. The rest of the batch still runs."""
    spy["found"] = [_card("c1", NOW + 10), _card("c2", NOW + 20)]
    spy["fire_error"] = "the runner exploded"
    out = await tp.check_rule(_rule())
    assert out["fired"] == 0
    assert spy["saved"][-1]["error"] == ""


async def test_a_rule_with_no_cursor_starts_from_now_rather_than_zero(spy):
    """The second line of defence behind the COALESCE in _rules. A zero
    here treats every card on the list as new, which is an agent turn per
    card in somebody's backlog."""
    spy["found"] = [_card("c1", NOW - 86_400)]
    out = await tp.check_rule(_rule(after=0))
    assert out["fired"] == 0
    assert spy["read"] == [], "it must not even look before it has a cursor"
    assert spy["saved"][0]["after"] > 0


async def test_a_rule_pointing_at_nothing_is_recorded_not_fired(spy):
    """Refused at creation, so this is a rule edited in the database by
    hand, or one from before the check existed."""
    out = await tp.check_rule(_rule(list_id=""))
    assert out["fired"] == 0
    assert spy["read"] == []
    assert "list" in spy["saved"][0]["error"]


async def test_a_rule_with_no_owner_never_reaches_trello(spy):
    out = await tp.check_rule(_rule(owner=""))
    assert out["fired"] == 0
    assert spy["read"] == []


# --- the loop over everybody --------------------------------------------------

async def test_one_persons_broken_rule_does_not_stop_anybody_elses(spy,
                                                                   monkeypatch):
    """The reason every rule is wrapped on its own. A poller that dies
    takes every rule with it, in a background task where nobody sees it."""
    async def rules():
        return [_rule("bad", owner="a@example.com"),
                _rule("good", owner="b@example.com")]

    monkeypatch.setattr(tp, "_rules_seam", rules)

    real = tp.check_rule

    async def flaky(rule):
        if rule["id"] == "bad":
            raise RuntimeError("something nobody anticipated")
        return await real(rule)

    monkeypatch.setattr(tp, "check_rule", flaky)
    spy["found"] = [_card("c1", NOW + 30)]
    out = await tp.tick_once()
    assert out["rules"] == 2
    assert out["fired"] == 1


async def test_a_tick_that_cannot_list_its_rules_is_not_a_crash(spy,
                                                                monkeypatch):
    async def boom():
        raise RuntimeError("the database is down")

    monkeypatch.setattr(tp, "_rules_seam", boom)
    assert await tp.tick_once() == {"rules": 0, "fired": 0}


# --- what it watches, and on whose behalf -------------------------------------

async def test_it_reads_the_list_the_rule_names_as_the_rules_owner(spy):
    spy["found"] = []
    await tp.check_rule(_rule(owner="her@example.com"))
    assert spy["read"] == [("her@example.com", LIST_ID)]


async def test_the_poller_watches_only_trello_rules():
    """The email poller and this one select on the trigger, which is what
    makes one trigger_query column safe to share between them."""
    import automations
    import inspect
    source = inspect.getsource(tp._rules)
    assert "a.trigger = :kind" in source
    assert automations.TRIGGER_TRELLO == "trello"
