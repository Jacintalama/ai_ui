"""The terminal client a user actually downloads.

The row tells people to fetch this file, so it must ship inside the image
rather than be read from the bind mount. The mount was stale in production on
2026-08-13: 3279 bytes from before the Cloudflare User-Agent fix against 3907
in the repository, so serving from it would have handed every user a client
that 403s before reaching IO.

Two copies exist on purpose: repository users expect scripts/io.py, and the
served copy must live under static/ for Caddy to proxy it. This file is what
stops them drifting apart.
"""
import pathlib

TASKS = pathlib.Path(__file__).resolve().parents[1]
REPO = TASKS.parents[1]

SERVED = TASKS / "static" / "io.py"
MIRROR = REPO / "scripts" / "io.py"


def test_the_served_client_exists_where_caddy_proxies_it():
    assert SERVED.is_file(), (
        "Caddy proxies /tasks/static/*, so the client must be here to be "
        "downloadable at all")


def test_the_two_copies_are_byte_identical():
    # Drift here means a user downloads a different program than a developer
    # runs, and nothing else would report it.
    assert SERVED.read_bytes() == MIRROR.read_bytes()


def test_the_client_still_sets_its_own_user_agent():
    # Cloudflare answers 1010 to urllib's default Python-urllib/3.x agent, so
    # without this the download works and then every request 403s.
    source = SERVED.read_text(encoding="utf-8")
    assert "User-Agent" in source
    assert "USER_AGENT" in source


def test_the_client_is_runnable_as_a_script():
    assert SERVED.read_text(encoding="utf-8").startswith("#!")


def test_the_client_needs_nothing_installed():
    # "single dependency-free script" is the promise the channel row makes.
    source = SERVED.read_text(encoding="utf-8")
    for banned in ("import requests", "import httpx", "from requests", "from httpx"):
        assert banned not in source
