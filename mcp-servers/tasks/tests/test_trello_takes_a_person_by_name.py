"""Per-user Trello can assign, unassign, archive and complete (2026-11-11).

Measured off `mcp_proxy.tool_embeddings` on 2026-11-11, the shared Trello
connector has 25 tools and the per-user one has 7:

    my-trello   list_my_boards, list_board_lists, list_cards, create_card,
                update_card, comment_on_card, whoami
    trello      ...plus assign_member_to_card, remove_member_from_card,
                archive_card, get_board_members, get_my_cards and 13 more

That gap is why the shared `trello` server is still switched on, and why
four admins act as `clarenzbacalla` whenever a `trello_*` tool is picked.
It is also why our own end-of-day workflow has a line in it saying that to
assign a member or move a card I have to drop to raw Trello REST: the
per-user tools cannot do it.

So this closes the practical half of the gap, following the ClickUp
precedent exactly: ids are looked up before the call, from Trello's own
answers, and nothing is written on a guess.

Two things Trello does differently from ClickUp, both of which the tests
below pin down:

  - A member id is 24 hex characters, so the SHAPE of the value says
    whether it needs looking up, the same way `needs_list_lookup` reads a
    ClickUp list.
  - A card knows its board (`idBoard`) but a card id is not a board id, so
    resolving a name costs two reads: the card, then that board's members.

The member fixture is the real HS RESEARCH TEAM board, which is the honest
case: it has TWO accounts both called "Lukas Herajt", so "assign it to
Lukas" is genuinely ambiguous and must not pick one at random.
"""
import asyncio
import json

import pytest

import mytools
import trello_people as tp

# GET /boards/{id}/members, Trello's own shape: a flat list, no envelope.
BOARD_MEMBERS = [
    {"id": "677516d725a2685d2f192a41", "fullName": "Clarenz",
     "username": "clarenzbacalla"},
    {"id": "695e6a06ceaa80bd911526a6", "fullName": "Jacint Alama",
     "username": "jacintalama1"},
    {"id": "695e6a595f94f329ebef8cdd", "fullName": "Lukas Herajt",
     "username": "lukasherajt2"},
    {"id": "697791efc9eb5c0cf0c7640d", "fullName": "Lukas Herajt",
     "username": "lukasherajt3"},
    {"id": "6598cf639c285cdb6e639124", "fullName": "Ralph Benitez",
     "username": "ralphbenitez1"},
]

RALPH = "6598cf639c285cdb6e639124"
CLARENZ = "677516d725a2685d2f192a41"
BOARD = "695e66722b207c49a7e829c3"
CARD = "6ae9e7ab0000000000000001"

# GET /cards/{id}
CARD_ROW = {"id": CARD, "name": "Reconnect GitHub", "idBoard": BOARD,
            "idList": "695e669823c7213cd15275ac", "idMembers": []}

MEMBERS = tp.members_of(BOARD_MEMBERS)


# --- the shape of a value tells you whether to look it up -------------------

def test_a_24_character_hex_id_needs_no_lookup():
    assert tp.needs_lookup(RALPH) is False


def test_a_name_needs_a_lookup():
    assert tp.needs_lookup("ralph") is True


def test_a_username_needs_a_lookup():
    assert tp.needs_lookup("ralphbenitez1") is True


def test_blank_is_not_a_name_to_look_up():
    """Nothing to resolve, and a walk would list the whole board as a
    suggestion for a value nobody gave."""
    assert tp.needs_lookup("") is False
    assert tp.needs_lookup(None) is False


def test_a_24_character_string_that_is_not_hex_is_still_a_name():
    assert tp.needs_lookup("z" * 24) is True


# --- resolving a person -----------------------------------------------------

def test_members_come_off_trellos_flat_list():
    assert len(MEMBERS) == 5
    assert {m["username"] for m in MEMBERS} >= {"ralphbenitez1", "clarenzbacalla"}


def test_an_id_resolves_to_itself():
    assert tp.resolve_person(RALPH, MEMBERS) == (RALPH, None)


def test_a_username_resolves_to_its_id():
    assert tp.resolve_person("ralphbenitez1", MEMBERS) == (RALPH, None)


def test_a_full_name_resolves_to_its_id():
    assert tp.resolve_person("Ralph Benitez", MEMBERS) == (RALPH, None)


