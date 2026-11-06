"""A simple site, built by one model call instead of an agent.

The App Builder spawns a Claude Code CLI subprocess for every build. It
peaks at ~900MB inside a 1GB container, which is why only one person
could build at a time: a second was refused with a 429, and two at once
would OOM the service that runs the whole platform.

Measured 2026-11-05: of 51 apps in this repo, 50 are static sites with
no database. So the platform was paying ~900MB and a global lock to
produce, nearly every time, a landing page.

This module is that landing page without the subprocess. One call to a
model, one HTML file, tens of megabytes. Several can run at once.

Everything here is pure except `write_site`. The decisions, the prompt
and the checking are all testable without a model, a subprocess or a
filesystem.

Design: docs/superpowers/specs/2026-11-05-light-build-lane-design.md
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import app_theme

__all__ = [
    "needs_the_agent", "lane_for", "lane_note", "LANE_LIGHT", "LANE_AGENT",
    "page_prompt", "html_from", "page_problem",
    "write_site", "readme_for",
]


# ---------------------------------------------------------------------------
# Which lane
# ---------------------------------------------------------------------------

#: What a request mentions when it needs something this lane cannot give
#: it. Each entry is (pattern, what to tell the person).
#:
#: The anti-goal this exists for: the light lane quietly taking a job it
#: cannot do, and somebody getting a worse app without being told. When
#: one of these matches, the build goes to the agent and the person is
#: told which lane they got and why.
#:
#: Matched on word boundaries, because "cart" inside "cartoon" and
#: "log in" inside "catalogue" would send plain sites down the slow lane
#: for nothing.
_NEEDS_A_BACKEND: tuple[tuple[str, str], ...] = (
    (r"log ?in|sign ?in|sign ?up|sign-up",
     "This needs people to log in, so it is being built by the full "
     "builder, which can set up accounts."),
    (r"account|profiles?\b|register\b",
     "This needs user accounts, so it is being built by the full "
     "builder."),
    (r"database|supabase|postgres|sql\b",
     "This needs a database, so it is being built by the full builder."),
    (r"save|saves|saving|stores?\b|storing|remember(s|ed)?\b|persist",
     "This needs to save what people enter, so it is being built by the "
     "full builder."),
    (r"cart\b|carts\b|checkout|payment|stripe",
     "This needs a shopping cart, so it is being built by the full "
     "builder."),
    (r"booking|bookings|reservation|appointments?\b",
     "This needs to take bookings, so it is being built by the full "
     "builder."),
    (r"comments?\b|reviews?\b|messages?\b|chat\b",
     "This needs to collect what visitors write, so it is being built "
     "by the full builder."),
    (r"dashboard|analytics|admin\b|crud\b",
     "This needs live data behind it, so it is being built by the full "
     "builder."),
    (r"todo|to-do|task list|inventory",
     "This needs to keep a list between visits, so it is being built by "
     "the full builder."),
)

_COMPILED = tuple((re.compile(r"\b(?:%s)\b" % pat, re.I), why)
                  for pat, why in _NEEDS_A_BACKEND)


def needs_the_agent(description: str) -> str | None:
    """Why this request cannot take the light lane, or None if it can.

    The string is shown to the person, so it is a sentence rather than a
    rule name.
    """
    text = str(description or "")
    for pattern, why in _COMPILED:
        if pattern.search(text):
            return why
    return None


#: Lane names. The same two strings `build_progress` derives from a step,
#: so a task on disk and a fresh decision agree on what to call it.
LANE_LIGHT = "light"
LANE_AGENT = "agent"

#: A template is several files by definition, so it cannot take a lane
#: that writes exactly one. Worth saying out loud because nothing in the
#: person's own words predicts it: they asked for a portfolio and would
#: otherwise be promised a minute and wait several.
_TEMPLATE_WHY = ("This starts from a template, so it is being built by the "
                 "full builder.")

_LIGHT_NOTE = ("This is a plain site, so it is being written straight away "
               "and should be ready in under a minute.")

#: What the slow lane buys, said where the slowness is admitted. It used
#: to be a fixed sentence in the chat tool, which promised every build a
#: smoke test and an automatic rollback: the light lane has neither, so
#: that sentence became untrue for most builds the day the lane shipped.
_SLOW = (" That takes a few minutes, and the app is smoke tested when it "
         "finishes and rolled back automatically if it breaks.")


def lane_for(description: str,
             template_key: str | None = None) -> tuple[str, str | None]:
    """Which lane this request takes, and why when it is not the light one.

    The ONE decider. The build and whatever tells the person about it both
    read this, because a sentence that disagrees with the lane actually
    used is worse than no sentence at all.

    `template_key` must already be normalised: `blank` and `custom` mean
    no template, and reading them as one here would send plain sites down
    the slow lane.
    """
    why = needs_the_agent(description)
    if why:
        # What the person actually asked for beats "you picked a template"
        # when both are true: it is the more useful of the two sentences.
        return LANE_AGENT, why
    if template_key:
        return LANE_AGENT, _TEMPLATE_WHY
    return LANE_LIGHT, None


def lane_note(lane: str, why: str | None = None) -> str:
    """One sentence for the person: which lane, and why if it is the slow one.

    Never empty, for any lane name, because this lands in a chat reply and
    an empty note renders as a blank line somebody has to interpret.
    """
    if str(lane or "") == LANE_LIGHT:
        return _LIGHT_NOTE
    return (why or _TEMPLATE_WHY) + _SLOW


# ---------------------------------------------------------------------------
# What the model is asked for
# ---------------------------------------------------------------------------

def _tokens_block() -> str:
    return "\n".join("      %s: %s;" % (t.name, t.default)
                     for t in app_theme.TOKENS)


_SYSTEM = """You write a complete, finished one page website as a single
HTML file. You write no explanation, no preamble and no code fence: your
whole answer is the file, starting with <!doctype html> and ending with
</html>.

