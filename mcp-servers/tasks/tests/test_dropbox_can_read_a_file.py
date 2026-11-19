# -*- coding: utf-8 -*-
"""A Dropbox you can list but not read is half a connector.

WHY THIS EXISTS. Dropbox shipped with four tools, all reads of metadata:
list a folder, search by name, one entry's details, whoami. So the chat
could say a file exists and how big it is and NOTHING about what is in
it, which is the one thing somebody asks an assistant about a document.
The catalogue said so plainly in its `cannot` line, and that line was
true, which is why this is a gap rather than a bug.

Written BEFORE anybody connected Dropbox (0 rows in
tasks.user_connections on 2026-11-19), which is the only moment this is
free: `files.content.read` is a scope on the consent screen, and a scope
added later leaves every existing connection unable to use the tool
until its owner reconnects.

THREE VENDOR FACTS, each of which silently breaks this if got wrong:

**Content is on a DIFFERENT HOSTNAME.** The RPC endpoints are on
api.dropboxapi.com and file content is on content.dropboxapi.com. Both
are Dropbox and both take the same bearer token, but `_same_host`
compares hostnames, so a download written the obvious way goes out with
NO Authorization header and answers 401 with nothing in it pointing
here. That guard is right and must not be loosened: it is what stops an
n8n tool carrying a self-hosted key to n8n's cloud. So the second host
is named, per provider, and anything not named is still a stranger.

**The argument rides in a HEADER.** `Dropbox-API-Arg`, JSON, and the
body must be empty. A header has to be ASCII, so a file with an accent
in its name needs the JSON escaped rather than sent raw.

**The answer is BYTES, not JSON.** The file's metadata comes back in the
`Dropbox-API-Result` header instead.

AND TWO THINGS THAT WOULD HURT US RATHER THAN THE VENDOR:

**A download is unbounded.** This box has 3.8GB of RAM and somebody's
Dropbox holds video. The cap is a `Range` header, so the bytes are never
sent at all, rather than a check after they arrive.

**Most files in a Dropbox are not text.** A PDF decoded with "replace"
is forty thousand replacement characters, which is a turn spent and an
assistant describing junk. It says it is not text instead.

The Range cap and the text test fight each other in one place: cutting
at a byte boundary can slice a multi-byte character in half, and that
failure is NOT evidence of binary. Hence the tail retry.
"""
import json
import os

os.environ.setdefault("AIUI_FERNET_KEY",
                      "SFNQQkFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=")

import app_triage
import mytools
import oauth_providers as O


def _tool(name):
    for t in mytools.DROPBOX_TOOLS:
        if t.name == name:
            return t
    raise AssertionError("no Dropbox tool named %r" % name)


# --- the credential reaches the second host, and nothing else -------------

def test_the_content_host_is_still_dropbox():
    """Without this the token is stripped and the download 401s."""
    assert mytools._is_vendor_host(
        "dropbox", "https://content.dropboxapi.com/2") is True


def test_a_stranger_is_not_the_vendor():
    assert mytools._is_vendor_host("dropbox", "https://evil.example/2") is False


def test_the_n8n_cloud_host_is_still_refused():
    """The case the host guard was written for, 2026-11-18."""
    assert mytools._is_vendor_host("n8n", "https://api.n8n.io/api/v1") is False


def test_a_plain_http_sibling_is_refused():
    """A credential must not be sent in the clear, named host or not."""
    assert mytools._is_vendor_host(
        "dropbox", "http://content.dropboxapi.com/2") is False


def test_the_tool_points_at_the_content_host():
    assert _tool("read_file").base == mytools.DROPBOX_CONTENT


# --- the argument goes in a header ---------------------------------------

def test_the_path_goes_in_the_header():
    head = mytools._dropbox_arg({"path": "/Documents/a.txt"})
    assert json.loads(head["Dropbox-API-Arg"]) == {"path": "/Documents/a.txt"}


