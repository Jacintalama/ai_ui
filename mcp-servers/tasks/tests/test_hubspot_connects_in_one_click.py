"""HubSpot, the last app on the blocked list, connects by approving.

It was blocked for one reason and the reason was right: HubSpot's access
token dies in 1800 seconds and nothing in this service refreshed anything,
so a one-click connect would have worked for half an hour and then quietly
stopped, with the card still reading "Connected", replacing a paste form
whose private-app token never expires. A downgrade, not a gap.

`oauth_refresh` closed that on 2026-11-11 and Airtable went in behind it.
This is what is left, and it needs no new machinery: `token_auth="body"`
with `token_body="form"` is GitHub's working configuration, so this is a
provider entry, a client id and a secret.

Every endpoint, parameter name and scope string below was read off
HubSpot's own documentation on 2026-11-12, not guessed. Two of those
readings changed the entry:

  - The v1 token API, which is what every HubSpot example on the internet
    still shows, has a published sunset: 16 February 2027, after which
    calls "will begin returning errors". Building a new connector on it
    would be shipping fourteen months of life.
  - `/account-info/v3/details`, which is what the whoami tool and the
    label already use, needs only the `oauth` scope, and HubSpot adds that
    to every public app by itself. So the probe that proves a fresh token
    works needs nothing asked for on the consent screen.
"""
import oauth_providers as O
import oauth_refresh as F


# A real token response, in HubSpot's documented shape. `hub_id` and
# `scopes` are in the 2026-03 response and were not in v1's.
TOKEN_RESPONSE = {
    "token_type": "bearer",
    "access_token": "CJS--wE...",
    "refresh_token": "eu1-0f1a-...",
    "expires_in": 1800,
    "hub_id": 243512345,
    "scopes": ["oauth", "crm.objects.contacts.read"],
}


# --- the provider entry ---------------------------------------------------

def test_hubspot_can_be_connected_by_approving():
    assert O.supports_oauth("hubspot") is True
    assert O.one_click("hubspot") is True


def test_nothing_is_blocked_for_want_of_a_refresh_any_more():
    """The list exists so a gap reads as a decision rather than an
    oversight. HubSpot was the last name on it, so leaving it there after
    building it would make the list a lie."""
    assert "hubspot" not in O.NEEDS_TOKEN_REFRESH_FIRST
    assert O.NEEDS_TOKEN_REFRESH_FIRST == frozenset()


def test_the_endpoints_are_the_ones_hubspot_documents():
    p = O.PROVIDERS["hubspot"]
    assert p.authorize_endpoint == "https://app.hubspot.com/oauth/authorize"
    assert p.token_endpoint == "https://api.hubapi.com/oauth/v3/token"


def test_the_token_endpoint_is_not_the_one_that_stops_working_in_2027():
    """v1 is what every HubSpot example and every tutorial still shows, and
    HubSpot's own migration guide gives it until 16 February 2027, after
    which calls "will begin returning errors". A connector built on it
    today is a connector with fourteen months of life.
    """
    p = O.PROVIDERS["hubspot"]
    assert "/oauth/v1/" not in p.token_endpoint, (
        "the v1 OAuth API is sunset on 2027-02-16")


def test_the_token_endpoint_is_the_one_a_NEW_app_uses():
    """There are four live HubSpot token endpoints and picking the wrong one
    is a connect that never works. This is the one that applies.

    Legacy public apps CANNOT BE CREATED any more, as of 23 June 2026, so
    the only app anybody can register for this is on the new developer
    platform, and that platform's own quickstart says
    `https://api.hubapi.com/oauth/v3/token`.

    The other three, and why not:
      /oauth/v1/token            sunset 2027-02-16.
      /oauth/2026-03/token       what the LEGACY v1 migration guide points
                                 legacy apps at. Right answer to a
                                 different question.
      api.hubspot.com/oauth/2026-09/token
                                 in the newest reference, on a different
                                 host from every other HubSpot call this
                                 service makes. Where this moves next, not
                                 where it starts.
    """
    p = O.PROVIDERS["hubspot"]
    assert p.token_endpoint == "https://api.hubapi.com/oauth/v3/token"
    # Same host as every other HubSpot call here, which connections.py
    # already uses as the API base.
    assert p.token_endpoint.startswith("https://api.hubapi.com/")


