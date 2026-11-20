# -*- coding: utf-8 -*-
"""A read called a write sends somebody to reconnect for no reason.

WHY THIS EXISTS. `_writes` asks the HTTP method, which is right almost
everywhere and wrong for every vendor that reads over POST. The flag is
not cosmetic: `_refusal` uses it to decide what a 403 MEANS. On a write,
a 403 adds "reconnect it from Connections to allow that". On a read that
sentence is a wrong instruction, because a 403 on a read is a thing this
person cannot see, and reconnecting changes nothing. They reconnect,
fail again, and have no way to find out why. That is exactly what
happened to a ClickUp plan limit on 2026-11-11.

Dropbox and Jira were already declared, one at a time, as each connector
was built. This sweeps the catalogue instead, and found three more:

    notion   search           POST /search
    notion   query_database   POST /databases/{id}/query
    clickup  find_list        a composite, no endpoint at all

THE COMPOSITE IS THE INTERESTING ONE, because it is a rule rather than a
fact. A `run` tool is handed `get(path)`, which does one authenticated
GET, and nothing else. It therefore CANNOT write, whatever `method`
says, and `method` on such a tool is documented as unused. So the guard
below is about the shape of the seam, not about one tool's name.

The last test here is the one that matters in a year: a new POST tool
whose name begins with a reading verb has to declare itself, or it fails
here rather than in somebody's chat.
"""
import os

os.environ.setdefault("AIUI_FERNET_KEY",
                      "SFNQQkFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=")

import mytools as M

#: Names that begin with one of these are reads unless something says
#: otherwise. Deliberately verbs, not substrings: ClickUp has
#: `create_list`, `delete_list` and `update_list`, which contain the word
#: list and are emphatically writes.
READING_VERBS = ("search", "list_", "get_", "read_", "query_", "find_",
                 "whoami", "fetch_")


def _tool(provider_id, name):
    for t in M.PROVIDER_TOOLS[provider_id]:
        if t.name == name:
            return t
    raise AssertionError("no %s tool called %s" % (provider_id, name))


class _Refused:
    """The shape `_refusal` reads off a response."""

    def __init__(self, status, payload, text=""):
        self.status_code = status
        self._payload = payload
        self.text = text or ""

    def json(self):
        return self._payload


# --- the three this sweep found -------------------------------------------

def test_a_notion_search_is_a_read():
    """Notion searches over POST because the query is a body. Nothing is
    created."""
    assert M._writes(_tool("notion", "search")) is False


def test_asking_a_notion_database_for_its_rows_is_a_read():
    assert M._writes(_tool("notion", "query_database")) is False


def test_a_composite_tool_is_a_read_because_it_can_only_get():
    """`run(get, args)` is handed one helper, and that helper does a GET.
    A composite cannot write even if it wanted to."""
    assert M._writes(_tool("clickup", "find_list")) is False


def test_every_composite_tool_anywhere_is_a_read():
    """The rule, not the instance. If a future composite is allowed to
    write, this test is where that decision has to be made out loud."""
    for pid, tools in M.PROVIDER_TOOLS.items():
        for t in tools:
            if t.run:
                assert M._writes(t) is False, (pid, t.name)


# --- what the flag actually changes ---------------------------------------

def test_a_403_on_a_write_offers_the_reconnect():
    said = _Refused(403, {"err": "OAuth scope does not allow this"})
    out = M._refusal(said, "Notion", {}, "notion", "create_page", writes=True)
    assert "reconnect" in out.lower(), out


def test_a_403_on_a_read_does_not_send_anybody_to_reconnect():
    """The whole point of the flag. On a read, a 403 means this person
    cannot see that thing, and reconnecting changes nothing."""
    said = _Refused(403, {"err": "OAuth scope does not allow this"})
    out = M._refusal(said, "Notion", {}, "notion", "search", writes=False)
    assert "reconnect it from connections to allow" not in out.lower(), out


def test_the_vendors_own_reason_survives_either_way():
    """Removing the wrong instruction must not remove the useful part."""
    said = _Refused(403, {"err": "Your plan is limited to 5 usages"})
    for writes in (True, False):
        out = M._refusal(said, "ClickUp", {}, "clickup", "x", writes=writes)
        assert "plan is limited" in out, (writes, out)


# --- teeth, and the guard for the next one --------------------------------

def test_a_real_write_is_still_a_write():
    """Without this, declaring everything a read would pass the sweep."""
    for pid, name in (("clickup", "create_task"),
                      ("dropbox", "upload_file"),
                      ("dropbox", "share_link"),
                      ("notion", "search")):
        expected = name in ("create_task", "upload_file", "share_link")
        assert M._writes(_tool(pid, name)) is expected, (pid, name)


def test_a_post_named_like_a_read_has_to_declare_itself():
    """The guard that outlives this sweep.

    A new tool called search_whatever, added over POST, is counted as a
    write by default, and nothing would say so until somebody hit a 403
    and was told to reconnect. It fails here instead.
    """
    undeclared = sorted(
        (pid, t.name)
        for pid, tools in M.PROVIDER_TOOLS.items()
        for t in tools
        if str(t.method or "").upper() == "POST"
        and t.name.lower().startswith(READING_VERBS)
        and M._writes(t))
    assert undeclared == [], (
        "these read over POST and are counted as writes, so a 403 on them "
        "tells somebody to reconnect for no reason: %s" % (undeclared,))
