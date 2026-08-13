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


def test_the_page_never_hardcodes_a_checkout_only_path():
    # Not a historical guard: this string never lived in this file. The old
    # "Run python scripts/io.py" instruction came from the server as a runtime
    # value. This guards the future, where someone could type that path
    # straight into the page, which would again leave anyone without the
    # repository unable to use the channel.
    assert "scripts/io.py" not in HTML


def test_the_terminal_steps_never_mention_a_bot():
    # You connect a DEVICE to the terminal, not a bot. An earlier build of this
    # page printed "IO's bot @aiuiteam_bot" on the Terminal row, which was
    # false, and it was caught by eye rather than by a test.
    start = HTML.index("function terminalSteps(")
    # Find the closing brace by searching for "return steps(" (unique to this function)
    # and then finding the closing } that ends it.
    return_pos = HTML.index("return steps(", start)
    end = HTML.index("}", return_pos) + 1
    body = HTML[start:end]
    assert "bot" not in body.lower(), (
        "terminalSteps must not name a bot: the terminal connects a device")


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


def test_an_unconnected_row_renders_its_route_line():
    # The server computes via_label for these rows; without this branch it is
    # computed and shown to nobody. Keyed on the label rather than on
    # via === "offer": that narrower test passed while a saved-but-unpaired
    # bot still rendered nothing at all.
    assert "else if (c.via_label)" in HTML


def test_a_saved_but_unpaired_bot_gets_its_own_badge():
    # "Ready to connect" on a row whose bot is already saved understates the
    # state: there IS work left, and it is one step.
    assert "One step left" in HTML

