"""The drill that asks a vendor whether we read its documentation right.

Every rule here is pure, so it is tested with no vendor, no network and
no database. What it cannot test is the thing the drill exists for, which
is a real answer from a real account: that is the point of the script.
"""
import os

import pytest

os.environ.setdefault("AIUI_FERNET_KEY",
                      "SFNQQkFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=")

import connector_drill as D
import mytools


def _tool(provider, name):
    for t in mytools.PROVIDER_TOOLS[provider]:
        if t.name == name:
            return t
    raise AssertionError("no such tool: " + provider + "." + name)


# --- which arguments a tool cannot do without -----------------------------

def test_required_reads_the_third_element_of_the_spec():
    assert D.required(_tool("airtable", "list_my_bases")) == []
    assert D.required(_tool("airtable", "list_tables")) == ["base_id"]


def test_an_optional_argument_is_not_required():
    """list_records takes a limit and a view and needs neither."""
    needed = set(D.required(_tool("airtable", "list_records")))
    assert needed == {"base_id", "table"}


# --- a write is told from a read ------------------------------------------

def test_a_post_that_only_reads_is_not_a_write():
    assert D.writes(_tool("jira", "search_issues")) is False
    assert D.writes(_tool("dropbox", "list_folder")) is False


def test_a_real_write_is_a_write():
    assert D.writes(_tool("jira", "create_issue")) is True
    assert D.writes(_tool("airtable", "create_table")) is True


def test_the_flag_wins_over_the_method():
    """Mirrors mytools._writes. If these two ever disagree the drill would
    create something while reporting a read."""
    for pid, tools in mytools.PROVIDER_TOOLS.items():
        for t in tools:
            assert D.writes(t) is mytools._writes(t), (pid, t.name)


# --- filling an id from what an earlier tool answered ---------------------

def test_an_id_is_taken_from_an_earlier_answer():
    seen = {"list_my_bases": [{"id": "appABC", "name": "Leads"}]}
    args, missing = D.fill(_tool("airtable", "list_tables"), seen)
    assert args == {"base_id": "appABC"}
    assert missing == []


def test_a_value_passed_by_hand_wins():
    seen = {"list_my_bases": [{"id": "appABC"}]}
    args, _ = D.fill(_tool("airtable", "list_tables"), seen,
                     {"base_id": "appTYPED"})
    assert args["base_id"] == "appTYPED"


def test_an_id_nothing_answered_is_reported_rather_than_guessed():
    args, missing = D.fill(_tool("airtable", "list_tables"), {})
    assert args == {}
    assert missing == ["base_id"]


def test_an_empty_value_does_not_count_as_found():
    """A vendor that answers {"id": ""} would otherwise have the drill
    call the next tool with an empty id and report a 404 as a failure of
    the endpoint."""
    seen = {"list_my_bases": [{"id": ""}, {"id": "appREAL"}]}
    args, missing = D.fill(_tool("airtable", "list_tables"), seen)
    assert args == {"base_id": "appREAL"}


def test_a_jira_issue_key_comes_from_a_search():
    seen = {"search_issues": [{"id": "1", "key": "IO-42",
                              "fields": {"summary": "x"}}]}
    args, missing = D.fill(_tool("jira", "get_issue"), seen)
    assert args == {"issue_key": "IO-42"}


def test_a_dropbox_path_comes_from_a_listing():
    seen = {"list_folder": [{".tag": "file", "name": "a.pdf",
                             "path_display": "/a.pdf"}]}
    args, missing = D.fill(_tool("dropbox", "get_metadata"), seen)
    assert args == {"path": "/a.pdf"}


def test_free_text_is_never_invented():
    """A comment or a message is content somebody would read. The drill
    says it is missing rather than posting the word "test" into a real
    issue.

    This passed on 2026-11-13 for the wrong reason. There was a deny-list
    of argument names not to guess, and emptying it changed nothing,
    because FROM_RESULT is an ALLOW-LIST: an argument it does not name is
    never filled anyway. The deny-list was deleted and this asserts the
    property that actually holds, over the real catalogue rather than one
    example.
    """
    args, missing = D.fill(_tool("jira", "comment_on_issue"),
                           {"search_issues": [{"key": "IO-1"}]})
    assert "comment" in missing and "comment" not in args


