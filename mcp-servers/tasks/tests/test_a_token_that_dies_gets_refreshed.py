"""A connected account that stops working while the card still says Connected.

Nothing in this service refreshes anything, and `oauth_providers` has carried
a comment saying so, with the consequence spelled out: HubSpot's access token
dies in 1800 seconds and Airtable's in 3600, so a one-click connect for either
would work for half an hour and then quietly stop. The card would go on saying
"Connected" because a stored credential is all it checks. The paste form each
would replace hands over a token that never expires, so shipping the button
first would be a DOWNGRADE, which is why both are deliberately absent from
PROVIDERS and named in NEEDS_TOKEN_REFRESH_FIRST.

So this is the prerequisite, not a nicety, and the comment even says where it
starts: "`read_token` returning expires_in".

It is worth having for its own sake too. A token that quietly dies currently
reads as Connected forever. My own GitHub credential is in that state right
now, answering 401 on /user under a card that says Connected.

FIVE DECISIONS, each one tested below.

1. A token that never expires is never refreshed. ClickUp, GitHub and Trello
   all hand over credentials with no expiry, which is why nobody has noticed
   the gap. Absent expiry must mean "leave it alone", not "refresh constantly".

2. Refresh EARLY, not at the wire. `_ensure_fresh_token` in
   routes_supabase_oauth.py, the working precedent in this repo, goes at
   expiry minus 30 seconds and stores the expiry 60 seconds short of what the
   vendor said. Copied rather than re-derived.

3. A vendor that does not rotate its refresh token keeps the old one.
   Supabase's `tok.get("refresh_token") or refresh` is there for exactly that,
   and dropping it would turn the second refresh into a dead end.

4. Everything else in the credential survives. ClickUp stores `scheme:
   Bearer` beside its token because an OAuth token sent raw is a 401, and a
   refresh that rebuilt the credential from the token response alone would
   silently drop it. The next call would then fail with a message about a bad
   credential when the credential was fine.

5. A FAILED refresh hands back the credential it has rather than nothing.
   Returning {} would make every tool say "You have not connected your X
   account yet", which is false and sends somebody to connect an account
   they already connected. Handing the stale token to the vendor gets a 401,
   and `mytools._refusal` already turns that into "Your X credential was
   rejected. It may have expired. Reconnect it from Connections." The right
   words exist; the refresh must not talk over them. It also means a vendor
   having a bad minute costs nothing, because we refresh 30 seconds early and
   the token in hand still works.
"""
import json

import pytest

import connections as C
import crypto_utils
import oauth_refresh as F
import oauth_providers as O
import routes_connections as R

NOW = 1_700_000_000.0
EMAIL = "ralph@example.com"


# --- 1. a token with no expiry is left alone ------------------------------

def test_a_token_that_never_expires_is_never_refreshed():
    """The three live one-click apps are all in this state. A missing expiry
    is not a reason to go asking the vendor for a new token on every call."""
    assert F.expired({"token": "ghp_whatever"}, now=NOW) is False


def test_a_vendor_that_named_no_expiry_stores_none():
    """GitHub and ClickUp answer with an access token and nothing else, so
    `with_expiry` must not invent one. Anything else changes behaviour for
    the three apps that already work."""
    out = F.with_expiry({"token": "t"}, {"access_token": "t"}, now=NOW)
    assert out == {"token": "t"}


def test_an_expiry_is_recorded_when_the_vendor_names_one():
    out = F.with_expiry({"token": "t"},
                        {"access_token": "t", "expires_in": 1800,
                         "refresh_token": "r"}, now=NOW)
    assert out["refresh_token"] == "r"
    assert out["expires_at"]


# --- 2. refresh early, with the margins the precedent uses ----------------

def test_the_stored_expiry_is_short_of_what_the_vendor_said():
    """MARGIN_SEC, as `_ensure_fresh_token` stores `expires_in - 60`. A token
    is then never used in the last minute of its life."""
    assert F.expiry_from({"expires_in": 1800}, now=NOW) == NOW + 1800 - 60


