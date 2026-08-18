"""How many of the users' own bots are online, and which.

Generalises gateway/buzz_manager.py to any channel where a personal connection
is a socket IO holds open rather than a webhook the platform calls. Telegram is
the odd one out and stays outside this: it calls us, so an idle Telegram bot
costs nothing and needs no manager at all.

Two things carried over from Buzz because both were learned the hard way:

  The cap is a resource decision, not a detail. A held-open socket costs
  memory for as long as the user wants to be reachable, on a box with 3.8GB.
  And it is NOT "connect on demand, drop when idle", which is the obvious
  design and is wrong: the socket IS how a message reaches us, so dropping an
  idle one means silently not receiving. The demand signal is whether the user
  has the channel switched on.

  Reconcile by polling, not by tasks pushing. Polling is self-healing: a
  connection that died, a service that restarted, a credential edited in
  another browser tab all converge within one interval, with no new inbound
  route and nothing to get out of step.

The budget is SHARED across platforms here, unlike Buzz's own cap. Memory does
not care which channel spent it, and two independent caps of 25 quietly mean
50.
"""
import asyncio
import logging
from typing import Callable

log = logging.getLogger(__name__)

#: Open sockets allowed at once across EVERY channel that holds one, all users:
#: Buzz relays and users' own Slack and Discord bots draw on this one
#: allowance. Buzz used to keep a separate cap of 25, which meant the real
#: ceiling was 45 while this file believed it was enforcing 20.
#:
#: 25 rather than 20 because 25 is the number already judged acceptable for
#: held-open sockets on this box, and sharing must not quietly cut Buzz's
#: capacity under cover of a safety fix.
MAX_CONNECTIONS = 25

#: How often to reconcile what is open against what tasks says should be.
POLL_SECONDS = 30


class ConnectionBudget:
    """One shared allowance, so two platforms cannot each spend the maximum."""

    def __init__(self, limit: int = MAX_CONNECTIONS) -> None:
        self.limit = limit
        self._managers: list["OwnBotManager"] = []

    def join(self, manager: "OwnBotManager") -> None:
        self._managers.append(manager)

    def in_use(self) -> int:
        return sum(len(m.live) for m in self._managers)

    def has_room(self) -> bool:
        return self.in_use() < self.limit


class OwnBotManager:
    """Owns every live connection for one platform. One instance per platform."""

    def __init__(self, platform: str, tasks_client, build, *,
                 budget: ConnectionBudget) -> None:
        self.platform = platform
        self._tasks = tasks_client
        #: (bot_key, config) -> a started-on-demand connection, or None with a
        #: reason recorded in `skipped`.
        self._build = build
        self._budget = budget
        budget.join(self)
        self.live: dict = {}
        self._task: asyncio.Task | None = None
        self._stopping = False
        #: Connections we could not start, and why, so the count is never a
        #: silent truncation. Read by the status endpoint.
        self.skipped: dict[str, str] = {}
        #: Last state pushed to tasks per bot, so a steady connection is not
        #: re-reported every poll.
        self._reported: dict[str, tuple] = {}

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stopping = False
            self._task = asyncio.create_task(self._loop(),
                                             name=f"{self.platform}:manager")

    async def stop(self) -> None:
        self._stopping = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):        # noqa: BLE001
                pass
            self._task = None
        await asyncio.gather(*(c.stop() for c in list(self.live.values())),
                             return_exceptions=True)
        self.live.clear()

    async def _loop(self) -> None:
        while not self._stopping:
            try:
                await self.reconcile()
                await self.report()
            except asyncio.CancelledError:
                raise
            except Exception:                                  # noqa: BLE001
                # tasks being briefly unreachable must not stop the loop, or
                # the channel never comes back without a restart.
                log.warning("%s: reconcile failed", self.platform, exc_info=True)
            await asyncio.sleep(POLL_SECONDS)

    async def report(self) -> None:
        """Tell tasks which connections are actually up, on change only.

        Without this the Channels page can say what a user SAVED and never
        whether it works, so an app that has been refused all day looks
        identical to one that is fine.
        """
        for key, conn in list(self.live.items()):
            state = (conn.connected, conn.last_error)
            if self._reported.get(key) == state:
                continue
            self._reported[key] = state
            await self._tasks.gateway_bot_state(key, conn.connected,
                                                conn.last_error)
        for key in list(self._reported):
            if key not in self.live:
                self._reported.pop(key, None)

    async def reconcile(self) -> None:
        """Make what is open match what tasks says should be open."""
        wanted = await self._tasks.gateway_bots_for_platform(self.platform)
        by_key = {b["bot_key"]: b for b in wanted if b.get("bot_key")}

        for key in list(self.live):
            if key not in by_key:
                log.info("%s: dropping %s, no longer enabled", self.platform, key)
                await self.live.pop(key).stop()

        self.skipped = {}
        for key, config in by_key.items():
            if key in self.live:
                continue
            if not self._budget.has_room():
                # Never silently. A user whose channel is switched on and not
                # running has to be discoverable, not a mystery.
                self.skipped[key] = (
                    f"waiting for a free slot ({self._budget.limit} in use)")
                log.warning("%s: %s is over the shared cap of %d and was not "
                            "started", self.platform, key, self._budget.limit)
                continue
            try:
                conn = self._build(key, config)
            except Exception as e:                             # noqa: BLE001
                # Never the credential, and never the exception's payload: it
                # can quote the request that carried the token.
                self.skipped[key] = "the saved credentials could not be used"
                log.warning("%s: %s could not be started (%s)", self.platform,
                            key, type(e).__name__)
                continue
            if conn is None:
                self.skipped.setdefault(key, "the saved credentials were incomplete")
                continue
            self.live[key] = conn
            conn.start()
            log.info("%s: connecting %s (%d/%d shared)", self.platform, key,
                     self._budget.in_use(), self._budget.limit)

    def status(self) -> dict:
        """What is open right now. No credential and no endpoint: this is read
        by an operator endpoint, and an endpoint identifies a user's workspace.
        """
        return {
            "open": len(self.live),
            "cap": self._budget.limit,
            "shared_in_use": self._budget.in_use(),
            "connected": sum(1 for c in self.live.values() if c.connected),
            "skipped": dict(self.skipped),
            "errors": {k: c.last_error for k, c in self.live.items()
                       if c.last_error},
        }
