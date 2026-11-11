"""A 403 is not proof the credential is bad (2026-11-11).

Found from a real conversation. Ralph asked the chat to create a ClickUp
space and was told, twice:

    "the ClickUp connection got rejected on the way in, so it was not
     created. Your credentials need to be reconnected: open Connections and
     reconnect ClickUp, then tell me and I will run it again."

    "Your credential is failing on writes like this, even though reading
     your workspace works."

Both sentences are wrong, and the second is self-refuting: `create_task` is
a write and it had succeeded in the same conversation seconds earlier.

What ClickUp actually answered, asked directly with that same credential:

    POST /api/v2/team/<id>/space  ->  403
    {"err":"Your plan is limited to 5 usages of feature, 5 usage.",
     "ECODE":"PAYWALL_004"}

A PAYWALL. The credential was fine: it read /user as him, listed his team
and all three of his spaces. `_refusal` mapped every 403 to "credential was
rejected ... Reconnect it from Connections", so the one useful fact,
ClickUp's own sentence, was thrown away and replaced with advice that would
have cost him a reconnect, a second failure, and his trust in the whole
connector.

401 and 403 are different answers and must not share a sentence:

    401  we do not know who you are        -> reconnect
    403  we know, and you may not do this  -> say WHY, do not blame the
                                              credential

This is the same rule the 400 path already follows: "Without it the model
read 'returned an error (400)' and had nothing to correct". The 403 path
just never got it.
"""
import json

import mytools

CREDS = {"token": "pk_86753099_ABCDEFGHIJKLMNOPQRSTUVWXYZ"}

PAYWALL = {"err": "Your plan is limited to 5 usages of feature, 5 usage.",
           "ECODE": "PAYWALL_004"}


class _Resp:
    def __init__(self, status_code, payload=None, text=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload or {})

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def _said(status, payload=None, text=None, creds=None):
    return mytools._refusal(_Resp(status, payload, text), "ClickUp",
                            creds if creds is not None else CREDS,
                            "clickup", "create_space")


# --- the regression that started it ----------------------------------------

def test_the_real_paywall_answer_names_the_plan_limit():
    said = _said(403, PAYWALL)
    assert "plan is limited" in said, said


def test_the_real_paywall_answer_does_not_say_to_reconnect():
    """The whole bug. He was about to reconnect a credential that works."""
    assert "econnect" not in _said(403, PAYWALL)


def test_the_real_paywall_answer_does_not_claim_the_credential_is_bad():
    said = _said(403, PAYWALL).lower()
    assert "expired" not in said
    assert "rejected" not in said


# --- 401 is a different answer and keeps its advice ------------------------

def test_a_401_still_tells_them_to_reconnect():
    said = _said(401, {"err": "Token invalid"})
    assert "econnect" in said


def test_a_401_still_names_the_app():
    assert "ClickUp" in _said(401, {"err": "Token invalid"})


# --- 403 in general ---------------------------------------------------------

def test_a_403_with_any_reason_repeats_that_reason():
    said = _said(403, {"err": "Team not authorized to use this feature."})
    assert "Team not authorized" in said


def test_a_403_with_no_readable_body_still_says_something_useful():
    """It must not go silent, and it must not go back to blaming the
    credential as the FIRST explanation."""
    said = _said(403, None, text="<html>nope</html>")
    assert said
    assert said.lower().index("permission") < said.lower().index("reconnect") \
        if "reconnect" in said.lower() else True


def test_a_403_with_no_reason_may_still_offer_a_reconnect_last():
    """An expired token does 403 on some APIs, so the advice is not
    removed, only demoted behind the likelier cause."""
    said = _said(403, None, text="").lower()
    assert "permission" in said or "plan" in said


# --- the safety rule that already existed must survive ---------------------

def test_a_403_never_echoes_the_credential():
    """Trello's token rides in the query string and its errors echo the
    request. A 403 must not become the route by which it reaches a chat."""
    leak = {"err": "Invalid token " + CREDS["token"] + " for this board"}
    assert CREDS["token"] not in _said(403, leak)


def test_a_403_that_would_leak_still_says_something():
    leak = {"err": "Invalid token " + CREDS["token"] + " for this board"}
    assert _said(403, leak).strip()


# --- everything else is untouched ------------------------------------------

def test_a_404_is_unchanged():
    said = _said(404, {"err": "Space not found"})
    assert "could not find that" in said
    assert "Space not found" in said


def test_a_400_still_carries_the_vendors_reason():
    said = _said(400, {"err": "Status not found"})
    assert "400" in said and "Status not found" in said


def test_a_200_is_not_a_refusal():
    assert _said(200, {"id": "x"}) == ""