THE FILE

  * ONE file, index.html. There is nowhere to put a second file, so
    every style and script is inline or from an allowed CDN. Never
    reference styles/main.css, src/main.js or any other local path: it
    would be a 404 on a page that looks fine to you.
  * Tailwind from https://cdn.tailwindcss.com for layout and spacing.
  * Alpine from https://unpkg.com only if the page actually needs
    behaviour, such as a mobile menu or an accordion. A page that only
    scrolls does not need it.
  * Those two hosts, plus https://cdn.jsdelivr.net, are the only places
    you may load anything from. No other script or stylesheet host.
  * No forms that submit anywhere, no logins, no databases. This page
    has no backend. A contact section shows an email address or a phone
    number instead of a form that goes nowhere.

THEME TOKENS (MANDATORY)

  <head> must contain a <style> declaring exactly these on :root, with
  values you choose to suit the design:

    <style>
      :root {
%(tokens)s
      }
    </style>

  Keep the NAMES exactly as written and change the values to fit. Then
  USE them: every colour, font and corner radius a visitor sees comes
  from a token. Declaring them and then writing bg-blue-600 or #1a1a1a
  in the markup leaves the page exactly as unstyleable as declaring
  nothing at all. Wire Tailwind to them with an inline config in <head>,
  after the Tailwind script:

    <script>
      tailwind.config = { theme: { extend: {
        colors: { primary: 'var(--site-primary)',
                  'on-primary': 'var(--site-on-primary)',
                  secondary: 'var(--site-secondary)',
                  site: 'var(--site-background)',
                  ink: 'var(--site-text)' },
        fontFamily: { sans: 'var(--site-font-body)',
                      display: 'var(--site-font-heading)' },
      } } };
    </script>

  Use the three scales in your inline CSS, for example
  font-size: calc(2.5rem * var(--site-heading-scale)) on a heading,
  padding: calc(4rem * var(--site-spacing-scale)) on a section, and
  border-radius: calc(.75rem * var(--site-radius-scale)) on a card.
  Apply --site-decoration-opacity to purely decorative flourishes.

THE CONTENT

  * Write the real words. Never "Lorem ipsum", never "Your headline
    here", never a bracketed placeholder. Invent plausible specifics:
    names, prices, opening hours, three or four real-sounding
    testimonials with names.
  * Images come from https://images.unsplash.com with a descriptive
    query, or are drawn with CSS. Never a broken file path.
  * It must look deliberate and finished: a hero that fills the screen,
    clear sections, generous spacing, a real footer. Responsive, and
    correct on a phone.
  * <title> and a meta description that name the business.