def test_hubspot_does_not_use_pkce():
    """It never asked for one. A `code_challenge` on somebody else's
    authorize URL is an unknown parameter, not a free improvement."""
    assert O.PROVIDERS["hubspot"].pkce is False


# --- the authorize URL ----------------------------------------------------

def _params(url):
    from urllib.parse import parse_qs, urlsplit
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


def test_the_authorize_url_carries_what_hubspot_requires():
    url = O.authorize_url("hubspot", "cid-1", "https://io.example/cb", "st-1")
    assert url.startswith("https://app.hubspot.com/oauth/authorize?")
    q = _params(url)
    assert q["client_id"] == "cid-1"
    assert q["redirect_uri"] == "https://io.example/cb"
    assert q["state"] == "st-1"
    assert q["scope"] == O.HUBSPOT_SCOPE


def test_the_scope_parameter_is_singular():
    """HubSpot's required parameter is `scope`. The token RESPONSE calls the
    same thing `scopes`, and sending the plural on the authorize URL asks
    for nothing and leaves the required parameter absent."""
    q = _params(O.authorize_url("hubspot", "c", "https://io.example/cb", "s"))
    assert "scope" in q
    assert "scopes" not in q


def test_no_pkce_parameters_reach_hubspot():
    url = O.authorize_url("hubspot", "c", "https://io.example/cb", "s")
    assert "code_challenge" not in url
    assert "code_challenge_method" not in url


def test_a_verifier_offered_to_hubspot_is_ignored_rather_than_sent():
    """The route mints one only for PKCE providers, but a caller that passed
    one anyway must not leak it into the URL beside the code."""
    url = O.authorize_url("hubspot", "c", "https://io.example/cb", "s",
                          verifier="never-send-me")
    assert "never-send-me" not in url


def test_the_scope_asks_for_exactly_what_the_five_tools_call():
    """Three reads and one write, because that is every HubSpot tool there
    is. Asking for more than the platform can use is the opposite of the
    boundary work the rest of this service just did."""
    asked = set(O.HUBSPOT_SCOPE.split())
    assert asked == {
        "crm.objects.contacts.read",
        "crm.objects.contacts.write",
        "crm.objects.companies.read",
        "crm.objects.deals.read",
    }


def test_the_scope_does_not_ask_for_oauth_itself():
    """HubSpot adds `oauth` to every public app by itself, which is what
    makes the account-info probe work with no scope of its own. Asking for
    it again is noise on a consent screen somebody is reading."""
    assert "oauth" not in O.HUBSPOT_SCOPE.split()


def test_the_scope_is_space_delimited_as_hubspot_specifies():
    assert "," not in O.HUBSPOT_SCOPE
    assert len(O.HUBSPOT_SCOPE.split()) == 4


# --- how the client authenticates ----------------------------------------

def test_the_client_credentials_go_in_the_body():
    """HubSpot documents client_id and client_secret as body parameters and
    documents no Basic header at all."""
    assert O.client_in_body("hubspot") is True
    assert O.basic_header("hubspot") == {}


def test_the_token_request_is_form_encoded():
    """`content-type: application/x-www-form-urlencoded`, in HubSpot's own
    words, and its migration guide adds that the parameters must be body
    fields rather than query parameters."""
    assert O.PROVIDERS["hubspot"].token_body == "form"


# --- reading the token response ------------------------------------------

def test_the_token_and_its_renewal_both_survive_the_exchange():
    """The refresh token arrives exactly once, in this response. One
    dropped here cannot be recovered afterwards, and a HubSpot token is
    dead in half an hour, so this is the whole connector."""
    values, _label = O.read_token_response("hubspot", TOKEN_RESPONSE)
    assert values["token"] == "CJS--wE..."
    assert values["refresh_token"] == "eu1-0f1a-..."


def test_the_expiry_is_recorded_so_the_token_renews_before_it_dies():
    values, _label = O.read_token_response("hubspot", TOKEN_RESPONSE)
    at = float(values["expires_at"])
    # 1800 seconds, less the margin that makes the stored expiry
    # deliberately early.
    assert 1700 < at - F._clock(None) <= 1800


def test_a_fresh_hubspot_connection_is_renewable():
    values, _label = O.read_token_response("hubspot", TOKEN_RESPONSE)
    assert F.refreshable("hubspot", values) is True


