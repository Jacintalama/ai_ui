"""Airtable, the first connector that needs PKCE.

Ralph chose the order: "we can do airtable first". I had put HubSpot first
because it needs no new machinery at all, so this is his call and worth
recording as such, not mine. It means the PKCE work lands here rather than
later.

Airtable was deliberately absent from PROVIDERS, named in
NEEDS_TOKEN_REFRESH_FIRST, for two reasons. One is now gone: its access token
dies in 3600 seconds and nothing refreshed anything, which PR #186 fixed. The
other is this file.

WHAT PKCE IS FOR, since it is easy to implement without understanding and
therefore easy to implement uselessly. The authorization code comes back
through the BROWSER, which means through the person's address bar, their
history, and any referrer or extension that sees it. A client secret kept on
our server proves the exchange is ours, but PKCE proves the exchange belongs
to THE SAME FLOW that asked: a code stolen in transit cannot be spent without
the verifier, which never left this process. Airtable requires it, and says
plainly that omitting `S256` earns `invalid_grant`.

EVERY FACT HERE WAS READ OFF AIRTABLE'S OWN DOCS on 2026-11-11, because both
provider cards said to confirm the endpoints rather than trust the card:

    authorize   https://airtable.com/oauth2/v1/authorize
    token       POST https://airtable.com/oauth2/v1/token
    PKCE        code_challenge + code_challenge_method=S256, then
                code_verifier on the exchange
    client auth Authorization: Basic, base64URL of client_id:client_secret
    body        application/x-www-form-urlencoded
    scopes      data.records:read, data.records:write, schema.bases:read,
                user.email:read and others, space separated
    response    access_token, refresh_token, token_type, scope, expires_in
                (60 min), refresh_expires_in (60 days)
    refresh     ROTATES. The old access and refresh tokens are both
                invalidated and new ones returned.

THE THREE DECISIONS IN THIS FILE THAT ARE NOT JUST PLUMBING.

1. `authorize_url` computes the challenge from the verifier itself rather
   than accepting a challenge from its caller. If a caller could pass a
   challenge, a caller could pass the verifier by mistake, and that puts the
   secret in the URL where the code already is, which defeats the whole
   point. A caller that has no verifier to give is refused rather than
   quietly handed a URL Airtable will reject.

2. base64URL, not base64. httpx's BasicAuth builds a STANDARD base64 header,
   and the two differ exactly when the encoded `id:secret` contains + or /.
   So this gets its own `token_auth` value and its own header, and Notion's
   working basic path is left untouched rather than refactored underneath it.

3. The default scope asks for what the four Airtable tools actually use and
   nothing more, including `user.email:read` without which `/meta/whoami`
   names no account and the card says "Connected" over a blank. Overridable
   by env, the same shape as GITHUB_SCOPE.
"""
import base64
import hashlib
import os
import re

import pytest

os.environ.setdefault("AIUI_FERNET_KEY",
                      "SFNQQkFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=")

import oauth_providers as O
import oauth_refresh as F

#: RFC 7636 appendix B's own worked example, so the challenge is checked
#: against the spec rather than against my arithmetic.
RFC_VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
RFC_CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"

#: RFC 7636 section 4.1: 43 to 128 characters of ALPHA / DIGIT / "-" / "."
#: / "_" / "~".
UNRESERVED = re.compile(r"^[A-Za-z0-9._~-]{43,128}$")


# --- the PKCE primitives --------------------------------------------------

def test_a_verifier_is_the_length_and_alphabet_the_spec_requires():
    assert UNRESERVED.match(O.new_verifier())


def test_two_verifiers_are_not_the_same():
    """It is a one-time secret. A fixed one would be no secret at all."""
    assert O.new_verifier() != O.new_verifier()


def test_the_challenge_matches_the_specs_own_worked_example():
    assert O.challenge_for(RFC_VERIFIER) == RFC_CHALLENGE


def test_the_challenge_is_url_safe_and_unpadded():
    """Padding and + and / all have to be escaped in a query string, and
    Airtable compares the string it was sent."""
    ch = O.challenge_for(O.new_verifier())
    assert "=" not in ch and "+" not in ch and "/" not in ch


def test_the_challenge_is_a_hash_and_not_the_verifier():
    v = O.new_verifier()
    assert O.challenge_for(v) != v


