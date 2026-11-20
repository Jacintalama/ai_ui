# -*- coding: utf-8 -*-
"""A Dropbox you can read but not write to is still half a connector.

WHY THIS EXISTS. After read_file shipped on 2026-11-19 Dropbox had five
tools and all five were reads. Google Drive gained saving the same day
(#259), so the platform could save a document to one file store and not
to the other, which is a difference nobody would expect and nobody asked
for.

Still written BEFORE anybody has connected Dropbox (0 rows in
tasks.user_connections, checked again on 2026-11-20), which is the only
moment a new scope is free. `files.content.write` is on the consent
screen, and a scope added after people connect never reaches the tokens
they already hold.

WHAT THIS DELIBERATELY DOES NOT DO, so the limits are testable rather
than remembered:

**It cannot overwrite.** The upload goes out with `mode: add` and
`autorename: true`, so a save onto an existing path becomes
"notes (1).txt" and the file that was there is untouched. That is what
keeps the catalogue's "cannot change or delete anything" literally true
while a write exists, and it is a vendor-side guarantee rather than a
check of ours.

**There is no share link.** It needs `sharing.write`, and Dropbox
answers a second request for a link with 409 `shared_link_already_exists`
carrying the existing link in the error body. `_refusal` turns every 409
into an error sentence, so a share tool without a new seam would fail
the moment somebody asked twice. Holding the scope before the tool
exists would put "share your files" on the consent screen with nothing
behind it, which is the same promise-with-no-tool defect as #256, #259
and #261.

THE ONE NEW SEAM. Every other tool here sends JSON that `_payload_for`
builds. An upload sends the file itself: raw bytes, with the argument in
a header and `Content-Type: application/octet-stream`. So `Tool.send`
returns the body, and a raw body only ever leaves for the vendor's own
host, because unlike a JSON payload of ours it is the PERSON'S data.
"""
import dataclasses
import json
import os

import pytest

os.environ.setdefault("AIUI_FERNET_KEY",
                      "SFNQQkFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=")

import app_triage
import mytools as M
import oauth_providers as O

EMAIL = "me@example.com"


def _tool(name="upload_file"):
    for t in M.PROVIDER_TOOLS["dropbox"]:
        if t.name == name:
            return t
    raise AssertionError("no such dropbox tool: " + name)


def _arg(args):
    """The Dropbox-API-Arg header this tool would send, parsed."""
    return json.loads(_tool().head(args)["Dropbox-API-Arg"])


# --- where the file goes --------------------------------------------------

def test_the_upload_points_at_the_content_host():
    """Same second hostname as the download, and for the same reason."""
    assert _tool().base == M.DROPBOX_CONTENT
    assert M._is_vendor_host("dropbox", _tool().base) is True


def test_the_path_goes_in_the_header_and_is_normalised():
    assert _arg({"path": "Documents/notes.txt",
                 "content": "x"})["path"] == "/Documents/notes.txt"


def test_the_header_is_ascii_only():
    """A header with an accent in it can be refused by a client or a proxy
    before Dropbox ever sees it."""
    raw = _tool().head({"path": "/Café/résumé.txt",
                        "content": "x"})["Dropbox-API-Arg"]
    raw.encode("ascii")
    assert json.loads(raw)["path"] == "/Café/résumé.txt"


def test_the_body_is_declared_as_bytes():
    assert _tool().head({"path": "/a.txt", "content": "x"})[
        "Content-Type"] == "application/octet-stream"


def test_an_upload_asks_for_no_range():
    """Range is the download's cap. On an upload it means nothing and is a
    request header a vendor is entitled to act on."""
    assert "Range" not in _tool().head({"path": "/a.txt", "content": "x"})


# --- what it refuses to do ------------------------------------------------

def test_the_mode_is_add_so_a_save_can_never_overwrite():
    """The whole reason the catalogue can still say it changes nothing."""
    got = _arg({"path": "/a.txt", "content": "x"})
    assert got["mode"] == "add"
    assert got["autorename"] is True


def test_a_path_with_no_file_name_is_refused():
    """The root, and a folder. `_dropbox_path` turns "/" into the root,
    which is the right answer for listing and a saved file called nothing
    for this."""
    for given in ("", "/", "   ", "/Documents/", "Documents/"):
        with pytest.raises(ValueError) as e:
            _tool().head({"path": given, "content": "x"})
        assert "name" in str(e.value).lower(), given


def test_the_text_goes_out_as_utf8_bytes():
    assert _tool().send({"path": "/a.txt",
                         "content": "café"}) == "café".encode("utf-8")


def test_a_file_bigger_than_the_cap_is_refused_before_it_is_sent():
    """Bounded at the request, like the download. This box has 3.8GB."""
    with pytest.raises(ValueError) as e:
        _tool().send({"path": "/a.txt", "content": "x" * (M.MAX_FILE_BYTES + 1)})
    assert "long" in str(e.value).lower() or "big" in str(e.value).lower()


def test_content_that_was_never_given_is_refused_by_name():
    with pytest.raises(ValueError) as e:
        _tool().send({"path": "/a.txt"})
    assert "content" in str(e.value).lower()


def test_an_empty_file_is_allowed():
    """Nothing is wrong with saving an empty file, and "" must not read as
    the argument being absent."""
    assert _tool().send({"path": "/a.txt", "content": ""}) == b""


