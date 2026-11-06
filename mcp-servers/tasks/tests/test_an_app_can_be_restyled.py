"""The appearance panel can only move what the app itself declares.

ChatGPT's canvas changes a site's colours and type instantly because the
PAGE declares its palette as CSS variables on :root, and the panel only
writes those variables. It rewrites no files to do it.

Measured 2026-11-05: not one of the 51 apps in this repo declared a
single CSS variable, so dropping that panel on them as they stood would
have given somebody sliders that moved nothing. These are the pieces
that make an app themeable, and that keep what the panel writes safe,
because a token value ends up inside a stylesheet on disk.
"""
import pytest

import app_theme as T


# --- one list, not three -------------------------------------------------

def test_the_tokens_are_declared_once():
    """The builder prompt asks for them, the checker looks for them and
    the panel draws them. Three copies of this list is three places to
    change and two chances to drift."""
    names = T.names()
    assert len(names) == len(set(names)), "a token is listed twice"
    assert len(names) >= 8
    for n in names:
        assert n.startswith("--site-"), n


def test_every_token_says_what_it_is_and_where_it_starts():
    for tok in T.TOKENS:
        assert tok.kind in ("color", "font", "scale"), tok.name
        assert tok.label.strip(), tok.name
        assert tok.default.strip(), tok.name
        assert T.value_problem(tok.name, tok.default) is None, (
            f"{tok.name}'s own default would be rejected: {tok.default}")


def test_the_prompt_names_every_token_it_wants():
    """An app is themeable only if it declares the names the panel writes.
    A prompt that asks for "some CSS variables" produces an app the panel
    cannot touch."""
    block = T.prompt_block()
    for n in T.names():
        assert n in block, f"the builder is never told about {n}"


def test_what_is_served_is_what_the_panel_needs_to_draw_a_control():
    for row in T.served():
        assert set(row) >= {"name", "kind", "label", "default"}


# --- reading what an app actually declares -------------------------------

CSS = """
:root {
  --site-primary: #8b5a2b;
  --site-background: #fffaf3;
  --site-font-body: 'Inter', sans-serif;
  --site-radius-scale: 1.25;
}
body { background: var(--site-background); }
"""


def test_it_reads_the_values_out_of_the_root_block():
    got = T.declared(CSS)
    assert got["--site-primary"] == "#8b5a2b"
    assert got["--site-font-body"] == "'Inter', sans-serif"
    assert got["--site-radius-scale"] == "1.25"


def test_a_variable_outside_root_is_not_the_site_palette():
    """A component may declare its own local variables. Those are not the
    knobs the panel owns, and treating them as such would have the panel
    writing into a rule it does not understand."""
    scoped = ":root { --site-primary: #111; }\n.card { --site-secondary: #eee; }"
    assert T.declared(scoped) == {"--site-primary": "#111"}


def test_an_app_with_no_variables_at_all_is_not_themeable():
    """This is every app built before today."""
    assert T.declared("body { color: #333; }") == {}
    assert T.is_themeable("body { color: #333; }") is False


def test_an_app_is_themeable_only_when_nothing_is_missing():
    assert T.is_themeable(CSS) is False
    assert "--site-secondary" in T.missing(CSS)
    assert "--site-primary" not in T.missing(CSS)

    whole = ":root {\n" + "".join(
        f"  {t.name}: {t.default};\n" for t in T.TOKENS) + "}\n"
    assert T.missing(whole) == []
    assert T.is_themeable(whole) is True


# --- what may be written into a stylesheet -------------------------------

def test_an_unknown_token_is_refused():
    assert T.value_problem("--site-nonsense", "#fff") is not None
    assert T.value_problem("color", "#fff") is not None


@pytest.mark.parametrize("good", [
    "#fff", "#FFAA33", "#ffaa3380",
    "rgb(12, 34, 56)", "rgba(12,34,56,.5)",
    "hsl(210 40% 50%)", "hsl(210, 40%, 50%)",
])
def test_a_colour_may_be_written(good):
    assert T.value_problem("--site-primary", good) is None, good


