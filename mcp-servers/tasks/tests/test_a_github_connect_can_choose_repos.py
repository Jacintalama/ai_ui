"""A GitHub connect always ends with a way to choose repositories.

Ralph, 2026-11-04, after connecting: "it didnt choose my repo or any of my
option it just connected".

He was right, and the cause is the split GitHub makes between the two
acts. Authorisation says who you are. INSTALLATION is what grants access
to repositories, and they are approved on different pages. So a token can
be valid, name the right person, and reach nothing.

The connect offered the install link only to somebody with NO
installation. That is the one case where its absence is obvious, and the
only case it was offered: anybody who had installed it once got
"Connected to X. You can close this window." and no way to change which
repositories it covers, which is the thing they opened it to do.
"""
import os

import pytest

os.environ.setdefault("AIUI_FERNET_KEY",
                      "SFNQQkFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=")

import routes_connections as R


# --- what the page says ----------------------------------------------------

def test_it_names_the_repositories_it_can_see():
    said = R._github_said("hub", ["me/one", "me/two"])
    assert "2 repositories" in said
    assert "me/one" in said and "me/two" in said


def test_one_repository_is_not_called_1_repositories():
    assert "1 repository:" in R._github_said("hub", ["me/one"])


def test_a_long_list_is_cut_short():
    """Forty names on a popup helps nobody. They need to know it worked
    and where to change it."""
    said = R._github_said("hub", ["o/%d" % i for i in range(40)])
    assert "40 repositories" in said
    assert "and 36 more" in said
    assert said.count("o/") == R.REPOS_NAMED


def test_none_given_is_said_plainly_and_is_not_an_error():
    """This is the state that looks fine and works for nothing. It has to
    be named, or the person leaves believing they are done."""
    said = R._github_said("hub", [])
    assert "cannot see any repositories" in said


def test_could_not_look_is_not_the_same_as_none():
    """None is "we could not ask", [] is "it has been given none". Only
    one of those is alarming, and guessing between them would either
    frighten somebody whose connect is fine or reassure somebody whose is
    not."""
    unknown = R._github_said("hub", None)
    assert "cannot see any" not in unknown
    assert unknown.strip().endswith("hub.")


def test_the_vendor_label_is_not_trusted_markup():
    """It comes from GitHub. _oauth_done puts the message in through
    textContent and escapes anything scriptable, so this only checks the
    wording does not pre-render it."""
    said = R._github_said("</script><script>alert(1)</script>", ["a/b"])
    assert "<script>" in said, "the raw label is passed through as text"
    page = R._oauth_done(True, said, link="https://x", link_text="Go").body
    assert b"<script>alert(1)</script>" not in page


# --- the actual fix --------------------------------------------------------

def test_a_successful_github_connect_always_offers_the_chooser():
    src = open(os.path.join(os.path.dirname(__file__), "..",
                            "routes_connections.py"), encoding="utf-8").read()
    after = src[src.index('if provider_id == "github":'):]
    done = after[:after.index("return _oauth_done(True, \"Connected to \"")]
    assert "link=O.install_url()" in done
    assert "Choose which repositories" in done


def test_the_chooser_is_not_gated_on_having_no_installation():
    """The whole bug. Offering it only when reach == 0 means the people
    who most want to change their selection are the ones never shown it.

    ANCHORED, not windowed. This read 1400 characters from the first
    `if provider_id == "github":` and asserted the word "reach" was not in
    them, which made it a test of what happens to sit nearby: on
    2026-11-13 a new helper's docstring, about Jira, used the word "reach"
    and failed this while the chooser was untouched. The block is bounded
    by its own return now.

    The behaviour itself is DRIVEN in
    tests/test_a_connect_always_has_a_next_step.py, where
    test_an_installed_app_is_stored_and_still_offered_the_chooser runs the
    real callback with one installation and reads the page. This stays as
    the cheap structural guard.
    """
    src = open(os.path.join(os.path.dirname(__file__), "..",
                            "routes_connections.py"), encoding="utf-8").read()
    start = src.index('if provider_id == "github":', src.index("_store_connection("))
    end = src.index('link_text="Choose which repositories")', start)
    block = src[start:end]
    assert "reach" not in block, (
        "the repository chooser is gated on the installation count again")
    assert block.count("if ") == 1, (
        "the chooser gained a condition: " + block)


def test_a_page_with_a_link_does_not_close_itself():
    """A popup that vanishes before anybody can read, let alone click, is
    the same as no link at all."""
    page = R._oauth_done(True, "Connected.", link="https://github.com/x",
                         link_text="Choose which repositories").body.decode()
    assert "Choose which repositories" in page
    # The close is GUARDED, not absent: the same page closes itself when
    # there is nowhere to go, so the string is legitimately in the source.
    # Asserting it is missing fails on correct code, which is what this
    # test did first.
    #
    # The guard gained a second half on 2026-11-13: a page with no opener
    # cannot close itself at all, and pretending otherwise is what left
    # Ralph looking at a finished connect that looked broken. The
    # behaviour itself is driven in a real browser now, in
    # tests/browser/test_the_connect_page_in_a_tab.py.
    assert "if (opener && !href) { setTimeout(" in page, (
        "the popup closes itself whether or not it carries a link")
    assert page.index("if (opener && !href)") < page.index("window.close()")


def test_a_page_with_nothing_to_do_still_closes_itself():
    """The other half. A finished Trello connect should not sit there
    waiting to be dismissed."""
    page = R._oauth_done(True, "Connected.").body.decode()
    assert "window.close()" in page


def test_only_github_gets_this():
    """Trello and the others have no second act to complete, and an extra
    link on a finished connect is one more thing to wonder about."""
    src = open(os.path.join(os.path.dirname(__file__), "..",
                            "routes_connections.py"), encoding="utf-8").read()
    assert src.count("Choose which repositories") == 1


# --- asking the vendor -----------------------------------------------------

def test_listing_repositories_never_breaks_the_connect():
    """The grant is already stored by this point. A vendor hiccup while
    reading a nicety must not turn a finished connect into a failure."""
    import inspect
    src = inspect.getsource(R._github_repos)
    assert "except Exception" in src
    assert "return None" in src


def test_it_does_not_ask_about_unbounded_installations():
    """Somebody in many organisations would otherwise turn one connect
    into one vendor call per organisation."""
    import inspect
    assert "MAX_INSTALLATIONS_ASKED" in inspect.getsource(R._github_repos)
