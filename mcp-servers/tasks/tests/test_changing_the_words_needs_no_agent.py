"""Changing the words on a page should not cost a build.

Ralph, 2026-11-12: "user can manualy change the words... or ask agent to
do it... you know.. uiser can see easily and fast since its only edit...
its not that soo long".

Pointing at something and asking for a change runs an agent, which is a
build: minutes, a commit, a reload. That is the right price for "make the
hero more dramatic" and the wrong one for fixing a typo in a rating.

So there are two ways out of the same pencil now. This module is the fast
one: an exact text swap in the app's own files, no agent, committed like
any other change so the history and the rollback still work. The
precedent is the appearance panel, which has written files directly since
2026-11-05 and is not a build either.

WHAT IT REFUSES, and why each refusal is the point:

  - Words it cannot find exactly once. Two matches means it cannot tell
    which one was meant, and guessing would edit the wrong line of
    somebody's page silently.
  - `<`, `>` and `&`. The new words land in an HTML file. Those three
    characters are the difference between words and markup, and a text
    box that can write markup into a page is a text box that can write
    a <script> into it.
  - Anything long. The longer the text, the likelier it is a whole
    section rather than a label, and a whole section is what the agent
    is for.

Every refusal names the agent as the way through, because there always
is one.
"""
import os

import pytest

import app_text


# --- what it will not do, decided without touching a disk ------------------

def test_empty_new_words_are_refused():
    """Deleting an element is not a word swap, and emptying it leaves a
    page with a gap where a rating was."""
    assert app_text.problem("4.9/5", "")
    assert app_text.problem("4.9/5", "   ")


def test_empty_old_words_are_refused():
    assert app_text.problem("", "hello")


def test_ordinary_words_are_allowed():
    assert app_text.problem("4.9/5 from 2,300+ happy sippers",
                            "4.8/5 from 3,100+ happy sippers") == ""


def test_punctuation_people_actually_type_is_allowed():
    """A refusal list that catches apostrophes and dashes would refuse
    most real sentences."""
    assert app_text.problem("Buy now", "Buy now, it's worth it (really)") == ""


@pytest.mark.parametrize("bad", ["<b>hi</b>", "a < b", "Tom & Jerry",
                                 "5 > 3", "<script>x</script>"])
def test_markup_characters_are_refused(bad):
    said = app_text.problem("hello", bad)
    assert said, bad + " was allowed into a page"
    assert "agent" in said.lower(), "a refusal has to say what to do instead"


def test_a_newline_is_refused():
    """A word swap is one run of text. Something spanning lines is a
    layout change wearing a text change's clothes."""
    assert app_text.problem("hi", "line one\nline two")


def test_very_long_text_is_refused():
    long = "word " * 200
    said = app_text.problem("hello", long)
    assert said
    assert "agent" in said.lower()


def test_the_old_words_are_held_to_the_same_rule():
    """They came from the page's own textContent, so they can carry an
    ampersand the file holds as &amp;. Saying so beats "could not find
    those words", which reads as a bug."""
    assert app_text.problem("Tom & Jerry", "Tom and Jerry")


# --- finding them ---------------------------------------------------------

@pytest.fixture
def app(tmp_path, monkeypatch):
    """A one-file app, the shape nearly every build makes now."""
    root = tmp_path / "apps"
    (root / "cup-landing-page").mkdir(parents=True)
    page = root / "cup-landing-page" / "index.html"
    page.write_text(
        "<!doctype html><html><body>\n"
        "  <h1>A cup that holds the heat</h1>\n"
        "  <span class=\"rating\">4.9/5 from 2,300+ happy sippers</span>\n"
        "  <a href=\"#buy\">Buy Now</a>\n"
        "</body></html>\n", encoding="utf-8")
    monkeypatch.setenv("APPS_ROOT", str(root))
    return page


def test_the_words_are_swapped_in_place(app):
    app_text.swap("cup-landing-page", "4.9/5 from 2,300+ happy sippers",
                  "4.8/5 from 3,100+ happy sippers")
    out = app.read_text(encoding="utf-8")
    assert "4.8/5 from 3,100+ happy sippers" in out
    assert "4.9/5" not in out


def test_nothing_else_on_the_page_moves(app):
    before = app.read_text(encoding="utf-8")
    app_text.swap("cup-landing-page", "Buy Now", "Buy one")
    after = app.read_text(encoding="utf-8")
    assert len(after.split("\n")) == len(before.split("\n"))
    assert "A cup that holds the heat" in after
    assert "4.9/5 from 2,300+ happy sippers" in after


def test_it_says_which_file_it_changed(app):
    where = app_text.swap("cup-landing-page", "Buy Now", "Buy one")
    assert where == "index.html", where


def test_words_that_are_not_there_are_refused_rather_than_guessed(app):
    with pytest.raises(ValueError) as caught:
        app_text.swap("cup-landing-page", "Add to basket", "Buy one")
    assert "agent" in str(caught.value).lower()
    assert "Buy one" not in app.read_text(encoding="utf-8")


