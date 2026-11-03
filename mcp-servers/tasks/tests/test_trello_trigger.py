"""A card on a Trello list starting an automation: the deciding half.

The one-click connect was built so a rule could watch a board. Connecting
was finished on 2026-10-31 and nothing could watch anything: automations had
two triggers, a webhook and an email. This is the third.

What these pin down, all of it decided here and none of it in the poller, so
none of it needs a board to test:

  * a brand new rule does NOT fire on the cards already sitting on the list.
    Unlike Gmail, Trello filters nothing for us: the cards call returns every
    card on the list whatever its age, so the window is ours to apply and
    getting it wrong is an agent turn per card in somebody's backlog.
  * a card that changes twice fires twice, and the same change never fires
    twice. An email arrives once; a card keeps changing, which is why the
    mark is `id@epoch` and not the id.
  * a burst is capped, and the cursor still moves past what the cap dropped.
  * a card nobody can date is dropped rather than fired on for ever.
"""
import pytest

import trello_trigger as T

LIST_ID = "6ae472c14cc1b6e65b622e10"
NOW = 1_762_000_000


def _card(cid, epoch, name="Write the brief", list_id=LIST_ID):
    """A card as Trello returns it, with the fields the poller asks for."""
    from datetime import datetime, timezone
    when = datetime.fromtimestamp(epoch, timezone.utc)
    return {"id": cid, "name": name, "url": "https://trello.com/c/" + cid,
            "due": None, "desc": "", "idList": list_id,
            "idBoard": "b" * 24,
            "dateLastActivity": when.strftime("%Y-%m-%dT%H:%M:%S.000Z")}


# --- which list a rule may watch ---------------------------------------------

def test_a_rule_must_say_which_list():
    """Refused at the door, for the same reason an empty Gmail query is: a
    rule that can never fire is indistinguishable from one nobody has
    touched, so it must not be saveable."""
    assert T.list_problem("") != ""
    assert T.list_problem(None) != ""
    assert T.list_problem("   ") != ""


def test_a_real_list_id_passes():
    assert T.list_problem(LIST_ID) == ""
    assert T.looks_like_id(LIST_ID) is True


def test_something_that_was_never_an_id_is_refused():
    """A board URL, a list name, or anything else somebody might paste."""
    for junk in ["Review", "https://trello.com/b/Kp6lFKUl/my-trello-board",
                 "6ae472c14cc1b6e65b622e1", "6ae472c14cc1b6e65b622e100",
                 "z" * 24]:
        assert T.list_problem(junk) != "", junk


# --- a new rule does not fire on the backlog ---------------------------------

def test_a_new_rule_ignores_the_cards_already_there():
    """THE expensive mistake. A list with twenty cards on it and a rule made
    today is twenty agent turns if the window is wrong, and that is a bill
    and a board full of comments rather than a feature."""
    old = [_card("c%d" % i, NOW - 86_400) for i in range(20)]
    to_fire, skipped, cursor, seen = T.new_cards(old, [], NOW)
    assert to_fire == []
    assert skipped == 0
    assert cursor == NOW, "nothing was accounted for, so nothing moved"
    assert seen == []


def test_a_card_that_changes_after_the_rule_was_made_fires():
    fresh = [_card("c1", NOW + 30)]
    to_fire, _, cursor, seen = T.new_cards(fresh, [], NOW)
    assert [c["id"] for c in to_fire] == ["c1"]
    assert cursor == NOW + 30
    assert seen == [T.mark("c1", NOW + 30)]


# --- the same change never fires twice ---------------------------------------

def test_the_overlap_does_not_re_fire_what_was_already_handled():
    """The look deliberately reaches back OVERLAP_SECONDS, because Trello
    stamps its own clock. The marks are what stop that becoming a duplicate
    agent turn."""
    card = _card("c1", NOW + 10)
    first, _, cursor, seen = T.new_cards([card], [], NOW)
    assert len(first) == 1
    second, _, cursor2, _ = T.new_cards([card], seen, cursor)
    assert second == [], "the same change fired twice"
    assert cursor2 == cursor


def test_a_card_that_changes_again_fires_again():
    """The whole reason the mark carries the time. A card is not an email:
    remembering only its id would fire once and then stay silent however
    much happened to it afterwards."""
    _, _, cursor, seen = T.new_cards([_card("c1", NOW + 10)], [], NOW)
    again, _, _, _ = T.new_cards([_card("c1", NOW + 600)], seen, cursor)
    assert [c["id"] for c in again] == ["c1"]


def test_the_same_card_twice_in_one_answer_counts_once():
    card = _card("c1", NOW + 10)
    to_fire, _, _, _ = T.new_cards([card, dict(card)], [], NOW)
    assert len(to_fire) == 1


# --- order, the cap, and the cursor ------------------------------------------

def test_cards_reach_the_agent_oldest_first():
    """Three cards moved in a row should arrive in the order they moved,
    not backwards."""
    cards = [_card("c3", NOW + 300), _card("c1", NOW + 100),
             _card("c2", NOW + 200)]
    to_fire, _, _, _ = T.new_cards(cards, [], NOW)
    assert [c["id"] for c in to_fire] == ["c1", "c2", "c3"]


def test_a_flood_is_capped_and_the_rest_counted():
    """Somebody dragging twenty cards into Review at once must not become
    twenty agent turns."""
    cards = [_card("c%02d" % i, NOW + i + 1) for i in range(20)]
    to_fire, skipped, _, _ = T.new_cards(cards, [], NOW)
    assert len(to_fire) == T.BURST
    assert skipped == 20 - T.BURST