def test_the_challenge_is_sha256_of_the_ascii_verifier():
    """Stated independently of the implementation, so a change of digest or
    of encoding fails here rather than at Airtable."""
    v = O.new_verifier()
    want = base64.urlsafe_b64encode(
        hashlib.sha256(v.encode("ascii")).digest()).rstrip(b"=").decode()
    assert O.challenge_for(v) == want


# --- the state has to carry the verifier between two requests -------------

@pytest.fixture
def store():
    s = O.StateStore()
    yield s
    s.clear()


def test_a_state_can_carry_a_verifier(store):
    """The authorize URL and the exchange are different requests. Without
    somewhere to put it, the verifier is gone by the time it is needed."""
    s = store.mint("ralph@example.com", verifier="v123")
    got = store.take(s)
    assert got.email == "ralph@example.com"
    assert got.verifier == "v123"


def test_taking_a_state_spends_it(store):
    """Still single use. The verifier has to come out in the same pop,
    because there is no second read."""
    s = store.mint("ralph@example.com", verifier="v123")
    assert store.take(s) is not None
    assert store.take(s) is None


def test_an_expired_state_gives_nothing_back(store):
    s = store.mint("ralph@example.com", verifier="v123", now=1000.0)
    assert store.take(s, now=1000.0 + O.STATE_TTL_SEC + 1) is None


def test_a_state_minted_without_a_verifier_still_works(store):
    """Every provider except Airtable, and Trello's own flow, mint without
    one. They must not break."""
    s = store.mint("ralph@example.com")
    got = store.take(s)
    assert got.email == "ralph@example.com"
    assert got.verifier == ""


def test_the_old_way_of_reading_a_state_still_answers(store):
    """`consume` is what the Trello road and the existing tests use."""
    s = store.mint("ralph@example.com")
    assert store.consume(s) == "ralph@example.com"


# --- the provider entry ---------------------------------------------------

def test_airtable_can_be_connected_by_approving():
    assert O.supports_oauth("airtable") is True
    assert O.one_click("airtable") is True


def test_airtable_is_no_longer_listed_as_blocked():
    """The list exists so a gap reads as a decision. Leaving Airtable on it
    after building it would make the list a lie.

    This also asserted that HubSpot was still on the list, which was true
    for one day. HubSpot was built on 2026-11-12 and the shape of the rule
    is guarded in test_a_token_that_dies_gets_refreshed.py, which is where
    it belongs: it is about the list, not about Airtable.
    """
    assert "airtable" not in O.NEEDS_TOKEN_REFRESH_FIRST


def test_the_endpoints_are_the_ones_airtable_documents():
    p = O.PROVIDERS["airtable"]
    assert p.authorize_endpoint == "https://airtable.com/oauth2/v1/authorize"
    assert p.token_endpoint == "https://airtable.com/oauth2/v1/token"


def test_airtable_is_the_only_provider_that_wants_pkce():
    """Sending a challenge to a vendor that did not ask is not harmless: it
    is an unknown parameter on somebody else's authorize URL."""
    assert O.PROVIDERS["airtable"].pkce is True
    for pid in ("github", "clickup", "notion"):
        assert O.PROVIDERS[pid].pkce is False, pid


def test_the_default_scope_can_name_the_account():
    """`/meta/whoami` returns an email only with user.email:read, and
    without it the card says Connected over a blank."""
    assert "user.email:read" in O.AIRTABLE_SCOPE


def test_the_default_scope_covers_what_the_tools_actually_call():
    """list_my_bases and list_tables read schema; list_records reads data."""
    assert "schema.bases:read" in O.AIRTABLE_SCOPE
    assert "data.records:read" in O.AIRTABLE_SCOPE


def test_the_scope_survives_an_empty_variable(monkeypatch):
    """The trap this almost shipped with.

    Compose declares the variable as `${AIRTABLE_SCOPE:-}`, so on a
    deployment that never sets it the container receives an EMPTY STRING,
    not nothing. `os.environ.get(name, default)` hands back that empty
    string, and the connect would then ask Airtable for no scopes at all,
    which is not a thing Airtable can grant. The symptom would be a button
    that works and a credential that reaches nothing, which is the worst
    shape a connection can have, because it passes every check we make.
    """
    import importlib
    monkeypatch.setenv("AIRTABLE_SCOPE", "")
    reloaded = importlib.reload(O)
    try:
        assert reloaded.AIRTABLE_SCOPE, "an empty variable wiped the scope"
        assert "user.email:read" in reloaded.AIRTABLE_SCOPE
    finally:
        monkeypatch.undo()
        importlib.reload(O)


