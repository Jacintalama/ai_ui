"""A URL somebody types must not become a way into our own network.

n8n has no fixed vendor host and a Jira site is one address per customer, so
both ask the person to type one. `connections._http_base` checked the scheme
and that there was a host, and nothing else, while `_zapier_auth` three
functions below it pins its URL to Zapier's own host and says why: "This
platform is about to make a request to an address a user typed, and any URL
would be a request forgery primitive." One file, two standards, same class of
input.

Nothing was exposed when this was written: 4 stored connections on the box, 0
of them carrying a typed URL. It is a fix, not an incident, and the daily
credential check wants these same probes on a timer with nobody watching.

TWO LAYERS, because either alone is cosmetic:

  - the literal rule is SYNC and runs inside `vendor_auth`, so it guards
    every call ever made with a stored credential, not just the connect;
  - the DNS rule runs where somebody is waiting and can read the answer,
    because `localtest.me` is a real public name that resolves to 127.0.0.1.
"""
import os

import pytest

os.environ.setdefault("AIUI_FERNET_KEY",
                      "SFNQQkFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=")

import connections as C                                     # noqa: E402
import host_guard as G                                      # noqa: E402


# --- the address rule -----------------------------------------------------

def test_the_cloud_metadata_address_is_private():
    """169.254.169.254 is the first address anybody tries, because on most
    clouds it answers with the instance's own configuration."""
    assert G.private_address("169.254.169.254") is True


@pytest.mark.parametrize("ip", [
    "127.0.0.1", "127.1.2.3", "::1",             # ourselves
    "10.0.0.5", "172.16.3.4", "192.168.1.1",     # the private ranges
    "fd00::1",                                   # IPv6 private
    "169.254.1.1",                               # link local
    "0.0.0.0", "224.0.0.1",                      # unspecified, multicast
])
def test_the_addresses_that_must_never_be_requested(ip):
    assert G.private_address(ip) is True


@pytest.mark.parametrize("ip", ["8.8.8.8", "1.1.1.1", "2001:4860:4860::8888"])
def test_a_real_public_address_is_allowed(ip):
    """Teeth: without this the rule could refuse everything and every test
    above would still pass."""
    assert G.private_address(ip) is False


@pytest.mark.parametrize("junk", ["", "nonsense", "999.1.1.1", None])
def test_an_address_we_cannot_read_counts_as_private(junk):
    """Fail closed. An address we cannot parse is not evidence that it is
    safe to request."""
    assert G.private_address(junk) is True


# --- the name rule --------------------------------------------------------

@pytest.mark.parametrize("host", ["mcp-proxy", "tasks", "db", "localhost"])
def test_a_name_with_no_dot_is_how_our_own_containers_are_addressed(host):
    """`http://mcp-proxy:8000` is exactly how this service reaches its
    neighbours, so a bare name is the cheapest attack and the easiest to
    refuse: a public n8n always has a dot in it."""
    assert G.local_name(host) is True


@pytest.mark.parametrize("host", ["LOCALHOST", "box.local", "api.INTERNAL",
                                  "thing.localdomain"])
def test_the_local_suffixes_whatever_the_case(host):
    assert G.local_name(host) is True


@pytest.mark.parametrize("host", ["n8n.example.com", "jira.acme.co.uk",
                                  "n8n.srv1041674.hstgr.cloud"])
def test_a_real_hostname_is_not_a_local_name(host):
    assert G.local_name(host) is False


# --- the sync rule, which runs on every call ------------------------------

def test_a_private_literal_is_refused_without_asking_dns(monkeypatch):
    """The whole point of the sync layer. If it resolved, it could not live
    inside `vendor_auth`, which runs on every single tool call."""
    def no(*_a, **_k):
        raise AssertionError("the sync rule performed a DNS lookup")
    monkeypatch.setattr(G, "_resolve", no)
    assert G.literal_problem("http://127.0.0.1:5678") != ""


@pytest.mark.parametrize("url", [
    "http://169.254.169.254/",
    "http://mcp-proxy:8000",
    "http://127.0.0.1:8210",
    "https://10.0.0.5",
    "http://localhost:5678",
])
def test_the_urls_this_exists_to_refuse(url):
    assert G.literal_problem(url) != ""


@pytest.mark.parametrize("url", [
    "https://n8n.mydomain.com",
    "https://yourteam.atlassian.net",
    "http://n8n.srv1041674.hstgr.cloud:5678",
])
def test_a_legitimate_address_is_not_refused(url):
    """Teeth: a rule that refused everything would pass every test above."""
    assert G.literal_problem(url) == ""


def test_the_scheme_message_still_teaches_the_example_it_was_given():
    """Unchanged behaviour, kept because the message is read by whoever is
    connecting and the example is per provider."""
    said = G.literal_problem("ftp://files.example.com",
                             example="https://yourteam.atlassian.net")
    assert "https://yourteam.atlassian.net" in said