def test_a_first_name_resolves_to_its_id():
    assert tp.resolve_person("ralph", MEMBERS) == (RALPH, None)


def test_a_one_word_full_name_resolves():
    assert tp.resolve_person("Clarenz", MEMBERS) == (CLARENZ, None)


def test_two_people_of_the_same_name_are_not_guessed_between():
    """The real reason this matters: the board has two Lukas Herajt
    accounts, and our workflow notes say to ask which is live."""
    who, problem = tp.resolve_person("Lukas", MEMBERS)
    assert who is None
    assert "lukasherajt2" in problem and "lukasherajt3" in problem


def test_nobody_matching_says_who_is_on_the_board():
    who, problem = tp.resolve_person("Gabriel", MEMBERS)
    assert who is None
    assert "Gabriel" in problem
    assert "ralphbenitez1" in problem


def test_no_members_read_says_to_use_an_id():
    who, problem = tp.resolve_person("ralph", [])
    assert who is None
    assert "id" in problem.lower()


def test_a_boolean_is_not_a_person():
    who, problem = tp.resolve_person(True, MEMBERS)
    assert who is None and problem


# --- the tools exist, and say what they do ----------------------------------

def _tools():
    return {t.name: t for t in mytools.TRELLO_TOOLS}


def test_the_six_missing_tools_are_now_on_the_per_user_server():
    have = set(_tools())
    assert {"list_board_members", "assign_member_to_card",
            "remove_member_from_card", "archive_card", "complete_card",
            "list_my_cards"} <= have


def test_the_seven_that_already_worked_are_untouched():
    have = set(_tools())
    assert {"list_my_boards", "list_board_lists", "list_cards", "create_card",
            "update_card", "comment_on_card", "whoami"} <= have


def test_assign_says_it_takes_a_name():
    """The #168 and #177 lesson: if the model cannot tell that a name is
    accepted, it will not send one."""
    said = _tools()["assign_member_to_card"].summary.lower()
    assert "name" in said
    assert "username" in said or "id" in said


def test_assign_names_the_tool_that_lists_people():
    said = _tools()["assign_member_to_card"].args["member"][1]
    assert "list_board_members" in said


def test_archive_card_does_not_claim_to_delete():
    """Trello archives; it does not delete. Saying "delete" would make the
    model reach for this when somebody wants a card gone for good."""
    said = _tools()["archive_card"].summary.lower()
    assert "archive" in said
    assert "delete" not in said


def test_complete_card_is_its_own_tool_not_a_flag_on_update():
    """#177's lesson: the model uses the tool the search returns, so a
    separate verb beats an extra argument on an existing tool."""
    assert "complete_card" in _tools()
    assert "dueComplete" not in (_tools()["update_card"].args or {})


# --- through the real call --------------------------------------------------

class _Resp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = json.dumps(self._payload)

    def json(self):
        return self._payload


@pytest.fixture
def trello(monkeypatch):
    calls = []
    answers = {}

    async def secrets(email, provider):
        return ({"api_key": "k" * 32, "token": "t" * 64}
                if provider == "trello" else {})

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def request(self, method, url, headers=None, params=None,
                          json=None):
            calls.append({"method": method, "url": url, "json": json,
                          "params": params or {}})
            for (m, tail), resp in answers.items():
                if m == method and url.endswith(tail):
                    return resp
            return _Resp(200, {"id": "new1", "name": "x"})

    monkeypatch.setattr(mytools, "_secrets_for", secrets)
    monkeypatch.setattr(mytools.httpx, "AsyncClient", _Client)
    answers[("GET", "/cards/" + CARD)] = _Resp(200, CARD_ROW)
    answers[("GET", "/boards/%s/members" % BOARD)] = _Resp(200, BOARD_MEMBERS)
    return calls, answers


def _run(name, args):
    tool = {t.name: t for t in mytools.TRELLO_TOOLS}[name]
    return asyncio.run(mytools._call("trello", tool, "r@example.com", args))


def test_assigning_by_name_sends_the_id(trello):
    calls, _ = trello
    out = _run("assign_member_to_card", {"card_id": CARD, "member": "ralph"})
    assert out["ok"] is True
    sent = [c for c in calls if c["method"] == "POST"][-1]
    assert sent["url"].endswith("/cards/%s/idMembers" % CARD)
    assert sent["params"]["value"] == RALPH