def test_a_real_override_is_still_honoured(monkeypatch):
    import importlib
    monkeypatch.setenv("AIRTABLE_SCOPE", "data.records:write")
    reloaded = importlib.reload(O)
    try:
        assert reloaded.AIRTABLE_SCOPE == "data.records:write"
    finally:
        monkeypatch.undo()
        importlib.reload(O)


def test_the_scope_variable_reaches_the_container():
    """The bug this whole class of test exists for: a variable that is right
    in .env, right in the code, and declared nowhere in between, so the
    container cannot see it and the only symptom is a feature that silently
    does the wrong thing. It cost a day on 2026-10-30 with TRELLO_API_KEY.
    """
    import re

    from repo_checkout import repo_root_or_skip

    compose = (repo_root_or_skip() / "docker-compose.unified.yml").read_text(
        encoding="utf-8")
    start = compose.index("\n  tasks:\n")
    rest = compose[start + 1:]
    end = re.search(r"\n  [a-z0-9][a-z0-9-]*:\n", rest)
    block = rest[:end.start()] if end else rest
    assert re.search(r"^\s*-\s*AIRTABLE_SCOPE=", block, re.M), (
        "the tasks container cannot see AIRTABLE_SCOPE, so setting it on the "
        "server would do nothing at all")


# --- the authorize URL ----------------------------------------------------

def _url(pid="airtable", **kw):
    kw.setdefault("client_id", "cid")
    kw.setdefault("redirect_uri", "https://example.test/connect/x/callback")
    kw.setdefault("state", "st")
    return O.authorize_url(pid, **kw)


def test_the_authorize_url_carries_the_challenge_and_the_method():
    url = _url(verifier=RFC_VERIFIER)
    assert "code_challenge=" + RFC_CHALLENGE in url
    assert "code_challenge_method=S256" in url


def test_the_verifier_itself_never_reaches_the_url():
    """The whole point of PKCE. The code travels through the browser; the
    verifier must not travel with it."""
    assert RFC_VERIFIER not in _url(verifier=RFC_VERIFIER)


def test_a_pkce_provider_will_not_build_a_url_without_a_verifier():
    """Fail closed. Airtable answers invalid_grant for a flow with no
    challenge, which would read as a broken connect with no cause."""
    with pytest.raises(ValueError):
        _url()


def test_the_other_providers_urls_are_untouched_by_this():
    for pid in ("github", "clickup", "notion"):
        url = _url(pid)
        assert "code_challenge" not in url, pid


def test_a_verifier_handed_to_a_provider_that_does_not_want_one_is_ignored():
    """Rather than appended. `authorize_extra` is per vendor and an
    unexpected parameter is the vendor's business, not ours."""
    assert "code_challenge" not in _url("github", verifier=RFC_VERIFIER)


# --- how the client authenticates at the token endpoint -------------------

#: A credential pair whose STANDARD base64 contains a "+", found by search
#: rather than by hoping. Without a pair like this the base64url distinction
#: cannot be tested at all, because for most inputs the two alphabets agree.
DIVERGENT_ID = "app3kQ"
DIVERGENT_SECRET = "pat!>!"


def test_airtable_gets_a_url_safe_basic_header(monkeypatch):
    monkeypatch.setattr(O, "client_credentials",
                        lambda p: (DIVERGENT_ID, DIVERGENT_SECRET))
    pair = (DIVERGENT_ID + ":" + DIVERGENT_SECRET).encode("utf-8")
    assert O.basic_header("airtable") == {
        "Authorization": "Basic " + base64.urlsafe_b64encode(pair).decode()}


