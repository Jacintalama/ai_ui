"""A credential that has quietly died is found before somebody needs it.

`connection_health` learns from real calls, which is cheap and accurate and
has one hole in it: a connector nobody used this week is never asked about,
so its card keeps saying Connected. That is not hypothetical. My own GitHub
credential answered 401 for days while the page said it was fine, and it was
found by drilling it on purpose, not by the platform noticing.

The module argued against asking every vendor WHEN THE CONNECTIONS PAGE
OPENS, and it was right: that spends a request per app per visit to answer a
question that is almost always "still fine", and spends it while somebody is
waiting for a page. This is the other shape, and the objection does not
apply to it: once a day, in the background, with nobody waiting.

It is also why the typed-URL guard had to land first. Putting a probe on a
timer means making requests nobody is watching, so the addresses those
requests can reach had to be settled before this existed.

TWO THINGS HERE ARE LOAD-BEARING and both have a test of their own:

  - The sweep records that it LOOKED even when the vendor's answer taught it
    nothing. `note` deliberately writes nothing on a 403, so a row probed
    through `note` alone would stay due and be probed again on every single
    tick, forever.
  - Nothing it does can raise. It runs in a background task where a
    traceback goes unseen, and one person's revoked token must not stop
    everybody else from being checked.
"""
import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("AIUI_FERNET_KEY",
                      "SFNQQkFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=")

import connection_sweep as S                                # noqa: E402

NOW = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)


def row(email="a@b.co", provider="trello", checked_at=None):
    return {"email": email, "provider": provider, "checked_at": checked_at}


def ago(hours):
    return NOW - timedelta(hours=hours)


# --- who gets asked -------------------------------------------------------

def test_a_connection_nobody_has_ever_checked_is_asked_about():
    """`check_ok` is nullable and every connection made before the column
    existed is NULL, so these are precisely the ones nothing is known
    about."""
    assert S.due([row(checked_at=None)], now=NOW) == [("a@b.co", "trello")]


def test_a_connection_checked_an_hour_ago_is_left_alone():
    assert S.due([row(checked_at=ago(1))], now=NOW) == []


def test_a_connection_checked_yesterday_is_asked_again():
    assert S.due([row(checked_at=ago(25))], now=NOW) == [("a@b.co", "trello")]


def test_the_longest_unchecked_go_first_and_the_never_checked_go_first_of_all():
    """So a backlog drains oldest first rather than by whatever order the
    database felt like returning."""
    rows = [row("c@x.co", "github", ago(2)),
            row("a@x.co", "trello", ago(40)),
            row("b@x.co", "clickup", None)]
    assert S.due(rows, now=NOW, cap=10) == [("b@x.co", "clickup"),
                                            ("a@x.co", "trello")]


def test_only_so_many_in_one_tick():
    """A platform with a thousand connections must not become a thousand
    outbound requests in one minute."""
    rows = [row("p%d@x.co" % i, "trello", None) for i in range(40)]
    assert len(S.due(rows, now=NOW, cap=5)) == 5


def test_a_provider_this_build_no_longer_has_is_skipped():
    """A row for a connector that was removed. Without this the sweep
    raises on it every tick forever, in a background task where nobody sees
    the traceback."""
    assert S.due([row(provider="something-we-dropped")], now=NOW) == []


def test_a_timestamp_with_no_timezone_does_not_blow_up():
    """Comparing a naive datetime with an aware one raises TypeError, and
    that would kill the loop rather than skip the row. Treated as UTC."""
    naive = NOW.replace(tzinfo=None) - timedelta(hours=30)
    assert S.due([row(checked_at=naive)], now=NOW) == [("a@b.co", "trello")]


def test_a_garbled_timestamp_means_ask_rather_than_crash():
    assert S.due([row(checked_at="not a time")], now=NOW) == [
        ("a@b.co", "trello")]


# --- the sweep itself -----------------------------------------------------

class _Fake:
    """Enough of the outside world to run a sweep without one."""

    def __init__(self, answers, creds=None):
        #: provider -> what `_ask` should do: a status code, or an Exception
        self.answers = answers
        self.creds = {"trello": {"token": "x"}} if creds is None else creds
        self.asked = []
        self.looked = []
        self.noted = []

    async def rows(self):
        return [row(provider=p) for p in sorted(self.answers)]

    async def secrets(self, email, provider):
        return self.creds.get(provider, {})

    async def ask(self, email, provider, values):
        self.asked.append(provider)
        out = self.answers[provider]
        if isinstance(out, Exception):
            raise out
        self.noted.append((provider, out))
        return out

    async def mark(self, email, provider):
        # NOT named `looked`: that is the list below, and an instance
        # attribute shadows the method, so the seam would be set to a list.
        self.looked.append(provider)