"""


def page_prompt(description: str, slug: str, app_name: str) -> list[dict]:
    """The messages that produce the page."""
    asked = str(description or "").strip()
    name = str(app_name or "").strip() or str(slug or "").strip()
    return [
        {"role": "system", "content": _SYSTEM % {"tokens": _tokens_block()}},
        {"role": "user", "content":
            "Build this one page website.\n\n"
            "WHAT THEY ASKED FOR: %s\n\n"
            "THE SITE'S NAME: %s\n"
            "ITS FOLDER: %s\n\n"
            "Answer with the file and nothing else."
            % (asked, name, str(slug or "").strip())},
    ]


# ---------------------------------------------------------------------------
# Reading the answer
# ---------------------------------------------------------------------------

_FENCE = re.compile(r"^\s*```[a-zA-Z]*\s*\n(.*?)\n?\s*```\s*$", re.DOTALL)


def html_from(answer: str) -> str:
    """The page out of whatever the model actually sent back.

    Models wrap code in fences and add a sentence either side even when
    told not to. An answer with no page in it comes back empty rather
    than guessed at, so the caller can fail honestly.
    """
    text = str(answer or "").strip()
    if not text:
        return ""
    fenced = _FENCE.match(text)
    if fenced:
        text = fenced.group(1).strip()

    low = text.lower()
    start = low.find("<!doctype")
    if start < 0:
        start = low.find("<html")
    end = low.rfind("</html>")
    if start < 0 or end < 0:
        return ""
    return text[start:end + len("</html>")].strip()


# ---------------------------------------------------------------------------
# Is it a finished page
# ---------------------------------------------------------------------------

#: The only hosts a built page may load anything from. The page is
#: served from our own domain to this person's visitors, so a script tag
#: the model invented pointing anywhere else is somebody else's code
#: running under our name.
_ALLOWED_HOSTS = (
    "cdn.tailwindcss.com",
    "unpkg.com",
    "cdn.jsdelivr.net",
    "fonts.googleapis.com",
    "fonts.gstatic.com",
    "images.unsplash.com",
)

_SRC = re.compile(r"""(?:src|href)\s*=\s*["']([^"']+)["']""", re.I)
_MAX_PAGE = 400_000


def page_problem(html: str) -> str | None:
    """Why this is not a finished page, or None if it is."""
    text = str(html or "")
    if not text.strip():
        return "The model sent back no page at all"
    if len(text) > _MAX_PAGE:
        return "The page is too large to publish"

    low = text.lower()
    if "<!doctype" not in low:
        return "The page has no doctype, so it is not a complete file"
    if not low.rstrip().endswith("</html>"):
        return "The page stops partway through, so it was cut off"
    if "<title" not in low:
        return "The page has no title"

    missing = app_theme.missing(text)
    if missing:
        return ("The page does not declare %s, so its appearance could "
                "not be changed afterwards" % missing[0])

    for ref in _SRC.findall(text):
        value = ref.strip()
        if (not value or value.startswith("#") or value.startswith("data:")
                or value.startswith("mailto:") or value.startswith("tel:")):
            continue
        if value.startswith("//"):
            value = "https:" + value
        if value.startswith("http://") or value.startswith("https://"):
            host = value.split("//", 1)[1].split("/", 1)[0].split(":")[0]
            if not any(host == ok or host.endswith("." + ok)
                       for ok in _ALLOWED_HOSTS):
                return ("The page loads something from %s, which is not a "
                        "place we load code from" % host)
            continue
        # Anything else is a path beside the file, and this lane writes
        # exactly one file, so it would be a 404 on a page that looked
        # fine to the model that wrote it.
        return ("The page asks for %s next to it, but a simple site is "
                "one file" % value)
    return None


# ---------------------------------------------------------------------------
# Writing it out
# ---------------------------------------------------------------------------

def readme_for(slug: str, app_name: str, description: str) -> str:
    return (
        "# %s\n\n"
        "%s\n\n"
        "## What this is\n\n"
        "A one page site, built from this request:\n\n"
        "> %s\n\n"
        "## How it is put together\n\n"
        "Everything is in `index.html`: there is no build step and "
        "nothing to install. Tailwind and, where the page needs it, "
        "Alpine are loaded from a CDN.\n\n"
        "## Changing how it looks\n\n"
        "The palette, fonts and spacing are CSS variables on `:root` at "
        "the top of the file, named `--site-*`. Changing one changes the "
        "whole page, and the appearance panel in the chat writes exactly "
        "these.\n"
        % (str(app_name or slug).strip(), str(description or "").strip(),
           str(description or "").strip())
    )


def _apps_root() -> str:
    return os.environ.get(
        "APPS_ROOT",
        os.path.join(
            os.environ.get("CLAUDE_WORKSPACE", "/workspace/ai_ui"), "apps"),
    )


_SLUG_RE = re.compile(r"\A[a-z0-9][a-z0-9-]{0,80}\Z")


def write_site(slug: str, html: str, readme: str) -> Path:
    """Write the page and its README under apps/<slug>/.

    The slug is re-checked here because this is the function that turns a
    string into a filesystem path.
    """
    if not _SLUG_RE.match(str(slug or "")):
        raise ValueError("that is not an app name")
    problem = page_problem(html)
    if problem:
        raise ValueError(problem)

    folder = Path(_apps_root()) / slug
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "index.html").write_text(html, encoding="utf-8")
    (folder / "README.md").write_text(readme, encoding="utf-8")
    return folder