def test_a_refusal_never_repeats_the_url_back():
    """Zapier's URL IS its credential, and this module is shared. A guard
    that echoes what it was given is one provider away from logging a
    credential."""
    secret = "http://127.0.0.1:9999/hooks/catch/123456/abcdefg"
    assert secret not in G.literal_problem(secret)
    assert "abcdefg" not in G.literal_problem(secret)


# --- the DNS rule ---------------------------------------------------------

async def test_a_public_name_that_resolves_inside_is_refused(monkeypatch):
    """`localtest.me` is a real, public, registered name whose A record is
    127.0.0.1. Without this the literal rule is a speed bump."""
    monkeypatch.setattr(G, "_resolve", lambda host: ["127.0.0.1"])
    assert await G.problem("https://localtest.me") != ""


async def test_a_name_with_one_bad_address_among_good_ones_is_refused(
        monkeypatch):
    monkeypatch.setattr(G, "_resolve", lambda host: ["8.8.8.8", "10.0.0.5"])
    assert await G.problem("https://split.example.com") != ""


async def test_a_public_name_is_allowed(monkeypatch):
    monkeypatch.setattr(G, "_resolve", lambda host: ["8.8.8.8"])
    assert await G.problem("https://n8n.example.com") == ""


async def test_a_name_that_does_not_resolve_is_refused(monkeypatch):
    def gone(host):
        raise OSError("nope")
    monkeypatch.setattr(G, "_resolve", gone)
    assert await G.problem("https://nowhere.example.com") != ""


async def test_a_literal_is_refused_before_anything_is_resolved(monkeypatch):
    """A flag rather than a raise: `problem` catches a resolver that fails
    and answers "could not be found", so a raise here would be swallowed
    and the test would pass while doing the lookup it exists to forbid."""
    asked = []

    def watch(host):
        asked.append(host)
        return ["8.8.8.8"]

    monkeypatch.setattr(G, "_resolve", watch)
    assert await G.problem("http://192.168.0.9:5678") != ""
    assert asked == [], "it resolved an address it had already refused"


# --- the connect, where the lookup happens --------------------------------

async def test_a_connect_to_a_name_pointing_inside_makes_no_request_at_all(
        monkeypatch):
    """`_ask_vendor` is the one function both the connect and the Test
    button go through, so the DNS rule belongs there and nowhere else.

    The request must not be attempted: a refusal that still fires the
    request has protected nothing, it has only hidden the answer.
    """
    import routes_connections as R

    tried = []

    class _NoClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def request(self, *a, **k):
            tried.append(a)
            raise AssertionError("it made the request anyway")

    monkeypatch.setattr(R.httpx, "AsyncClient", _NoClient)
    monkeypatch.setattr(G, "_resolve", lambda host: ["127.0.0.1"])

    ok, label, err = await R._ask_vendor(
        C.PROVIDERS["n8n"],
        {"base_url": "https://localtest.me", "api_key": "x"})

    assert ok is False
    assert tried == [], "it resolved inside and asked anyway"
    assert err and "internet" in err.lower()


async def test_a_connect_to_a_public_name_is_not_blocked(monkeypatch):
    """Teeth: a guard that refused every connect would pass the test above
    and break every one of the fourteen connectors."""
    import routes_connections as R

    class _OkResponse:
        status_code = 200

        def json(self):
            return {"data": [{"id": "w1"}]}

    class _OkClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def request(self, *a, **k):
            return _OkResponse()

    monkeypatch.setattr(R.httpx, "AsyncClient", _OkClient)
    monkeypatch.setattr(G, "_resolve", lambda host: ["8.8.8.8"])

    ok, _label, err = await R._ask_vendor(
        C.PROVIDERS["n8n"],
        {"base_url": "https://n8n.example.com", "api_key": "x"})
    assert ok is True, err


# --- what it is for: the providers ----------------------------------------

def test_n8n_cannot_be_pointed_at_our_own_containers():
    with pytest.raises(ValueError) as e:
        C.vendor_auth("n8n", {"base_url": "http://mcp-proxy:8000",
                              "api_key": "x"})
    said = str(e.value).lower()
    assert "public" in said or "internet" in said, said


def test_jira_cannot_be_pointed_at_a_private_address():
    with pytest.raises(ValueError):
        C.vendor_auth("jira", {"site_url": "http://10.0.0.5",
                               "email": "a@b.co", "token": "x"})


def test_a_real_n8n_still_works():
    auth = C.vendor_auth("n8n", {"base_url": "https://n8n.example.com/",
                                 "api_key": "x"})
    assert auth.base_url == "https://n8n.example.com"


def test_a_real_jira_still_works():
    auth = C.vendor_auth("jira", {"site_url": "https://team.atlassian.net",
                                  "email": "a@b.co", "token": "x"})
    assert "team.atlassian.net" in auth.base_url