def test_words_that_appear_twice_are_refused(app):
    app.write_text(app.read_text(encoding="utf-8")
                   + "<footer>Buy Now</footer>\n", encoding="utf-8")
    with pytest.raises(ValueError) as caught:
        app_text.swap("cup-landing-page", "Buy Now", "Buy one")
    said = str(caught.value)
    assert "2" in said, "say how many, or the refusal is a shrug"
    assert "Buy one" not in app.read_text(encoding="utf-8")


def test_the_page_is_left_exactly_as_it_was_when_it_refuses(app):
    before = app.read_text(encoding="utf-8")
    for old, new in (("Add to basket", "x"), ("Buy Now", "<b>x</b>")):
        with pytest.raises(ValueError):
            app_text.swap("cup-landing-page", old, new)
    assert app.read_text(encoding="utf-8") == before


# --- the page is not always written the way it reads ----------------------

def test_words_split_across_lines_are_still_found(tmp_path, monkeypatch):
    """`textContent` gives one run of text. The FILE can hold it wrapped
    and indented, which is how a formatter leaves a long line, and a
    literal search would answer "I could not find those words" about
    words the person is looking straight at.
    """
    root = tmp_path / "apps"
    (root / "a").mkdir(parents=True)
    page = root / "a" / "index.html"
    page.write_text("<p>\n      The Ember Cup keeps your coffee hot\n"
                    "      for hours\n    </p>\n", encoding="utf-8")
    monkeypatch.setenv("APPS_ROOT", str(root))

    app_text.swap("a", "The Ember Cup keeps your coffee hot for hours",
                  "It keeps coffee hot all morning")
    assert "It keeps coffee hot all morning" in page.read_text(encoding="utf-8")


def test_a_loose_match_still_has_to_be_the_only_one(tmp_path, monkeypatch):
    root = tmp_path / "apps"
    (root / "a").mkdir(parents=True)
    page = root / "a" / "index.html"
    page.write_text("<p>hot   coffee</p><p>hot\ncoffee</p>", encoding="utf-8")
    monkeypatch.setenv("APPS_ROOT", str(root))
    with pytest.raises(ValueError):
        app_text.swap("a", "hot coffee", "iced tea")


# --- it only ever touches that app ----------------------------------------

def test_a_slug_cannot_climb_out_of_the_apps_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("APPS_ROOT", str(tmp_path / "apps"))
    for bad in ("../secrets", "a/../../etc", "/etc", "Also-Upper"):
        with pytest.raises(ValueError):
            app_text.swap(bad, "a", "b")


def test_only_the_files_an_app_is_made_of_are_searched(tmp_path, monkeypatch):
    """Not a lockfile, not a build output, and nothing under .git."""
    root = tmp_path / "apps"
    (root / "a" / "node_modules" / "dep").mkdir(parents=True)
    (root / "a" / "index.html").write_text("<p>hello</p>", encoding="utf-8")
    (root / "a" / "node_modules" / "dep" / "x.js").write_text(
        "var s = 'hello';", encoding="utf-8")
    monkeypatch.setenv("APPS_ROOT", str(root))

    # Two matches on disk, one of them in a place no page is served from.
    where = app_text.swap("a", "hello", "goodbye")
    assert where == "index.html"
    assert "hello" in (root / "a" / "node_modules" / "dep" / "x.js").read_text(
        encoding="utf-8")


# --- the route around it ---------------------------------------------------
#
# Structural, like the appearance routes beside it: driving them needs the
# DB tier, and what matters here is the wiring, not FastAPI.

import pathlib

ROUTES = pathlib.Path(__file__).resolve().parents[1] / "routes_aiuibuilder.py"


def _routes():
    return ROUTES.read_text(encoding="utf-8")


def _route_body():
    src = _routes()
    at = src.index('@router.post("/{slug}/text"')
    return src[at:]


def test_the_route_exists_where_the_panel_will_ask():
    assert '@router.post("/{slug}/text"' in _routes()


def test_only_the_owner_can_change_the_words():
    """Every per-slug route here is owner-scoped, and this one writes to
    somebody's app without an agent anywhere in the way."""
    body = _route_body()
    assert '_require_role(s, slug, user.email, "owner"' in body


def test_the_slug_is_checked_before_the_database_is_touched():
    body = _route_body()
    assert body.index("_validate_slug(slug)") < body.index("session()")


def test_a_refusal_reaches_the_person_as_the_sentence_it_is():
    """app_text's refusals are written to be read. A 400 with "Bad
    Request" would throw away the only useful part."""
    body = _route_body()
    assert "except ValueError as err:" in body
    assert "status_code=400, detail=str(err)" in body


def test_a_change_is_committed_like_any_other():
    """The version list and the rollback are git log for apps/<slug>/, so
    a change that is not a commit is a change neither can see."""
    body = _route_body()
    assert "app_git.sweep_app_commit" in body
    assert body.index("app_text.swap") < body.index("app_git.sweep_app_commit")


def test_nothing_a_vendor_or_a_person_typed_is_logged():
    """The old words are a person's page content. The log line names the
    app, not what it says."""
    body = _route_body()
    for line in body.splitlines():
        if "logger." in line:
            assert "body.old" not in line and "body.new" not in line
