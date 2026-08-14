"""Every channel gets a real brand mark, not a bare emoji, and a channel
added to CHANNEL_CATALOGUE without one must never silently render blank.

The marks live in a declarative LOGOS map near the top of gateway-link.html's
script, built into real SVG elements with document.createElementNS, never as
an HTML string, since this same page also prints a bot username and
Telegram's own error text, both of which come from outside this server.
"""
import re
from pathlib import Path

import routes_gateway as rg

PAGE = Path(__file__).resolve().parents[1] / "static" / "gateway-link.html"
HTML = PAGE.read_text(encoding="utf-8")


def _logos_block() -> str:
    start = HTML.index("const LOGOS = {")
    open_idx = HTML.index("{", start)
    depth = 0
    for i in range(open_idx, len(HTML)):
        if HTML[i] == "{":
            depth += 1
        elif HTML[i] == "}":
            depth -= 1
            if depth == 0:
                return HTML[open_idx:i + 1]
    raise AssertionError("LOGOS block is never closed")


def test_every_catalogue_platform_has_a_logo_entry():
    # A channel added to CHANNEL_CATALOGUE without a matching entry here
    # falls back to emoji at render time (by design), but it must never be
    # silently forgotten from the map that is supposed to cover it.
    block = _logos_block()
    # Allows an optional viewBox before shapes. Slack draws on a 127 canvas and
    # Teams on a 2228 one, because those are the official files' own coordinate
    # systems, and rescaling them by hand would reintroduce exactly the
    # from-memory guesswork these marks were replaced to get rid of.
    keys = set(re.findall(r"\n\s*(\w+): \{[^\n]*shapes:", block))
    platforms = {c["platform"] for c in rg.CHANNEL_CATALOGUE}
    assert platforms == keys, platforms.symmetric_difference(keys)


def test_the_logo_map_never_uses_innerhtml_or_an_image_tag():
    block = _logos_block()
    assert "innerHTML" not in block
    assert "<img" not in block
    assert "http://" not in block and "https://" not in block


def test_icons_are_built_with_createElementNS_not_a_string():
    assert "document.createElementNS" in HTML
    assert "buildIcon(c.platform, c.icon)" in HTML


def test_the_page_never_uses_innerhtml_anywhere():
    # This page has to print a bot username and Telegram's own error text,
    # both attacker-influenced, so nothing on the page may build markup from
    # a string, including the icon code added here.
    assert "innerHTML" not in HTML


def test_a_platform_with_no_logo_entry_falls_back_to_its_emoji():
    # buildIcon's fallback path is what keeps a future channel from
    # rendering blank before someone gets around to drawing its mark.
    assert 'span.textContent = fallbackEmoji || "*"' in HTML


def test_the_terminal_uses_the_page_text_color_not_a_brand_color():
    # It has no brand owner, so it rides the page's own currentColor rather
    # than a hardcoded hex. Email was checked here too and is no longer a
    # channel.
    block = _logos_block()
    cli_start = block.index("cli: { shapes:")
    cli_end = block.index("},\n", cli_start)
    assert "currentColor" in block[cli_start:cli_end]