def test_a_response_with_no_token_is_refused():
    """HubSpot can answer 200 with an error body. Storing an empty
    credential produces a card claiming a connection that cannot work."""
    import pytest
    # The message is asserted because ValueError is also what an UNKNOWN
    # provider raises, so a bare `raises` passes before HubSpot exists at
    # all and proves nothing about reading its response.
    for payload in ({"message": "expired authorization"}, {}):
        with pytest.raises(ValueError) as caught:
            O.read_token_response("hubspot", payload)
        assert "access token" in str(caught.value), caught.value


def test_the_portal_is_asked_for_rather_than_read_off_the_exchange():
    """The response carries `hub_id`, which is the portal id the card wants,
    and the label is still left empty on purpose.

    Asking HubSpot who this is proves the token WORKS before any card says
    Connected, through the same function the paste form and the Test button
    use. A label lifted out of the exchange would skip that, and the worst
    shape a connection can have is one that names the right account and
    reaches nothing: it passes every check we make. That is not a
    hypothetical, it is what the first real GitHub connect did.
    """
    _values, label = O.read_token_response("hubspot", TOKEN_RESPONSE)
    assert label == ""


# --- renewing it ----------------------------------------------------------

def test_the_renewal_is_the_grant_hubspot_documents():
    values, _label = O.read_token_response("hubspot", TOKEN_RESPONSE)
    post = F.refresh_post("hubspot", values,
                          redirect_uri="https://io.example/cb")
    assert post["url"] == "https://api.hubapi.com/oauth/v3/token"
    body = post["data"]
    assert body["grant_type"] == "refresh_token"
    assert body["refresh_token"] == "eu1-0f1a-..."
    assert "json" not in post, "HubSpot documents a form body"


def test_the_renewal_sends_the_client_credentials_in_the_body():
    """Same placement as the exchange, and HubSpot's refresh request
    documents both as required body fields."""
    import oauth_providers as OP

    original = OP._env
    OP._env = lambda name, default="": {
        "HUBSPOT_CLIENT_ID": "cid-9",
        "HUBSPOT_CLIENT_SECRET": "sec-9",
    }.get(name, default)
    try:
        values, _label = O.read_token_response("hubspot", TOKEN_RESPONSE)
        body = F.refresh_post(
            "hubspot", values, redirect_uri="https://io.example/cb")["data"]
        assert body["client_id"] == "cid-9"
        assert body["client_secret"] == "sec-9"
    finally:
        OP._env = original


def test_a_renewed_token_keeps_its_place_in_the_stored_credential():
    """HubSpot's refresh response is the same shape as the exchange's, so a
    renewal has to overwrite the token and the expiry and leave the rest of
    the row alone."""
    values, _label = O.read_token_response("hubspot", TOKEN_RESPONSE)
    renewed = F.after_refresh(values, {"access_token": "CJS--second",
                                       "refresh_token": "eu1-second",
                                       "expires_in": 1800})
    assert renewed["token"] == "CJS--second"
    assert renewed["refresh_token"] == "eu1-second"
    assert F.expired(renewed) is False


def test_the_renewal_sends_the_redirect_uri_hubspot_asks_for():
    """HubSpot's refresh request lists `redirect_uri` among its body
    fields, alongside the client id and secret. RFC 6749 does not ask for
    it on a refresh and no other vendor here wants it, which is exactly how
    it gets left out.

    Getting this wrong is the worst-shaped bug this connector can have: the
    connect works, the card says Connected, every tool works, and thirty
    minutes later the renewal 400s and the person is told to reconnect. It
    would look like a flaky vendor rather than a missing parameter.
    """
    values, _label = O.read_token_response("hubspot", TOKEN_RESPONSE)
    body = F.refresh_post("hubspot", values,
                          redirect_uri="https://io.example/cb")["data"]
    assert body["redirect_uri"] == "https://io.example/cb"


def test_nobody_else_is_sent_a_redirect_uri_on_a_renewal():
    """Airtable, Notion, ClickUp and GitHub do not document one, and an
    unknown parameter on a token endpoint is somebody else's 400 to
    explain."""
    for pid in ("airtable", "notion", "clickup", "github"):
        values = {"token": "t", "refresh_token": "r"}
        post = F.refresh_post(pid, values,
                              redirect_uri="https://io.example/cb")
        body = post.get("data") or post.get("json") or {}
        assert "redirect_uri" not in body, pid


