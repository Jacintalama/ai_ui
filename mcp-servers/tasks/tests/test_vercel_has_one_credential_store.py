"""Vercel's credential lives where every other credential lives.

Measured on production 2026-11-16. `vercel_tokens` is known to exactly
one file in the codebase, and Vercel is in none of the machinery built
for credentials:

    connections.PROVIDERS      no  -> no card, so nobody can see or
                                      manage it where everything else is
    mytools.PROVIDER_TOOLS     no  -> no my-vercel_* tools
    connection_health          no  -> the daily sweep never asks Vercel
                                      whether the token still works
    app_triage.APPS            YES -> the chat recommends it

So the platform recommends Vercel to people while that credential sits
outside everything. One real token exists, installed 2026-07-31, and it
has never once been checked. Three published apps depend on it. A dead
Vercel token is found when a deploy fails, not by the morning sweep that
catches every other one.

THE MIGRATION IS LAZY ON PURPOSE. A SQL move would need a window in which
the token is in neither place, and there is a live one. Instead the read
path tries the shared store, falls back to the old table, and PROMOTES
what it finds. Nothing is lost if it runs twice, nothing breaks if it
never runs for somebody, and the old table can be dropped once it is
empty. That is also why these tests drive `_stored_token` with a fake
connection rather than a database: the decision is what is being tested,
not Postgres.
"""
import os

import pytest

os.environ.setdefault("AIUI_FERNET_KEY",
                      "SFNQQkFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=")

import connections as C
import crypto_utils
import routes_vercel as V

EMAIL = "someone@example.com"


class FakeConn:
    """Answers the two reads the token path makes, and records writes.

    Keyed by a fragment of the SQL rather than the whole statement, so
    reformatting the query does not silently turn every test green by
    matching nothing.
    """

    def __init__(self, shared=None, legacy=None):
        self.shared = shared
        self.legacy = legacy
        self.executed = []

    async def fetchrow(self, sql, *args):
        if "user_connections" in sql:
            return self.shared
        if "vercel_tokens" in sql:
            return self.legacy
        raise AssertionError("unexpected read: %s" % sql[:90])

    async def fetchval(self, sql, *args):
        row = await self.fetchrow(sql, *args)
        return None if row is None else list(row.values())[0]

    async def execute(self, sql, *args):
        self.executed.append((sql, args))
        return "OK"


def _shared_row(values: dict, label="ralph"):
    return {"secrets_encrypted": crypto_utils.encrypt_values(values)
            if hasattr(crypto_utils, "encrypt_values")
            else crypto_utils.encrypt(__import__("json").dumps(values)),
            "account_label": label}


# --- the card ---------------------------------------------------------------

def test_vercel_is_a_provider():
    assert C.provider("vercel") is not None, (
        "vercel is not in connections.PROVIDERS, so it has no card and "
        "nobody can see or manage it where every other connection lives")


def test_the_card_knows_which_account_is_connected():
    read = C.provider("vercel").read_label
    assert read({"user": {"username": "aiuiteams-8820"}}) == "aiuiteams-8820"
    assert read({"user": {"email": "r@example.com"}}) == "r@example.com"
    assert read({}) == ""


def test_the_probe_asks_vercel_who_this_is():
    """What the daily sweep will call. Without a probe path there is
    nothing for connection_health to ask."""
    assert C.provider("vercel").probe_path == "/v2/user"


def test_it_signs_as_a_bearer_token_at_vercels_api():
    auth = C.vendor_auth("vercel", {"token": "vc_tok"})
    assert auth.base_url.rstrip("/").endswith("vercel.com")
    assert auth.headers["Authorization"] == "Bearer vc_tok"


# --- reading, and the promotion ---------------------------------------------

async def test_the_shared_store_is_read_first():
    conn = FakeConn(shared=_shared_row({"token": "vc_new",
                                        "team_id": "team_1",
                                        "username": "ralph"}))
    got = await V._stored_token(conn, EMAIL)
    assert got["token"] == "vc_new"
    assert got["team_id"] == "team_1"
    assert got["username"] == "ralph"


async def test_a_token_still_in_the_old_table_is_found():
    """The live token was installed 2026-07-31 and must keep working on
    the deploy somebody runs five minutes after this ships."""
    conn = FakeConn(shared=None, legacy={
        "token_enc": crypto_utils.encrypt("vc_old"),
        "team_id": "team_old", "username": "aiuiteams-8820"})
    got = await V._stored_token(conn, EMAIL)
    assert got is not None, "the existing connection was dropped"
    assert got["token"] == "vc_old"
    assert got["username"] == "aiuiteams-8820"


async def test_finding_it_in_the_old_table_promotes_it():
    conn = FakeConn(shared=None, legacy={
        "token_enc": crypto_utils.encrypt("vc_old"),
        "team_id": None, "username": "aiuiteams-8820"})
    await V._stored_token(conn, EMAIL)
    wrote = [sql for sql, _ in conn.executed if "user_connections" in sql]
    assert wrote, (
        "a token found in the old table must be promoted, or the old "
        "table can never be emptied and there are two stores for ever")


async def test_nothing_anywhere_is_not_connected():
    assert await V._stored_token(FakeConn(), EMAIL) is None


async def test_a_credential_that_will_not_decrypt_is_not_connected():
    """A wrong key or a tampered row reads as not connected, never as a
    crash in the middle of somebody's deploy."""
    conn = FakeConn(shared={"secrets_encrypted": "not-encrypted-at-all",
                            "account_label": "x"})
    assert await V._stored_token(conn, EMAIL) is None


# --- the thing this was all for ---------------------------------------------

def test_the_daily_sweep_can_see_vercel():
    import connection_health as H
    providers = getattr(H, "PROVIDERS", None) or list(C.PROVIDERS)
    assert "vercel" in providers, (
        "the sweep asks every provider in the shared store whether the "
        "credential still works; Vercel's has never once been checked")


def test_the_old_table_is_no_longer_written_to():
    """Two writers is how the two stores got here. Reading the old one is
    a migration; writing it is a second store."""
    src = open(os.path.join(os.path.dirname(__file__), "..",
                            "routes_vercel.py"), encoding="utf-8").read()
    writes = [line.strip() for line in src.splitlines()
              if "vercel_tokens" in line
              and ("INSERT" in line.upper() or "UPDATE" in line.upper())]
    assert writes == [], (
        "still writing the old table: " + "; ".join(writes))