def test_every_provider_that_takes_a_typed_url_refuses_a_private_one():
    """The one that matters in six months.

    This is not a list of today's two providers: it reads the registry, so
    the next connector whose vendor has no fixed host is guarded the day it
    is added, or this fails and names it.
    """
    takes_url = {}
    for pid, p in C.PROVIDERS.items():
        for f in p.fields:
            if f.name.endswith("_url") or f.name == "url":
                takes_url.setdefault(pid, []).append(f.name)
    assert "n8n" in takes_url and "jira" in takes_url, (
        "the two providers this was written for are not being checked: "
        + repr(sorted(takes_url)))

    unguarded = []
    for pid, names in sorted(takes_url.items()):
        for name in names:
            values = {f.name: "x" for f in C.PROVIDERS[pid].fields}
            values[name] = "http://127.0.0.1:9999"
            try:
                C.vendor_auth(pid, values)
            except ValueError:
                continue
            except Exception:                               # noqa: BLE001
                # Refused for some other reason, which is still a refusal.
                continue
            unguarded.append(pid + "." + name)
    assert unguarded == [], (
        "these let a person name an address inside our network: "
        + ", ".join(unguarded))


# --- the tool-call path, which the connect check does not cover -----------
#
# The connect resolves once. A hostname that answers public then and points
# inside a week later is requested on every tool call after that, and the
# literal rule cannot see it because it is a name, not an address. So the
# lookup runs on the call too, for the providers that take a typed URL and
# only for those: a vendor host written in our own source is not user input
# and asking DNS about it on every call would be pure cost.

import mytools as M                                         # noqa: E402

TOOLS = {"n8n": "list_my_workflows", "trello": "list_my_boards"}

CREDS = {"n8n": {"base_url": "https://n8n.example.com", "api_key": "k"},
         "trello": {"api_key": "k", "token": "t"}}


def _tool(provider_id):
    name = TOOLS[provider_id]
    for t in M.PROVIDER_TOOLS[provider_id]:
        if t.name == name:
            return t
    raise AssertionError("no %s tool called %s any more" % (provider_id, name))


@pytest.fixture
def calling(monkeypatch):
    """Drive `mytools._call` with the vendor and the resolver both faked."""
    state = {"requested": [], "resolved": [], "addrs": ["8.8.8.8"]}

    async def secrets(email, provider):
        return dict(CREDS.get(provider, {}))

    class _Resp:
        status_code = 200

        def json(self):
            return {"data": []}

        text = "{}"

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def request(self, method, url, **k):
            state["requested"].append(url)
            return _Resp()

    def resolve(host):
        state["resolved"].append(host)
        return list(state["addrs"])

    monkeypatch.setattr(M, "_secrets_for", secrets)
    monkeypatch.setattr(M.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(G, "_resolve", resolve)
    return state


async def test_a_tool_call_to_a_host_that_now_points_inside_is_refused(
        calling):
    """The hole the connect check leaves. The address was public when they
    connected and resolves to 127.0.0.1 now."""
    calling["addrs"] = ["127.0.0.1"]
    out = await M._call("n8n", _tool("n8n"), "me@example.com", {})
    assert calling["requested"] == [], "it asked an address inside our network"
    said = out.get("error") or ""
    assert "internet" in said.lower(), said


async def test_a_tool_call_to_a_host_that_is_still_public_goes_through(
        calling):
    """Teeth: without this, refusing every n8n call would pass the test
    above and nobody could use the connector at all."""
    out = await M._call("n8n", _tool("n8n"), "me@example.com", {})
    assert len(calling["requested"]) == 1
    assert "n8n.example.com" in calling["requested"][0]
    assert not out.get("error"), out


async def test_a_vendor_with_a_fixed_host_is_not_looked_up_on_every_call(
        calling):
    """Trello's host is written in our own source, so it is not user input
    and asking DNS about it on every single tool call would be cost with
    nothing bought. This is what keeps the check targeted."""
    out = await M._call("trello", _tool("trello"), "me@example.com", {})
    assert len(calling["requested"]) == 1
    assert calling["resolved"] == [], (
        "it resolved a host nobody typed: " + repr(calling["resolved"]))
    assert not out.get("error"), out


def test_which_providers_take_a_typed_url_has_one_definition():
    """`types_a_url` and the registry must not drift apart: the tool-call
    check reads the first and the property test above reads the second."""
    from_fields = {pid for pid, p in C.PROVIDERS.items()
                   for f in p.fields
                   if f.name.endswith("_url") or f.name == "url"}
    from_helper = {pid for pid in C.PROVIDERS if C.types_a_url(pid)}
    assert from_helper == from_fields
    assert "n8n" in from_helper and "jira" in from_helper
    assert "trello" not in from_helper