def test_no_expiry_in_the_payload_means_no_expiry_stored():
    assert F.expiry_from({"access_token": "t"}, now=NOW) == 0.0


def test_a_token_is_refreshed_before_it_dies_not_after():
    """SKEW_SEC early. Waiting for the exact second guarantees a race with
    the request already in flight."""
    values = {"token": "t", "refresh_token": "r",
              "expires_at": NOW + F.SKEW_SEC - 1}
    assert F.expired(values, now=NOW) is True


def test_a_token_with_plenty_of_life_left_is_not_touched():
    values = {"token": "t", "refresh_token": "r", "expires_at": NOW + 600}
    assert F.expired(values, now=NOW) is False


def test_an_unreadable_expiry_counts_as_expired():
    """A garbled expiry is not evidence the token is good. Refreshing on it
    costs one request; trusting it strands the credential for good."""
    assert F.expired({"token": "t", "refresh_token": "r",
                      "expires_at": "sometime next week"}, now=NOW) is True


def test_an_expiry_written_by_with_expiry_reads_back():
    """The round trip, because the two halves are written apart and a format
    only one of them understands would fail silently at renewal time."""
    stored = F.with_expiry({"token": "t"},
                           {"access_token": "t", "expires_in": 100,
                            "refresh_token": "r"}, now=NOW)
    assert F.expired(stored, now=NOW) is False
    assert F.expired(stored, now=NOW + 100) is True


# --- which credentials can be refreshed at all ----------------------------

def test_a_credential_with_no_refresh_token_cannot_be_refreshed():
    """Every credential stored before this existed is in this state, and a
    pasted personal token always will be."""
    assert F.refreshable("clickup", {"token": "t",
                                     "expires_at": NOW - 10}) is False


def test_a_provider_with_no_oauth_cannot_be_refreshed():
    """n8n is the user's own server and Zapier's hook is not a grant. Neither
    has a token endpoint to ask."""
    assert F.refreshable("n8n", {"api_key": "k", "refresh_token": "r"}) is False


def test_a_refresh_token_and_an_oauth_provider_can_be_refreshed():
    assert F.refreshable("clickup", {"token": "t", "refresh_token": "r"}) is True


# --- the request itself matches the exchange that got the token -----------

def test_the_refresh_asks_for_a_refresh_grant():
    post = F.refresh_post("clickup", {"token": "t", "refresh_token": "r"})
    body = post.get("json") or post.get("data") or {}
    assert body["grant_type"] == "refresh_token"
    assert body["refresh_token"] == "r"
    assert post["url"] == O.PROVIDERS["clickup"].token_endpoint


def test_the_refresh_is_encoded_the_way_that_vendor_wants_it():
    """Notion documents a JSON body and HTTP Basic; GitHub documents neither
    and gets the form encoding RFC 6749 specifies. Getting this wrong on a
    refresh is the same 400 as getting it wrong on the exchange, so it reads
    the provider rather than guessing."""
    notion = F.refresh_post("notion", {"token": "t", "refresh_token": "r"})
    github = F.refresh_post("github", {"token": "t", "refresh_token": "r"})
    assert "json" in notion and notion.get("auth")
    assert "data" in github


def test_a_refresh_cannot_be_built_without_a_refresh_token():
    with pytest.raises(ValueError):
        F.refresh_post("clickup", {"token": "t"})


# --- 3 and 4. reading the answer ------------------------------------------

def test_a_vendor_that_does_not_rotate_keeps_the_old_refresh_token():
    out = F.after_refresh({"token": "old", "refresh_token": "r",
                           "expires_at": NOW - 1},
                          {"access_token": "new", "expires_in": 1800},
                          now=NOW)
    assert out["token"] == "new"
    assert out["refresh_token"] == "r"


def test_a_vendor_that_rotates_gets_its_new_refresh_token_stored():
    out = F.after_refresh({"token": "old", "refresh_token": "r1"},
                          {"access_token": "new", "refresh_token": "r2",
                           "expires_in": 1800}, now=NOW)
    assert out["refresh_token"] == "r2"