def test_the_header_path_is_normalised_like_every_other_tool():
    """A model writes "Documents/a.txt" about half the time."""
    head = mytools._dropbox_arg({"path": "Documents/a.txt"})
    assert json.loads(head["Dropbox-API-Arg"])["path"] == "/Documents/a.txt"


def test_the_header_is_ascii_only():
    """A header carrying raw UTF-8 is rejected before Dropbox reads it."""
    head = mytools._dropbox_arg({"path": "/Café/résumé.txt"})
    arg = head["Dropbox-API-Arg"]
    arg.encode("ascii")
    assert json.loads(arg)["path"] == "/Café/résumé.txt"


def test_the_download_is_capped_before_it_is_sent():
    """Bounded memory on a 3.8GB box, without a second round trip."""
    head = mytools._dropbox_arg({"path": "/big.bin"})
    assert head["Range"] == "bytes=0-%d" % (mytools.MAX_FILE_BYTES - 1)


def test_the_download_sends_no_body():
    """Dropbox refuses a content download that carries one."""
    assert mytools._payload_for(_tool("read_file"), {"path": "/a.txt"}) is None


# --- reading the answer ---------------------------------------------------

def _result(size=None, path="/a.txt"):
    meta = {"path_display": path}
    if size is not None:
        meta["size"] = size
    return {"Dropbox-API-Result": json.dumps(meta)}


def test_a_text_file_comes_back_as_text():
    out = mytools._dropbox_file(b"hello there", _result(11))
    assert out["content"] == "hello there"
    assert out["truncated"] is False
    assert out["path"] == "/a.txt"


def test_a_file_longer_than_the_cap_says_it_was_cut():
    body = ("x" * (mytools.MAX_FILE_CHARS + 500)).encode()
    out = mytools._dropbox_file(body, _result(len(body)))
    assert len(out["content"]) == mytools.MAX_FILE_CHARS
    assert out["truncated"] is True


def test_a_file_bigger_than_what_arrived_says_it_was_cut():
    """The Range cap means the whole file never arrives. Saying nothing
    here would present a slice as the document."""
    out = mytools._dropbox_file(b"the first part", _result(900000))
    assert out["truncated"] is True


def test_a_binary_file_says_so_instead_of_dumping_bytes():
    out = mytools._dropbox_file(b"%PDF-1.7\x00\x01\x02binary", _result(2048))
    assert out["content"] == ""
    assert "not a text file" in out["why"]
    assert "get_metadata" in out["why"]


def test_a_file_cut_mid_character_is_still_text():
    """The trap where the two safeguards meet: a slice is not binary."""
    body = ("café " * 10).encode("utf-8")[:-1]
    out = mytools._dropbox_file(body, _result(900000))
    assert out["content"].startswith("café")
    assert "why" not in out


def test_an_answer_with_no_metadata_header_still_reads():
    out = mytools._dropbox_file(b"plain", {})
    assert out["content"] == "plain"
    assert out["size"] == 5


# --- the contract the router and the catalogue publish -------------------

def test_the_tool_is_a_read():
    assert _tool("read_file").writes is False


def test_the_result_keeps_the_fields_the_reader_returns():
    """A field the reader sets and `keep` drops is a field nobody sees."""
    keep = set(_tool("read_file").keep)
    for name in ("path", "size", "truncated", "content", "why"):
        assert name in keep, name


def test_the_scope_asks_to_read_content():
    """Without this the tool exists and every call is a 401."""
    assert "files.content.read" in O.DROPBOX_SCOPE.split()


def test_the_catalogue_no_longer_says_it_cannot_read_a_file():
    """The lesson from the Drive and account notes, 2026-11-19: a note
    that promises what no tool does, or denies what one now does, is the
    whole contract and it is wrong either way."""
    app = app_triage.APPS["dropbox"]
    assert "read_file" in app.tools
    assert "read the contents of a file" not in app.cannot
    assert "read" in app.can
