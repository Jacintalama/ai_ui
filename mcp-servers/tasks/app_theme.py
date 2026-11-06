"""The knobs an app has to declare before its appearance can be changed.

A panel that changes a site's colours and type instantly can only do it
by writing CSS variables the page already declares. It is the page that
makes this possible, not the panel, which is why this module is mostly
about what the builder is told to declare and what may safely be written
back into a stylesheet.

Everything here is pure. The token list is the single source: the builder
prompt is generated from it, the themeable check looks for exactly these
names, and the panel is served them rather than carrying its own copy.
Three copies of this list would be three places to change and two chances
to drift, which is the mistake the build steps already avoid.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "Token", "TOKENS", "names", "served", "prompt_block", "declared",
    "missing", "is_themeable", "value_problem", "rewrite", "upgrade_prompt",
]


@dataclass(frozen=True)
class Token:
    """One appearance knob.

    `kind` decides both the control the panel draws and the rule the value
    is checked against. `low`/`high` apply to scales only.
    """
    name: str
    kind: str
    label: str
    default: str
    low: float = 0.0
    high: float = 0.0


TOKENS: tuple[Token, ...] = (
    Token("--site-primary", "color", "Primary", "#2563eb"),
    Token("--site-on-primary", "color", "Text on primary", "#ffffff"),
    Token("--site-secondary", "color", "Accent", "#f59e0b"),
    Token("--site-background", "color", "Background", "#ffffff"),
    Token("--site-text", "color", "Text", "#111827"),
    Token("--site-font-body", "font", "Body font",
          "system-ui, -apple-system, sans-serif"),
    Token("--site-font-heading", "font", "Heading font",
          "system-ui, -apple-system, sans-serif"),
    Token("--site-heading-scale", "scale", "Heading size", "1", 0.75, 1.6),
    Token("--site-spacing-scale", "scale", "Spacing", "1", 0.5, 2.0),
    Token("--site-radius-scale", "scale", "Corner rounding", "1", 0.0, 3.0),
    Token("--site-decoration-opacity", "scale", "Decoration", "1", 0.0, 1.0),
)

_BY_NAME: dict[str, Token] = {t.name: t for t in TOKENS}


def names() -> tuple[str, ...]:
    return tuple(t.name for t in TOKENS)


def served() -> list[dict]:
    """What the panel needs to draw a control, and nothing more."""
    out = []
    for t in TOKENS:
        row = {"name": t.name, "kind": t.kind, "label": t.label,
               "default": t.default}
        if t.kind == "scale":
            row["low"] = t.low
            row["high"] = t.high
        out.append(row)
    return out


# --- what the builder is told --------------------------------------------

def prompt_block() -> str:
    """The section of the build prompt that makes an app themeable.

    Generated, never hand-written, so a token added above cannot be
    forgotten here. It asks for two things, because either alone is
    useless: the declaration, and actually USING the declaration. An app
    that declares the tokens and then writes `bg-blue-600` everywhere is
    exactly as unthemeable as one that declares nothing.
    """
    lines = [
        "THEME TOKENS (MANDATORY: the platform's appearance panel writes",
        "these, and an app that does not declare them cannot be restyled):",
        "",
        "  1. `styles/main.css` MUST OPEN with this exact :root block, with",
        "     values chosen to suit the app you are building:",
        "",
        "       :root {",
    ]
    for t in TOKENS:
        lines.append(f"         {t.name}: {t.default};")
    lines += [
        "       }",
        "",
        "     Keep the names exactly as written. Change the VALUES to fit the",
        "     design; those above are only a starting point.",
        "",
        "  2. Every colour, font and corner radius the visitor sees MUST come",
        "     from those tokens. Declaring them and then hardcoding",
        "     `bg-blue-600` or `#1a1a1a` in the markup leaves the app exactly",
        "     as unstyleable as declaring nothing at all. Wire Tailwind to",
        "     them with an inline config in <head>, AFTER the Tailwind CDN",
        "     script and BEFORE your stylesheet:",
        "",
        "       <script>",
        "         tailwind.config = { theme: { extend: {",
        "           colors: {",
        "             primary: 'var(--site-primary)',",
        "             'on-primary': 'var(--site-on-primary)',",
        "             secondary: 'var(--site-secondary)',",
        "             site: 'var(--site-background)',",
        "             ink: 'var(--site-text)',",
        "           },",
        "           fontFamily: {",
        "             sans: 'var(--site-font-body)',",
        "             display: 'var(--site-font-heading)',",
        "           },",
        "         } } };",
        "       </script>",
        "",
        "     Then use `bg-primary`, `text-ink`, `font-display` and so on.",
        "     For the three scales, use them in `styles/main.css`, e.g.",
        "     `h1 { font-size: calc(2.5rem * var(--site-heading-scale)); }`,",
        "     `section { padding: calc(4rem * var(--site-spacing-scale)); }`,",
        "     `.card { border-radius: calc(.75rem * var(--site-radius-scale)); }`",
        "     and apply --site-decoration-opacity to purely decorative",
        "     flourishes (background shapes, glows, dividers).",
        "",
        "  3. The app must look finished and deliberate at the values you",
        "     ship. The tokens are for changing it later, not an excuse to",
        "     leave it generic.",
    ]
    return "\n".join(lines)


def upgrade_prompt(slug: str) -> str:
    """The enhance that makes an app built before today themeable.

    Deliberately narrow. The point is that the app looks the same
    afterwards, with its existing palette lifted into tokens, so somebody
    can press this without gambling their site on a redesign.

    Takes the slug because WHERE the block goes depends on the app. This
    named `styles/main.css` for every app until 2026-11-06, so an upgrade
    on a one-file page would have created a stylesheet the page does not
    load: sliders that move nothing, which is the failure this offer
    exists to avoid.
    """
    one_file = token_file(slug).suffix.lower() in (".html", ".htm")
    if one_file:
        where = [
            "Read the app's existing colours, fonts and corner radii out of",
            "its markup. Lift those EXISTING values into a :root block inside",
            "the <style> block in index.html, which is this app's only file.",
            "DO NOT create a stylesheet: this page does not load one, so a",
            "stylesheet would change nothing. Use these exact names:",
        ]
    else:
        where = [
            "Read the app's existing colours, fonts and corner radii out of",
            "its markup and stylesheet. Lift those EXISTING values into a",
            ":root block at the top of styles/main.css using these exact",
            "names:",
        ]
    lines = [
        "Make this app's appearance changeable, WITHOUT changing how it",
        "currently looks.",
        "",
    ] + where + [
        "",
    ]
    for t in TOKENS:
        lines.append(f"  {t.name}")
    lines += [
        "",
        "Use the values the app already has. Where the app has no obvious",
        "equivalent for one of them, pick the value that reproduces its",
        "current look, and use 1 for the three scales.",
        "",
        "Then replace the hardcoded colours, fonts and radii throughout the",
        "markup with those tokens, wiring Tailwind to them with an inline",
        "tailwind.config in <head> if the app uses Tailwind.",
        "",
        "The finished app must render IDENTICALLY to how it renders now. Do",
        "not change the layout, the copy, the images or the design. This is a",
        "refactor of how the styling is expressed, nothing more.",
    ]
    return "\n".join(lines)


# --- what an app actually declares ---------------------------------------

_ROOT_RE = re.compile(r":root\s*\{(.*?)\}", re.DOTALL)
_DECL_RE = re.compile(r"(--site-[a-z0-9-]+)\s*:\s*([^;{}]*?)\s*(?:;|$)")


def _root_body(css: str) -> str | None:
    found = _ROOT_RE.search(css or "")
    return found.group(1) if found else None


def declared(css: str) -> dict[str, str]:
    """The site tokens this stylesheet declares on :root.

    Only :root. A variable on `.card` is that component's own business and
    is not a knob this panel owns; writing into it would mean writing into
    a rule we have not understood.
    """
    body = _root_body(css)
    if body is None:
        return {}
    out: dict[str, str] = {}
    for name, value in _DECL_RE.findall(body):
        if name in _BY_NAME and value.strip():
            out[name] = value.strip()
    return out


def missing(css: str) -> list[str]:
    have = declared(css)
    return [n for n in names() if n not in have]


def is_themeable(css: str) -> bool:
    return not missing(css)


# --- what may be written back --------------------------------------------

# A token value is written into a stylesheet, so a value that can close
# the declaration or the rule can add arbitrary CSS to the app. These
# patterns are allowlists for that reason, not merely for tidiness.
_HEX = re.compile(r"#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\Z")
_FUNC = re.compile(
    r"(?:rgb|rgba|hsl|hsla)\(\s*[0-9]+(?:\.[0-9]+)?%?"
    r"(?:\s*[, /]\s*[0-9]*\.?[0-9]+%?)*\s*\)\Z")
_FONT = re.compile(r"[A-Za-z0-9 ,'\"-]+\Z")
_NUMBER = re.compile(r"[0-9]+(?:\.[0-9]+)?\Z")

_MAX_COLOR = 64
_MAX_FONT = 160


def value_problem(name: str, value: str) -> str | None:
    """Why this value may not be written, or None if it may be.

    One function, used by both the route and the writer, so a route that
    forgets to call it cannot open a hole: `rewrite` calls it too.
    """
    tok = _BY_NAME.get(str(name or ""))
    if tok is None:
        return f"{name} is not one of the appearance settings"

    raw = str(value if value is not None else "")
    if not raw.strip():
        return f"{name} was given no value"
    text = raw.strip()

    if tok.kind == "color":
        if len(text) > _MAX_COLOR:
            return f"{name} is too long to be a colour"
        if _HEX.match(text) or _FUNC.match(text):
            return None
        return f"{name} is not a colour"

    if tok.kind == "font":
        if len(text) > _MAX_FONT:
            return f"{name} is too long to be a font"
        if _FONT.match(text):
            return None
        return f"{name} is not a plain font name list"

    if len(text) > 12 or not _NUMBER.match(text):
        return f"{name} is not a number"
    amount = float(text)
    if amount < tok.low or amount > tok.high:
        return f"{name} must be between {tok.low} and {tok.high}"
    return None


def rewrite(css: str, values: dict) -> str:
    """The stylesheet with these token values set, and nothing else moved.

    Raises ValueError on anything `value_problem` refuses, so there is no
    path to a written stylesheet that skipped the check.
    """
    if not values:
        raise ValueError("nothing to change")
    for name, value in values.items():
        problem = value_problem(name, value)
        if problem:
            raise ValueError(problem)

    clean = {str(k): str(v).strip() for k, v in values.items()}
    body = _root_body(css)
    if body is None:
        block = ":root {\n" + "".join(
            f"  {n}: {clean[n]};\n" for n in names() if n in clean) + "}\n\n"
        return block + (css or "")

    have = declared(css)
    new_body = body
    for name, value in clean.items():
        if name in have:
            # Replace this declaration's value only. Anchored on the name
            # so a value that happens to look like another token's cannot
            # be the thing that matches.
            new_body = re.sub(
                re.escape(name) + r"\s*:\s*[^;{}]*",
                name + ": " + value,
                new_body, count=1)
        else:
            stripped = new_body.rstrip()
            sep = "" if (not stripped or stripped.endswith(";")) else ";"
            new_body = stripped + sep + "\n  " + name + ": " + value + ";\n"

    found = _ROOT_RE.search(css)
    return css[:found.start(1)] + new_body + css[found.end(1):]


# --- the app's own stylesheet --------------------------------------------
#
# The only I/O in this module. It is here rather than in a route because
# two routes and the post-build check all need the same answer to "what
# does this app declare", and a second copy of the path logic is a second
# way to disagree about where an app lives.

import os
from pathlib import Path

_SLUG_RE = re.compile(r"\A[a-z0-9][a-z0-9-]{0,80}\Z")


def _apps_root() -> str:
    return os.environ.get(
        "APPS_ROOT",
        os.path.join(
            os.environ.get("CLAUDE_WORKSPACE", "/workspace/ai_ui"), "apps"),
    )


def css_path(slug: str) -> Path:
    """Where this app's stylesheet lives, if it has one.

    The slug is re-checked here even though callers check it, because this
    is the function that turns a string into a filesystem path and a
    caller that forgets is a path traversal.
    """
    if not _SLUG_RE.match(str(slug or "")):
        raise ValueError("that is not an app name")
    return Path(_apps_root()) / slug / "styles" / "main.css"


def page_path(slug: str) -> Path:
    """The app's single page, for an app that is one file."""
    if not _SLUG_RE.match(str(slug or "")):
        raise ValueError("that is not an app name")
    return Path(_apps_root()) / slug / "index.html"