def test_only_an_argument_the_allow_list_names_is_ever_filled():
    """The general form, over every tool there is. A plausible-looking
    answer must not become a value for an argument nobody mapped."""
    rich = {"anything": [{"id": "x1", "key": "K-1", "name": "n",
                          "email": "someone@example.com",
                          "message": "hello", "body": "text",
                          "comment": "words", "to": "a@b.c",
                          "path_display": "/f", "full_name": "o/r"}]}
    for pid, tools in mytools.PROVIDER_TOOLS.items():
        for t in tools:
            args, missing = D.fill(t, rich)
            assert args == {}, (
                "a value was taken from a tool the map never names: "
                + repr((pid, t.name, args)))
            assert set(missing) == set(D.required(t)), (pid, t.name)


def test_a_value_is_only_taken_from_the_tool_that_answers_it():
    """The first live run, as data. `whoami` ran first and answered the
    account's own id, the map said base_id came from any `id`, and
    list_tables was called with a USER id: "Airtable could not find that.
    NOT_FOUND" from two endpoints that were both fine."""
    seen = {"whoami": {"id": "usr4eZGD4NZqiEJHu",
                       "email": "aiui.teams@gmail.com"}}
    args, missing = D.fill(_tool("airtable", "list_tables"), seen)
    assert args == {}, "whoami's own id was used as a base id"
    assert missing == ["base_id"]

    seen["list_my_bases"] = [{"id": "appRfuGrchrhxsrAl",
                              "name": "Untitled Base"}]
    args, missing = D.fill(_tool("airtable", "list_tables"), seen)
    assert args == {"base_id": "appRfuGrchrhxsrAl"}
    assert missing == []


# --- the order it runs them in --------------------------------------------

def test_whoami_goes_first_because_it_proves_the_credential():
    names = [t.name for t in D.order(mytools.PROVIDER_TOOLS["jira"])]
    assert names[0] == "whoami"


def test_reads_come_before_writes():
    tools = D.order(mytools.PROVIDER_TOOLS["airtable"])
    writes_at = [i for i, t in enumerate(tools) if D.writes(t)]
    reads_at = [i for i, t in enumerate(tools) if not D.writes(t)]
    assert min(writes_at) > max(reads_at)


def test_a_tool_that_needs_nothing_runs_before_one_that_needs_an_id():
    tools = [t.name for t in D.order(mytools.PROVIDER_TOOLS["airtable"])]
    assert tools.index("list_my_bases") < tools.index("list_tables")


def test_every_provider_can_be_ordered():
    for pid, tools in mytools.PROVIDER_TOOLS.items():
        assert len(D.order(tools)) == len(tools), pid


# --- what the run proved --------------------------------------------------

def test_one_real_answer_is_what_proves_the_vendor_agrees():
    v = D.verdict([{"tool": "whoami", "ok": True},
                   {"tool": "list_tables", "skipped": "base_id"}])
    assert v == {"tools": 2, "answered": 1, "refused": 0, "skipped": 1,
                 "proved_the_vendor_agrees": True}


def test_a_run_where_nothing_was_answered_proves_nothing():
    """Every tool skipped for want of an id looks tidy and says nothing
    about whether the endpoints are right."""
    v = D.verdict([{"tool": "list_tables", "skipped": "base_id"}])
    assert v["proved_the_vendor_agrees"] is False


def test_a_refusal_is_counted_separately_from_a_skip():
    v = D.verdict([{"tool": "whoami", "error": "401"},
                   {"tool": "x", "skipped": "id"}])
    assert v["refused"] == 1 and v["skipped"] == 1
    assert v["proved_the_vendor_agrees"] is False


# --- the trap this script fell into ---------------------------------------

def test_a_script_never_shadows_a_module():
    """A script's OWN directory goes first on sys.path, so a script called
    connector_drill.py imports itself when it asks for the module of that
    name, whatever the script then inserts on the path. The failure is
    "module X has no attribute Y" at the first call, which reads like a
    missing function rather than the wrong file.

    Found on the box on 2026-11-13, after the script had already been
    copied into a running container. One name collision for the whole
    service is enough.
    """
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    modules = {p.stem for p in root.glob("*.py")}
    clashes = sorted(p.name for p in (root / "scripts").glob("*.py")
                     if p.stem in modules)
    assert clashes == [], (
        "these scripts shadow a module of the same name and will import "
        "themselves: " + ", ".join(clashes))