@pytest.fixture
def sweeping(monkeypatch):
    def run(fake):
        monkeypatch.setattr(S, "_rows", fake.rows)
        monkeypatch.setattr(S, "_secrets", fake.secrets)
        monkeypatch.setattr(S, "_ask", fake.ask)
        monkeypatch.setattr(S, "_looked", fake.mark)
        return fake
    return run


async def test_it_asks_every_connection_that_is_due(sweeping):
    fake = sweeping(_Fake({"trello": 200, "github": 401},
                          creds={"trello": {"token": "x"},
                                 "github": {"token": "y"}}))
    await S.sweep_once(now=NOW)
    assert sorted(fake.asked) == ["github", "trello"]


async def test_it_writes_down_that_it_looked_even_when_it_learned_nothing(
        sweeping):
    """The one that keeps the sweep from eating itself.

    403 is deliberately not evidence about a credential (ClickUp answers a
    plan limit with one), so `note` writes nothing at all for it. If the
    sweep relied on that write, this row would still be due on the next
    tick, and the next, and would be probed every tick for ever.
    """
    fake = sweeping(_Fake({"clickup": 403}, creds={"clickup": {"token": "x"}}))
    await S.sweep_once(now=NOW)
    assert fake.asked == ["clickup"]
    assert fake.looked == ["clickup"], (
        "it asked and did not write down that it had asked, so this "
        "connection is due again immediately")


async def test_one_broken_connection_does_not_stop_the_others(sweeping):
    """It runs in a background task. A traceback here is invisible and
    takes everybody else's check with it."""
    fake = sweeping(_Fake({"trello": RuntimeError("vendor exploded"),
                           "github": 200},
                          creds={"trello": {"token": "x"},
                                 "github": {"token": "y"}}))
    out = await S.sweep_once(now=NOW)
    assert "github" in fake.asked, "the other connection was never reached"
    assert out["asked"] == 1 and out["failed"] == 1
    assert fake.looked == ["github"], (
        "the one that threw must not be stamped: nothing was learned and "
        "nothing was recorded, so it should be tried again")


async def test_a_connection_with_no_stored_credential_is_not_asked_about(
        sweeping):
    fake = sweeping(_Fake({"trello": 200}, creds={}))
    await S.sweep_once(now=NOW)
    assert fake.asked == []


async def test_a_connection_with_no_credential_is_still_marked_as_looked_at(
        sweeping):
    """Same trap as the 403: nothing to ask means nothing to learn, and a
    row that is never stamped is retried on every tick."""
    fake = sweeping(_Fake({"trello": 200}, creds={}))
    await S.sweep_once(now=NOW)
    assert fake.looked == ["trello"]


async def test_the_sweep_never_raises_even_when_the_database_is_gone(
        monkeypatch):
    async def broken():
        raise RuntimeError("no database")

    monkeypatch.setattr(S, "_rows", broken)
    out = await S.sweep_once(now=NOW)
    assert out["asked"] == 0


# --- the settings ---------------------------------------------------------

def test_it_asks_about_each_connection_about_once_a_day():
    """Not a number pulled out of the air: often enough that a dead
    credential is found the day it dies, rare enough that fourteen
    connectors across nine people is about a hundred requests a day."""
    assert 12 <= S.INTERVAL_HOURS <= 48


def test_a_tick_is_not_so_often_that_it_is_a_poller():
    assert S.TICK_SECONDS >= 600


def test_every_seam_points_at_something_that_really_exists():
    """A harness that supplies a name the real code lacks tests the
    harness.

    Each test above replaces `_rows`, `_secrets`, `_ask` and `_looked`, so
    all of them would pass with every one of those pointing at nothing.
    `connection_health.looked` did not exist when this file was written,
    and this is what said so.
    """
    import connection_health as H
    import routes_connections as R

    assert callable(getattr(H, "looked", None)), (
        "connection_sweep._looked calls connection_health.looked")
    assert callable(getattr(R, "secrets_for", None))
    assert callable(getattr(R, "_ask_vendor", None))


def test_the_loop_is_actually_started_when_the_service_boots():
    """The invisible step.

    Every test in this file can pass with the loop never running, the same
    way a provider can pass its whole suite and be unreachable because
    nothing registered it with mcp-proxy. This reads `main.py` and asserts
    both halves, because the import alone schedules nothing.
    """
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "main.py").read_text(encoding="utf-8")
    assert "from connection_sweep import sweep_loop" in src
    assert "asyncio.create_task(sweep_loop())" in src