def test_everything_else_in_the_credential_survives_a_refresh():
    """ClickUp's `scheme` is the case that bites: without it the new token is
    sent raw and the vendor answers 401, which reads as a bad credential."""
    out = F.after_refresh({"token": "old", "refresh_token": "r",
                           "scheme": "Bearer"},
                          {"access_token": "new", "expires_in": 1800},
                          now=NOW)
    assert out["scheme"] == "Bearer"


def test_the_new_expiry_replaces_the_old_one():
    out = F.after_refresh({"token": "old", "refresh_token": "r",
                           "expires_at": NOW - 100},
                          {"access_token": "new", "expires_in": 1800},
                          now=NOW)
    assert F.expired(out, now=NOW) is False


def test_an_answer_with_no_token_in_it_is_refused():
    """Vendors answer 200 with an error body. Storing that would replace a
    working credential with an empty one."""
    with pytest.raises(ValueError):
        F.after_refresh({"token": "old", "refresh_token": "r"},
                        {"error": "invalid_grant"}, now=NOW)


# --- a refresh token is a secret, and redact must know it -----------------

def test_a_refresh_token_is_never_echoed_by_redact():
    """`redact` reads the provider's FORM fields to decide what is secret, and
    a refresh token is in none of them. It exists so a log line cannot leak a
    credential, and a refresh token is the longer-lived half of one."""
    red = C.redact("clickup", {"token": "pk_abc", "refresh_token": "r_SECRET",
                               "scheme": "Bearer"})
    assert "r_SECRET" not in json.dumps(red)
    assert red["scheme"] == "Bearer"


# --- 5. the route layer, where it plugs in --------------------------------

class _Conn:
    """Just enough asyncpg to watch what a refresh persists."""

    def __init__(self, store):
        self.store = store
        self.statements = []

    async def fetchrow(self, sql, *args):
        hit = self.store.get(args[1])
        return {"secrets_encrypted": hit} if hit else None

    async def execute(self, sql, *args):
        self.statements.append((sql, args))
        self.store[args[-1] if len(args) > 2 else "clickup"] = args[0]
        return "UPDATE 1"

    async def close(self):
        pass


@pytest.fixture
def stored(monkeypatch):
    """One connected ClickUp account whose token is about to die."""
    values = {"token": "old_access", "refresh_token": "r1",
              "scheme": "Bearer", "expires_at": NOW - 5}
    store = {"clickup": crypto_utils.encrypt(json.dumps(values))}
    conns = []

    async def _fake_connect():
        c = _Conn(store)
        conns.append(c)
        return c

    monkeypatch.setattr(R, "_connect", _fake_connect)
    monkeypatch.setattr(R, "_now", lambda: NOW)
    return store, conns


def _answer(monkeypatch, payload, status=200):
    sent = []

    class _Resp:
        status_code = status
        is_success = 200 <= status < 300

        def json(self):
            return payload

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, **kw):
            sent.append({"url": url, **kw})
            return _Resp()

    monkeypatch.setattr(R.httpx, "AsyncClient", _Client)
    return sent


async def test_reading_a_dying_credential_refreshes_it_first(stored,
                                                             monkeypatch):
    """The whole point. `secrets_for` is the one place a stored credential is
    decrypted, so a refresh behind it reaches every tool call, every
    automation and the Trello poller without any of them knowing."""
    store, _ = stored
    sent = _answer(monkeypatch, {"access_token": "new_access",
                                 "expires_in": 1800})

    out = await R.secrets_for(EMAIL, "clickup")

    assert len(sent) == 1, "the vendor was not asked for a new token"
    assert out["token"] == "new_access"
    assert out["scheme"] == "Bearer"


