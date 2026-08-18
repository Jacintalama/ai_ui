"""How many Buzz relays are open, and which.

Every other channel costs nothing while idle: a webhook route sits there and
the platform calls it. A Buzz connection is a socket we hold open for as long
as the user wants to be reachable, on a box with 3.8GB of RAM, so the count is
a resource decision rather than a detail.

Hence the cap. It is not "connect on demand and drop when idle", which is the
obvious design and is wrong here: the socket IS how a message reaches us, so
dropping an idle one means silently not receiving. The demand signal is
therefore whether the user has the channel switched on, and turning it off is
what frees the slot.

Reconciled by polling rather than by tasks pushing at us. Polling is
self-healing: a relay that died, a service that restarted, a credential edited
in another window all converge within one interval, with no new inbound route
and nothing to get out of step.
"""
import asyncio
import logging

from gateway.platforms.buzz import BuzzRelay

log = logging.getLogger(__name__)

#: Open sockets allowed at once, across all users.
MAX_CONNECTIONS = 25

#: How often to reconcile what is open against what tasks says should be.
POLL_SECONDS = 30


class BuzzManager:
    """Owns every live relay. One instance, held by main.py."""

    def __init__(self, tasks_client, on_event, *, decode_key, allow_factory,
                 budget=None) -> None:
        # One allowance shared with every other channel that holds a socket
        # open. Buzz had its own cap of 25 and the own-bot manager was given a
        # separate 20, so the real ceiling was 45 while the newer code believed
        # it was enforcing 20. Two independent caps of N mean 2N, and the
        # memory they spend is the same memory.
        #
        # Falling back to a private budget rather than to no limit: a caller
        # that has not been updated must not silently get an unbounded manager.
        from gateway.own_bot_manager import ConnectionBudget
        self._budget = budget if budget is not None else ConnectionBudget(
            limit=MAX_CONNECTIONS)
        self._budget.join(self)
        self._tasks = tasks_client
        self._on_event = on_event
        self._decode_key = decode_key
        self._allow_factory = allow_factory
        self._relays: dict[str, BuzzRelay] = {}
        self._task: asyncio.Task | None = None
        self._stopping = False
        #: Bots we could not start, and why, so the count is never a silent
        #: truncation. Read by the status endpoint.
        self.skipped: dict[str, str] = {}
        #: Last state pushed to tasks per bot, so a steady connection is not
        #: re-reported every poll.
        self._reported: dict[str, tuple] = {}

    @property
    def live(self) -> dict:
        """What this manager currently holds open.

        The name the shared budget counts. Buzz calls them relays and the
        own-bot manager calls them connections; the budget only cares how many
        sockets are open, so both answer to the same word.
        """
        return self._relays

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stopping = False
            self._task = asyncio.create_task(self._loop(), name="buzz:manager")

    async def stop(self) -> None:
        self._stopping = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):         # noqa: BLE001
                pass
            self._task = None
        await asyncio.gather(*(r.stop() for r in list(self._relays.values())),
                             return_exceptions=True)
        self._relays.clear()

    async def _loop(self) -> None:
        while not self._stopping:
            try:
                await self.reconcile()
                await self.report()
            except asyncio.CancelledError:
                raise
            except Exception:                                   # noqa: BLE001
                # tasks being briefly unreachable must not stop the loop, or
                # the channel never comes back without a restart.
                log.warning("buzz: reconcile failed", exc_info=True)
            await asyncio.sleep(POLL_SECONDS)

    async def report(self) -> None:
        """Tell tasks which connections are actually up.

        Only on change. Without this the Channels page can say what a user
        SAVED and never whether it is working, so a relay that has been
        refusing us all day looks identical to one that is fine.
        """
        for key, relay in list(self._relays.items()):
            state = (relay.connected, relay.last_error)
            if self._reported.get(key) == state:
                continue
            self._reported[key] = state
            await self._tasks.gateway_bot_state(key, relay.connected,
                                                relay.last_error)
        for key in list(self._reported):
            if key not in self._relays:
                self._reported.pop(key, None)

    async def reconcile(self) -> None:
        """Make the open connections match what tasks says should be open."""
        wanted = await self._tasks.gateway_bots_for_platform("buzz")
        by_key = {b["bot_key"]: b for b in wanted if b.get("bot_key")}

        for key in list(self._relays):
            if key not in by_key:
                log.info("buzz: dropping %s, no longer enabled", key)
                await self._relays.pop(key).stop()

        self.skipped = {}
        for key, config in by_key.items():
            if key in self._relays:
                continue
            if not self._budget.has_room():
                # Never silently. A user whose channel is switched on and not
                # running has to be discoverable, not a mystery.
                self.skipped[key] = (
                    f"waiting for a free slot ({self._budget.limit} in use)")
                log.warning("buzz: %s is over the shared cap of %d and was not "
                            "started", key, self._budget.limit)
                continue
            relay = self._build(key, config)
            if relay is not None:
                self._relays[key] = relay
                relay.start()
                log.info("buzz: connecting %s (%d/%d shared)", key,
                         self._budget.in_use(), self._budget.limit)

    def _build(self, key: str, config: dict) -> BuzzRelay | None:
        endpoint = (config.get("endpoint") or "").strip()
        if not endpoint.startswith(("wss://", "ws://")):
            self.skipped[key] = "the relay URL is not a websocket address"
            return None
        try:
            seckey = self._decode_key(config.get("token") or "")
        except Exception as e:                                  # noqa: BLE001
            # Never log the key or the exception's payload.
            self.skipped[key] = "the agent key could not be read"
            log.warning("buzz: %s has an unusable key (%s)", key, type(e).__name__)
            return None
        return BuzzRelay(key, endpoint, seckey, self._on_event,
                         allow=self._allow_factory(config))

    def status(self) -> dict:
        """What is open right now. No credential, no relay URL: this is read by
        an operator endpoint and a relay URL identifies a user's workspace."""
        return {
            "open": len(self._relays),
            "cap": self._budget.limit,
            "shared_in_use": self._budget.in_use(),
            "connected": sum(1 for r in self._relays.values() if r.connected),
            "skipped": dict(self.skipped),
            "errors": {k: r.last_error for k, r in self._relays.items()
                       if r.last_error},
        }
