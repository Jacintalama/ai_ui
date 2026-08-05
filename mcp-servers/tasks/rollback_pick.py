"""Turn a plain sentence into ONE specific version to roll back to.

Origin: Lukas, standup 2026-08-03 — "if I just tell the LLM go back to the
working part where we didn't start doing this feature that broke it, the LLM
usually knows where to go back to and does it."

Pure by design. No git, no database, no model, no network: the caller passes the
already-fetched version list and gets a decision back. Rollback MUTATES the
user's app, and a prompt is not a guarantee (see
docs/superpowers/specs/2026-07-30-app-user-roles-design.md, and the git-commit
bug that silently broke history for 43 of 47 apps), so the decision lives in
rules that can be tested exhaustively rather than in an LLM's judgement.

That costs nothing in capability. A model would see exactly what these rules see
— commit messages, dates and statuses — because nothing here can inspect what
the app actually looked like. Its only genuine edge is paraphrase, so the caller
may use a model to RANK the candidates this module returns, never to invent one.

The invariant everything rests on: a returned target is always an element of the
list passed in.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

Version = dict[str, Any]

_MAX_CANDIDATES = 8

# A word the user says to mean "the run that failed" rather than naming a feature.
_BROKE_WORDS = ("broke", "broken", "break", "error", "failed", "failing",
                "worked", "working", "last good")
_UNDO_WORDS = ("undo", "one step back", "go back one", "previous version",
               "step back", "last version")

# Words carried by the phrasing itself, never by a feature name. Stripping these
# stops "before the cart" from matching a commit merely because both contain
# "the".
_STOPWORDS = frozenset({
    "go", "back", "to", "before", "the", "a", "an", "we", "us", "it", "that",
    "this", "when", "where", "was", "is", "were", "started", "start", "doing",
    "feature", "version", "revert", "restore", "roll", "rollback", "take",
    "put", "make", "get", "please", "my", "our", "app", "site", "everything",
    "since", "undo", "all", "changes", "and", "of", "on", "in", "at", "for",
    "last", "first", "add", "adds", "added", "just", "again", "still", "into",
})


@dataclass(frozen=True)
class RollbackChoice:
    """What to do about a rollback request.

    Exactly one of these three shapes:
      - target set                      -> roll back here, `reason` says why
      - needs_user_choice, candidates   -> we could not decide; ask
      - neither                         -> nothing is possible; `reason` says so
    """
    target: Version | None = None
    reason: str = ""
    needs_user_choice: bool = False
    candidates: list[Version] = field(default_factory=list)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower())


def _keywords(phrase: str) -> list[str]:
    """The words in the phrase that could name a feature."""
    return [w for w in _norm(phrase).split() if w not in _STOPWORDS and len(w) > 2]


def _discriminating(words: list[str], versions: list[Version]) -> list[str]:
    """Drop words that appear in most messages, because they identify nothing.

    Real App Builder commits are conventional-commit style — every message for
    apps/portfolio/ starts `feat(portfolio):`. So "go back to before the
    portfolio" matched the NEWEST commit and produced a confident wrong answer.
    Found by running this picker over the real git history rather than the
    canned fixtures, which all used bare messages.

    Frequency is the general fix: it removes the app's own name without the
    picker needing to be told the slug, and it removes house words like "feat"
    or "fix" for free.
    """
    if not versions:
        return words
    limit = max(1, len(versions) // 2)
    msgs = [_norm(v.get("message", "")) for v in versions]
    keep = [w for w in words if sum(1 for m in msgs if w in m) <= limit]
    # If every word was too common the user still said something; better to ask
    # than to match on noise.
    return keep


def _best_match(versions: list[Version], words: list[str]) -> int:
    """Index of the version whose message matches the MOST keywords, -1 if none.

    Scored rather than first-hit: "profile photo" must land on "add profile
    photo to hero section" (2 words) rather than on the newer "move profile
    image to right side" (1 word). Ties go to the newer version, which is the
    one the user is more likely to be undoing.
    """
    best_i, best_score = -1, 0
    for i, ver in enumerate(versions):
        msg = _norm(ver.get("message", ""))
        score = sum(1 for w in words if w in msg)
        if score > best_score:
            best_i, best_score = i, score
    return best_i


def _rollbackish(ver: Version) -> bool:
    """Bookkeeping commits, not builds. Going 'before' one would walk the user
    backwards through their own undo history."""
    return (ver.get("status") == "rollback"
            or _norm(ver.get("message", "")).startswith("rollback"))


def _older_than(versions: list[Version], index: int) -> list[Version]:
    """Versions after `index` in the list. The list is newest-first, so a higher
    index is an older commit."""
    return versions[index + 1:]


def _first_good(versions: list[Version]) -> Version | None:
    for ver in versions:
        if ver.get("status") not in ("error",) and not _rollbackish(ver):
            return ver
    return None


def _selectable(versions: list[Version]) -> list[Version]:
    """Everything a user could sensibly be offered: not the current version
    (rolling back to where you already are is a no-op dressed as an action)."""
    return [v for v in versions if not v.get("is_current")]


def _ask(versions: list[Version], reason: str) -> RollbackChoice:
    return RollbackChoice(
        reason=reason,
        needs_user_choice=True,
        candidates=_selectable(versions)[:_MAX_CANDIDATES],
    )


def choose_rollback_target(versions: list[Version], phrase: str) -> RollbackChoice:
    """Pick the version `phrase` refers to.

    Rules are tried in order of how explicit the user was: a SHA they typed
    beats a feature they named, which beats the generic "it broke", which beats
    "undo". Anything unmatched asks rather than guessing — a wrong rollback is
    worse than a question.
    """
    if not versions:
        return RollbackChoice(
            reason="There are no saved versions for this app yet, "
                   "so there is nothing to go back to.")

    text = _norm(phrase)
    if not text.strip():
        return _ask(versions, "Which version should I go back to?")

    # 1. An explicit SHA. Only accepted if it belongs to THIS app's history —
    #    a real SHA from another app must not slip through.
    for token in re.findall(r"\b[0-9a-f]{7,40}\b", text):
        for ver in versions:
            if ver["sha"].startswith(token) or token.startswith(ver["short_sha"]):
                return RollbackChoice(
                    target=ver,
                    reason=f"the version you named ({ver['short_sha']})")
        return _ask(
            versions,
            f"I could not find a version {token[:7]} in this app's history.")

    # 2. A named feature: "before the cart". More specific than the error rule,
    #    so it wins even when something later failed.
    if "before" in text or "since" in text:
        words = _discriminating(_keywords(phrase), versions)
        if words:
            i = _best_match(versions, words)
            if i >= 0:
                ver = versions[i]
                older = _older_than(versions, i)
                if not older:
                    return RollbackChoice(
                        reason=f"'{ver['message']}' is the oldest version, "
                               "so there is nothing before it.")
                return RollbackChoice(
                    target=older[0],
                    reason=f"the version just before '{ver['message']}'")
            # The user named something specific that is not in the history.
            # Falling through to another rule would look like it worked.
            if not any(w in text for w in _BROKE_WORDS):
                return _ask(
                    versions,
                    "I could not find that in this app's history.")

    # 3. "before it broke" — deterministic, because list_app_versions_core
    #    already marks a version 'error' when its task failed.
    if any(w in text for w in _BROKE_WORDS):
        for i, ver in enumerate(versions):
            if ver.get("status") == "error":
                good = _first_good(_older_than(versions, i))
                if good is None:
                    return RollbackChoice(
                        reason=f"'{ver['message']}' failed, but there is no "
                               "working version before it to go back to.")
                return RollbackChoice(
                    target=good,
                    reason=f"'{ver['message']}' failed — this is the last "
                           "version that worked before it")
        return _ask(
            versions,
            "None of the saved versions are marked as failed, so I am not sure "
            "which one broke.")

    # 4. "undo" — one step back from where we are.
    if any(w in text for w in _UNDO_WORDS):
        older = _selectable(versions)
        if not older:
            return RollbackChoice(
                reason="There is only one version, so there is nothing to undo.")
        return RollbackChoice(target=older[0], reason="one step back")

    return _ask(versions, "Which version should I go back to?")
