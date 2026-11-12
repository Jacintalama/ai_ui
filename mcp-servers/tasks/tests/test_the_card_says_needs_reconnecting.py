"""The third state: Connected, Not connected, and Needs reconnecting.

"Needs reconnecting" is a different thing from both of the other two, and
the card has room to say so. A credential that is STORED and REJECTED is
not "not connected": there is something there, it has a name on it, and
the fix is one button rather than a fresh setup.

Keeping `connected` true for it is deliberate. Other code reads that field
to decide whether somebody has a task tracker at all, and a dead GitHub
token is still a GitHub connection for the purposes of "which skills can
this person use". Flipping it would quietly change those answers too, for
a change that is about what a card SAYS.
"""
import os
import re

import pytest

import connections as C
import routes_connections as R

HERE = os.path.dirname(__file__)
MIGRATIONS = os.path.join(HERE, "..", "migrations")
JS = os.path.join(HERE, "..", "..", "gdrive", "integrations-ui.js")


def _migration():
    for name in sorted(os.listdir(MIGRATIONS)):
        if name.startswith("068"):
            with open(os.path.join(MIGRATIONS, name), encoding="utf-8") as fh:
                return fh.read()
    raise AssertionError("no migration 068")


def _ddl():
    """The migration's statements, with every comment line removed first.

    These tests ask what the SQL does, and the comments above it explain
    at length what it deliberately does NOT do: "NULLABLE WITH NO
    DEFAULT", "there is no column for what the vendor said". Scanning the
    whole file for those words finds the explanation and fails on it.
    """
    lines = [l for l in _migration().splitlines()
             if not l.strip().startswith("--")]
    body = " ".join(" ".join(lines).split())
    return [s.strip().lower() for s in body.split(";") if s.strip()]


