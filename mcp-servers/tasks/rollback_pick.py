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
    # The failure vocabulary. These say WHICH RULE the user wants, never which
    # feature. Leaving them out was the worst bug in review: a history holding
    # "fix broken checkout" made "go back to before it broke" match on "broke",
    # fire the feature rule, and hand back the FAILED build itself.
    *(w for phrase in _BROKE_WORDS for w in phrase.split()),
    *(w for phrase in _UNDO_WORDS for w in phrase.split()),
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


def _words(text: str) -> set[str]:
    """Whole words, so 'cart' cannot match inside 'cartoon'."""
    return set(_norm(text).split())


def _keywords(phrase: str) -> list[str]:
    """The words in the phrase that could name a feature."""
    return [w for w in _norm(phrase).split() if w not in _STOPWORDS and len(w) > 2]


def _strip_slug(words: list[str], slug: str) -> list[str]:
    """Remove the app's own name. It identifies the app, never a feature.

    Real App Builder commits are conventional-commit style, so every message
    for apps/portfolio/ contains "portfolio". Without this, "go back to before
    the portfolio" matched a commit and confidently offered the wrong version.
    Exact beats statistical here: the caller knows the slug, so there is no
    reason to infer it from message frequency and get it wrong both ways.
    """
    junk = _words(slug.replace("-", " ").replace("_", " "))
    return [w for w in words if w not in junk]


def _discriminating(words: list[str], versions: list[Version]) -> list[str]:
    """Drop words that appear in nearly every message, because they identify
    nothing. Catches conventional-commit house words ("feat", "fix", "chore")
    when they dominate a history.

    This used to be the defence against the app's own name too, at a
    half-the-messages threshold. That was both too weak (a name in exactly half
    survived) and far too strong (on a 4-commit history it erased "profile",
    the actual keyword, and the picker then returned a version that still
    contained the profile image). The slug is now stripped exactly instead --
    see `_strip_slug` -- so this only has to catch the statistical case.
    """
    if len(versions) < 4:
        # Too few messages for frequency to mean anything. On a 3-commit
        # history "half of them" is one commit, and the filter erased the very
        # word the user was identifying (review finding).
        return words
    msgs = [_words(v.get("message", "")) for v in versions]
    limit = 0.8 * len(msgs)
    return [w for w in words if sum(1 for m in msgs if w in m) < limit]


def _introduced_at(versions: list[Version], words: list[str]) -> int:
    """Index of the version that INTRODUCED what the user named, -1 if none.

    Two properties, and getting only one of them was wrong both times:

    * SCORE first. The anchor must be a commit that matches the MOST of the
      user's words. Matching any single word let a generic one like "theme"
      drag the anchor to the oldest commit that happened to mention it, so
      "before the dark navy theme" stopped resolving at all.
    * Then OLDEST among those. "before the profile image" means before it
      EXISTED. Taking the newest mention returned a version that still
      contained it -- the opposite of the request.

    Both failures were found on the real apps/portfolio/ log, where the profile
    image is touched by six commits spanning the whole history. The list is
    newest-first, so the oldest match is the highest index.
    """
    scores = [sum(1 for w in words if w in _words(v.get("message", "")))
              for v in versions]
    best = max(scores, default=0)
    if best == 0:
        return -1
    # Oldest commit at the top score: the strongest statement of the topic.
    anchor = max(i for i, s in enumerate(scores) if s == best)
    # Then walk older through the contiguous run of commits that still touch
    # the topic at all. This is what makes a synonym work: "before the profile
    # image" scores highest on "move profile image", but "add profile photo"
    # sits directly under it and is where the thing actually arrived. The run
    # stops at the first unrelated commit, so a generic word cannot drag the
    # anchor to the bottom of the history.
    while anchor + 1 < len(versions) and scores[anchor + 1] > 0:
        anchor += 1
    return anchor


def _rollbackish(ver: Version) -> bool:
    """Bookkeeping commits, not builds. Going 'before' one would walk the user
    backwards through their own undo history."""
    return (ver.get("status") == "rollback"
            or _norm(ver.get("message", "")).startswith("rollback"))


