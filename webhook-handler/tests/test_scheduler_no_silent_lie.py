"""Never tell a user a scheduled job was created when it can never run.

Found in an audit: asking chat to "run this workflow every morning" reaches the
mcp-scheduler tools -> webhook-handler's APScheduler -> an n8n webhook. The
create path validated the cron expression, the job count and the interval, but
never checked that n8n was reachable. It returned success, stored the job in an
in-memory dict, and every firing then failed into a `last_status` field no
surface reads. The user is told it worked, forever, and it never runs.

That is the same failure class as the git-commit bug in CLAUDE.md -- announce an
action, never check the outcome -- except here the platform actively reports
success. Zero users have ever created one of these jobs, so the fix is about
never starting to lie rather than repairing lost work.

Deliberately NOT solved by pointing at a different n8n: these jobs live only in
a Python dict (`_user_jobs`), so they are lost on every container restart. The
durable, multi-tenant scheduler is `tasks.schedules`, which has five self-serve
surfaces. The honest move is to refuse and say where to go.
"""
import pytest

import scheduler as sched


def _create(**kw):
    base = dict(
        job_id="probe", cron_expression="0 8 * * *", workflow_id="wf1",
        trigger_method="webhook", webhook_path="hook", n8n_url="http://n8n:5678",
        n8n_api_key="k",
    )
    base.update(kw)
    return sched.create_user_cron_job(**base)


@pytest.fixture(autouse=True)
def _fresh_scheduler():
    """A real, empty scheduler for every test, restored afterwards.

    Two reasons this cannot just be `if sched.scheduler is None: init()`:
    another module installs a `_FakeScheduler` into this global and never puts
    it back, so we would inherit a stub without `get_job`; and leaving OUR
    scheduler behind would do the same thing to whoever runs next. Both
    directions matter — the failure only appears in a full-suite run, which is
    the worst place to discover it.
    """
    saved_sched, saved_jobs = sched.scheduler, dict(sched._user_jobs)
    sched.init_scheduler()
    sched._user_jobs.clear()
    try:
        yield
    finally:
        sched.scheduler = saved_sched
        sched._user_jobs.clear()
        sched._user_jobs.update(saved_jobs)


def _reset():
    sched._user_jobs.clear()


def test_refuses_when_n8n_is_unreachable(monkeypatch):
    _reset()
    monkeypatch.setattr(sched, "_n8n_reachable", lambda url: False)
    res = _create()
    assert res["success"] is False, (
        "told the user the job was created when it can never fire")
    assert "n8n" in (res.get("error") or "").lower()


def test_the_refusal_points_at_the_scheduler_that_actually_works(monkeypatch):
    _reset()
    monkeypatch.setattr(sched, "_n8n_reachable", lambda url: False)
    err = (_create().get("error") or "").lower()
    assert "schedule" in err, "a refusal with no alternative is a dead end"


def test_no_job_is_registered_when_it_would_never_fire(monkeypatch):
    """A stored-but-dead job also shows up in list_cron_jobs, which makes the
    lie persistent rather than momentary."""
    _reset()
    monkeypatch.setattr(sched, "_n8n_reachable", lambda url: False)
    _create()
    # Asserting on _user_jobs rather than scheduler.get_job on purpose: another
    # module stubs the whole apscheduler package in sys.modules when it is not
    # installed, so the scheduler object may be a stub without get_job. The job
    # registry is also the thing the user actually sees via list_cron_jobs.
    assert "probe" not in sched._user_jobs


def test_still_creates_normally_when_n8n_is_reachable(monkeypatch):
    _reset()
    monkeypatch.setattr(sched, "_n8n_reachable", lambda url: True)
    res = _create()
    assert res["success"] is True, res
    assert "probe" in sched._user_jobs


def test_an_empty_n8n_url_is_treated_as_unreachable(monkeypatch):
    """Config that was never set must not read as 'fine'."""
    _reset()
    monkeypatch.setattr(sched, "_n8n_reachable", lambda url: bool(url))
    res = _create(n8n_url="")
    assert res["success"] is False


def test_the_reachability_check_never_raises(monkeypatch):
    """A DNS failure is the EXPECTED case here (the local n8n host does not
    resolve at all). It must read as unreachable, not crash the tool."""
    import socket

    def boom(host, port):
        raise socket.gaierror("Name or service not known")

    monkeypatch.setattr(sched.socket, "create_connection", boom)
    assert sched._n8n_reachable("http://n8n:5678") is False


def test_reachability_parses_host_and_port_from_the_url(monkeypatch):
    seen = {}

    def fake(addr, timeout=None):
        seen["addr"] = addr

        class S:
            def close(self):
                pass
        return S()

    monkeypatch.setattr(sched.socket, "create_connection", fake)
    assert sched._n8n_reachable("http://n8n:5678") is True
    assert seen["addr"] == ("n8n", 5678)


def test_reachability_defaults_the_port_for_https(monkeypatch):
    seen = {}

    def fake(addr, timeout=None):
        seen["addr"] = addr

        class S:
            def close(self):
                pass
        return S()

    monkeypatch.setattr(sched.socket, "create_connection", fake)
    assert sched._n8n_reachable("https://n8n.srv1041674.hstgr.cloud") is True
    assert seen["addr"] == ("n8n.srv1041674.hstgr.cloud", 443)


def test_a_garbage_url_is_unreachable_not_an_exception():
    assert sched._n8n_reachable("not a url") is False
    assert sched._n8n_reachable("") is False