def _src(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


# --- the two columns ------------------------------------------------------

def test_the_row_can_hold_what_we_learned_and_when():
    sql = _migration().lower()
    assert "check_ok" in sql
    assert "checked_at" in sql


def test_the_migration_can_run_twice():
    """db.py re-runs every migration on every startup."""
    sql = _migration().lower()
    assert sql.count("add column if not exists") >= 2


def test_there_is_no_column_for_what_a_vendor_said():
    """Vendors echo the request in their errors, and Trello's credential
    rides in its query string. A boolean and a time cannot leak one."""
    for line in _ddl():
        for word in ("error", "message", "detail", "reason", "body", "text"):
            assert word not in line, "068 stores " + word


def test_a_credential_nobody_has_used_is_null_not_false():
    """NULL is "we have not learned anything", which is the honest state
    for every row that exists before this migration runs and every one
    nobody has used since.

    A default of false would accuse every connection on the platform at
    once. A default of true would be a second thing asserting something
    nobody checked, which is the bug this migration exists to fix.
    """
    adds = [line for line in _ddl() if "add column" in line]
    assert len(adds) == 2, adds
    for line in adds:
        assert "default" not in line, line
        assert "not null" not in line, line


# --- what the listing reads -----------------------------------------------

def test_the_listing_asks_for_what_it_now_shows():
    src = _src(os.path.join(HERE, "..", "routes_connections.py"))
    stored = src[src.index("async def _stored("):]
    stored = stored[:stored.index("\n\n\n")]
    assert "check_ok" in stored
    assert "checked_at" in stored


# --- what the card is told ------------------------------------------------

def _described(**row):
    provider = C.PROVIDERS["github"]
    return R._describe(provider, {"github": row} if row else {})


def test_a_rejected_credential_says_it_needs_reconnecting():
    out = _described(account_label="aiuiteams-hub", updated_at="x",
                     check_ok=False, checked_at="y")
    assert out["needs_reconnect"] is True


def test_a_working_credential_does_not():
    out = _described(account_label="aiuiteams-hub", updated_at="x",
                     check_ok=True, checked_at="y")
    assert out["needs_reconnect"] is False


def test_a_credential_nobody_has_used_yet_is_not_accused():
    """Every connection made before this existed, and every one made since
    that nobody has used. Silence is not evidence."""
    out = _described(account_label="aiuiteams-hub", updated_at="x",
                     check_ok=None, checked_at=None)
    assert out["needs_reconnect"] is False


def test_an_app_nobody_connected_is_not_accused_either():
    out = _described()
    assert out["connected"] is False
    assert out["needs_reconnect"] is False


def test_a_rejected_credential_is_still_a_connection():
    """Three states, not two. Something is stored, it has a name on it,
    and other code reads `connected` to decide which skills a person can
    use at all."""
    out = _described(account_label="aiuiteams-hub", updated_at="x",
                     check_ok=False, checked_at="y")
    assert out["connected"] is True
    assert out["account_label"] == "aiuiteams-hub"


def test_the_card_is_told_when_it_was_last_checked():
    out = _described(account_label="x", updated_at="x",
                     check_ok=True, checked_at="2026-11-12T01:00:00")
    assert out["checked_at"] == "2026-11-12T01:00:00"


def test_the_description_carries_only_the_fields_it_is_meant_to():
    """An allowlist rather than a scan for suspicious words.

    A scan is both too weak and too strong: `where` is help text that
    legitimately says "token" ("set up a personal access token"), and a
    credential that happened not to contain the word would sail past. The
    set of keys is the thing that must not grow by accident, because this
    dict is built from a row that also holds `secrets_encrypted`.
    """
    out = _described(account_label="x", updated_at="x", check_ok=False,
                     checked_at="y")
    assert set(out) == {
        "provider", "label", "connected", "needs_reconnect", "checked_at",
        "account_label", "connected_at", "where", "oauth", "fields",
    }, sorted(out)
    assert "secrets_encrypted" not in out


# --- where it is learned --------------------------------------------------

def test_a_tool_call_teaches_the_card():
    """The whole point: no probe of our own. The calls are already being
    made, and _refusal already reads the answer."""
    src = _src(os.path.join(HERE, "..", "mytools.py"))
    assert "connection_health" in src
    # Both places a vendor's answer is read: the single call and the walk
    # a composite tool makes.
    assert src.count("H.note(") >= 2, (
        "only one of the two call paths tells the card anything")


def test_the_single_call_path_notes_before_it_gives_up():
    src = _src(os.path.join(HERE, "..", "mytools.py"))
    body = src[src.index("async def _call("):]
    body = body[:body.index("\n# ---")]
    assert body.index("H.note(") < body.index("problem = _refusal("), (
        "a refusal returns early, so the note has to come first")


def test_pressing_test_records_the_answer():
    """The one place somebody explicitly asks "is this still good". It
    would be strange to ask, be told no, and leave the card saying yes."""
    src = _src(os.path.join(HERE, "..", "routes_connections.py"))
    body = src[src.index("async def _ask_vendor("):]
    body = body[:body.index("\n\n\n")]
    assert "H.note(" in body


def test_reconnecting_clears_the_accusation():
    """The connect proved the new credential against the vendor before
    storing it, so the row is good by construction."""
    src = _src(os.path.join(HERE, "..", "routes_connections.py"))
    body = src[src.index("async def _store_connection("):]
    body = body[:body.index("\n\n\n")]
    assert "check_ok" in body
    assert "H.forget(" in body, (
        "the memo from the dead credential would suppress the write that "
        "says the new one works")


# --- and what it looks like ------------------------------------------------
#
# TWO surfaces draw this, and the badge lied on both: the Connections list
# on the agents page, and the integrations grid in the main chat.

PAGE = os.path.join(HERE, "..", "static", "agents.html")


def test_the_agents_page_has_a_third_state():
    src = _src(PAGE)
    assert "Needs reconnecting" in src
    assert "needs_reconnect" in src


def test_the_agents_page_does_not_draw_it_as_connected():
    """The same green pill would make the whole fix invisible."""
    src = _src(PAGE)
    row = src[src.index("function connRow("):]
    row = row[:row.index("\n    function ")]
    assert "needsReconnect" in row
    at = row.index("needsReconnect")
    assert "warn" in row[at:at + 200], (
        "it is drawn with the same class as a working connection")


def test_the_warning_is_not_drawn_as_an_error():
    """Amber, not red. Nothing is broken that one button does not fix,
    and red beside an app somebody connected on purpose reads as a
    failure they caused."""
    src = _src(PAGE)
    assert ".conn-state.warn" in src
    at = src.index(".conn-state.warn")
    style = src[at:at + 60].lower()
    assert "#f0b429" in style or "amber" in style
    assert "#f00" not in style and "red" not in style


def test_the_button_on_a_dead_credential_still_says_reconnect():
    """It is a replacement, not a first setup: the account name and the
    history are still there."""
    src = _src(PAGE)
    row = src[src.index("function connRow("):]
    row = row[:row.index("\n    function ")]
    assert "Reconnect" in row


def test_the_grid_in_the_main_chat_has_it_too():
    src = _src(JS)
    assert "Needs reconnecting" in src
    grid = src[src.index("var statusEl = document.createElement"):][:1600]
    assert "needs_reconnect" in grid


def test_the_grid_checks_it_before_it_says_connected():
    """Order matters in an if/else chain: `connected` is true for a dead
    credential, so a later branch never runs."""
    src = _src(JS)
    grid = src[src.index("var statusEl = document.createElement"):][:1800]
    assert grid.index("needs_reconnect") < grid.index(">Connected<")


def test_opening_a_rejected_app_says_what_happened():
    """The card says two words. The panel behind it has room to say which
    account was rejected and that reconnecting replaces it."""
    src = _src(JS)
    assert "rejected the credential stored for" in src