@pytest.mark.parametrize("bad", [
    "red; } body { display: none",          # closes the rule and adds another
    "url(http://evil.example/x.png)",       # fetches from somebody else
    "#fff /* ) */",                         # a comment hiding a paren
    "var(--something-else)",                # points at a value we did not check
    "expression(alert(1))",
    "#ff",                                  # not a colour at all
    "",
    "#" + "f" * 400,
])
def test_a_colour_that_is_not_a_colour_is_refused(bad):
    assert T.value_problem("--site-primary", bad) is not None, bad


@pytest.mark.parametrize("good", [
    "'Inter', sans-serif", "Georgia, serif",
    '"Playfair Display", Georgia, serif',
    "system-ui, -apple-system, sans-serif",
])
def test_a_font_stack_may_be_written(good):
    assert T.value_problem("--site-font-body", good) is None, good


@pytest.mark.parametrize("bad", [
    "Inter; } * { visibility: hidden",
    "url('//evil.example/f.woff')",
    "Inter}",
    "Inter/*x*/",
    "@import 'x'",
    "a" * 300,
])
def test_a_font_that_could_carry_anything_else_is_refused(bad):
    assert T.value_problem("--site-font-body", bad) is not None, bad


def test_a_scale_stays_inside_its_range():
    assert T.value_problem("--site-radius-scale", "1.5") is None
    assert T.value_problem("--site-radius-scale", "999") is not None
    assert T.value_problem("--site-radius-scale", "-1") is not None
    assert T.value_problem("--site-radius-scale", "1.5; }") is not None
    assert T.value_problem("--site-radius-scale", "1e9") is not None


# --- writing it back -----------------------------------------------------

def test_saving_changes_the_value_and_touches_nothing_else():
    out = T.rewrite(CSS, {"--site-primary": "#123456"})
    assert "--site-primary: #123456;" in out
    assert "--site-background: #fffaf3;" in out
    assert "body { background: var(--site-background); }" in out
    assert out.count("--site-primary:") == 1


def test_saving_a_token_the_app_lacks_adds_it_to_the_same_block():
    out = T.rewrite(CSS, {"--site-secondary": "#abcdef"})
    root = out[out.index(":root"):out.index("}", out.index(":root"))]
    assert "--site-secondary: #abcdef;" in root


def test_an_app_with_no_root_block_gets_one_at_the_top():
    out = T.rewrite("body { color: #333; }", {"--site-primary": "#123456"})
    assert out.index(":root") < out.index("body")
    assert "--site-primary: #123456;" in out
    assert "body { color: #333; }" in out


def test_a_refused_value_is_never_written():
    """The validator and the writer must not be able to disagree. If
    rewrite trusted its caller, one route forgetting to validate would be
    a stylesheet injection."""
    with pytest.raises(ValueError):
        T.rewrite(CSS, {"--site-primary": "red; } body { display: none"})
    with pytest.raises(ValueError):
        T.rewrite(CSS, {"--site-made-up": "#fff"})


def test_saving_nothing_is_refused_rather_than_committing_an_empty_change():
    with pytest.raises(ValueError):
        T.rewrite(CSS, {})


# --- the way out for the 51 apps that predate this -----------------------

@pytest.mark.parametrize("layout", ["stylesheet", "one file"])
def test_the_upgrade_asks_for_exactly_the_tokens_the_panel_writes(
        layout, tmp_path, monkeypatch):
    """Both layouts. The prompt takes the slug since 2026-11-06 because
    WHERE the block goes depends on the app, and the tokens it asks for
    must not depend on that."""
    monkeypatch.setenv("APPS_ROOT", str(tmp_path))
    app = tmp_path / "bean-there"
    if layout == "stylesheet":
        (app / "styles").mkdir(parents=True)
        (app / "styles" / "main.css").write_text(".a{}", encoding="utf-8")
    else:
        app.mkdir(parents=True)
        (app / "index.html").write_text("<html></html>", encoding="utf-8")
    said = T.upgrade_prompt("bean-there")
    for n in T.names():
        assert n in said, f"the upgrade never asks for {n}"
    # Normalised, because where the prompt happens to wrap is not the
    # behaviour under test and a line break once hid this sentence.
    flat = " ".join(said.lower().split())
    assert "do not change the layout" in flat, (
        "an upgrade that is allowed to redesign the app is not an upgrade")
    assert "render identically" in flat


