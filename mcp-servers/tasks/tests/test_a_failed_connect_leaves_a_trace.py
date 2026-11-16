# -*- coding: utf-8 -*-
"""A connect attempt that fails must leave a trace that survives a deploy.

Measured 2026-11-16: nine people are on this platform and ONE has ever
connected anything. Asked whether the other eight tried and failed, the
honest answer was that we cannot know. Every failure path in the OAuth
callback is a `logger.warning` and nothing more, and the container log
begins at the last deploy, which on that morning was 41,651 lines starting
Friday 14:10 UTC with zero oauth lines in it. We deploy several times a day,
so each deploy destroys the only evidence there was.

That leaves two situations we cannot tell apart, and they call for opposite
responses: nobody wants connectors, or connectors are broken for everybody
who is not Ralph.

What must NOT happen while fixing it: storing what the vendor said. Migration
068 already states the reason on itself. Vendors echo the request back in
their errors and Trello's credential rides in its query string, so a
free-text column is a credential store with extra steps. Hence a closed set
of stage names we chose and an integer status, and tests that hold the line
rather than trusting the next call site to be careful.
"""
import inspect
import re

import pytest

import connect_attempt as A


# ---------------------------------------------------------------- the stages

def test_a_stage_nobody_declared_is_refused():
    """A call site cannot invent a stage, because an invented one is how
    free text gets in. 'github said: Bad credentials {...}' is a stage name
    as far as a string column is concerned."""
    assert A.clean("connected") == ("connected", None)
    with pytest.raises(ValueError):
        A.clean("github said: Bad credentials")
    with pytest.raises(ValueError):
        A.clean("")
    with pytest.raises(ValueError):
        A.clean(None)


def test_every_stage_is_a_short_name_we_chose():
    """The property that makes the column safe: no stage can carry an
    address, a URL, a token or a sentence."""
    assert A.STAGES, "there must be stages"
    for stage in A.STAGES:
        assert re.fullmatch(r"[a-z][a-z_]{2,23}", stage), stage
        assert "@" not in stage and "/" not in stage and " " not in stage


def test_exactly_one_stage_means_it_worked():
    """Counting failures needs one unambiguous success, or 'did anyone get
    through' is a judgement call at read time."""
    assert A.OK_STAGE in A.STAGES
    assert A.ok("connected") is True
    assert A.ok("exchange_refused") is False
    assert A.ok("token_rejected") is False


# ---------------------------------------------------------------- the status

def test_only_an_integer_http_status_is_kept():
    """A status is evidence worth having: 401 is a dead credential, 403 is a
    plan limit, 500 is their problem. Anything that is not a status code is
    dropped rather than stored, because the thing most likely to arrive in
    its place is the vendor's error body."""
    assert A.clean("exchange_refused", 401) == ("exchange_refused", 401)
    assert A.clean("exchange_refused", "403") == ("exchange_refused", 403)
    assert A.clean("exchange_refused", 0)[1] is None
    assert A.clean("exchange_refused", 99)[1] is None
    assert A.clean("exchange_refused", 600)[1] is None
    assert A.clean("exchange_refused", None)[1] is None


def test_a_vendor_sentence_offered_as_a_status_is_dropped():
    """The exact mistake this guards: passing the vendor's message where the
    status goes. It must not reach the database and must not raise either,
    because a connect must never break over its own logging."""
    for junk in ("Bad credentials",
                 "invalid_grant: token=abc123",
                 "https://api.trello.com/1/members/me?key=K&token=T",
                 {"error": "bad"}, ["401"], 4.5):
        stage, status = A.clean("exchange_refused", junk)
        assert stage == "exchange_refused"
        assert status is None, junk


# ------------------------------------------------------------- writing a row

class _Db:
    def __init__(self, blow_up=False):
        self.rows = []
        self.blow_up = blow_up

    async def write(self, email, provider, stage, status):
        if self.blow_up:
            raise RuntimeError("database is down")
        self.rows.append((email, provider, stage, status))


