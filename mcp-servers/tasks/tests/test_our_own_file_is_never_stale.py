"""A deploy of integrations-ui.js reaches a browser on the next page load.

The file is bind-mounted into Open WebUI and changes with every deploy,
and Open WebUI answers for /static with max-age=14400. What saves us is
one line in loader.js:

    s.src = '/static/integrations-ui.js?v=' + new Date().getTime();

Every page load therefore asks for a URL nothing has ever seen, so it is
always a miss and always the current file. Confirmed live on 2026-11-04
with cf-cache-status MISS and that day's code present.

**This was nearly recorded as a bug that did not exist.** A bare request
for /static/integrations-ui.js came back cached and eight hours stale, and
I concluded three shipped features were invisible to everybody. They were
not: no browser ever requests that URL. The lesson is in the shape of the
mistake, which is why these tests guard the query string FIRST and the
header second, in the order they actually matter.
"""
import os
import re

import pytest

HERE = os.path.dirname(__file__)
LOADER = os.path.join(HERE, "..", "..", "gdrive", "loader.js")
CADDYFILE = os.path.join(HERE, "..", "..", "..", "Caddyfile")
COMPOSE = os.path.join(HERE, "..", "..", "..", "docker-compose.unified.yml")


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _block(matcher):
    """One Caddy handle block's body."""
    src = _read(CADDYFILE)
    start = src.index("handle " + matcher + " {")
    depth = 0
    for j in range(src.index("{", start), len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[start:j + 1]
    raise AssertionError("unbalanced braces after " + matcher)


def _comment_above(matcher):
    """The run of comment lines immediately preceding a handle block."""
    src = _read(CADDYFILE)
    lines = src.splitlines()
    at = next(i for i, ln in enumerate(lines)
              if ln.strip().startswith("handle " + matcher + " {"))
    out = []
    i = at - 1
    while i >= 0 and lines[i].strip().startswith("#"):
        out.append(lines[i])
        i -= 1
    return chr(10).join(reversed(out))


# --- what actually protects us --------------------------------------------

def test_the_page_asks_for_a_url_nothing_has_cached():
    """This single expression is the whole protection. Without it, Open
    WebUI's max-age=14400 means a deploy reaches nobody who loaded the
    page in the previous four hours."""
    src = _read(LOADER)
    assert "integrations-ui.js?v=" in src
    assert "new Date().getTime()" in src


def test_the_buster_changes_every_load():
    """A constant or a build-time string would be cached exactly as hard
    as the bare URL. It has to vary per load."""
    src = _read(LOADER)
    busted = re.search(r"integrations-ui\.js\?v='\s*\+\s*(.+?);", src)
    assert busted, "the ?v= value is not an expression"
    expr = busted.group(1)
    assert "Date" in expr or "random" in expr, (
        "?v= is a fixed value, so it caches like no query at all: " + expr)


def test_nothing_else_loads_it_unbusted():
    """A second loader without the query string would quietly reintroduce
    the four-hour window for the pages that use it."""
    src = _read(LOADER)
    for hit in re.findall(r"integrations-ui\.js[^'\"]*", src):
        assert "?v=" in hit, "loaded without a cache buster: " + hit


# --- the second line of defence -------------------------------------------

def test_the_origin_still_says_not_to_cache_it():
    """Belt and braces. The line above is one expression in someone
    else's directory; delete it and this is all that is left."""
    body = _block("/static/integrations-ui.js")
    assert "Cache-Control" in body
    assert "no-cache" in body


def test_it_is_not_no_store():
    """no-store makes every load re-download the file. no-cache lets the
    browser keep it and ask with its etag, so the usual answer is a 304.
    The box has 3.8GB of RAM and is not a CDN."""
    assert "no-store" not in _block("/static/integrations-ui.js")


def test_the_specific_block_comes_first():
    """Caddy evaluates handle blocks in the order written and they are
    mutually exclusive. Below the catch-all this is dead config that
    validates cleanly and does nothing, which is the worst kind."""
    src = _read(CADDYFILE)
    assert (src.index("handle /static/integrations-ui.js {")
            < src.index("handle /static/* {"))


def test_open_webui_s_own_build_is_still_cacheable():
    """Everything else under /static is Open WebUI's build output with a
    hash in the filename. Blanket no-cache would make every page load
    re-fetch the whole front end."""
    assert "Cache-Control" not in _block("/static/*")


def test_the_comment_does_not_promise_the_header_reaches_a_browser():
    """It does not. Cloudflare's Browser Cache TTL rewrites no-cache to
    max-age=14400 at the edge, measured on 2026-11-04. Anybody reading
    this block needs to know the query string is the real protection, or
    they will delete it believing the header has them covered."""
    # The comments sit ABOVE the braces, which is where a Caddyfile puts
    # them, so this reads the lines leading up to the block rather than
    # its body.
    assert "Cloudflare" in _comment_above("/static/integrations-ui.js")
    assert "loader.js" in _comment_above("/static/integrations-ui.js")


# --- the mount both of these depend on ------------------------------------

def test_the_file_this_protects_still_lives_there():
    assert os.path.exists(os.path.join(HERE, "..", "..",
                                       "gdrive", "integrations-ui.js"))
    assert re.search(
        r"integrations-ui\.js:/app/build/static/integrations-ui\.js",
        _read(COMPOSE)), "the mount this protects is not in compose"


def test_the_loader_is_mounted_too():
    """loader.js is ours and bind-mounted into two places in the Open
    WebUI tree. If that mount goes, the buster goes with it."""
    assert _read(COMPOSE).count("gdrive/loader.js:") >= 1