# --- the builder is actually told ----------------------------------------

def test_every_prompt_that_lays_out_an_app_asks_for_the_tokens():
    """There are two build prompts, not one, and whichever path runs
    decides whether the app can ever be restyled. A third prompt added
    later with a file layout and no tokens would silently produce
    unthemeable apps, so this counts them rather than checking one.
    """
    import claude_executor as C
    with open(C.__file__, encoding="utf-8") as fh:
        src = fh.read()
    lays_out = src.count("FILE LAYOUT (MANDATORY")
    assert lays_out >= 2, "the prompts moved; re-check this"
    assert src.count("{theme_block}") == lays_out, (
        "a prompt lays out an app without asking for the theme tokens")
    assert src.count("theme_block=app_theme.prompt_block()") == lays_out, (
        "a placeholder is never filled, so .format would raise KeyError")


def test_both_prompts_carry_the_tokens_when_built():
    """The placeholder being present is not the same as it being filled."""
    import claude_executor as C
    built = C.build_prompt(
        description="a coffee shop landing page", action_type="build",
        priority="normal", meeting_title="t", meeting_date="2026-11-05",
        slug="bean-there")
    tdd = C.build_tdd_execute_prompt(
        description="x", action_type="build", priority="normal",
        meeting_title="t", meeting_date="d", plan="p",
        conversation_history=[])
    for prompt in (built, tdd):
        for n in T.names():
            assert n in prompt, n
        assert len(prompt) < C.MAX_PROMPT_CHARS


# --- reading and writing a real app --------------------------------------

def test_an_app_with_no_stylesheet_is_simply_not_themeable_yet(tmp_path, monkeypatch):
    """Not an error. Plenty of apps have no styles/main.css and the panel
    has to say something sensible rather than fail."""
    monkeypatch.setenv("APPS_ROOT", str(tmp_path))
    assert T.read_css("nothing-here") == ""
    assert T.state("nothing-here")["themeable"] is False


@pytest.mark.parametrize("bad", [
    "../../../etc/passwd", "a/b", "..", "", "Bean-There", "x" * 200,
])
def test_a_name_that_is_not_an_app_name_never_becomes_a_path(bad):
    """css_path is where a string turns into a filesystem path, so it
    re-checks the name even though the routes check it too."""
    with pytest.raises(ValueError):
        T.css_path(bad)


def test_saving_writes_the_value_and_keeps_the_rest_of_the_stylesheet(tmp_path, monkeypatch):
    monkeypatch.setenv("APPS_ROOT", str(tmp_path))
    app = tmp_path / "bean-there" / "styles"
    app.mkdir(parents=True)
    (app / "main.css").write_text(CSS, encoding="utf-8")

    written = T.save("bean-there", {"--site-primary": "#0f766e"})
    assert written == ["--site-primary"]

    after = (app / "main.css").read_text(encoding="utf-8")
    assert "--site-primary: #0f766e;" in after
    assert "--site-background: #fffaf3;" in after
    assert "body { background: var(--site-background); }" in after
    assert T.state("bean-there")["values"]["--site-primary"] == "#0f766e"


def test_a_refused_value_leaves_the_file_untouched(tmp_path, monkeypatch):
    """The write must not be half done. A stylesheet truncated by a
    rejected value breaks the app the panel was meant to restyle."""
    monkeypatch.setenv("APPS_ROOT", str(tmp_path))
    app = tmp_path / "bean-there" / "styles"
    app.mkdir(parents=True)
    (app / "main.css").write_text(CSS, encoding="utf-8")

    with pytest.raises(ValueError):
        T.save("bean-there", {"--site-primary": "#fff; } html { display:none"})
    assert (app / "main.css").read_text(encoding="utf-8") == CSS
