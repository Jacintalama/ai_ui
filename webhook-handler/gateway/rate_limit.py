"""A brake for endpoints the internet can reach without authenticating.

Caddy routes /webhook/* straight to this service, so those paths never pass
through api-gateway and therefore never meet its auth or its rate limiter. The
terminal endpoint is the one that matters: an unpaired device mints a
pairing-code row, and device ids cost nothing to generate.

In-process on purpose. A shared store would be more correct across replicas,
and there is one replica on a 3.8GB box, so Redis here would buy nothing and
add a dependency this service does not otherwise need.
"""
import logging
import time
from collections import deque

log = logging.getLogger(__name__)


def client_key(headers: dict, peer: str) -> str:
    """Who to charge for this request.

    NOT the socket peer: Caddy is the direct peer for every inbound request,
    so keying on it would put the entire internet in one bucket and let a
    single noisy caller lock everyone out.

    Cloudflare sets CF-Connecting-IP and Caddy forwards it, so it is the best
    signal available. It is only as trustworthy as the path in front of us:
    anything reaching the origin directly can claim to be any address. That is
    acceptable for a brake, which is meant to blunt casual abuse rather than
    to be an authorization decision.
    """
    lower = {k.lower(): v for k, v in (headers or {}).items()}

    cf = (lower.get("cf-connecting-ip") or "").strip()
    if cf:
        return cf

    # First hop is the original client; the rest is the proxy chain.
    forwarded = (lower.get("x-forwarded-for") or "").split(",")[0].strip()
    if forwarded:
        return forwarded

    return peer or "unknown"


class SlidingWindow:
    """Per-key sliding window counter.

    Sliding rather than a fixed bucket: a bucket that resets on the minute
    lets a caller spend its whole allowance at 59s and again at 61s, which is
    twice the limit through the moment that matters most.
    """

    def __init__(self, limit: int, window_seconds: float,
                 max_keys: int = 10_000, now=time.monotonic):
        self.limit = limit
        self.window = window_seconds
        self.max_keys = max_keys
        self._now = now
        self._hits: dict[str, deque] = {}

    def allow(self, key: str) -> bool:
        """True if this hit is within budget. Records it when it is."""
        now = self._now()
        hits = self._hits.get(key)
        if hits is None:
            if len(self._hits) >= self.max_keys:
                self._prune(now)
            hits = self._hits.setdefault(key, deque())

        cutoff = now - self.window
        while hits and hits[0] <= cutoff:
            hits.popleft()

        if len(hits) >= self.limit:
            return False

        hits.append(now)
        return True

    def _prune(self, now: float) -> None:
        """Drop keys with nothing left inside the window.

        Keys arrive from the internet, so an attacker picking a fresh key per
        request would otherwise grow this dict until the box runs out of
        memory. Staleness is the eviction rule, not arrival order: evicting
        the oldest-seen key would throw out an active caller and keep an idle
        one.
        """
        cutoff = now - self.window
        for key in [k for k, v in self._hits.items() if not v or v[-1] <= cutoff]:
            del self._hits[key]

        if len(self._hits) >= self.max_keys:
            # Everything is live and we are still over. Drop the least
            # recently active half rather than refuse service outright.
            ordered = sorted(self._hits.items(), key=lambda kv: kv[1][-1])
            for key, _ in ordered[: max(1, len(ordered) // 2)]:
                del self._hits[key]
            log.warning("rate limit: evicted live keys, %d remain", len(self._hits))