def test_the_cursor_moves_past_what_the_cap_dropped():
    """Holding it back would make the same flood arrive again on the next
    tick, for ever."""
    cards = [_card("c%02d" % i, NOW + i + 1) for i in range(20)]
    _, _, cursor, seen = T.new_cards(cards, [], NOW)
    assert cursor == NOW + 20
    again, skipped, _, _ = T.new_cards(cards, seen, cursor)
    assert again == [] and skipped == 0


def test_the_cursor_never_goes_backwards():
    old = [_card("c1", NOW - 5000)]
    _, _, cursor, _ = T.new_cards(old, [], NOW)
    assert cursor == NOW


def test_what_is_remembered_is_capped_and_keeps_the_newest():
    """The cap must keep what the overlap might show us again, so the list
    is newest first."""
    cards = [_card("c%04d" % i, NOW + i + 1) for i in range(T.SEEN_KEPT + 50)]
    _, _, _, seen = T.new_cards(cards, [], NOW)
    assert len(seen) == T.SEEN_KEPT
    assert seen[0] == T.mark("c%04d" % (T.SEEN_KEPT + 49), NOW + T.SEEN_KEPT + 50)


# --- reading Trello's own timestamp -------------------------------------------

def test_the_time_comes_from_trellos_last_activity():
    assert T._epoch_of(_card("c1", NOW + 7)) == NOW + 7


def test_a_card_nobody_can_date_is_dropped_not_fired_on():
    """The deliberate direction. The other way round, one malformed card
    fires its rule on every tick for ever."""
    for bad in [{}, {"id": "c1"}, {"id": "c1", "dateLastActivity": ""},
                {"id": "c1", "dateLastActivity": "last tuesday"},
                {"id": "c1", "dateLastActivity": None}]:
        assert T._epoch_of(bad) == 0
    to_fire, _, cursor, _ = T.new_cards(
        [{"id": "c1", "dateLastActivity": "last tuesday"}], [], NOW)
    assert to_fire == []
    assert cursor == NOW


def test_a_due_date_is_never_mistaken_for_activity():
    """A due date is set by whoever made the card and says nothing about
    when it changed. Using it would fire on cards due next week and never
    on the one that just moved."""
    card = _card("c1", NOW - 86_400)
    card["due"] = "2099-01-01T00:00:00.000Z"
    to_fire, _, _, _ = T.new_cards([card], [], NOW)
    assert to_fire == []


def test_rubbish_in_the_answer_is_stepped_over():
    """Never raises on what a vendor sends, because this runs in a
    background loop where a traceback is invisible."""
    to_fire, _, _, _ = T.new_cards(
        ["not a card", None, 7, {"no": "id"}, _card("c1", NOW + 5)], [], NOW)
    assert [c["id"] for c in to_fire] == ["c1"]


def test_nothing_at_all_is_not_an_error():
    for empty in [None, [], ()]:
        assert T.new_cards(empty, [], NOW) == ([], 0, NOW, [])


# --- what the agent is handed -------------------------------------------------

def test_the_payload_names_the_card_and_where_it_is():
    """Flat and named: automations.message_for puts this under a line
    saying it is data, and an agent reading "name" and "list_id" can act on
    it where a raw Trello card would make it guess at nesting."""
    card = _card("c1", NOW, name="  Chase   the invoice ")
    payload = T.payload_for(card)
    assert payload["id"] == "c1"
    assert payload["name"] == "Chase the invoice"
    assert payload["list_id"] == LIST_ID
    assert payload["url"].endswith("/c1")
    assert payload["changed"]


def test_a_card_with_an_essay_on_it_does_not_crowd_out_the_rule():
    """The rest is one tool call away. A card's description must not push
    the rule's own instructions out of the agent's turn."""
    card = _card("c1", NOW)
    card["desc"] = "x" * 5000
    assert len(T.payload_for(card)["description"]) == T.MAX_DESC_CHARS


def test_a_payload_never_carries_a_nested_trello_object():
    """Everything in it is a string, so nothing downstream has to walk it."""
    card = _card("c1", NOW)
    card["badges"] = {"votes": 3}
    card["labels"] = [{"color": "red"}]
    payload = T.payload_for(card)
    assert "badges" not in payload and "labels" not in payload
    assert all(isinstance(v, str) for v in payload.values())


# --- the shape of the thing ---------------------------------------------------

def test_trello_is_a_trigger_an_automation_can_have():
    import automations
    assert automations.TRIGGER_TRELLO in automations.TRIGGERS


def test_a_trello_rule_cannot_be_saved_without_a_list():
    """The validation the form and the API share. Same door as the email
    rule's empty query."""
    import automations
    assert automations.problem_with(
        "Watch Review", "Summarise it.", "chat",
        automations.TRIGGER_TRELLO, "") != ""
    assert automations.problem_with(
        "Watch Review", "Summarise it.", "chat",
        automations.TRIGGER_TRELLO, LIST_ID) == ""


def test_a_webhook_rule_is_unaffected_by_any_of_this():
    """Every rule that existed before this is a webhook, and none of them
    says what to watch."""
    import automations
    assert automations.problem_with(
        "Old rule", "Do the thing.", "chat",
        automations.TRIGGER_WEBHOOK, "") == ""
