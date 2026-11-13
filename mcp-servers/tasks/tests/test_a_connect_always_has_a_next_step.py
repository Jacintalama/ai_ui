"""A connect that cannot go on has to say where to go.

Authorising a GitHub App and installing one are two different acts.
Authorisation says who you are; installation is what grants access to
repositories. Somebody can finish the first and have a working token that
reaches nothing, which is exactly what happened on the first real connect:
right login, zero installations, zero repositories.

Refusing that was right. Refusing it with nowhere to go was not: the
install page is not somewhere a person can find on their own, and the
popup closed itself after two and a half seconds anyway.
"""
import re

import pytest

import oauth_providers as O
import routes_connections as R


def _page(resp):
    return resp.body.decode("utf-8")


def test_a_page_with_a_link_shows_it():
    page = _page(R._oauth_done(False, "One more step.",
                               link="https://github.com/apps/io-aiui/installations/new",
                               link_text="Install IO on GitHub"))
    assert "installations/new" in page
    assert "Install IO on GitHub" in page


def test_a_page_with_a_link_does_not_close_itself():
    """A popup that vanishes before anybody can read it, let alone click,
    is the same as no link at all."""
    page = _page(R._oauth_done(False, "One more step.",
                               link="https://example.com/x", link_text="Go"))
    assert "window.close" in page, "the close helper should still be defined"
    # The guard gained a second half on 2026-11-13: a page with no opener
    # cannot close itself at all. The behaviour both halves describe is
    # driven in a real browser now, in
    # tests/browser/test_the_connect_page_in_a_tab.py; this stays as the
    # cheap check that the guard is still in front of the close.
    assert re.search(r"if \(opener && !href\) \{ setTimeout", page), (
        "a page carrying a link must not schedule its own close")


def test_an_ordinary_page_still_closes_itself():
    """Every connect that worked before this must behave exactly as it
    did."""
    page = _page(R._oauth_done(True, "GitHub connected."))
    assert "setTimeout" in page and "window.close" in page


def test_an_ordinary_page_shows_no_empty_link():
    page = _page(R._oauth_done(True, "GitHub connected."))
    assert "hidden" in page, "the anchor should stay hidden with no link"


def test_the_message_is_never_interpolated_into_markup():
    """It can carry a vendor-supplied name. This is the existing rule and
    the link must not have introduced a way around it."""
    page = _page(R._oauth_done(False, "</script><script>alert(1)</script>",
                               link="https://example.com/x", link_text="Go"))
    assert "<script>alert(1)" not in page


def test_a_link_is_never_interpolated_into_markup_either():
    """The link is ours today. It is still built from a string, and the
    same escaping has to cover it."""
    page = _page(R._oauth_done(False, "x", link="</script><script>alert(1)</script>",
                               link_text="Go"))
    assert "<script>alert(1)" not in page


def test_the_link_text_is_escaped_too():
    page = _page(R._oauth_done(False, "x", link="https://example.com/",
                               link_text="</script><script>alert(1)</script>"))
    assert "<script>alert(1)" not in page


# --- the join: the callback actually offers it -----------------------------
# Tested through the real callback, not by reading the source. The piece
# above and the piece below both passed while nothing connected them, which
# is the same gap that let create() drop a Trello list id earlier today.

import asyncio


@pytest.fixture
def github_callback(monkeypatch):
    """The callback with the vendor, the database and GitHub all faked."""
    state = {"stored": [], "installations": 1}

    async def _store(email, provider_id, values, label):
        state["stored"].append((email, provider_id, label))

    async def _ask(provider, values):
        return True, "aiuiteams-hub", ""

    async def _installs(values):
        return state["installations"]

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"access_token": "gho_whatever"}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            return _Resp()

    monkeypatch.setattr(R, "_store_connection", _store)
    monkeypatch.setattr(R, "_ask_vendor", _ask)
    monkeypatch.setattr(R, "_github_installations", _installs)
    monkeypatch.setattr(R.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(O, "GITHUB_APP_SLUG", "io-aiui")
    monkeypatch.setenv("GITHUB_CLIENT_ID", "cid")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "csec")
    state["token"] = O.STATES.mint("ralph@example.com")
    return state


def test_no_installation_offers_the_install_page(github_callback):
    """The whole point. Authorised, token works, reaches nothing, and the
    person has no way to find that page on their own."""
    github_callback["installations"] = 0
    page = asyncio.run(R.oauth_callback(
        "github", code="c", state=github_callback["token"])).body.decode()
    assert "installations/new" in page
    assert "Install IO on GitHub" in page
    assert github_callback["stored"] == [], "a connection reaching nothing was stored"


def test_an_installed_app_is_stored_and_still_offered_the_chooser(
        github_callback):
    """This test said "and offered nothing" until 2026-11-04, and it was
    wrong in the way that matters: it locked in the behaviour Ralph then
    hit, which was "it didnt choose my repo or any of my option it just
    connected".

    Having an installation is not the same as having the RIGHT
    repositories in it. Somebody reconnecting is usually there to change
    exactly that, and they were the only people never shown the page that
    does it. GitHub's own page says Configure in this state and edits the
    selection, so it is the right destination either way.
    """
    github_callback["installations"] = 1
    page = asyncio.run(R.oauth_callback(
        "github", code="c", state=github_callback["token"])).body.decode()
    assert "installations/new" in page
    assert "Choose which repositories" in page
    assert github_callback["stored"] == [("ralph@example.com", "github",
                                          "aiuiteams-hub")]


def test_a_question_that_could_not_be_asked_does_not_block_the_connect(
        github_callback):
    """-1 means the count could not be read. A network blip must not read
    as "install it" and must not discard a grant somebody just approved."""
    github_callback["installations"] = -1
    asyncio.run(R.oauth_callback(
        "github", code="c", state=github_callback["token"]))
    assert len(github_callback["stored"]) == 1