def _explain(target: Version, versions: list[Version], reason: str) -> str:
    """Add what a rollback marker actually restored.

    "Roll back to 'Rollback apps/shop/ to 8736cd7'" tells the user nothing, and
    the confirm card's whole job is to let them check the reasoning. The state
    is genuinely correct -- a rollback commit is a real, distinct state of the
    app -- so the fix is the label, not the choice. Review flagged this.
    """
    if not _rollbackish(target):
        return reason
    m = re.search(r"\b([0-9a-f]{7,40})\b", target.get("message", ""))
    if m:
        for ver in versions:
            if ver["sha"].startswith(m.group(1)) or m.group(1).startswith(ver["short_sha"]):
                return (f"{reason} — that one is an earlier undo, which puts the "
                        f"app back to '{ver['message']}'")
    return f"{reason} — that one is an earlier undo"


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
    """Everything a user could sensibly be offered: not the current version,
    since rolling back to where you already are is a no-op dressed as an action.

    Deliberately does NOT trust `is_current`. That flag compares each commit to
    the WHOLE monorepo's HEAD (routes_projects.py, list_app_versions_core),
    while the list is `git log -- apps/<slug>/`. So for every app except the
    most recently committed one it is False on every row, and "undo" happily
    returned the app's current content. The list is newest-first by
    construction, so index 0 is the current state whatever the flag says.
    """
    return [v for i, v in enumerate(versions) if i > 0 and not v.get("is_current")]


def _ask(versions: list[Version], reason: str) -> RollbackChoice:
    """Hand the decision back. Only claims to be a question when there is
    something to answer it with -- an app whose only version is the current one
    has nothing to offer, and asking would be a dead end."""
    candidates = _selectable(versions)[:_MAX_CANDIDATES]
    if not candidates:
        return RollbackChoice(
            reason="There are no earlier versions of this app to go back to.")
    return RollbackChoice(
        reason=reason, needs_user_choice=True, candidates=candidates)


def choose_rollback_target(versions: list[Version], phrase: str,
                           slug: str = "") -> RollbackChoice:
    """Pick the version `phrase` refers to.

    `slug` is the app's name. Passing it lets the picker ignore the app's own
    name when the user says it -- real commit messages contain it in every line.

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
    # `\b[0-9a-f]{7,40}\b` also matches ordinary words ("defaced", "acceded")
    # and any run of 7+ digits. Review found that bailing on the FIRST such
    # token threw away a real sha later in the same sentence, so every token is
    # tried and only an all-miss is reported.
    hex_tokens = re.findall(r"\b[0-9a-f]{7,40}\b", text)
    for token in hex_tokens:
        for ver in versions:
            if ver["sha"].startswith(token) or token.startswith(ver["short_sha"]):
                return RollbackChoice(
                    target=ver,
                    reason=f"the version you named ({ver['short_sha']})")
    # Only complain when the user plainly meant a sha: a bare hex-looking word
    # in a sentence that also names a feature should fall through to the rules.
    if hex_tokens and not _discriminating(_strip_slug(_keywords(phrase), slug), versions):
        return _ask(
            versions,
            f"I could not find a version {hex_tokens[0][:7]} in this app's history.")

    # 2. A named feature: "before the cart". More specific than the error rule,
    #    so it wins even when something later failed.
    if "before" in text or "since" in text:
        raw_words = _strip_slug(_keywords(phrase), slug)
        words = _discriminating(raw_words, versions)
        if words:
            i = _introduced_at(versions, words)
            if i >= 0:
                ver = versions[i]
                older = _older_than(versions, i)
                if not older:
                    return RollbackChoice(
                        reason=f"'{ver['message']}' is the oldest version, "
                               "so there is nothing before it.")
                return RollbackChoice(
                    target=older[0],
                    reason=_explain(older[0], versions,
                                    f"the version just before '{ver['message']}'"))
            # The user named something specific that is not in the history.
            # Falling through to another rule would look like it worked.
            return _ask(versions, "I could not find that in this app's history.")
        if raw_words:
            # They named something, but every word of it is too common to
            # identify a version. Falling through to the failure rule would
            # answer a DIFFERENT question confidently, which review caught.
            return _ask(
                versions,
                "That could match most of the versions, so I am not sure "
                "which one you mean.")

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
