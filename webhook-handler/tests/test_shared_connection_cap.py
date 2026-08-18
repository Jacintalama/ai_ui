"""One ceiling on held-open sockets, across every channel that holds one.

Buzz, a user's own Slack app and a user's own Discord bot all keep a socket
open for as long as the channel is switched on, because the socket IS how a
message arrives. They cost the same memory on the same 3.8GB box.

They did not share a limit. Buzz kept its own cap of 25 and the own-bot
manager was given a separate 20, so the real ceiling was 45 rather than the 20
the newer code believed it was enforcing. Two independent caps of N mean 2N,
and nothing in either file said so.
"""
import pytest

from gateway.buzz_manager import BuzzManager
from gateway.own_bot_manager import ConnectionBudget, OwnBotManager


class FakeConn:
    def __init__(self, key):
        self.bot_key = key
        self.connected = False
        self.last_error = ""

    def start(self):
        self.connected = True

    async def stop(self):
        self.connected = False


class FakeTasks:
    def __init__(self, bots):
        self.bots = bots

    async def gateway_bots_for_platform(self, platform):
        return self.bots

    async def gateway_bot_state(self, key, connected, error):
        pass


def _buzz(budget, n):
    """A BuzzManager whose relays are built without touching a socket."""
    bots = [{"bot_key": f"b{i}", "endpoint": "wss://x", "token": "t"}
            for i in range(n)]
    m = BuzzManager(FakeTasks(bots), lambda *a: None,
                    decode_key=lambda t: b"\x01" * 32,
                    allow_factory=lambda cfg: (lambda who: True),
                    budget=budget)
    m._build = lambda key, config: FakeConn(key)
    return m


def _own(budget, n, platform="slack"):
    bots = [{"bot_key": f"{platform}{i}", "token": "t", "app_token": "a"}
            for i in range(n)]
    return OwnBotManager(platform, FakeTasks(bots),
                         lambda key, config: FakeConn(key), budget=budget)


async def test_buzz_and_own_bots_draw_on_the_same_allowance():
    budget = ConnectionBudget(limit=3)
    buzz = _buzz(budget, 3)
    slack = _own(budget, 3)
    await buzz.reconcile()
    await slack.reconcile()
    assert len(buzz.live) == 3
    assert slack.live == {}, "slack spent an allowance buzz had already used"


async def test_the_total_across_channels_never_exceeds_the_limit():
    budget = ConnectionBudget(limit=4)
    managers = [_buzz(budget, 5), _own(budget, 5, "slack"),
                _own(budget, 5, "discord")]
    for m in managers:
        await m.reconcile()
    assert budget.in_use() == 4, f"{budget.in_use()} sockets open against a cap of 4"


async def test_buzz_reports_what_it_could_not_start():
    """Never silently. A user whose channel is switched on and not running has
    to be discoverable rather than a mystery."""
    budget = ConnectionBudget(limit=1)
    buzz = _buzz(budget, 3)
    await buzz.reconcile()
    assert len(buzz.live) == 1
    assert len(buzz.skipped) == 2
    assert all("slot" in why for why in buzz.skipped.values())


async def test_freeing_a_buzz_slot_lets_another_channel_take_it():
    """The point of sharing: turning one channel off has to release the
    allowance for the others, not just for itself."""
    budget = ConnectionBudget(limit=1)
    buzz = _buzz(budget, 1)
    slack = _own(budget, 1)
    await buzz.reconcile()
    assert slack.live == {} or True
    await slack.reconcile()
    assert slack.live == {}, "the cap was not enforced across managers"

    buzz._tasks.bots = []          # user switched Buzz off
    await buzz.reconcile()
    await slack.reconcile()
    assert len(slack.live) == 1, "the freed slot was never released"


def test_buzz_still_has_a_limit_when_nobody_gives_it_a_budget():
    """Its own cap remains the fallback, so a caller that has not been updated
    cannot accidentally get an unbounded manager."""
    m = _buzz(None, 1)
    assert m._budget is not None
    assert m._budget.limit > 0
