"""A simple site is one model call, not a Claude Code subprocess.

Measured 2026-11-05: the agent peaks at ~900MB inside a 1GB container,
which is why only one person could build at a time and a second was
refused with a 429. Of 51 apps in the repo, 50 are static sites with no
database. So the platform was paying ~900MB and a global lock to
produce, nearly every time, a landing page.

This is the lane that does not pay it. Design:
docs/superpowers/specs/2026-11-05-light-build-lane-design.md

Everything here is pure, so the decisions can be tested without a model
call, a subprocess or a filesystem.
"""
import pytest

import light_build as L


# --- which lane a request belongs in -------------------------------------

@pytest.mark.parametrize("asked", [
    "a landing page for a coffee shop called Bean There",
    "create me a juice shop landing page",
    "a portfolio site for a photographer",
    "a one page site about my band",
    "make me a website for a shoe shop, dark and sporty",
    "a simple page with my opening hours and a map",
])
def test_a_plain_site_takes_the_light_lane(asked):
    assert L.needs_the_agent(asked) is None, asked


@pytest.mark.parametrize("asked", [
    "a site where customers can log in",
    "a landing page with a signup form that saves emails",
    "a todo app that remembers my tasks",
    "a booking system for my salon",
    "a shop with a cart and checkout",
    "an admin dashboard showing our sales database",
    "a blog where visitors can leave comments",
    "a page with user accounts and profiles",
])
def test_anything_needing_a_backend_goes_to_the_agent(asked):
    """The anti-goal is the light lane quietly taking a job it cannot do
    and handing somebody a worse app without saying so."""
    assert L.needs_the_agent(asked) is not None, asked


def test_the_reason_is_something_a_person_can_read():
    """It is shown in the chat, so "matched pattern 3" is no use."""
    why = L.needs_the_agent("a site where customers can log in")
    assert why and why[0].isupper() and len(why) > 20
    assert "log in" in why.lower() or "login" in why.lower()


def test_the_decision_does_not_depend_on_shouting():
    assert L.needs_the_agent("A SITE WHERE CUSTOMERS CAN LOG IN") is not None
    assert L.needs_the_agent("a LANDING page") is None


def test_a_word_inside_another_word_is_not_a_backend():
    """"cart" inside "cartoon" and "log in" inside "catalogue" would send
    plain sites down the slow lane for nothing."""
    assert L.needs_the_agent("a landing page for a cartoon studio") is None
    assert L.needs_the_agent("a page showing our catalogue of rugs") is None


# --- what the model is asked for -----------------------------------------

def test_the_prompt_asks_for_one_file():
    said = L.page_prompt("a coffee shop landing page", "bean-there",
                         "Bean There")
    flat = " ".join(" ".join(m["content"] for m in said).split())
    assert "single" in flat.lower() or "one file" in flat.lower()
    assert "index.html" in flat


def test_the_prompt_carries_the_theme_tokens():
    """So the appearance panel works on a light build from the first
    build, instead of offering to upgrade an app made minutes ago."""
    import app_theme
    said = L.page_prompt("a page", "slug-1", "Slug")
    flat = " ".join(m["content"] for m in said)
    for name in app_theme.names():
        assert name in flat, name


def test_the_prompt_names_the_app_and_what_was_asked_for():
    said = L.page_prompt("a juice shop called JuiceThere", "juice-1", "Juice")
    flat = " ".join(m["content"] for m in said)
    assert "a juice shop called JuiceThere" in flat
    assert "juice-1" in flat


# --- reading the answer ---------------------------------------------------

def test_a_fenced_answer_is_unwrapped():
    """Models wrap code in fences even when told not to."""
    assert L.html_from("```html\n<!doctype html><html></html>\n```") == (
        "<!doctype html><html></html>")
    assert L.html_from("```\n<!doctype html><html></html>\n```") == (
        "<!doctype html><html></html>")


def test_chatter_around_the_page_is_dropped():
    answer = ("Here is your page!\n\n<!doctype html>\n<html></html>\n\n"
              "Let me know if you want changes.")
    assert L.html_from(answer).startswith("<!doctype html>")
    assert L.html_from(answer).endswith("</html>")


def test_an_answer_with_no_page_in_it_is_empty_not_guessed():
    assert L.html_from("I cannot do that.") == ""
    assert L.html_from("") == ""


# --- what may be called a finished page ----------------------------------

def _good_page():
    import app_theme
    tokens = "".join("    %s: %s;\n" % (t.name, t.default) for t in app_theme.TOKENS)
    return (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>Bean There</title>\n"
        "<script src=\"https://cdn.tailwindcss.com\"></script>\n"
        "<style>:root {\n" + tokens + "}</style>\n"
        "</head>\n<body><h1>Bean There</h1></body>\n</html>")


def test_a_good_page_passes():
    assert L.page_problem(_good_page()) is None


@pytest.mark.parametrize("missing,text", [
    ("no doctype", "<html><head><title>x</title></head><body>hi</body></html>"),
    ("no title", "<!doctype html><html><head></head><body>hi</body></html>"),
    ("not finished", "<!doctype html><html><head><title>x</title></head><body>"),
    ("empty", ""),
])
def test_a_page_that_is_not_a_page_is_refused(missing, text):
    assert L.page_problem(text) is not None, missing


def test_a_page_without_the_theme_tokens_is_refused():
    """Otherwise the appearance panel offers to upgrade an app this lane
    built thirty seconds ago."""
    page = _good_page().replace("--site-primary", "--brand-colour")
    problem = L.page_problem(page)
    assert problem is not None
    assert "--site-primary" in problem


def test_a_script_from_somewhere_we_do_not_trust_is_refused():
    """The page is served from our own domain to this person's visitors.
    A script tag the model invented pointing at an arbitrary host is
    somebody else's code running under our name."""
    page = _good_page().replace(
        "https://cdn.tailwindcss.com", "https://evil.example/x.js")
    problem = L.page_problem(page)
    assert problem is not None
    assert "evil.example" in problem


@pytest.mark.parametrize("ok", [
    "https://cdn.tailwindcss.com",
    "https://unpkg.com/alpinejs@3.x.x/dist/cdn.min.js",
    "https://cdn.jsdelivr.net/npm/thing@1/x.js",
])
def test_the_cdns_the_builder_already_uses_are_allowed(ok):
    page = _good_page().replace("https://cdn.tailwindcss.com", ok)
    assert L.page_problem(page) is None, ok


def test_a_page_that_asks_for_a_file_beside_it_is_refused():
    """This lane writes ONE file. A reference to styles/main.css is a 404
    on a page that looks fine to the model that wrote it."""
    page = _good_page().replace(
        "</head>", '<link rel="stylesheet" href="styles/main.css"></head>')
    problem = L.page_problem(page)
    assert problem is not None
    assert "styles/main.css" in problem