# --- driven through the caller -------------------------------------------

@pytest.fixture
def calling(monkeypatch):
    """Drive `mytools._call` with Dropbox faked, capturing the request."""
    state = {"sent": []}

    async def secrets(email, provider):
        return {"token": "sl.tok"}

    class _Resp:
        status_code = 200
        headers = {}
        content = b"{}"
        text = "{}"

        def json(self):
            return {"name": "notes.txt", "path_display": "/notes.txt",
                    "size": 5, "server_modified": "2026-11-20T00:00:00Z",
                    "id": "id:1", "rev": "0123"}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def request(self, method, url, **k):
            state["sent"].append(dict(k, method=method, url=url))
            return _Resp()

    monkeypatch.setattr(M, "_secrets_for", secrets)
    monkeypatch.setattr(M.httpx, "AsyncClient", _Client)
    return state


async def test_the_bytes_are_the_body_and_no_json_is_sent(calling):
    out = await M._call("dropbox", _tool(), EMAIL,
                        {"path": "/notes.txt", "content": "hello"})
    assert not out.get("error"), out
    assert len(calling["sent"]) == 1
    sent = calling["sent"][0]
    assert sent["content"] == b"hello"
    assert sent.get("json") is None, "an upload must not carry a JSON body"
    assert sent["url"] == M.DROPBOX_CONTENT + "/files/upload"


async def test_the_credential_and_the_argument_both_arrive(calling):
    await M._call("dropbox", _tool(), EMAIL,
                  {"path": "/notes.txt", "content": "hello"})
    head = calling["sent"][0]["headers"]
    assert head["Authorization"] == "Bearer sl.tok"
    assert json.loads(head["Dropbox-API-Arg"])["path"] == "/notes.txt"


async def test_what_was_saved_is_read_back_to_the_model(calling):
    out = await M._call("dropbox", _tool(), EMAIL,
                        {"path": "/notes.txt", "content": "hello"})
    assert out["item"]["path_display"] == "/notes.txt"
    assert "rev" not in out["item"], "keep is a shortlist, not a passthrough"


async def test_a_file_never_leaves_for_a_host_that_is_not_the_vendor(calling):
    """A JSON payload is ours. A raw body is the PERSON'S file, so it goes
    only where the credential goes. Nothing can reach this today, which is
    what the census test below is for; this is the belt."""
    stranger = dataclasses.replace(_tool(), base="https://evil.example/2")
    out = await M._call("dropbox", stranger, EMAIL,
                        {"path": "/notes.txt", "content": "hello"})
    assert calling["sent"] == [], "it sent somebody's file to a stranger"
    assert out.get("error"), out


async def test_a_refusal_from_the_header_reaches_the_model_as_an_answer(
        calling):
    """A ValueError out of `head` used to escape the whole call, so a chat
    turn got a 500 instead of the sentence telling it what to fix."""
    out = await M._call("dropbox", _tool(), EMAIL,
                        {"path": "/", "content": "hello"})
    assert calling["sent"] == []
    assert "name" in (out.get("error") or "").lower(), out


# --- the contract ---------------------------------------------------------

def test_saving_is_a_write():
    """So a 403 on it says reconnect, which is the right instruction for a
    missing scope, and so approval treats it as a write everywhere."""
    assert M._writes(_tool()) is True


def test_every_tool_that_sends_a_body_points_at_its_own_vendor():
    """The census that keeps the runtime guard above unreachable. A new
    send tool pointed at a stranger fails here, in a unit test, rather
    than in production with somebody's file in flight."""
    for pid, tools in M.PROVIDER_TOOLS.items():
        for t in tools:
            if t.send and t.base:
                assert M._is_vendor_host(pid, t.base) is True, (pid, t.name)


def test_the_six_tools_are_what_dropbox_has_now():
    assert {t.name for t in M.PROVIDER_TOOLS["dropbox"]} == {
        "list_folder", "search_files", "get_metadata", "read_file",
        "upload_file", "whoami"}


def test_the_scope_asks_to_write_content():
    assert "files.content.write" in O.DROPBOX_SCOPE.split()


def test_the_scope_does_not_ask_for_sharing():
    """Permission we do not use is permission we should not hold. The same
    rule is written against Outlook's Files.* scopes in oauth_providers."""
    scope = O.DROPBOX_SCOPE.split()
    assert not [s for s in scope if s.startswith("sharing.")], scope


def test_the_catalogue_says_it_can_save_and_still_cannot_change_or_delete():
    app = app_triage.APPS["dropbox"]
    assert "save" in app.can.lower(), app.can
    assert "upload_file" in app.tools
    cannot = app.cannot.lower()
    assert "delete" in cannot
    assert "share link" in cannot
    assert "upload" not in cannot, (
        "it can upload now, and a cannot that denies a tool we have costs "
        "exactly what a cannot that promises one we lack costs")


def test_every_can_line_still_rests_on_a_real_tool():
    """app_triage's own rule, asserted here too because this change is the
    kind that breaks it."""
    names = {t.name for t in M.PROVIDER_TOOLS["dropbox"]}
    assert set(app_triage.APPS["dropbox"].tools) <= names