def test_assigning_by_name_reads_the_card_then_its_board(trello):
    """A card id is not a board id, so the board has to be found first."""
    calls, _ = trello
    _run("assign_member_to_card", {"card_id": CARD, "member": "ralph"})
    reads = [c["url"] for c in calls if c["method"] == "GET"]
    assert any(u.endswith("/cards/" + CARD) for u in reads)
    assert any(u.endswith("/boards/%s/members" % BOARD) for u in reads)


def test_assigning_by_id_reads_nothing(trello):
    """No lookup needed, so no extra request. The ClickUp equivalent is
    test_ids_need_no_lookup."""
    calls, _ = trello
    _run("assign_member_to_card", {"card_id": CARD, "member": RALPH})
    assert [c["method"] for c in calls] == ["POST"]


def test_nobody_is_assigned_when_the_name_does_not_match(trello):
    calls, _ = trello
    out = _run("assign_member_to_card", {"card_id": CARD, "member": "Gabriel"})
    assert out["ok"] is False and "Gabriel" in out["error"]
    assert not [c for c in calls if c["method"] == "POST"]


def test_nobody_is_assigned_when_two_people_share_the_name(trello):
    calls, _ = trello
    out = _run("assign_member_to_card", {"card_id": CARD, "member": "Lukas"})
    assert out["ok"] is False
    assert not [c for c in calls if c["method"] == "POST"]


def test_unassigning_by_name_puts_the_id_in_the_path(trello):
    calls, _ = trello
    out = _run("remove_member_from_card",
               {"card_id": CARD, "member": "clarenzbacalla"})
    assert out["ok"] is True
    sent = [c for c in calls if c["method"] == "DELETE"][-1]
    assert sent["url"].endswith("/cards/%s/idMembers/%s" % (CARD, CLARENZ))


def test_archiving_a_card_sends_closed_true(trello):
    calls, _ = trello
    out = _run("archive_card", {"card_id": CARD})
    assert out["ok"] is True
    sent = [c for c in calls if c["method"] == "PUT"][-1]
    assert sent["url"].endswith("/cards/" + CARD)
    assert str(sent["params"]["closed"]).lower() == "true"


def test_completing_a_card_sends_duecomplete_and_no_due_date(trello):
    """Every card in our Done list is dueComplete with no due date, which
    is the shape this has to produce."""
    calls, _ = trello
    out = _run("complete_card", {"card_id": CARD})
    assert out["ok"] is True
    sent = [c for c in calls if c["method"] == "PUT"][-1]
    assert str(sent["params"]["dueComplete"]).lower() == "true"
    assert "due" not in sent["params"]


def test_listing_board_members_keeps_the_username(trello):
    calls, answers = trello
    answers[("GET", "/boards/%s/members" % BOARD)] = _Resp(200, BOARD_MEMBERS)
    out = _run("list_board_members", {"board_id": BOARD})
    assert out["ok"] is True
    got = out["data"] if isinstance(out.get("data"), list) else out
    assert any("ralphbenitez1" in json.dumps(got) for _ in [0])


def test_listing_my_cards_asks_for_my_own_cards(trello):
    calls, _ = trello
    out = _run("list_my_cards", {})
    assert out["ok"] is True
    sent = [c for c in calls if c["method"] == "GET"][-1]
    assert sent["url"].endswith("/members/me/cards")


# --- the wiring, which is what actually makes it work -----------------------

def test_trello_has_a_prepare_step_registered():
    """Without this the resolver exists and is never called, which is the
    #174 failure mode: correct code reaching nobody."""
    assert "trello" in mytools.PREPARE


def test_a_tool_that_takes_no_member_is_not_slowed_down(trello):
    calls, _ = trello
    _run("create_card", {"list_id": "695e669823c7213cd15275ac",
                         "name": "Buy milk 9"})
    assert [c["method"] for c in calls] == ["POST"]


def test_the_wording_reaches_the_served_api():
    """#174: a description that never leaves the service teaches nobody."""
    from fastapi.testclient import TestClient
    app = mytools._sub_app("trello", mytools.TRELLO_TOOLS)
    with TestClient(app) as c:
        spec = json.dumps(c.get("/openapi.json").json())
    assert "assign_member_to_card" in spec
    assert "list_board_members" in spec
    assert "complete_card" in spec