async def test_the_refreshed_credential_is_written_back(stored, monkeypatch):
    """Otherwise every single call refreshes, which is a request per call and
    a rotation-based vendor invalidating its own token mid-flight."""
    store, _ = stored
    _answer(monkeypatch, {"access_token": "new_access", "expires_in": 1800})

    await R.secrets_for(EMAIL, "clickup")

    saved = json.loads(crypto_utils.decrypt(store["clickup"]))
    assert saved["token"] == "new_access"
    assert saved["refresh_token"] == "r1"


async def test_a_refresh_does_not_look_like_a_fresh_connection(stored,
                                                               monkeypatch):
    """The card shows `updated_at` as "connected_at", and the account label is
    what the person reads to tell which account this is. A renewal is neither
    of those things, so it writes the credential and nothing else."""
    store, conns = stored
    _answer(monkeypatch, {"access_token": "new_access", "expires_in": 1800})

    await R.secrets_for(EMAIL, "clickup")

    writes = [s for c in conns for (s, _) in c.statements]
    assert writes, "nothing was written"
    for sql in writes:
        assert "secrets_encrypted" in sql
        assert "account_label" not in sql
        assert "updated_at" not in sql


async def test_a_credential_that_is_still_good_is_handed_back_untouched(
        stored, monkeypatch):
    store, _ = stored
    good = {"token": "fine", "refresh_token": "r1", "expires_at": NOW + 9999}
    store["clickup"] = crypto_utils.encrypt(json.dumps(good))
    sent = _answer(monkeypatch, {"access_token": "should_not_be_asked_for"})

    out = await R.secrets_for(EMAIL, "clickup")

    assert sent == [], "a live token was renewed for no reason"
    assert out["token"] == "fine"


async def test_a_failed_refresh_hands_back_the_credential_it_has(
        stored, monkeypatch):
    """So the vendor answers 401 and the person is told to reconnect, rather
    than being told they never connected. See decision 5 at the top."""
    store, _ = stored
    _answer(monkeypatch, {"error": "invalid_grant"}, status=400)

    out = await R.secrets_for(EMAIL, "clickup")

    assert out.get("token") == "old_access"


async def test_a_vendor_that_cannot_be_reached_does_not_lose_the_credential(
        stored, monkeypatch):
    store, _ = stored

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            raise RuntimeError("connection reset")

    monkeypatch.setattr(R.httpx, "AsyncClient", _Client)

    out = await R.secrets_for(EMAIL, "clickup")

    assert out.get("token") == "old_access"
    saved = json.loads(crypto_utils.decrypt(store["clickup"]))
    assert saved["token"] == "old_access", "a failed refresh overwrote the row"


async def test_a_credential_with_no_refresh_token_is_read_as_before(
        stored, monkeypatch):
    """Every credential that exists today. This must not start making
    requests to a token endpoint on their behalf."""
    store, _ = stored
    store["clickup"] = crypto_utils.encrypt(json.dumps({"token": "pasted"}))
    sent = _answer(monkeypatch, {"access_token": "nope"})

    out = await R.secrets_for(EMAIL, "clickup")

    assert sent == []
    assert out == {"token": "pasted"}


# --- and the two apps this unblocks ---------------------------------------

def test_the_two_blocked_apps_are_still_named_as_blocked():
    """A guard on the order of work, not on the refresh. These two go into
    PROVIDERS only once this is deployed and proven, and this list is what
    says so. If somebody adds them, this test should be the thing that asks
    whether the refresh is actually live."""
    assert O.NEEDS_TOKEN_REFRESH_FIRST == frozenset({"hubspot", "airtable"})
    for pid in O.NEEDS_TOKEN_REFRESH_FIRST:
        assert pid not in O.PROVIDERS


def test_an_oauth_token_response_carries_its_expiry_through():
    """Where the comment said this starts: `read_token` returning expires_in.
    A vendor that sends one must not have it dropped on the floor between the
    exchange and the store."""
    values, _label = O.read_token_response(
        "clickup", {"access_token": "t", "refresh_token": "r",
                    "expires_in": 1800})
    assert values.get("refresh_token") == "r"
    assert values.get("expires_at")
