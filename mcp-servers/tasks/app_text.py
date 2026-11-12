"""Change the words on an app's page, without an agent and without a build.

Pointing at a part of the page and asking for a change runs an agent,
which is a build: minutes, a commit, a reload. That is the right price for
"make the hero more dramatic" and the wrong one for fixing a typo in a
rating (2026-11-12, Ralph: "user can manualy change the words... since its
only edit... its not that soo long").

So the pencil has two ways out now, and this is the fast one: an exact
text swap in the app's own files. The precedent is `app_theme`, which has
written files directly since 2026-11-05 and is not a build either. The
route commits afterwards the same way, so the version history and the
rollback still see it.

Everything here is pure except `swap`, which is the only function that
touches a disk, and it changes nothing at all unless exactly one match was
found first.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Tuple

__all__ = ["problem", "swap", "files", "MAX_LEN", "MARKUP"]

_SLUG_RE = re.compile(r"\A[a-z0-9][a-z0-9-]{0,80}\Z")

#: The three characters that are the difference between words and markup.
#:
#: The new words land in an HTML file, so a box that can write these is a
#: box that can write a <script> into somebody's page. They are refused in
#: the OLD words too, because those arrive from the page's own
#: `textContent`, where an `&` is the file's `&amp;`: refusing with a
#: sentence that says so beats "I could not find those words", which reads
#: as a bug in the search.
MARKUP = ("<", ">", "&")

#: Longer than this and it is a section, not a label, and a section is
#: what the agent is for. Also the ceiling on how much of a page one
#: unreviewed swap can rewrite.
MAX_LEN = 500

#: What an app is actually made of. A lockfile and a build output are not
#: pages, and a match in one of them is a false positive that would block
#: a swap that should have gone through.
_TEXT_SUFFIXES = (".html", ".htm", ".js", ".jsx", ".ts", ".tsx", ".css",
                  ".md", ".txt", ".svelte", ".vue", ".astro")
_SKIP_DIRS = {"node_modules", ".git", "dist", "build", ".next", "__pycache__"}
#: No page is this big. Anything that is, is generated.
_MAX_FILE_BYTES = 2 * 1024 * 1024

_ASK = (" Ask for the change instead and the agent will do it.")


def _apps_root() -> str:
    return os.environ.get(
        "APPS_ROOT",
        os.path.join(
            os.environ.get("CLAUDE_WORKSPACE", "/workspace/ai_ui"), "apps"),
    )


def _app_dir(slug: str) -> Path:
    """The slug is re-checked here because this is the function that turns
    a string into a filesystem path, and a caller that forgets is a path
    traversal."""
    if not _SLUG_RE.match(str(slug or "")):
        raise ValueError("that is not an app name")
    return Path(_apps_root()) / slug


def problem(old: str, new: str) -> str:
    """The sentence refusing this swap, or "" when it is allowed.

    Pure, and separate from `swap`, so the reason a change is refused can
    be shown before anything is read off a disk.
    """
    old = str(old or "")
    new = str(new or "")

    if not old.strip():
        return "Point at some words first."
    if not new.strip():
        return ("The new words cannot be empty. Removing something is a "
                "change to the page, not to its words." + _ASK)
    if "\n" in old or "\n" in new:
        return ("A change like that spans more than one line." + _ASK)
    if len(old) > MAX_LEN or len(new) > MAX_LEN:
        return ("That is too much text to change this way." + _ASK)
    for ch in MARKUP:
        if ch in new or ch in old:
            return ("Words with " + " or ".join(MARKUP) + " in them mean "
                    "something to a page, so they are not changed this "
                    "way." + _ASK)
    return ""


def files(slug: str) -> List[Path]:
    """Every file this app is made of, in a stable order."""
    root = _app_dir(slug)
    found: List[Path] = []
    for here, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in _SKIP_DIRS)
        for name in sorted(names):
            path = Path(here) / name
            if path.suffix.lower() not in _TEXT_SUFFIXES:
                continue
            try:
                if path.stat().st_size > _MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            found.append(path)
    return found


def _loose(old: str) -> re.Pattern:
    """`old` with every run of whitespace allowed to be any whitespace.

    `textContent` hands back one run of text. The FILE can hold it wrapped
    and indented, which is what a formatter does to a long line, so a
    literal search answers "I could not find those words" about words the
    person is looking straight at.
    """
    parts = [re.escape(p) for p in old.split()]
    return re.compile(r"\s+".join(parts))


def _hits(slug: str, old: str) -> Tuple[List[Tuple[Path, str, list]], bool]:
    """Every file holding `old`, the file's text, and where the matches are.

    Literal first. Only if NOTHING matches literally is the whitespace
    loosened, so an exact match is never beaten by a loose one somewhere
    else in the app.
    """
    read: List[Tuple[Path, str]] = []
    for path in files(slug):
        try:
            read.append((path, path.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError):
            continue

    exact = [(p, t, [m.span() for m in re.finditer(re.escape(old), t)])
             for p, t in read]
    exact = [e for e in exact if e[2]]
    if exact:
        return exact, False

    pattern = _loose(old)
    loose = [(p, t, [m.span() for m in pattern.finditer(t)]) for p, t in read]
    return [l for l in loose if l[2]], True


def swap(slug: str, old: str, new: str) -> str:
    """Replace `old` with `new` in this app, and say which file changed.

    Raises ValueError, with a sentence meant to be read by the person who
    asked, when the swap is refused or the words are not findable exactly
    once. NOTHING is written in that case: the count is taken across every
    file before any of them is opened for writing.
    """
    said = problem(old, new)
    if said:
        raise ValueError(said)

    root = _app_dir(slug)
    if not root.is_dir():
        raise ValueError("I could not find that app.")

    hits, was_loose = _hits(slug, old)
    total = sum(len(spans) for _, _, spans in hits)

    if total == 0:
        raise ValueError("I could not find those exact words in the page."
                         + _ASK)
    if total > 1:
        raise ValueError("Those words appear " + str(total) + " times, so I "
                         "cannot tell which one you meant." + _ASK)

    path, text, spans = hits[0]
    start, end = spans[0]
    path.write_text(text[:start] + new + text[end:], encoding="utf-8")
    return str(path.relative_to(root)).replace(os.sep, "/")