def test_the_url_safe_header_really_differs_from_plain_base64(monkeypatch):
    """Otherwise this whole distinction is superstition and the extra
    `token_auth` value is dead weight.

    The fixture checks ITSELF first: if this pair ever stopped encoding to a
    string containing + or /, the assertions below would pass while proving
    nothing, which is the failure worth guarding against.
    """
    monkeypatch.setattr(O, "client_credentials",
                        lambda p: (DIVERGENT_ID, DIVERGENT_SECRET))
    pair = (DIVERGENT_ID + ":" + DIVERGENT_SECRET).encode("utf-8")
    plain = base64.b64encode(pair).decode()
    assert "+" in plain or "/" in plain, (
        "this fixture no longer exercises the difference between the two "
        "base64 alphabets, so the assertions below prove nothing")

    head = O.basic_header("airtable")["Authorization"]
    assert head != "Basic " + plain
    assert "+" not in head and "/" not in head


def test_the_basic_header_keeps_its_padding(monkeypatch):
    """A Basic header is padded base64. Airtable says base64url, which is a
    different ALPHABET, not a different padding rule, and PKCE's unpadded
    form is a separate thing stated separately in its own RFC."""
    monkeypatch.setattr(O, "client_credentials",
                        lambda p: (DIVERGENT_ID, DIVERGENT_SECRET))
    head = O.basic_header("airtable")["Authorization"]
    sent = head.split(" ", 1)[1]
    assert base64.urlsafe_b64decode(sent).decode() == (
        DIVERGENT_ID + ":" + DIVERGENT_SECRET)


def test_notions_basic_path_is_left_alone(monkeypatch):
    """It works. A refactor underneath a working exchange buys nothing and
    risks the one provider whose token endpoint wants Basic today."""
    monkeypatch.setattr(O, "client_credentials", lambda p: ("cid", "sec"))
    assert O.basic_header("notion") == {}


def test_a_body_auth_provider_gets_no_header(monkeypatch):
    monkeypatch.setattr(O, "client_credentials", lambda p: ("cid", "sec"))
    assert O.basic_header("github") == {}


def test_the_client_secret_goes_in_the_body_only_for_body_providers():
    """Airtable's docs forbid the Basic header when there is no secret and
    make client_id in the body optional when there is one. Sending the
    secret both ways would be sending it somewhere it was not asked for."""
    assert O.client_in_body("github") is True
    assert O.client_in_body("clickup") is True
    assert O.client_in_body("notion") is False
    assert O.client_in_body("airtable") is False


# --- reading the token response, and renewing it later --------------------

def test_the_token_response_keeps_what_a_renewal_will_need():
    values, label = O.read_token_response(
        "airtable", {"access_token": "a", "refresh_token": "r",
                     "expires_in": 3600, "token_type": "Bearer "})
    assert values["token"] == "a"
    assert values["refresh_token"] == "r"
    assert values["expires_at"]
    assert label == "", "the route asks the vendor who this is"


def test_an_airtable_credential_is_renewable():
    assert F.refreshable("airtable", {"token": "a", "refresh_token": "r"})


def test_renewing_airtable_sends_a_form_and_the_url_safe_header(monkeypatch):
    monkeypatch.setattr(O, "client_credentials", lambda p: ("cid", "sec"))
    post = F.refresh_post("airtable", {"token": "a", "refresh_token": "r"})
    assert post["url"] == "https://airtable.com/oauth2/v1/token"
    assert "data" in post, "Airtable documents x-www-form-urlencoded"
    assert post["data"]["grant_type"] == "refresh_token"
    assert post["data"]["refresh_token"] == "r"
    assert post["headers"]["Authorization"].startswith("Basic ")
    assert "client_secret" not in post["data"]


def test_a_rotated_airtable_refresh_token_replaces_the_old_one():
    """Airtable invalidates both tokens on every renewal, so keeping the old
    refresh token would break the NEXT renewal rather than this one."""
    out = F.after_refresh({"token": "a1", "refresh_token": "r1"},
                          {"access_token": "a2", "refresh_token": "r2",
                           "expires_in": 3600}, now=1000.0)
    assert out["token"] == "a2"
    assert out["refresh_token"] == "r2"


# --- the two routes, where the verifier has to survive the round trip -----

import asyncio                                                    # noqa: E402

import routes_connections as R                                    # noqa: E402


class _Who:
    email = "ralph@example.com"
    is_admin = False


