# -*- coding: utf-8 -*-
"""A file saved to Dropbox that nobody else can open is half an answer.

WHY THIS EXISTS, and it is a real request rather than a tidy-up. On
2026-11-20, minutes after Dropbox connected, the chat saved
sample-file-from-IO.txt into the root of a real Dropbox and then said,
correctly, that it could not produce a link for it. The honest refusal
was the design working. The missing link was still the thing that was
actually wanted.

THE COST THAT HAS ALREADY BEEN PAID. `sharing.write` and `sharing.read`
go on the consent screen, and unlike the two scopes before them this one
is NOT free: somebody is connected now, and a scope added after a
connection never reaches the token that connection holds. So this change
owes exactly one reconnect, and the tool answers a missing scope by
saying so rather than by failing blankly.

FOUR VENDOR FACTS, three of which break this if got wrong:

**A second request for a link is a 409, not a link.** Dropbox always
refuses `create_shared_link_with_settings` for a file that already has
one. Asking twice is the ORDINARY case here, because a person asks for
the link of a file they shared last week, so a tool that treats 409 as
an error is a tool that works once per file, for ever.

**The existing link is inside the error.** The 409 body carries
`error.shared_link_already_exists.metadata.url`, so the usual case needs
no second call.

**Except when it does not.** That inner object can come back tagged
`other`, with no metadata at all, and then the link has to be fetched
with `list_shared_links` and `direct_only`. Dropbox's own staff say to
handle the 409 regardless, because checking first still races.

**A share link is a PREVIEW link.** It ends `?dl=0`, which opens
Dropbox's viewer. The thing somebody wants when they say "so they can
download it" is the same URL with `dl=1`, so both are returned.

WHY THIS IS AN `act` TOOL. Every other tool here is one request that
`_call` makes. This one is a request whose FAILURE is the answer, and
sometimes a second request after it, which `_call` cannot express: its
`_refusal` turns every 409 into a sentence and returns. Adding a
conflict seam to `_refusal` would put a vendor's quirk in the path of
all seventeen providers, so the two-step lives in the tool.
"""
import json
import os

import pytest

os.environ.setdefault("AIUI_FERNET_KEY",
                      "SFNQQkFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=")

import app_triage
import connections as C
import mytools as M
import oauth_providers as O

EMAIL = "me@example.com"
P = "/sample-file-from-IO.txt"
LINK = "https://www.dropbox.com/scl/fi/abc/sample.txt?rlkey=zzz&dl=0"


def _auth():
    return C.vendor_auth("dropbox", {"token": "sl.tok"})


def _tool(name="share_link"):
    for t in M.PROVIDER_TOOLS["dropbox"]:
        if t.name == name:
            return t
    raise AssertionError("no such dropbox tool: " + name)


class _Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.text = json.dumps(payload)
        self.content = self.text.encode()

    def json(self):
        return self._payload


@pytest.fixture
def dropbox(monkeypatch):
    """Answer each call in turn, and record what was asked."""
    state = {"calls": [], "answers": []}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, **k):
            state["calls"].append({"url": url, "json": k.get("json"),
                                   "headers": k.get("headers")})
            if not state["answers"]:
                raise AssertionError("one call more than the test expected: "
                                     + url)
            return state["answers"].pop(0)

        async def request(self, method, url, **k):
            return await self.post(url, **k)

    monkeypatch.setattr(M.httpx, "AsyncClient", _Client)
    return state


ALREADY = {"error_summary": "shared_link_already_exists/..",
           "error": {".tag": "shared_link_already_exists",
                     "shared_link_already_exists": {
                         ".tag": "metadata",
                         "metadata": {".tag": "file", "name": "sample.txt",
                                      "url": LINK}}}}
ALREADY_BARE = {"error_summary": "shared_link_already_exists/..",
                "error": {".tag": "shared_link_already_exists",
                          "shared_link_already_exists": {".tag": "other"}}}
NO_SCOPE = {"error_summary": "missing_scope/..",
            "error": {".tag": "missing_scope",
                      "required_scope": "sharing.write"}}


# --- the download link ----------------------------------------------------

def test_a_preview_link_is_turned_into_a_download_link():
    """`dl=0` opens Dropbox's viewer. Somebody who says "so they can
    download it" wants `dl=1`."""
    assert M._dropbox_direct_link(LINK).endswith("dl=1")
    assert "rlkey=zzz" in M._dropbox_direct_link(LINK), (
        "the key in the link is what makes it work; it must survive")


def test_a_link_with_no_dl_at_all_gets_one():
    plain = "https://www.dropbox.com/scl/fi/abc/sample.txt?rlkey=zzz"
    assert M._dropbox_direct_link(plain).endswith("dl=1")


def test_a_link_that_is_already_a_download_link_is_left_alone():
    direct = "https://www.dropbox.com/scl/fi/abc/sample.txt?rlkey=z&dl=1"
    assert M._dropbox_direct_link(direct) == direct


def test_nothing_is_invented_from_nothing():
    assert M._dropbox_direct_link("") == ""
    assert M._dropbox_direct_link(None) == ""


# --- reading the link out of a refusal ------------------------------------

def test_the_existing_link_is_read_out_of_the_409():
    assert M._dropbox_link_from_error(ALREADY) == LINK


def test_a_409_with_no_metadata_yields_nothing_rather_than_guessing():
    assert M._dropbox_link_from_error(ALREADY_BARE) is None
    assert M._dropbox_link_from_error({}) is None
    assert M._dropbox_link_from_error({"error": {".tag": "other"}}) is None


