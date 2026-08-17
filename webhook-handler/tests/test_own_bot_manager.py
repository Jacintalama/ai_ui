"""Holding one socket per user, for the users who asked for one.

The rules here are all resource or safety rules, not features:
  - a socket is how a message ARRIVES, so it is never dropped for being idle
  - the cap is shared, because memory does not care which channel spent it
  - being over the cap is reported, never silently truncated
  - one user's broken credentials never stop anybody else connecting
  - tasks being briefly down must not permanently stop the loop
"""
import asyncio

import pytest

from gateway.own_bot_manager import ConnectionBudget, OwnBotManager


class FakeConn:
    def __init__(self, key, fail_on_start=False):
        self.bot_key = key
        self.connected = False
        self.last_error = ""
        self.started = False
        self.stopped = False
        self._fail = fail_on_start

    def start(self):
        self.started = True
        if self._fail:
            raise RuntimeError("boom")
        self.connected = True

    async def stop(self):
        self.stopped = True
        self.connected = False


class FakeTasks:
    def __init__(self, bots=None):
        self.bots = bots or []
        self.states = []
        self.calls = 0
        self.raise_next = False

    async def gateway_bots_for_platform(self, platform):
        self.calls += 1
        if self.raise_next:
            self.raise_next = False
            raise RuntimeError("tasks is down")
        return self.bots

    async def gateway_bot_state(self, key, connected, error):
        self.states.append((key, connected, error))


def _manager(tasks, budget=None, build=None, platform="slack"):
    budget = budget or ConnectionBudget(limit=3)
    build = build or (lambda key, config: FakeConn(key))
    return OwnBotManager(platform, tasks, build, budget=budget)


async def test_a_saved_connection_is_opened():
    tasks = FakeTasks([{"bot_key": "a", "token": "x"}])
    m = _manager(tasks)
    await m.reconcile()
    assert set(m.live) == {"a"}
    assert m.live["a"].started


async def test_switching_a_channel_off_closes_its_socket():
    tasks = FakeTasks([{"bot_key": "a"}])
    m = _manager(tasks)
    await m.reconcile()
    conn = m.live["a"]
    tasks.bots = []
    await m.reconcile()
    assert m.live == {}
    assert conn.stopped, "the socket was dropped from the map but left running"


async def test_an_already_open_connection_is_not_reopened():
    """Reconcile runs every 30 seconds. Rebuilding a live socket each time
    would drop every conversation twice a minute."""
    tasks = FakeTasks([{"bot_key": "a"}])
    m = _manager(tasks)
    await m.reconcile()
    first = m.live["a"]
    await m.reconcile()
    assert m.live["a"] is first


async def test_the_cap_is_shared_across_platforms():
    """Two independent caps of N quietly mean 2N, and the box has one pool of
    memory."""
    budget = ConnectionBudget(limit=2)
    slack = _manager(FakeTasks([{"bot_key": "s1"}, {"bot_key": "s2"}]),
                     budget=budget, platform="slack")
    discord = _manager(FakeTasks([{"bot_key": "d1"}]), budget=budget,
                       platform="discord")
    await slack.reconcile()
    await discord.reconcile()
    assert len(slack.live) == 2
    assert discord.live == {}, "discord spent a budget slack had already used"


async def test_being_over_the_cap_is_reported_not_hidden():
    """A user whose channel is switched on and not running has to be
    discoverable. Silent truncation reads as "covered everything"."""
    budget = ConnectionBudget(limit=1)
    m = _manager(FakeTasks([{"bot_key": "a"}, {"bot_key": "b"}]), budget=budget)
    await m.reconcile()
    assert len(m.live) == 1
    assert len(m.skipped) == 1
    assert "slot" in next(iter(m.skipped.values()))


async def test_one_broken_credential_does_not_block_everyone_else():
    def build(key, config):
        if key == "bad":
            raise ValueError("unusable token")
        return FakeConn(key)

    m = _manager(FakeTasks([{"bot_key": "bad"}, {"bot_key": "good"}]), build=build)
    await m.reconcile()
    assert set(m.live) == {"good"}
    assert "bad" in m.skipped


async def test_a_build_failure_never_records_the_credential():
    """The exception's payload can quote the request that carried the token."""
    def build(key, config):
        raise ValueError("token xoxb-super-secret was rejected")

    m = _manager(FakeTasks([{"bot_key": "a"}]), build=build)
    await m.reconcile()
    assert "xoxb-super-secret" not in m.skipped["a"]


async def test_state_is_reported_once_not_every_poll():
    tasks = FakeTasks([{"bot_key": "a"}])
    m = _manager(tasks)
    await m.reconcile()
    await m.report()
    await m.report()
    assert tasks.states == [("a", True, "")], "a steady connection was re-reported"


async def test_a_change_of_state_is_reported():
    tasks = FakeTasks([{"bot_key": "a"}])
    m = _manager(tasks)
    await m.reconcile()
    await m.report()
    m.live["a"].connected = False
    m.live["a"].last_error = "refused"
    await m.report()
    assert tasks.states[-1] == ("a", False, "refused")


async def test_state_for_a_removed_bot_is_forgotten():
    """Otherwise re-adding the same bot later would look unchanged and never
    be reported at all."""
    tasks = FakeTasks([{"bot_key": "a"}])
    m = _manager(tasks)
    await m.reconcile()
    await m.report()
    tasks.bots = []
    await m.reconcile()
    await m.report()
    assert "a" not in m._reported


async def test_tasks_being_down_does_not_kill_the_loop():
    """If one failed poll ended the loop, the channel would never come back
    without restarting the service."""
    tasks = FakeTasks([{"bot_key": "a"}])
    tasks.raise_next = True
    m = _manager(tasks)
    m.start()
    try:
        await asyncio.sleep(0.05)
        assert tasks.calls >= 1
        assert not m._task.done(), "one failed poll ended the reconcile loop"
    finally:
        await m.stop()


async def test_stopping_closes_every_socket():
    tasks = FakeTasks([{"bot_key": "a"}, {"bot_key": "b"}])
    m = _manager(tasks)
    await m.reconcile()
    conns = list(m.live.values())
    await m.stop()
    assert all(c.stopped for c in conns)
    assert m.live == {}


async def test_status_never_leaks_a_credential_or_an_endpoint():
    tasks = FakeTasks([{"bot_key": "a", "token": "xoxb-secret",
                        "endpoint": "wss://private.example.com"}])
    m = _manager(tasks)
    await m.reconcile()
    blob = repr(m.status())
    assert "xoxb-secret" not in blob
    assert "private.example.com" not in blob


@pytest.mark.parametrize("value", [None])
async def test_a_builder_that_declines_records_why(value):
    m = _manager(FakeTasks([{"bot_key": "a"}]), build=lambda k, c: value)
    await m.reconcile()
    assert m.live == {}
    assert m.skipped["a"]
