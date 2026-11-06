"""A one-file app can be restyled, because that is most apps now.

The appearance panel was built when every app had `styles/main.css`, so
`css_path` named that file and nothing else. The light lane writes ONE
file, `index.html`, with the tokens in an inline `:root` block, and that
lane now takes nearly every build.

Measured on the live box 2026-11-06, with a real build walked end to end:
the page declared all 11 tokens and used them 75 times, and the panel
answered `themeable: false` with all 11 missing. It would have offered an
upgrade, and the upgrade writes `styles/main.css`, which a one-file page
does not load: sliders that move nothing, which is the exact failure the
upgrade offer exists to avoid.

51 of the apps on the box have `styles/main.css` and 3 are one-file. The
3 is the side that grows.
"""
import pytest

import app_theme
import light_build

TOKENS = "".join("  %s: %s;\n" % (t.name, t.default) for t in app_theme.TOKENS)

PAGE = ("<!doctype html>\n<html><head><title>Bean There</title>\n"
        "<style>\n:root {\n" + TOKENS + "}\n"
        ".hero { color: var(--site-text); }\n</style>\n</head>\n"
        "<body><h1>Bean There</h1></body></html>\n")

BARE_PAGE = ("<!doctype html>\n<html><head><title>Old App</title>\n"
             "<style>\n.hero { color: #123456; }\n</style>\n</head>\n"
             "<body><h1>Old App</h1></body></html>\n")

SHEET = ":root {\n" + TOKENS + "}\n.card { padding: 1rem; }\n"


@pytest.fixture
def apps(tmp_path, monkeypatch):
    monkeypatch.setenv("APPS_ROOT", str(tmp_path))
    return tmp_path


def _one_file(apps, slug="bean-there", page=PAGE):
    folder = apps / slug
    folder.mkdir(parents=True)
    (folder / "index.html").write_text(page, encoding="utf-8")
    return folder


def _with_a_stylesheet(apps, slug="bean-there"):
    folder = apps / slug / "styles"
    folder.mkdir(parents=True)
    (folder / "main.css").write_text(SHEET, encoding="utf-8")
    (apps / slug / "index.html").write_text(
        '<!doctype html><html><head><link rel="stylesheet" '
        'href="styles/main.css"></head><body></body></html>',
        encoding="utf-8")
    return apps / slug


# --- finding the tokens --------------------------------------------------

def test_a_stylesheet_still_wins_when_there_is_one(apps):
    """51 of the apps on the box are laid out this way. Reading the page
    instead would find a <link> and no tokens."""
    _with_a_stylesheet(apps)
    assert app_theme.token_file("bean-there").name == "main.css"


def test_a_one_file_app_falls_back_to_its_page(apps):
    _one_file(apps)
    assert app_theme.token_file("bean-there").name == "index.html"


def test_an_app_with_neither_points_at_where_a_stylesheet_would_go(apps):
    """So the upgrade path has somewhere to write, and so this never
    returns None for a caller to trip over."""
    (apps / "bean-there").mkdir(parents=True)
    assert app_theme.token_file("bean-there").name == "main.css"


def test_the_slug_is_still_checked_before_it_becomes_a_path(apps):
    """This is the function that turns a string into a filesystem path."""
    for bad in ("../etc", "a/b", "", "Bean There"):
        with pytest.raises(ValueError):
            app_theme.token_file(bad)


# --- what the panel says -------------------------------------------------

def test_a_one_file_app_with_tokens_is_restylable(apps):
    _one_file(apps)
    state = app_theme.state("bean-there")
    assert state["themeable"] is True
    assert state["missing"] == []
    assert state["values"]["--site-primary"]


def test_a_one_file_app_without_tokens_is_offered_the_upgrade(apps):
    """Still the honest answer for a page that predates this."""
    _one_file(apps, page=BARE_PAGE)
    state = app_theme.state("bean-there")
    assert state["themeable"] is False
    assert len(state["missing"]) == len(app_theme.TOKENS)


def test_what_the_light_lane_actually_writes_is_restylable(apps):
    """The test that was missing. It joins the two modules rather than
    trusting that a page the light lane wrote looks like the page this
    module expects."""
    light_build.write_site("bean-there", PAGE, "# Bean There\n")
    assert app_theme.state("bean-there")["themeable"] is True


# --- writing -------------------------------------------------------------