# --- the tool, driven ------------------------------------------------------

async def test_a_file_with_no_link_yet_gets_one(dropbox):
    dropbox["answers"] = [_Resp(200, {".tag": "file", "url": LINK,
                                      "name": "sample.txt"})]
    out = await M._dropbox_share(EMAIL, _auth(), {"path": P})
    assert out["ok"] is True
    assert out["url"] == LINK
    assert out["download_url"].endswith("dl=1")
    assert out["existing"] is False
    assert len(dropbox["calls"]) == 1
    assert dropbox["calls"][0]["url"].endswith(
        "/sharing/create_shared_link_with_settings")
    assert dropbox["calls"][0]["json"]["path"] == P


async def test_a_file_that_already_has_a_link_returns_that_one(dropbox):
    """The ordinary case, not the edge case: asking twice for the link of
    a file is what people do."""
    dropbox["answers"] = [_Resp(409, ALREADY)]
    out = await M._dropbox_share(EMAIL, _auth(), {"path": P})
    assert out["ok"] is True
    assert out["url"] == LINK
    assert out["existing"] is True
    assert len(dropbox["calls"]) == 1, (
        "the link was in the refusal; a second call is a wasted round trip")


async def test_a_409_without_the_link_falls_back_to_listing(dropbox):
    dropbox["answers"] = [_Resp(409, ALREADY_BARE),
                          _Resp(200, {"links": [{".tag": "file",
                                                 "url": LINK}]})]
    out = await M._dropbox_share(EMAIL, _auth(), {"path": P})
    assert out["url"] == LINK
    assert out["existing"] is True
    assert len(dropbox["calls"]) == 2
    second = dropbox["calls"][1]
    assert second["url"].endswith("/sharing/list_shared_links")
    assert second["json"]["path"] == P
    assert second["json"]["direct_only"] is True


async def test_a_409_and_an_empty_listing_says_so_rather_than_crashing(
        dropbox):
    dropbox["answers"] = [_Resp(409, ALREADY_BARE), _Resp(200, {"links": []})]
    out = await M._dropbox_share(EMAIL, _auth(), {"path": P})
    assert out.get("error"), out
    assert "link" in out["error"].lower()


async def test_a_missing_scope_says_to_reconnect(dropbox):
    """The one error that is certain to happen: everybody connected
    before this shipped holds a token with no sharing permission in it."""
    dropbox["answers"] = [_Resp(401, NO_SCOPE)]
    out = await M._dropbox_share(EMAIL, _auth(), {"path": P})
    said = (out.get("error") or "").lower()
    assert "reconnect" in said, out
    assert "connections" in said, out


async def test_the_path_is_normalised_like_every_other_dropbox_tool(dropbox):
    dropbox["answers"] = [_Resp(200, {"url": LINK})]
    await M._dropbox_share(EMAIL, _auth(), {"path": "Documents/notes.txt"})
    assert dropbox["calls"][0]["json"]["path"] == "/Documents/notes.txt"


async def test_the_root_is_refused_without_asking_dropbox(dropbox):
    dropbox["answers"] = []
    out = await M._dropbox_share(EMAIL, _auth(), {"path": "/"})
    assert dropbox["calls"] == []
    assert out.get("error"), out


async def test_the_credential_goes_with_it(dropbox):
    dropbox["answers"] = [_Resp(200, {"url": LINK})]
    await M._dropbox_share(EMAIL, _auth(), {"path": P})
    assert dropbox["calls"][0]["headers"]["Authorization"] == "Bearer sl.tok"


async def test_a_vendor_that_says_nothing_useful_still_gets_a_sentence(
        dropbox):
    dropbox["answers"] = [_Resp(500, {"error_summary": "internal_error/.."})]
    out = await M._dropbox_share(EMAIL, _auth(), {"path": P})
    assert out.get("error"), out


# --- the contract ---------------------------------------------------------

def test_sharing_is_a_write():
    assert M._writes(_tool()) is True


def test_the_seven_tools_are_five_reads_and_two_writes():
    names = {t.name for t in M.PROVIDER_TOOLS["dropbox"]}
    assert names == {"list_folder", "search_files", "get_metadata",
                     "read_file", "upload_file", "share_link", "whoami"}
    writes = {t.name for t in M.PROVIDER_TOOLS["dropbox"] if M._writes(t)}
    assert writes == {"upload_file", "share_link"}


def test_the_scope_now_asks_to_share():
    scope = set(O.DROPBOX_SCOPE.split())
    assert {"sharing.write", "sharing.read"} <= scope, scope


def test_every_scope_is_still_earned_by_a_tool():
    """sharing.read is not decoration: it is what list_shared_links needs
    for the fallback when the 409 carries no metadata."""
    scope = set(O.DROPBOX_SCOPE.split())
    assert scope == {"account_info.read", "files.metadata.read",
                     "files.content.read", "files.content.write",
                     "sharing.write", "sharing.read"}


def test_the_catalogue_says_it_can_share_and_stops_saying_it_cannot():
    app = app_triage.APPS["dropbox"]
    assert "link" in app.can.lower(), app.can
    assert "share_link" in app.tools
    assert "share link" not in app.cannot.lower(), (
        "a cannot that denies what a tool now does costs exactly what a "
        "cannot that promises one we lack costs")
    assert "delete" in app.cannot.lower(), "deleting is still out"


def test_the_can_line_still_rests_only_on_real_tools():
    names = {t.name for t in M.PROVIDER_TOOLS["dropbox"]}
    assert set(app_triage.APPS["dropbox"].tools) <= names
