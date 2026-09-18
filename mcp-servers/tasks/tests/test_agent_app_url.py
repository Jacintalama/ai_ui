"""Where an agent sends somebody after it changes their app.

Ralph, 2026-09-18: when an agent creates an app the reply should carry a link
to it. The catch is that /apps/<slug>/ is served ONLY for a slug with a
tasks.published_apps row (main.py), so linking every app there would hand the
owner a 404 at the exact moment they were told their change had been applied.
"""
import pytest

import routes_code

BASE = "https://ai-ui.coolestdomain.win"


class _Result:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _Session:
    def __init__(self, row, raises=None):
        self._row = row
        self._raises = raises

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, *a, **k):
        if self._raises is not None:
            raise self._raises
        return _Result(self._row)


def _setup(monkeypatch, row=None, raises=None, base=BASE):
    monkeypatch.setenv("AIUI_PUBLIC_BASE_URL", base)
    monkeypatch.setattr(routes_code, "session",
                        lambda: _Session(row, raises))


async def test_a_published_app_links_to_where_it_is_served(monkeypatch):
    _setup(monkeypatch, row=(1,))
    assert await routes_code.app_url("shoe-site") == BASE + "/apps/shoe-site/"


async def test_an_unpublished_app_links_to_app_builder(monkeypatch):
    """Its files exist and its preview works there. /apps/<slug>/ would 404,
    and a dead link is worse than a longer walk."""
    _setup(monkeypatch, row=None)
    assert await routes_code.app_url("shoe-site") == BASE + "/app-builder"


async def test_a_lookup_that_fails_still_gives_them_somewhere_to_go(monkeypatch):
    """The change has just been applied. Failing to nothing would leave the
    one reply that needs a destination without one."""
    _setup(monkeypatch, raises=RuntimeError("no database"))
    assert await routes_code.app_url("shoe-site") == BASE + "/app-builder"


async def test_no_public_address_configured_means_no_link(monkeypatch):
    """Rather than inventing a hostname. An agent saying "open it at
    http://localhost" is worse than an agent saying nothing."""
    _setup(monkeypatch, row=(1,), base="")
    assert await routes_code.app_url("shoe-site") == ""


async def test_no_slug_means_no_link(monkeypatch):
    _setup(monkeypatch, row=(1,))
    assert await routes_code.app_url("") == ""


async def test_a_trailing_slash_in_the_base_is_not_doubled(monkeypatch):
    _setup(monkeypatch, row=(1,), base=BASE + "/")
    assert await routes_code.app_url("shoe-site") == BASE + "/apps/shoe-site/"


@pytest.mark.parametrize("slug", ["shoe-site", "create-me-a-shoe-website-fe02"])
async def test_the_slug_is_the_one_asked_about(monkeypatch, slug):
    _setup(monkeypatch, row=(1,))
    assert (await routes_code.app_url(slug)).endswith("/apps/%s/" % slug)