def test_saving_writes_into_the_page_itself(apps):
    folder = _one_file(apps)
    app_theme.save("bean-there", {"--site-primary": "#ff0000"})
    out = (folder / "index.html").read_text(encoding="utf-8")
    assert "--site-primary: #ff0000;" in out
    assert not (folder / "styles").exists(), (
        "a stylesheet the page does not load is a slider that moves nothing")


def test_saving_moves_nothing_else_in_the_page(apps):
    folder = _one_file(apps)
    app_theme.save("bean-there", {"--site-primary": "#ff0000"})
    out = (folder / "index.html").read_text(encoding="utf-8")
    assert out.startswith("<!doctype html>")
    assert out.rstrip().endswith("</html>")
    assert "<h1>Bean There</h1>" in out
    assert ".hero { color: var(--site-text); }" in out
    # Only the one declaration differs.
    assert out.replace("#ff0000", "#2563eb") == PAGE


def test_a_stylesheet_app_is_still_written_where_it_was(apps):
    folder = _with_a_stylesheet(apps)
    app_theme.save("bean-there", {"--site-primary": "#ff0000"})
    assert "--site-primary: #ff0000;" in (
        folder / "styles" / "main.css").read_text(encoding="utf-8")
    assert "#ff0000" not in (
        folder / "index.html").read_text(encoding="utf-8")


def test_a_page_with_no_token_block_is_refused_not_rewritten(apps):
    """The hazard. `rewrite` prepends a :root block when it finds none,
    which is right for a stylesheet and would put bare CSS in front of
    the doctype of somebody's page.

    The route does not gate on themeable before calling save, so this
    check has to live here.
    """
    folder = _one_file(apps, page=BARE_PAGE)
    before = (folder / "index.html").read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        app_theme.save("bean-there", {"--site-primary": "#ff0000"})
    assert (folder / "index.html").read_text(encoding="utf-8") == before


def test_a_refused_value_leaves_the_page_byte_for_byte(apps):
    folder = _one_file(apps)
    before = (folder / "index.html").read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        app_theme.save("bean-there", {"--site-primary": "red; } body { x:y"})
    assert (folder / "index.html").read_text(encoding="utf-8") == before


def test_a_stylesheet_with_no_tokens_is_still_created_as_before(apps):
    """No regression for the 51. A stylesheet CAN gain a :root block,
    because nothing else in the file cares where it sits."""
    folder = apps / "bean-there" / "styles"
    folder.mkdir(parents=True)
    (folder / "main.css").write_text(".card { padding: 1rem; }\n",
                                     encoding="utf-8")
    app_theme.save("bean-there", {"--site-primary": "#ff0000"})
    out = (folder / "main.css").read_text(encoding="utf-8")
    assert out.startswith(":root {")
    assert ".card { padding: 1rem; }" in out


# --- the upgrade offer, for a page that predates this --------------------

def test_the_upgrade_tells_a_one_file_app_to_stay_one_file(apps):
    """Otherwise the agent writes styles/main.css and a one-file page
    does not load it. That is the dead slider again, one step later."""
    _one_file(apps, page=BARE_PAGE)
    said = app_theme.upgrade_prompt("bean-there")
    assert "index.html" in said
    assert "styles/main.css" not in said
    assert "do not create" in said.lower()


def test_the_upgrade_still_names_the_stylesheet_when_there_is_one(apps):
    _with_a_stylesheet(apps)
    said = app_theme.upgrade_prompt("bean-there")
    assert "styles/main.css" in said


def test_the_upgrade_says_the_app_must_look_the_same_either_way(apps):
    """The whole point of the offer: pressing it is not a gamble."""
    for build in (_one_file, _with_a_stylesheet):
        import shutil
        shutil.rmtree(apps / "bean-there", ignore_errors=True)
        build(apps)
        said = app_theme.upgrade_prompt("bean-there")
        assert "IDENTICALLY" in said
        for t in app_theme.TOKENS:
            assert t.name in said


def test_the_route_asks_for_the_prompt_for_THIS_app():
    """A no-argument call would quietly use the stylesheet wording for
    every app, which is how this went wrong."""
    import os
    src = open(os.path.join(os.path.dirname(__file__), "..",
                            "routes_aiuibuilder.py"), encoding="utf-8").read()
    assert "app_theme.upgrade_prompt(slug)" in src