def token_file(slug: str) -> Path:
    """Where this app's tokens actually are.

    Two layouts. The agent writes `styles/main.css` and links it, and 51
    of the apps on the box are that shape. The light lane writes ONE
    file, `index.html`, with the tokens in an inline `:root` block, and
    that lane takes nearly every build now.

    Until 2026-11-06 this only ever named the stylesheet, so a one-file
    app read as having no tokens at all and the panel offered to upgrade
    an app built thirty seconds earlier. Worse, the upgrade writes a
    stylesheet that a one-file page does not load, which is sliders that
    move nothing: the exact failure the upgrade offer exists to avoid.

    The stylesheet wins when it exists, because a page that links one has
    a `<link>` and no tokens of its own. An app with neither points at
    where a stylesheet would go, so the upgrade path has a target and so
    this never hands a caller None.
    """
    sheet = css_path(slug)
    if sheet.is_file():
        return sheet
    page = page_path(slug)
    if page.is_file():
        return page
    return sheet


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, NotADirectoryError):
        return ""
    except OSError:
        return ""


def read_css(slug: str) -> str:
    """The text that holds this app's tokens, or '' if there is none.

    An app with no tokens anywhere is simply not themeable yet, which is
    a normal answer and not an error.
    """
    return _read(token_file(slug))


def state(slug: str) -> dict:
    """What the panel needs to decide between sliders and an upgrade offer."""
    css = read_css(slug)
    have = declared(css)
    return {
        "tokens": served(),
        "values": have,
        "missing": missing(css),
        "themeable": is_themeable(css),
    }


def save(slug: str, values: dict) -> list[str]:
    """Write these token values back into whichever file holds them.

    Returns the token names written. Raises ValueError on anything
    `value_problem` refuses, via `rewrite`.

    A page with no `:root` block is REFUSED rather than rewritten.
    `rewrite` prepends a block when it finds none, which is right for a
    stylesheet and would put bare CSS in front of the doctype of
    somebody's page. The route does not gate on `themeable` before
    calling this, so the check belongs here.
    """
    path = token_file(slug)
    css = _read(path)
    if path.suffix.lower() in (".html", ".htm") and _root_body(css) is None:
        raise ValueError(
            "this page has no appearance settings yet, so there is nothing "
            "to change")
    out = rewrite(css, values)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(out, encoding="utf-8")
    return sorted(str(k) for k in values)
