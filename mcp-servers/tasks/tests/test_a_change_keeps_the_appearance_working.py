"""A change to an app must not quietly undo its appearance controls.

The build prompts have asked for the theme tokens since 2026-11-05. The
ENHANCE prompt never mentioned them. So an app built with all 11 tokens,
used throughout, goes to an agent that has no idea they exist the moment
somebody asks for a change: "make the buttons green" gets a hardcoded
colour, and the sliders then move part of the page and not the rest.

That is worse than dead sliders, because dead sliders are obvious and
half-live ones are not.

Two judgements in here, both deliberate:

  * The block names the file the tokens are ACTUALLY in. `prompt_block`
    hardcodes `styles/main.css`, which is right for a new agent build and
    wrong for a one-file app, and that same assumption is what broke the
    appearance panel and the upgrade offer.

  * An app with NO tokens is told nothing. An enhance is not the place to
    force an upgrade: demanding tokens would turn "fix this typo" into a
    restyle of an app somebody never asked to change.
"""
import pytest

import app_theme

TOKENS = "".join("  %s: %s;\n" % (t.name, t.default) for t in app_theme.TOKENS)

PAGE = ("<!doctype html><html><head><style>\n:root {\n" + TOKENS + "}\n"
        "</style></head><body><h1>Hi</h1></body></html>\n")
BARE = "<!doctype html><html><body><h1>Hi</h1></body></html>\n"
SHEET = ":root {\n" + TOKENS + "}\n"


@pytest.fixture
def apps(tmp_path, monkeypatch):
    monkeypatch.setenv("APPS_ROOT", str(tmp_path))
    return tmp_path


def _one_file(apps, slug="bean-there", page=PAGE):
    (apps / slug).mkdir(parents=True)
    (apps / slug / "index.html").write_text(page, encoding="utf-8")


def _sheeted(apps, slug="bean-there", css=SHEET):
    (apps / slug / "styles").mkdir(parents=True)
    (apps / slug / "styles" / "main.css").write_text(css, encoding="utf-8")
    (apps / slug / "index.html").write_text(
        '<html><head><link rel="stylesheet" href="styles/main.css">'
        '</head><body></body></html>', encoding="utf-8")


# --- the block itself ----------------------------------------------------

def test_a_themeable_one_file_app_is_told_about_its_own_page(apps):
    _one_file(apps)
    said = app_theme.keep_block("bean-there")
    assert "index.html" in said
    assert "styles/main.css" not in said


def test_a_themeable_app_with_a_stylesheet_is_told_about_the_stylesheet(apps):
    _sheeted(apps)
    said = app_theme.keep_block("bean-there")
    assert "styles/main.css" in said


def test_it_names_every_token_so_none_can_be_dropped(apps):
    _one_file(apps)
    said = app_theme.keep_block("bean-there")
    for t in app_theme.TOKENS:
        assert t.name in said, "the agent is not told to keep " + t.name


def test_it_asks_for_both_keeping_and_using(apps):
    """Either alone is useless. An app that keeps the block and then
    hardcodes a colour in the new section is half-styleable, which is the
    failure this exists to stop."""
    _one_file(apps)
    flat = " ".join(app_theme.keep_block("bean-there").lower().split())
    assert "keep that :root block" in flat
    assert "do not hardcode" in flat
    assert "what you add or change" in flat


def test_an_app_with_no_tokens_is_told_nothing(apps):
    """An enhance is not the place to force an upgrade. Demanding tokens
    here would turn a typo fix into a restyle nobody asked for."""
    _one_file(apps, page=BARE)
    assert app_theme.keep_block("bean-there") == ""


def test_a_half_themed_app_is_told_nothing_either(apps):
    """Partly declared is not themeable, and asking an agent to finish
    the job mid-change is the same forced restyle."""
    _sheeted(apps, css=":root { --site-primary: #fff; }\n")
    assert app_theme.keep_block("bean-there") == ""


def test_an_app_that_is_not_there_is_not_an_error(apps):
    """A slug with no directory happens: an enhance of something deleted
    between the request and the run. It must not raise inside a prompt
    builder."""
    assert app_theme.keep_block("gone-a1b2") == ""


def test_a_bad_slug_is_still_refused(apps):
    for bad in ("../etc", "a/b", ""):
        with pytest.raises(ValueError):
            app_theme.keep_block(bad)


def test_nothing_in_it_uses_a_dash_for_punctuation(apps):
    _one_file(apps)
    said = app_theme.keep_block("bean-there")
    assert "—" not in said and "–" not in said


# --- it reaches the agent ------------------------------------------------

def test_the_enhance_prompt_carries_it(apps):
    _one_file(apps)
    import claude_executor as C
    out = C.build_enhance_prompt(slug="bean-there",
                                 user_request="make the buttons green")
    assert "--site-primary" in out, (
        "the agent is never told the app has appearance tokens")
    assert "index.html" in out


def test_the_enhance_prompt_of_an_untouched_old_app_is_unchanged(apps):
    """No new noise in the prompt for the apps that predate tokens."""
    _one_file(apps, page=BARE)
    import claude_executor as C
    out = C.build_enhance_prompt(slug="bean-there", user_request="fix a typo")
    assert "--site-primary" not in out
    assert "THEME TOKENS" not in out


def test_every_prompt_that_can_write_an_apps_css_mentions_the_tokens():
    """Counts them rather than checking one, like the build-prompt test
    does. A fourth prompt added later that can touch an app's styling and
    says nothing about tokens would silently undo them again.
    """
    import claude_executor as C
    with open(C.__file__, encoding="utf-8") as fh:
        src = fh.read()
    assert src.count("{theme_block}") == 3, (
        "a prompt that can write an app's CSS carries no theme block")
    # Two are filled from the build-time block, one from the keep block.
    assert src.count("theme_block=app_theme.prompt_block()") == 2
    assert src.count("theme_block=app_theme.keep_block(slug)") == 1
