"""Post-execution commit sweep for built apps.

Why this exists: `claude_executor.py:174-183` TELLS the build agent to run
`git add` + `git commit` after it changes files, and nothing verified that it
did. Measured on prod 2026-07-16: 43 of 47 app directories had zero commits, so
the version timeline + rollback feature (`routes_projects.list_app_versions_core`,
which reads `git log -- apps/<slug>/`) returned an empty list for 91% of apps.

This module makes the commit a step instead of a request. See
`docs/superpowers/specs/2026-07-16-app-history-commit-sweep-design.md`.
"""
import logging

from routes_projects import (
    _run_git as _run_git_default,
    _validate_slug as _validate_slug_default,
)

logger = logging.getLogger(__name__)

# Module-level seams so tests can drive this without a real git tree, matching
# the `_smoke_app` seam in routes_execution.
_run_git = _run_git_default
_validate_slug = _validate_slug_default


# Git's conventional subject cap. The version timeline renders this string
# straight into the UI, and the agent's completion payload is routinely a whole
# paragraph on a single line (observed live 2026-07-16 at 405 chars).
_MAX_SUBJECT = 72


def _safe_message(message: str | None, slug: str) -> str:
    """First line of the task summary, guaranteed non-empty, guaranteed not to
    be mistaken for a rollback entry, and short enough to read in a timeline."""
    lines = [ln for ln in (message or "").strip().splitlines() if ln.strip()]
    msg = lines[0].strip() if lines else ""
    if not msg:
        msg = f"Update apps/{slug}/"
    if msg.startswith("Rollback"):
        # list_app_versions_core marks a version as a rollback purely by this
        # prefix, so a real build summary starting with "Rollback" would
        # mislabel a genuine build in the timeline.
        msg = f"Build: {msg}"
    if len(msg) > _MAX_SUBJECT:
        msg = msg[:_MAX_SUBJECT - 3].rstrip() + "..."
    return msg


async def sweep_app_commit(
    slug: str,
    *,
    message: str | None,
    actor_email: str | None,
) -> str | None:
    """Commit any uncommitted work under apps/<slug>/, returning the new SHA.

    Returns None when there was nothing to do (the agent already committed) or
    when anything went wrong.

    Fails open by design, matching `_run_autofix`: this runs after a build has
    already reached "completed", so no failure here may flip that build to
    failed. The worst case is the app keeps the history it would have had
    anyway.

    Only ever touches `apps/<slug>/`. The same working tree holds IO's own
    platform code and the VPS's own drift, so both the `add` and the `commit`
    are pathspec-scoped. Never `git add -A`, never `git add .`.
    """
    try:
        _validate_slug(slug)
    except Exception:
        logger.warning("commit sweep: refusing invalid slug %r", slug)
        return None

    path = f"apps/{slug}/"
    try:
        rc, out = await _run_git("status", "--porcelain", "--", path)
        if rc != 0:
            logger.warning("commit sweep: status failed for %s: %s", path, out[:200])
            return None
        if not out.strip():
            # The agent committed its own work, which is the intended path.
            return None

        rc, out = await _run_git("add", "--", path)
        if rc != 0:
            logger.warning("commit sweep: add failed for %s: %s", path, out[:200])
            return None

        ident = _identity_args(actor_email)
        rc, out = await _run_git(
            *ident, "commit", "-m", _safe_message(message, slug), "--", path,
        )
        if rc != 0:
            logger.warning("commit sweep: commit failed for %s: %s", path, out[:200])
            return None

        rc, out = await _run_git("rev-parse", "HEAD")
        if rc != 0:
            return None
        sha = out.strip()
        logger.info("commit sweep: committed %s as %s", path, sha[:7])
        return sha
    except Exception as exc:
        logger.warning("commit sweep failed for slug=%s: %s", slug, exc)
        return None


def _identity_args(actor_email: str | None) -> list[str]:
    """`-c user.email=... -c user.name=...`, matching rollback_app_core so the
    timeline's actor_email resolves the same way for both."""
    email = (actor_email or "").strip()
    if not email:
        # No assignee: fall back to the repo's default identity. Losing the
        # commit is the failure this module exists to prevent, so an
        # unattributed commit beats no commit.
        return []
    return ["-c", f"user.email={email}", "-c", f"user.name={email.split('@')[0]}"]