def test_a_renewal_with_no_redirect_offered_is_refused_rather_than_sent():
    """Refused, so the wiring is loud. `_renewed` turns a ValueError into
    "your credential was rejected, reconnect it", which is a sentence
    somebody can act on; sending the request without the parameter would
    get a 400 that reads as the vendor's fault.
    """
    import pytest
    values, _label = O.read_token_response("hubspot", TOKEN_RESPONSE)
    with pytest.raises(ValueError):
        F.refresh_post("hubspot", values)


# --- until somebody registers the app ------------------------------------

def test_the_button_is_not_offered_until_a_client_id_and_secret_exist():
    """Half configured counts as off. A Connect button that strands someone
    on HubSpot's error page is worse than the paste form that works."""
    import oauth_providers as OP

    original = OP._env
    try:
        OP._env = lambda name, default="": default
        assert OP.configured("hubspot") is False

        OP._env = lambda name, default="": (
            "cid" if name == "HUBSPOT_CLIENT_ID" else default)
        assert OP.configured("hubspot") is False, "an id with no secret"

        OP._env = lambda name, default="": (
            "sec" if name == "HUBSPOT_CLIENT_SECRET" else default)
        assert OP.configured("hubspot") is False, "a secret with no id"

        OP._env = lambda name, default="": {
            "HUBSPOT_CLIENT_ID": "cid",
            "HUBSPOT_CLIENT_SECRET": "sec",
        }.get(name, default)
        assert OP.configured("hubspot") is True
    finally:
        OP._env = original


def test_the_credentials_are_read_from_the_names_a_deployment_sets():
    cid, csec = O._env_names("hubspot")
    assert (cid, csec) == ("HUBSPOT_CLIENT_ID", "HUBSPOT_CLIENT_SECRET")

# --- the wiring, which is the part a provider flag cannot prove ----------

import json  # noqa: E402

import pytest  # noqa: E402

import crypto_utils  # noqa: E402
import routes_connections as R  # noqa: E402

EMAIL = "someone@example.com"
NOW = 1_800_000_000.0


class _Conn:
    """Just enough of a connection for one read and one write."""

    def __init__(self, store):
        self.store = store
        self.statements = []

    async def fetchrow(self, sql, *args):
        hit = self.store.get(args[1])
        return {"secrets_encrypted": hit} if hit else None

    async def execute(self, sql, *args):
        self.statements.append((sql, args))
        self.store["hubspot"] = args[0]
        return "UPDATE 1"

    async def close(self):
        pass


@pytest.fixture
def dying_hubspot(monkeypatch):
    """One connected HubSpot portal whose 1800 seconds have run out."""
    values = {"token": "old_access", "refresh_token": "r1",
              "expires_at": NOW - 5}
    store = {"hubspot": crypto_utils.encrypt(json.dumps(values))}

    async def _fake_connect():
        return _Conn(store)

    monkeypatch.setattr(R, "_connect", _fake_connect)
    monkeypatch.setattr(R, "_now", lambda: NOW)
    return store


@pytest.fixture
def sent(monkeypatch):
    out = []

    class _Resp:
        status_code = 200
        is_success = True

        def json(self):
            return {"access_token": "new_access", "refresh_token": "r2",
                    "expires_in": 1800, "hub_id": 243512345}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, **kw):
            out.append({"url": url, **kw})
            return _Resp()

    monkeypatch.setattr(R.httpx, "AsyncClient", _Client)
    return out


async def test_the_route_hands_the_renewal_a_redirect_uri(dying_hubspot,
                                                          sent):
    """The flag on the provider says HubSpot wants one. This says somebody
    actually gives it one, which is the half that cannot be read off the
    provider table and the half that would fail in production only."""
    out = await R.secrets_for(EMAIL, "hubspot")

    assert len(sent) == 1, "HubSpot was never asked for a new token"
    body = sent[0]["data"]
    assert body["grant_type"] == "refresh_token"
    assert body["redirect_uri"] == R._redirect_uri("hubspot"), (
        "the renewal must send the same redirect the connect used")
    assert out["token"] == "new_access"


async def test_a_renewed_hubspot_token_is_written_back(dying_hubspot, sent):
    """Thirty minutes is short enough that renewing without storing would
    mean renewing on nearly every call."""
    await R.secrets_for(EMAIL, "hubspot")
    stored = json.loads(crypto_utils.decrypt(dying_hubspot["hubspot"]))
    assert stored["token"] == "new_access"
    assert stored["refresh_token"] == "r2"
    assert float(stored["expires_at"]) > NOW
