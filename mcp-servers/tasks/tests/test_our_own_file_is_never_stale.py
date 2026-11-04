"""Our own file under /static must not be served from a four-hour cache.

integrations-ui.js is bind-mounted into Open WebUI and changes with every
deploy. Open WebUI answers for /static with max-age=14400, and Cloudflare
honours it.

Measured on 2026-11-04, minutes after a successful deploy:

    cf-cache-status: HIT
    age: 1907
    cache-control: max-age=14400
    last-modified: Wed, 04 Nov 2026 07:57:03 GMT   <- eight hours earlier

The deploy was fine. Three features shipped that day were simply
invisible to any browser that had loaded the page in the previous four
hours, which is every returning person.
"""
import os
import re

import pytest

CADDYFILE = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                         "Caddyfile")


def _caddyfile():
    with open(CADDYFILE, encoding="utf-8") as fh:
        return fh.read()


def _block(matcher):
    """One handle block's body."""
    src = _caddyfile()
    start = src.index("handle " + matcher + " {")
    depth, i = 0, src.index("{", start)
    for j in range(i, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[start:j + 1]
    raise AssertionError("unbalanced braces after " + matcher)


def test_our_file_is_revalidated():
    body = _block("/static/integrations-ui.js")
    assert "Cache-Control" in body
    assert "no-cache" in body


def test_it_is_not_no_store():
    """no-store makes every page load re-download the whole file. no-cache
    lets the browser keep it and ask with its etag, so the usual answer is
    a 304. The box has 3.8GB of RAM and is not a CDN."""
    assert "no-store" not in _block("/static/integrations-ui.js")


def test_the_specific_block_comes_first():
    """Caddy evaluates handle blocks in the order written, and they are
    mutually exclusive. Below the catch-all, this block is dead config
    that validates cleanly and does nothing, which is the worst kind."""
    src = _caddyfile()
    assert (src.index("handle /static/integrations-ui.js {")
            < src.index("handle /static/* {"))


def test_open_webui_s_own_build_is_still_cacheable():
    """Everything else under /static is Open WebUI's build output, whose
    filenames carry a hash. Those are immutable and should stay cached;
    blanket no-cache here would make every page load re-fetch the whole
    front end on a small box."""
    assert "Cache-Control" not in _block("/static/*")


def test_the_file_this_protects_still_lives_there():
    """If the asset is ever renamed or moved, this block silently stops
    matching anything and the four-hour window comes back."""
    served = os.path.join(os.path.dirname(__file__), "..", "..",
                          "gdrive", "integrations-ui.js")
    assert os.path.exists(served)
    compose = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                           "docker-compose.unified.yml")
    with open(compose, encoding="utf-8") as fh:
        text = fh.read()
    assert re.search(r"integrations-ui\.js:/app/build/static/integrations-ui\.js",
                     text), "the mount this header protects is not in compose"