@pytest.fixture
def wired(monkeypatch):
    """Both routes, with the vendor and the database replaced.

    The assertions here are about what is SENT and what is carried between
    the two requests, which is the whole of PKCE.
    """
    monkeypatch.setattr(O, "configured", lambda p: True)
    monkeypatch.setattr(O, "client_credentials", lambda p: ("cid", "sec"))
    O.STATES.clear()

    sent = []
    reply = {"payload": {"access_token": "at", "refresh_token": "rt",
                         "expires_in": 3600},
             "status": 200}

    class _Resp:
        @property
        def status_code(self):
            return reply["status"]

        def json(self):
            return reply["payload"]

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

    stored = []

    async def _ask(provider, values):
        return True, "ralph@example.com", None

    async def _store(email, pid, values, label):
        stored.append({"email": email, "provider": pid, "values": values,
                       "label": label})

    async def _has(email, pid):
        return True

    monkeypatch.setattr(R, "_ask_vendor", _ask)
    monkeypatch.setattr(R, "_store_connection", _store)
    monkeypatch.setattr(R, "_has_connection", _has)

    yield sent, stored, reply
    O.STATES.clear()


def _start_url(pid):
    return asyncio.run(R.oauth_start(pid, user=_Who()))["url"]


def _state_from(url):
    from urllib.parse import parse_qs, urlparse
    return parse_qs(urlparse(url).query)["state"][0]


def test_starting_an_airtable_connect_sends_a_challenge(wired):
    url = _start_url("airtable")
    assert "code_challenge=" in url
    assert "code_challenge_method=S256" in url


def test_the_verifier_is_kept_on_the_state_not_in_the_url(wired):
    """The two halves of a PKCE flow are two HTTP requests. If the start
    does not keep the verifier, the exchange has nothing to prove with."""
    url = _start_url("airtable")
    started = O.STATES.take(_state_from(url))
    assert started is not None
    assert started.verifier
    assert started.verifier not in url


def test_the_exchange_proves_the_flow_with_the_verifier(wired):
    """The assertion that makes PKCE real: the code_verifier Airtable is
    sent has to be the one minted at the start of THIS flow."""
    sent, _stored, _reply = wired
    url = _start_url("airtable")
    state = _state_from(url)
    mine = O.STATES._states[state][0].verifier

    asyncio.run(R.oauth_callback("airtable", code="thecode", state=state))

    assert len(sent) == 1
    body = sent[0]["data"]
    assert body["code_verifier"] == mine
    assert body["grant_type"] == "authorization_code"


def test_the_airtable_exchange_sends_the_header_and_not_a_body_secret(wired):
    sent, _stored, _reply = wired
    url = _start_url("airtable")
    asyncio.run(R.oauth_callback("airtable", code="c",
                                 state=_state_from(url)))
    assert sent[0]["headers"]["Authorization"].startswith("Basic ")
    assert "client_secret" not in sent[0]["data"]


def test_a_non_pkce_exchange_is_unchanged(wired):
    """GitHub never asked for a verifier and must not be sent one."""
    sent, _stored, _reply = wired
    url = _start_url("github")
    asyncio.run(R.oauth_callback("github", code="c", state=_state_from(url)))
    assert "code_verifier" not in sent[0]["data"]


def test_a_finished_airtable_connect_stores_what_a_renewal_needs(wired):
    """End to end: the refresh token and the expiry reach the row, or the
    connection dies in an hour with nothing to renew it from."""
    _sent, stored, _reply = wired
    url = _start_url("airtable")
    asyncio.run(R.oauth_callback("airtable", code="c",
                                 state=_state_from(url)))
    assert len(stored) == 1
    values = stored[0]["values"]
    assert values["token"] == "at"
    assert values["refresh_token"] == "rt"
    assert values["expires_at"]


def test_a_pkce_callback_with_no_verifier_refuses_to_exchange(wired):
    """Fail closed. A state minted without a verifier cannot finish a PKCE
    flow, and sending the code anyway would spend it for nothing and earn
    an invalid_grant the person could not act on."""
    sent, _stored, _reply = wired
    state = O.STATES.mint("ralph@example.com")
    asyncio.run(R.oauth_callback("airtable", code="c", state=state))
    assert sent == [], "the code was exchanged without a verifier"