async def test_an_attempt_is_recorded(monkeypatch):
    db = _Db()
    monkeypatch.setattr(A, "_write", db.write)
    await A.record("someone@example.com", "notion", "exchange_refused", 400)
    assert db.rows == [("someone@example.com", "notion",
                        "exchange_refused", 400)]


async def test_recording_never_breaks_a_connect(monkeypatch):
    """Fails open, like every other post-step in this codebase: a person
    must not lose a connection they completed because we could not write a
    log row about it."""
    db = _Db(blow_up=True)
    monkeypatch.setattr(A, "_write", db.write)
    await A.record("someone@example.com", "notion", "connected")  # no raise


async def test_an_invented_stage_is_not_written_but_does_not_raise(
        monkeypatch):
    """Both halves matter. A bad stage must not reach the table, and must
    not take the connect down with it."""
    db = _Db()
    monkeypatch.setattr(A, "_write", db.write)
    await A.record("someone@example.com", "notion", "whatever the vendor said")
    assert db.rows == []


# -------------------------------------------------------- answering the question

def test_the_summary_tells_nobody_tried_from_everybody_failed():
    """The whole point. These two inputs must not produce the same answer."""
    nobody = A.summary([])
    everybody = A.summary([
        {"provider": "notion", "stage": "exchange_refused"},
        {"provider": "notion", "stage": "token_rejected"},
        {"provider": "dropbox", "stage": "state_bad"},
    ])
    assert nobody["attempts"] == 0
    assert nobody["people_who_got_through"] == 0
    assert everybody["attempts"] == 3
    assert everybody["people_who_got_through"] == 0
    assert nobody != everybody, (
        "nobody tried and everybody failed must read differently")
    assert everybody["by_provider"]["notion"]["failed"] == 2


def test_the_summary_counts_a_success_as_a_success():
    out = A.summary([
        {"provider": "notion", "stage": "connected", "email": "a@b.c"},
        {"provider": "notion", "stage": "exchange_refused", "email": "d@e.f"},
    ])
    assert out["by_provider"]["notion"] == {"attempts": 2, "connected": 1,
                                            "failed": 1}
    assert out["people_who_got_through"] == 1


def test_the_summary_survives_rubbish_rows():
    """It reads rows a future call site wrote, so it must not fall over on a
    stage it has never heard of."""
    out = A.summary([{"provider": "notion", "stage": "something_new"},
                     {}, {"provider": None, "stage": None}])
    assert out["attempts"] == 3
    assert out["people_who_got_through"] == 0


# ------------------------------------------------------- the call sites exist

def _wired_stages() -> set:
    """The stage names that really appear INSIDE a record() call.

    Not `'"connected" in src'`, which would pass on the JSON field of that
    name and tell us nothing. This is the lesson from `"name" in src`
    passing six times while the behaviour was gone: read the call sites.
    """
    import routes_connections as R
    src = inspect.getsource(R)
    found = set()
    for call in re.findall(r"CA\.record\((.*?)\)", src, re.S):
        found.update(re.findall(r'"([a-z_]{3,24})"', call))
    return found


def test_every_stage_is_actually_recorded_somewhere():
    """A stage nothing writes will never explain anything, and a stage
    written but never declared cannot be read back. Both directions."""
    wired = _wired_stages()
    assert not (A.STAGES - wired), (
        "declared and never recorded: %s" % sorted(A.STAGES - wired))
    assert not (wired - A.STAGES), (
        "recorded and never declared, so clean() will refuse them at "
        "runtime: %s" % sorted(wired - A.STAGES))


def test_the_callback_records_before_it_gives_up():
    """Every outcome of a connect must record first, or the failures we most
    want to see are exactly the ones that vanish."""
    import routes_connections as R
    src = inspect.getsource(R)
    assert "import connect_attempt as CA" in src
    sites = src.count("CA.record(")
    assert sites >= 14, (
        "found %d record() calls; the connect paths have more outcomes than "
        "that, and a missed one is a failure nobody can see" % sites)
