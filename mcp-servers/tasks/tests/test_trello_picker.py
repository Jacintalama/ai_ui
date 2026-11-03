"""The dropdown that makes a Trello rule creatable.

A Trello list id is 24 hexadecimal characters. Asking somebody to find one
and paste it is how a feature gets built and then not used, so the form
picks a board and then a list, and this is what fills it.

It is not a tool and is deliberately not in mytools.py: no agent calls it,
it answers a form. One call rather than one per board, because `lists=open`
embeds them and the alternative is a round trip per board every time the
panel opens.

The credential rules are the same as everywhere else that talks to a
vendor, and matter more here than at connect time: Trello's key and token
ride in the QUERY STRING, so an error that echoes the request echoes the
credential, and this answer goes straight into a page.
"""
import pytest
from fastapi import HTTPException

import routes_automations as R

OWNER = "ralph@example.com"
CREDS = {"api_key": "KEY123", "token": "TOK456"}


@pytest.fixture
def trello(monkeypatch):
    """The stored credential and Trello itself, both faked."""
    state = {"creds": dict(CREDS), "status": 200, "payload": [],
             "raise": None, "requests": []}

    async def secrets_for(email, provider):
        return state["creds"] if provider == "trello" else {}

    import routes_connections
    monkeypatch.setattr(routes_connections, "secrets_for", secrets_for)

    class _Resp:
        def __init__(self):
            self.status_code = state["status"]
            self.text = "GET /1/members/me/boards?key=KEY123&token=TOK456"

        def json(self):
            return state["payload"]

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None, params=None):
            state["requests"].append({"url": url, "params": params or {}})
            if state["raise"]:
                raise state["raise"]
            return _Resp()

    monkeypatch.setattr(R.httpx, "AsyncClient", _FakeClient)
    return state


def _board(bid, name, lists):
    return {"id": bid, "name": name,
            "lists": [{"id": lid, "name": lname} for lid, lname in lists]}


# --- not connected is a different answer from no boards -----------------------

async def test_a_person_who_never_connected_is_told_so(trello):
    """Three different nothings, and somebody can act on each of them only
    if they are told apart. This is the one where the answer is "connect
    Trello first"."""
    trello["creds"] = {}
    out = await R._trello_boards(OWNER)
    assert out == {"connected": False, "boards": []}
    assert trello["requests"] == [], "it must not call Trello unsigned"


async def test_connected_with_no_boards_is_connected(trello):
    trello["payload"] = []
    out = await R._trello_boards(OWNER)
    assert out["connected"] is True
    assert out["boards"] == []


# --- what is offered ----------------------------------------------------------

async def test_boards_come_back_with_their_lists(trello):
    trello["payload"] = [_board("b" * 24, "My Trello board",
                                [("l" * 24, "Incoming"), ("m" * 24, "Review")])]
    out = await R._trello_boards(OWNER)
    assert out["boards"][0]["name"] == "My Trello board"
    assert [l["name"] for l in out["boards"][0]["lists"]] == ["Incoming", "Review"]


async def test_a_board_with_no_open_lists_is_not_offered(trello):
    """Offering it means choosing it and then finding the second dropdown
    empty, with nothing saying why."""
    trello["payload"] = [_board("b" * 24, "Archive", []),
                         _board("c" * 24, "Live", [("l" * 24, "Doing")])]
    out = await R._trello_boards(OWNER)
    assert [b["name"] for b in out["boards"]] == ["Live"]


async def test_one_call_not_one_per_board(trello):
    """The whole reason for lists=open. A round trip per board would make
    the form slow to open for exactly the people who use it most."""
    trello["payload"] = [_board("%024d" % i, "B%d" % i, [("l" * 24, "A")])
                         for i in range(10)]
    await R._trello_boards(OWNER)
    assert len(trello["requests"]) == 1
    assert trello["requests"][0]["params"]["lists"] == "open"


async def test_an_enormous_account_is_capped(trello):
    trello["payload"] = [_board("%024d" % i, "B%d" % i, [("l" * 24, "A")])
                         for i in range(R.MAX_BOARDS + 20)]
    out = await R._trello_boards(OWNER)
    assert len(out["boards"]) == R.MAX_BOARDS


async def test_rubbish_in_the_answer_is_stepped_over(trello):
    trello["payload"] = ["not a board", None, 7,
                         _board("b" * 24, "Live", [("l" * 24, "Doing")])]
    out = await R._trello_boards(OWNER)
    assert len(out["boards"]) == 1


async def test_an_answer_that_is_not_a_list_is_not_a_crash(trello):
    trello["payload"] = {"message": "unexpected"}
    out = await R._trello_boards(OWNER)
    assert out == {"connected": True, "boards": []}


# --- the credential never comes back ------------------------------------------

async def test_a_rejection_says_reconnect_without_echoing_the_credential(trello):
    trello["status"] = 401
    with pytest.raises(HTTPException) as caught:
        await R._trello_boards(OWNER)
    assert caught.value.status_code == 400
    assert "Reconnect" in caught.value.detail
    assert "KEY123" not in caught.value.detail
    assert "TOK456" not in caught.value.detail


async def test_no_vendor_error_status_ever_echoes_the_credential(trello):
    """Not just 401. Trello's key and token ride in the query string, so
    any error that quotes the request quotes the credential."""
    for status in (400, 404, 409, 429, 500, 503):
        trello["status"] = status
        with pytest.raises(HTTPException) as caught:
            await R._trello_boards(OWNER)
        assert "KEY123" not in caught.value.detail, status
        assert "TOK456" not in caught.value.detail, status


async def test_an_unreachable_trello_does_not_echo_the_credential(trello):
    trello["raise"] = RuntimeError(
        "failed https://api.trello.com/1/members/me/boards?key=KEY123&token=TOK456")
    with pytest.raises(HTTPException) as caught:
        await R._trello_boards(OWNER)
    assert caught.value.status_code == 502
    assert "KEY123" not in caught.value.detail


async def test_the_answer_never_contains_the_credential(trello):
    trello["payload"] = [_board("b" * 24, "Live", [("l" * 24, "Doing")])]
    out = await R._trello_boards(OWNER)
    assert "KEY123" not in str(out) and "TOK456" not in str(out)
