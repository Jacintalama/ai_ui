"""What a built app is actually called.

The App Builder list showed each project as its slug:
create-me-a-keyboard-landing-de7b, aircon-page-5564,
build-a-website-and-make-3104. A slug is the URL segment, made by lowercasing
the prompt and appending four hex characters for uniqueness. It is not a name,
and a page of them reads like a directory listing rather than a list of
projects.

The agent has been naming these properly all along. Those three call themselves
Klakk, CoolStream HVAC and Lumen, in their own index.html <title>. Nothing read
it. The README heading is not an alternative: the docs sweep generates it FROM
the slug, so it says "Create Me A Keyboard Landing De7b - Landing Page".

Pure functions only, so the parsing is testable without a filesystem. The route
layer reads the file and does the caching.
"""
import html as _html
import re

#: Longest name put on a card. Titles are agent-written into a file the user
#: can also edit, so the length is bounded here rather than trusted.
MAX_NAME = 60
MAX_TAGLINE = 120

#: Only the first 8KB of the document is scanned. <title> lives in <head>, and
#: some of these apps inline an entire stylesheet.
SCAN_BYTES = 8192

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)

#: A name and a tagline joined by a dash or a pipe. The dash forms must be
#: SPACED: "Well-Being Co" and "E-Commerce Starter" are single names, and
#: splitting them on their own hyphen produces "Well" and "E".
_SPLIT_RE = re.compile(r"\s+[—–|]\s+|\s+[-]\s+|[—–]")


def _clean(text: str, limit: int) -> str:
    text = _html.unescape(text or "")
    # Angle brackets cannot reach the page: this string is rendered into the
    # App Builder list, and it comes out of a file rather than out of code.
    text = re.sub(r"<[^>]*>", "", text)
    text = text.replace("<", "").replace(">", "")
    return " ".join(text.split())[:limit].strip()


def split_title(title: str) -> tuple:
    """('Klakk', 'Mechanical keyboards that sound like home').

    A page title is usually the product name, a separator, then a line of
    positioning. The name is what belongs in a card heading; the tagline is
    worth keeping but not worth the heading.
    """
    cleaned = _clean(title, MAX_NAME + MAX_TAGLINE + 8)
    if not cleaned:
        return "", ""
    parts = _SPLIT_RE.split(cleaned, maxsplit=1)
    name = parts[0].strip()[:MAX_NAME]
    tagline = (parts[1].strip()[:MAX_TAGLINE] if len(parts) > 1 else "")
    return name, tagline


def title_from_html(markup) -> str:
    """The document's <title>, or "". Never raises: this reads a file written
    by an agent, and a card must render whatever it finds there."""
    if not markup:
        return ""
    if isinstance(markup, bytes):
        try:
            markup = markup.decode("utf-8", errors="replace")
        except Exception:
            return ""
    if not isinstance(markup, str):
        return ""
    m = _TITLE_RE.search(markup[:SCAN_BYTES])
    return m.group(1) if m else ""


def readable_slug(slug: str) -> str:
    """"aircon-page-5564" -> "Aircon Page". The last resort, used when an app
    has no title of its own. Still better than the slug: the four-hex suffix
    the builder appends for uniqueness means nothing to a reader."""
    parts = [p for p in re.split(r"[-_]+", (slug or "").strip()) if p]
    # Drop a trailing uniqueness suffix (4 or 8 hex characters), but never the
    # only word: "de7b" alone has to render as something.
    if len(parts) > 1 and re.fullmatch(r"[0-9a-f]{4}|[0-9a-f]{8}", parts[-1]):
        parts = parts[:-1]
    if not parts:
        return slug or "Untitled"
    return " ".join(w[:1].upper() + w[1:] for w in parts)[:MAX_NAME]


def display_name(slug: str, html: str = "") -> dict:
    """What the card shows: {name, tagline, source}.

    `source` is reported so the UI can tell a real name from a fallback, and so
    a sweep can find apps that never named themselves.
    """
    name, tagline = split_title(title_from_html(html))
    if name:
        return {"name": name, "tagline": tagline, "source": "title"}
    return {"name": readable_slug(slug), "tagline": "", "source": "slug"}
