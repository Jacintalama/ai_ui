"""Enhance regression guard: put the app back when an edit breaks what worked.

AutoFix (`routes_execution._run_autofix`) asks "does the app load now?". It
never asks "does it still do what it did before?", so an enhance that trades a
working feature for a broken one ships. Cascade regressions are the top
unsolved failure mode across prompt-to-app builders.

This module adds the missing comparison. Smoke the app BEFORE the agent runs
and remember the git SHA; after AutoFix and the commit sweep, compare. A clean
app that came out broken is reverted to the remembered SHA.

Deliberately narrow so it can only ever help:
  - enhances only (a fresh build has no prior state to regress from)
  - only clean -> broken (never revert an app that was already failing: the
    enhance may well be the fix)
  - skipped when the app has no prior commit (nothing to restore)
  - fails open, like AutoFix and the commit sweep

Runs AFTER the commit sweep on purpose, so the broken attempt is a real commit
and the revert is a second commit on top of it. Nothing is destroyed, the
history reads honestly, and someone can go forward and repair it by hand.

Enabling dependency: this needs version history, which 43 of 47 prod apps did
not have until the 2026-07-16 commit sweep.

See docs/superpowers/specs/2026-07-17-enhance-regression-guard-design.md
"""
import logging
from dataclasses import dataclass

from app_smoke import smoke_app as _smoke_app_default
from routes_projects import (
    _run_git as _run_git_default,
    rollback_app_core as _rollback_default,
)

logger = logging.getLogger(__name__)

# Module-level seams so tests drive this without a browser, git or an LLM,
# matching the `_smoke_app` seam in routes_execution.
_smoke_app = _smoke_app_default
_run_git = _run_git_default
_rollback = _rollback_default


@dataclass(frozen=True)
class Baseline:
    """What the app looked like before the agent touched it."""
    was_clean: bool
    sha: str


async def capture_baseline(slug: str) -> Baseline | None:
    """Smoke the app and remember the current SHA, before an enhance runs.

    Returns None when the guard cannot arm itself: no prior commit to restore,
    or anything went wrong. None disables the guard for this run.
    """
    try:
        rc, out = await _run_git("log", "--max-count=1", "--format=%H",
                                 "--", f"apps/{slug}/")
        if rc != 0 or not out.strip():
            # No history for this app, so there is nothing to roll back to.
            return None

        rc, head = await _run_git("rev-parse", "HEAD")
        if rc != 0 or not head.strip():
            return None

        report = await _smoke_app(slug)
        return Baseline(was_clean=report is None, sha=head.strip())
    except Exception as exc:
        logger.warning("regression guard: baseline failed for %s: %s", slug, exc)
        return None


def is_regression(baseline: Baseline | None, report: str | None) -> bool:
    """True only when a working app came out broken."""
    if baseline is None or not baseline.was_clean:
        return False
    return bool(report)


def compose_result(
    summary: str,
    *,
    smoke_report: str | None,
    revert_message: str | None,
) -> str:
    """The task result the user reads.

    A revert REPLACES the agent's summary rather than appending to it: the
    summary describes changes that are no longer in the app, so leading with
    "Added a dark mode toggle" would misdescribe the app's actual state.
    """
    if revert_message:
        return revert_message
    if smoke_report:
        return (
            f"{summary}\n\nAutoFix could not resolve these load errors:\n{smoke_report}"
        )
    return summary


async def revert_regression(
    slug: str,
    baseline: Baseline,
    report: str,
    *,
    actor_email: str,
) -> str | None:
    """Restore the app to the baseline SHA and return the user-facing message.

    Returns None when nothing was actually reverted (rollback failed, or was a
    no-op), so the caller never claims a revert that did not happen.
    """
    try:
        result = await _rollback(slug, baseline.sha, actor_email)
    except Exception as exc:
        # A failed revert leaves the app exactly where the enhance left it,
        # which is where it would have been without this guard at all.
        logger.warning("regression guard: revert failed for %s: %s", slug, exc)
        return None

    if isinstance(result, dict) and result.get("noop"):
        return None

    logger.info("regression guard: reverted %s to %s", slug, baseline.sha[:7])
    return (
        "Reverted: this change broke the app, so I put it back the way it was.\n\n"
        f"What broke:\n{report}\n\n"
        "Your attempt is saved in version history if you want to look at it."
    )
