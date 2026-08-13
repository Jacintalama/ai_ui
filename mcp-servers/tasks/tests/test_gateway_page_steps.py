"""The page has to tell someone what to DO, in order.

The terminal row previously said "Run python scripts/io.py", naming a path that
only exists in a checkout. Nobody without the repository could use the channel.
"""
import pathlib

PAGE = (pathlib.Path(__file__).resolve().parents[1] / "static" / "gateway-link.html")
HTML = PAGE.read_text(encoding="utf-8")


def test_the_page_offers_a_downloadable_client():
    assert "/tasks/static/io.py" in HTML


def test_the_command_is_built_from_the_current_origin():
    # A hardcoded domain silently breaks every other host, including local
    # development and any future domain.
    assert "location.origin" in HTML


def test_the_page_never_hardcodes_the_production_domain_in_the_command():
    assert "https://ai-ui.coolestdomain.win/tasks/static/io.py" not in HTML


def test_the_old_checkout_only_instruction_is_gone():
    assert "python scripts/io.py" not in HTML


def test_copying_falls_back_when_the_clipboard_is_denied():
    # This page runs inside an iframe, where clipboard-write can be refused.
    # Asserting on selectNodeContents specifically, not on "select": the page
    # is full of querySelector calls, so a looser check would pass with no
    # fallback present at all.
    assert "navigator.clipboard" in HTML
    assert "selectNodeContents" in HTML


def test_both_paths_render_as_steps():
    assert "steps(" in HTML


def test_the_windows_alternative_is_offered():
    assert "iwr" in HTML


def test_the_warning_sits_with_the_code_box():
    assert "Only paste a code you asked for yourself" in HTML


def test_the_page_still_builds_dom_safely():
    # These rows render remote strings: a bot username and Telegram error text.
    assert "innerHTML" not in HTML


def test_an_unconnected_row_renders_its_offer_line():
    # The server computes via_label for these rows; without this branch the
    # page computes it and shows nobody.
    assert 'c.via === "offer"' in HTML
