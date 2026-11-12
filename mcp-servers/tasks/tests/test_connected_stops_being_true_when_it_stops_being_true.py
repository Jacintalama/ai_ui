"""A card said Connected for as long as a credential was STORED.

Found on 2026-11-11 while building the token renewal, and deliberately left
alone then because it is a different thing. My own GitHub credential has
answered HTTP 401 "Bad credentials" for days while the Connections page
shows it connected as `aiuiteams-hub`, so `my-github` can do nothing at
all for me and the only place that says so is a failed tool call in a chat.

`_describe` set `"connected": bool(hit)`, and `hit` is simply whether a row
exists. Connecting proved the credential once and nothing proved it again.

WHY NOT A PROBE. The obvious fix is to ask the vendor when the Connections
page opens. That spends a request per app per visit to answer a question
that is almost always "still fine", and it answers it at the one moment a
person is waiting for a page.

THE CHEAPER AND MORE ACCURATE ANSWER is to learn from the calls already
being made. A tool call IS the question, asked in earnest, and `_refusal`
already reads the answer. So a 401 anywhere marks the credential, a
working call clears it, and the card gets a third state.

THE RULE THAT MATTERS MOST HERE IS THE ONE PR #182 PAID FOR: a 403 is not
a dead credential. ClickUp answered a create_space with

    {"err":"Your plan is limited to 5 usages of feature, 5 usage.",
     "ECODE":"PAYWALL_004"}

and the old code told Ralph to reconnect a credential that had just read
his whole workspace. If a 403 flipped this flag, the card would call a
working connection broken, on a plan limit, permanently.
"""
import pytest

import connection_health as H


# --- which answers teach us anything --------------------------------------

def test_a_401_is_the_one_answer_that_means_reconnect():
    """"We do not know who you are." Nothing else means that."""
    assert H.verdict(401) is False


@pytest.mark.parametrize("ok", [200, 201, 202, 204, 302])
def test_a_call_that_worked_says_the_credential_works(ok):
    assert H.verdict(ok) is True


def test_a_403_says_nothing_about_the_credential():
    """The PR #182 rule. "We know who you are and you may not do this" is a
    plan limit, a quota or a permission far more often than a bad token,
    and ClickUp's paywall is a 403 on an account whose credential is
    perfect."""
    assert H.verdict(403) is None


@pytest.mark.parametrize("quiet", [400, 404, 409, 422, 429, 500, 502, 503])
def test_nothing_else_teaches_us_anything(quiet):
    """A vendor having a bad minute must not mark somebody's credential,
    and a 404 is about a path, not a person."""
    assert H.verdict(quiet) is None


def test_an_answer_that_is_not_a_number_teaches_nothing():
    for odd in (None, "", "200", object()):
        assert H.verdict(odd) is None


# --- what gets written ----------------------------------------------------

class _Conn:
    def __init__(self, fail=False):
        self.sql = []
        self.args = []
        self.closed = False
        self.fail = fail

    async def execute(self, sql, *args):
        if self.fail:
            raise RuntimeError("the database went away")
        self.sql.append(" ".join(sql.split()))
        self.args.append(args)

    async def close(self):
        self.closed = True


@pytest.fixture
def conn(monkeypatch):
    made = []

    async def _connect():
        c = _Conn()
        made.append(c)
        return c

    monkeypatch.setattr(H, "_connect", _connect)
    H.forget_all()
    yield made
    H.forget_all()


async def test_a_rejected_credential_is_written_down(conn):
    await H.note("ralph@example.com", "github", 401)
    assert len(conn) == 1, "nothing was written"
    assert "UPDATE tasks.user_connections" in conn[0].sql[0]
    assert conn[0].args[0][0] is False


async def test_a_working_call_is_written_down_too(conn):
    """Otherwise a credential that comes back to life stays accused."""
    await H.note("ralph@example.com", "github", 200)
    assert conn[0].args[0][0] is True


async def test_an_answer_that_teaches_nothing_writes_nothing(conn):
    for quiet in (403, 429, 500):
        await H.note("ralph@example.com", "clickup", quiet)
    assert conn == [], "a plan limit marked the credential"


async def test_the_row_is_found_by_the_person_and_the_app(conn):
    await H.note("ralph@example.com", "github", 401)
    args = conn[0].args[0]
    assert "ralph@example.com" in args
    assert "github" in args


async def test_nothing_a_vendor_said_is_ever_stored(conn):
    """A vendor's own words can carry the request back, and Trello's
    credential rides in its query string. The row holds a boolean and a
    time, and the sentence is composed from the app's name instead."""
    await H.note("ralph@example.com", "trello", 401)
    for arg in conn[0].args[0]:
        assert not isinstance(arg, (bytes, dict, list))
    assert len(conn[0].args[0]) == 3, conn[0].args[0]


async def test_the_connection_is_always_closed(conn):
    await H.note("ralph@example.com", "github", 401)
    assert conn[0].closed is True


# --- it must never cost a tool call anything ------------------------------

async def test_the_same_answer_twice_is_written_once(conn):
    """A composite tool makes several calls of its own. Writing per call
    would turn one question into five updates."""
    for _ in range(5):
        await H.note("ralph@example.com", "clickup", 200)
    assert len(conn) == 1


async def test_a_credential_that_changes_its_mind_is_written_again(conn):
    """The memo is there to skip repeats, not to miss the moment that
    matters."""
    await H.note("ralph@example.com", "github", 200)
    await H.note("ralph@example.com", "github", 401)
    await H.note("ralph@example.com", "github", 200)
    assert [c.args[0][0] for c in conn] == [True, False, True]


async def test_two_people_are_remembered_apart(conn):
    await H.note("a@example.com", "github", 200)
    await H.note("b@example.com", "github", 200)
    assert len(conn) == 2


async def test_two_apps_are_remembered_apart(conn):
    await H.note("a@example.com", "github", 200)
    await H.note("a@example.com", "clickup", 200)
    assert len(conn) == 2


async def test_a_database_that_is_down_never_breaks_a_tool_call(monkeypatch):
    """This is bookkeeping on the side of somebody's real request. It is
    never worth failing that request for."""
    async def _connect():
        return _Conn(fail=True)

    monkeypatch.setattr(H, "_connect", _connect)
    H.forget_all()
    await H.note("ralph@example.com", "github", 401)   # must not raise


async def test_a_database_that_cannot_be_reached_never_breaks_one(monkeypatch):
    async def _connect():
        raise RuntimeError("no pool")

    monkeypatch.setattr(H, "_connect", _connect)
    H.forget_all()
    await H.note("ralph@example.com", "github", 401)   # must not raise


async def test_a_write_that_failed_is_not_remembered_as_done(monkeypatch):
    """Otherwise the memo swallows every retry and the flag never lands."""
    state = {"fail": True}
    made = []

    async def _connect():
        c = _Conn(fail=state["fail"])
        made.append(c)
        return c

    monkeypatch.setattr(H, "_connect", _connect)
    H.forget_all()
    await H.note("ralph@example.com", "github", 401)
    state["fail"] = False
    await H.note("ralph@example.com", "github", 401)
    assert len(made) == 2, "the failed write was remembered as a success"
    assert made[1].args[0][0] is False


# --- reconnecting is the way out ------------------------------------------

async def test_replacing_a_credential_forgets_what_we_knew(conn):
    """The row is overwritten by the connect, which proved the new
    credential against the vendor before storing it. A memo from the old
    one would then suppress the write that says so."""
    await H.note("ralph@example.com", "github", 401)
    H.forget("ralph@example.com", "github")
    await H.note("ralph@example.com", "github", 401)
    assert len(conn) == 2
