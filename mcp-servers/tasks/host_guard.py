"""Whether an address a person typed may be requested from inside here.

Two providers ask somebody to type a URL, because neither has one fixed
vendor host: n8n is their own server and a Jira site is one address per
customer. `connections._http_base` validated the scheme and that there was a
host, and nothing further, which is a request forgery primitive with a
friendly form around it. `_zapier_auth`, three functions below it in the same
file, already pins its URL to Zapier's own host and says exactly that in its
docstring. This module is the rule the other two were missing.

WHY IT IS A MODULE AND NOT A THIRD COPY. `routes_automation.callback_problem`
has resolved and refused private addresses for event hooks since they
shipped, and the address rule there was about to be copy-pasted a second
time. `oauth_state.py` exists four times in this repository and the note
about keeping those in sync is the reason not to do it again with a security
check, so `_private` there now delegates to `private_address` here.

TWO LAYERS, because either on its own is cosmetic:

  - `literal_problem` is SYNC and asks nothing of DNS, so it can live inside
    `connections.vendor_auth`, which runs on every tool call ever made with a
    stored credential. It refuses the addresses that need no lookup: a
    private, loopback, link-local, multicast or reserved literal, and any
    name that is local by shape.
  - `problem` adds the lookup. It is needed because `localtest.me` is a
    real, registered, public name whose A record is 127.0.0.1, so a
    literal-only rule is walked around by typing a domain. It runs at the
    connect and the Test button, where somebody is waiting and can read the
    answer, AND on each tool call for a provider whose address the person
    typed (`connections.types_a_url`), because a name that answered public
    at the connect can be repointed inside the week after it. Not for a
    vendor host written in our own source: that is not user input, and
    asking DNS about api.trello.com on every tool call is cost with nothing
    bought.

WHAT THIS DOES NOT CLAIM. A host that answers public to the lookup and
private to the socket a moment later is not caught, because catching that
means pinning the resolved address through to the connection itself, and
httpx does not hand that over without reaching under it. So the window is a
millisecond rather than a week: the lookup runs again on every call that
uses a typed address, the sync rule refuses every literal, and nothing is
assumed about a name that was checked once and never again.

A BARE NAME WITH NO DOT IS REFUSED, and that is the cheapest and most
valuable line here. `http://mcp-proxy:8000` is literally how this service
reaches its neighbours; a public n8n always has a dot in it.

AND NO REFUSAL EVER REPEATS THE URL. This is shared, and Zapier's URL IS its
credential: anyone holding that Catch Hook can fire that Zap. A guard that
echoes its input is one provider away from writing a credential into a log.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from typing import List
from urllib.parse import urlsplit

#: Names that mean something on this machine or this network. `.lan` and
#: `.home` are what consumer routers hand out, `.internal` is what cloud
#: DNS hands out, and `.local` is mDNS.
LOCAL_SUFFIXES = (".local", ".internal", ".localdomain", ".lan", ".home",
                  ".home.arpa", ".localhost")

#: One sentence, no URL in it, and the same words wherever it is refused, so
#: somebody who reads it twice learns the rule rather than two rules.
PUBLIC_ONLY = ("That address is not reachable from the public internet, so "
               "it cannot be used here. Use the address you would open in a "
               "browser from outside your network.")

NOT_FOUND = ("That host could not be found. Check the address and try "
             "again.")

DEFAULT_EXAMPLE = "https://n8n.yourdomain.com"


def private_address(ip) -> bool:
    """Whether this address is one we must never make a request to.

    Fails closed: an address that cannot be parsed is not evidence that it
    is safe. Same rule, same order, as the event-hook check that has been
    in `routes_automation` since hooks shipped, which now calls this.
    """
    try:
        addr = ipaddress.ip_address(ip)
    except Exception:                                       # noqa: BLE001
        return True
    return bool(addr.is_private or addr.is_loopback or addr.is_link_local
                or addr.is_multicast or addr.is_reserved
                or addr.is_unspecified)


def local_name(host) -> bool:
    """Whether this NAME is local by its shape, with no lookup.

    A name with no dot in it is the one worth refusing hardest: every
    container on this network is addressed exactly that way.
    """
    name = str(host or "").strip().rstrip(".").lower()
    if not name:
        return True
    if "." not in name:
        return True
    return any(name.endswith(s) for s in LOCAL_SUFFIXES)


def _resolve(host: str) -> List[str]:
    return [info[4][0] for info in socket.getaddrinfo(host, None)]


def _host_of(url) -> tuple:
    """(hostname, problem). The hostname is lowercase and bracket-free,
    which is what `urlsplit` gives for an IPv6 literal."""
    try:
        parts = urlsplit(str(url or ""))
    except ValueError:
        return "", "that address could not be read"
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return "", "scheme"
    return parts.hostname, ""


def literal_problem(url, example: str = DEFAULT_EXAMPLE) -> str:
    """Why this URL cannot be used, judged without asking DNS anything.

    "" means nothing is wrong with its shape, NOT that the host is public:
    a name still has to be resolved by `problem` before it is trusted.
    """
    host, trouble = _host_of(url)
    if trouble == "scheme" or not host:
        # The wording and the per-provider example are unchanged from
        # `_http_base`, because whoever is reading it is mid-connect and
        # the example is the useful half.
        return "Enter a full http(s) URL, for example " + str(example)

    try:
        ipaddress.ip_address(host)
    except ValueError:
        return PUBLIC_ONLY if local_name(host) else ""
    # It is a literal, so there is nothing to look up and the answer is
    # final either way.
    return PUBLIC_ONLY if private_address(host) else ""


async def problem(url, example: str = DEFAULT_EXAMPLE) -> str:
    """Why this URL cannot be used, DNS included. "" when it may be used.

    Every address the name resolves to has to be public, not merely the
    first: a name with an A record each side of the fence is the whole
    trick.
    """
    said = literal_problem(url, example=example)
    if said:
        return said

    host, _ = _host_of(url)
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        # A literal that got past `literal_problem` is public, and asking
        # DNS about it would be asking about nothing.
        return ""

    try:
        addrs = await asyncio.get_running_loop().run_in_executor(
            None, _resolve, host)
    except Exception:                                       # noqa: BLE001
        return NOT_FOUND
    if not addrs or any(private_address(a) for a in addrs):
        return PUBLIC_ONLY
    return ""
