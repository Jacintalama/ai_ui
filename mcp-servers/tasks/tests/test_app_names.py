"""What a built app is actually called.

The App Builder card showed the slug: create-me-a-keyboard-landing-de7b,
aircon-page-5564, build-a-website-and-make-3104. That is the URL segment, made
by lowercasing the user's prompt and adding four hex characters, and it is not
a name. It reads like a filename in a list of things that are supposed to be
projects.

The agent has been naming these properly the whole time and nobody read it.
Those three apps call themselves Klakk, CoolStream HVAC and Lumen, in their own
index.html <title>. The README H1 is no help: the docs sweep generates it FROM
the slug, so it says "Create Me A Keyboard Landing De7b - Landing Page".

So the name comes from the app's own markup, and these tests cover the shapes
that markup really takes, taken from apps on production:

    <title>Klakk - Mechanical keyboards that sound like home</title>
    <title>CoolStream HVAC - Fast, fair air conditioning install & service</title>
    <title>Lumen - Launch</title>

A title is a name and often a tagline, joined by a dash. The name is the part
worth putting on a card; the tagline is worth keeping but not worth the heading.
"""
import pytest

from app_names import display_name, split_title


# --- pulling the name out of a real title ---------------------------------

@pytest.mark.parametrize("title,name,tagline", [
    ("Klakk — Mechanical keyboards that sound like home",
     "Klakk", "Mechanical keyboards that sound like home"),
    ("CoolStream HVAC — Fast, fair air conditioning install & service",
     "CoolStream HVAC", "Fast, fair air conditioning install & service"),
    ("Lumen — Launch", "Lumen", "Launch"),
    ("Oakline Doors – Handcrafted hardwood doors",
     "Oakline Doors", "Handcrafted hardwood doors"),
    ("Chicken Joy - The crispiest fried chicken in town",
     "Chicken Joy", "The crispiest fried chicken in town"),
    ("Chicken Joy | The crispiest fried chicken",
     "Chicken Joy", "The crispiest fried chicken"),
])
def test_a_title_splits_into_a_name_and_a_tagline(title, name, tagline):
    assert split_title(title) == (name, tagline)


def test_a_title_with_no_separator_is_all_name():
    assert split_title("Klakk") == ("Klakk", "")


def test_a_hyphenated_name_is_not_split_on_its_own_hyphen():
    """"Well-Being Co" is one word to a reader. Splitting on any hyphen would
    turn it into "Well" with a tagline of "Being Co"."""
    assert split_title("Well-Being Co")[0] == "Well-Being Co"
    assert split_title("E-Commerce Starter")[0] == "E-Commerce Starter"


def test_a_spaced_hyphen_is_a_separator():
    assert split_title("Acme - Store")[0] == "Acme"


# --- what actually ends up on the card ------------------------------------

def test_the_apps_own_name_wins():
    got = display_name("create-me-a-keyboard-landing-de7b",
                       html="<html><head><title>Klakk — Mechanical "
                            "keyboards</title></head>")
    assert got["name"] == "Klakk"
    assert got["tagline"] == "Mechanical keyboards"
    assert got["source"] == "title"


def test_a_missing_title_falls_back_to_a_readable_slug():
    """Never the raw slug on the card. "aircon-page-5564" becomes "Aircon
    Page", which is worse than a real name and much better than a URL."""
    got = display_name("aircon-page-5564", html="<html><head></head>")
    assert got["name"] == "Aircon Page"
    assert got["source"] == "slug"


def test_the_random_suffix_is_dropped_from_a_fallback_name():
    """The builder appends four hex characters to keep slugs unique. They mean
    nothing to the person reading the card."""
    assert display_name("create-me-a-landing-page-eb8e", html="")["name"] \
        == "Create Me A Landing Page"
    assert display_name("upload-c2f78c78", html="")["name"] == "Upload"


def test_a_slug_that_is_only_a_suffix_still_produces_something():
    assert display_name("de7b", html="")["name"].strip()


def test_an_empty_or_whitespace_title_is_treated_as_missing():
    for html in ("<title></title>", "<title>   </title>", "<title>\n</title>"):
        assert display_name("aircon-page-5564", html=html)["source"] == "slug"


# --- the markup is not trusted --------------------------------------------

def test_entities_in_a_title_are_decoded():
    """Titles really do carry them: "install &amp; service" on production."""
    got = display_name("x-1234", html="<title>Fast &amp; Fair — HVAC</title>")
    assert got["name"] == "Fast & Fair"


def test_markup_inside_a_title_cannot_reach_the_page():
    """The title is written by an agent into a file a user can also edit, and
    it is rendered into the App Builder list."""
    got = display_name("x-1234",
                       html="<title><img src=x onerror=alert(1)></title>")
    assert "<" not in got["name"] and ">" not in got["name"]


def test_an_unclosed_bracket_cannot_reach_the_page_either():
    """The tag-strip regex needs a closing bracket to match, so it alone leaves
    an unterminated "<img src=x" intact. The first version of the test above
    used a well-formed tag, which the regex handled, so the second guard could
    have been deleted with the suite still green."""
    for bad in ("<img src=x", "Klakk <script", "a > b < c"):
        got = display_name("x-1234", html="<title>" + bad + "</title>")
        assert "<" not in got["name"] and ">" not in got["name"], bad


def test_an_absurdly_long_title_is_cut():
    got = display_name("x-1234", html="<title>" + "N" * 5000 + "</title>")
    assert 0 < len(got["name"]) <= 60


def test_a_title_spanning_lines_is_still_found():
    got = display_name("x-1234", html="<head>\n  <title>\n    Klakk\n  </title>\n</head>")
    assert got["name"] == "Klakk"


def test_the_first_title_wins_when_markup_is_malformed():
    got = display_name("x-1234", html="<title>Klakk</title><title>Other</title>")
    assert got["name"] == "Klakk"


def test_unreadable_markup_never_raises():
    for html in (None, "", b"\xff\xfe not text"):
        assert display_name("aircon-page-5564", html=html)["name"]
