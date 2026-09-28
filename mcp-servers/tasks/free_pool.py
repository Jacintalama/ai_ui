"""Whether the free models this platform is configured with still exist.

The router already copes with a withdrawn id: `agent_runner._fallback_pool`
filters the configured pool against OpenRouter's live catalogue, so a model
that has been taken down is skipped rather than dialled. That is the right
behaviour and it is why nothing ever errored.

It is also why nothing ever said anything. Measured on production 2026-09-28,
AGENT_FREE_MODELS named three ids and OpenRouter served one:

    nvidia/nemotron-3-super-120b-a12b:free   served
    nex-agi/nex-n2.5-pro:free                withdrawn (26 real runs in the
                                             fortnight before)
    nex-agi/nex-n2.5-mini:free               withdrawn

The surviving id is the one most agents already run on, and `_fallback_pool`
excludes an agent's own base model. So the pool an agent could actually fall
back to was EMPTY, and the first time a provider hiccupped the person was
told "The free models are all busy right now" without a second model ever
having been tried. A fallback chain that has silently become a single point
of failure looks exactly like one that is working.

This module is the part that says so. It decides nothing at runtime and
changes no behaviour; it reports, so a stale pool is something somebody
finds out rather than something a user discovers.
"""
from __future__ import annotations

import agent_runner

#: Read from agent_runner rather than the environment, so this reports on the
#: pool the router will actually use rather than on a second reading of the
#: same variable that could drift from it.
CONFIGURED = agent_runner.FREE_MODELS

#: Below this, the pool cannot do its job. Two is the real floor: an agent's
#: own base model is excluded from its fallbacks, so a pool of one leaves
#: whoever runs on that one id with nowhere to go.
MINIMUM = 2


def stale(configured, available) -> list[str]:
    """Configured ids the catalogue does not serve, in the configured order.

    `available` None means the catalogue could not be read. That reports
    nothing rather than everything: calling every id dead because OpenRouter
    was unreachable would turn a network blip into a page at 3am, and it is
    the same call `_available_free_ids` already makes when it decides not to
    filter.
    """
    if not available:
        return []
    return [m for m in configured if m not in available]


def usable(configured, available) -> list[str]:
    """What is left of the pool. An unreadable catalogue leaves it alone,
    which is what the router itself does."""
    if not available:
        return list(configured)
    return [m for m in configured if m in available]


def report(available) -> dict:
    """What is configured, what is gone, and whether that is still a pool.

    `ok` is None, not False, when the catalogue could not be read. Neither
    healthy nor broken: unknown. Saying ok would hide a real failure and
    saying broken would invent one.
    """
    gone = stale(CONFIGURED, available)
    keep = usable(CONFIGURED, available)
    ok = None if not available else len(keep) >= MINIMUM
    return {"configured": list(CONFIGURED), "stale": gone, "usable": keep,
            "ok": ok, "summary": _summary(gone, keep, ok)}


def _summary(gone, keep, ok) -> str:
    """One sentence naming the ids and the variable somebody has to edit."""
    if ok is None:
        return ("Could not read OpenRouter's catalogue, so the free pool was "
                "not checked.")
    if ok:
        return "%d free models configured and all of them are served." % len(keep)
    if gone:
        return ("OpenRouter no longer serves %s. Set AGENT_FREE_MODELS to ids "
                "it does serve: %d left, and an agent cannot fall back to the "
                "model it already runs on." % (", ".join(gone), len(keep)))
    return ("AGENT_FREE_MODELS names %d model(s). An agent cannot fall back to "
            "the model it already runs on, so a pool this small leaves it "
            "nowhere to go." % len(keep))


async def check() -> dict:
    """The report against the live catalogue.

    Reuses agent_runner's reader so this sees the same cached answer the
    router does, rather than spending a second request to possibly disagree
    with it.
    """
    return report(await agent_runner._available_free_ids())
