"""A person's credential is never sent to a host it does not belong to.

Found on 2026-11-18 while adding tools that read n8n's PUBLIC template
library. Those live at api.n8n.io, which is n8n's cloud and has nothing
to do with anybody's self-hosted instance, so they need no credential at
all.

`Tool.base` lets one tool point somewhere other than the provider's base
URL, and `_call` builds the request like this:

    url = (tool.base or auth.base_url) + path
    r = await client.request(tool.method, url, headers=auth.headers, ...)

The headers go out whatever the base is. So a template tool would have
carried a self-hosted X-N8N-API-KEY to n8n's cloud: a credential handed
to a third party by a tool whose whole point is that it needs none.

Nothing sets `base` today, so nothing relied on it, and the field's own
comment says what it is for: moving a provider to a newer API version,
"base to v3", where the host is the same vendor and the credential SHOULD
go. Dropping headers for any base at all would break that.

So the rule is about the HOST. Same host, different path or version: the
credential goes, because it is the same vendor. Different host: it does
not, because by definition that is not the vendor it belongs to.
"""
import os

import pytest

os.environ.setdefault("AIUI_FERNET_KEY",
                      "SFNQQkFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=")

import mytools


SAME = [
    # (vendor base, tool base) pairs that are the same vendor
    ("https://api.clickup.com/api/v2", "https://api.clickup.com/api/v3"),
    ("https://api.vendor.com", "https://api.vendor.com/v2"),
    ("https://n8n.srv1041674.hstgr.cloud",
     "https://n8n.srv1041674.hstgr.cloud/rest"),
    # Case and a trailing slash are not a different host.
    ("https://API.Vendor.com", "https://api.vendor.com/v2"),
]

ELSEWHERE = [
    ("https://n8n.srv1041674.hstgr.cloud", "https://api.n8n.io"),
    ("https://api.clickup.com/api/v2", "https://evil.example"),
    # A subdomain is a different host, and this is the shape of a
    # vendor's "api." split, which is exactly the n8n case.
    ("https://n8n.example.com", "https://api.n8n.example.com"),
    # http vs https to the same name is still worth refusing: a
    # credential must not be sent in the clear.
    ("https://api.vendor.com", "http://api.vendor.com"),
]


@pytest.mark.parametrize("vendor,base", SAME)
def test_the_same_vendor_still_gets_the_credential(vendor, base):
    assert mytools._same_host(vendor, base) is True, (vendor, base)


@pytest.mark.parametrize("vendor,base", ELSEWHERE)
def test_another_host_does_not(vendor, base):
    assert mytools._same_host(vendor, base) is False, (vendor, base)


def test_no_base_at_all_is_the_vendor():
    """The ordinary case: almost every tool."""
    assert mytools._same_host("https://api.vendor.com", "") is True
    assert mytools._same_host("https://api.vendor.com", None) is True


def test_something_unparseable_is_treated_as_elsewhere():
    """The safe direction. A base nobody can read is not proof it is the
    same vendor, and the cost of being wrong is a credential."""
    assert mytools._same_host("https://api.vendor.com", "not a url") is False


def test_the_call_path_uses_it():
    """The rule is worth nothing if _call does not consult it."""
    import inspect
    src = inspect.getsource(mytools._call)
    assert "_same_host" in src, (
        "_call still sends auth.headers whatever the base is")
