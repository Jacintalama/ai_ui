"""The appearance panel in the chat.

Structural, like the other tests of integrations-ui.js, which is vanilla
JS served as a static asset. The half that can be tested for real, what
may be written into a stylesheet, is in
test_an_app_can_be_restyled.py; this is about the panel's wiring.

Asserting whole statements rather than names, because a bare name match
passed six times in this repo while the behaviour under it was deleted.
"""
import os
import re

JS = os.path.join(os.path.dirname(__file__), "..", "..",
                  "gdrive", "integrations-ui.js")


def _js():
    with open(JS, encoding="utf-8") as fh:
        return fh.read()


def _section(name):
    src = _js()
    start = src.index("function " + name)
    ends = [src.find(mark, start + 10)
            for mark in ("\n  function ", "\n  // =====")]
    return src[start:min(e for e in ends if e != -1)]


# --- the list lives in one place -----------------------------------------

def test_no_token_name_is_copied_into_the_page():
    """The whole point of serving the token list is that there is one copy
    of it. A single `--site-primary` written here is a second list, and
    the day a token is renamed the panel draws a control that writes a
    variable no app declares, silently.
    """
    assert "--site-" not in _js(), (
        "a theme token name was copied into the page; serve it instead")


def test_the_controls_are_built_from_what_was_served():
    body = _section("aiuiAppearance")
    assert "for (var i = 0; i < state.tokens.length; i++)" in body
    assert "body.appendChild(control(tok, state.values[tok.name] || ''));" in body


def test_it_asks_the_app_what_it_declares():
    body = _section("aiuiAppearance")
    assert "'/api/aiuibuilder/' + encodeURIComponent(slug) + '/theme'" in body


# --- changing it is live, and only live ----------------------------------

def test_a_change_is_written_to_the_running_app_not_to_a_file():
    """This is the whole mechanism. A panel that saved on every nudge
    would commit once per drag of a slider and could not be undone."""
    body = _section("aiuiThemeSet")
    assert "root.style.setProperty(name, value);" in body


def test_moving_a_control_sends_nothing():
    """Measured by counting: the only fetches in this panel are the read,
    the save and the upgrade. A fourth would mean something fires on
    input."""
    body = _section("aiuiAppearance")
    assert body.count("fetch(") == 3, (
        "the panel gained or lost a request; is something firing on input?")


def test_what_is_saved_is_only_what_was_moved():
    """Sending every token on save would write values the person never
    touched into their stylesheet, and a colour input that cannot hold
    rgb() would quietly flatten the app's real palette to its fallback."""
    body = _section("aiuiAppearance")
    assert "changed[tok.name] = value;" in body
    assert "body: JSON.stringify({ values: changed })" in body
    assert "method: 'PUT'," in body


def test_putting_it_back_drops_what_we_wrote_and_rereads_the_file():
    body = _section("aiuiAppearance")
    assert "aiuiThemeDrop(frame, touched);" in body
    assert re.search(r"loaded = false;\s*// redraw from the file on next open",
                     body)


def test_a_saved_change_stops_being_an_override():
    """After a save the values are in the app's own stylesheet. Leaving
    our inline copies on top means the panel would show a save working
    even when the write silently did nothing."""
    body = _section("aiuiAppearance")
    saved = body[body.index("status.textContent = 'Saved';"):]
    assert "aiuiThemeDrop(frame, touched);" in saved
    assert "+ '?changed=' + Date.now();" in saved


def test_the_app_is_re_fetched_rather_than_reloaded():
    """Cloudflare rewrites this origin's no-cache to a four hour
    max-age, so location.reload() can be handed the stylesheet as it was
    BEFORE the save: a save that worked, showing nothing. The query
    string is what makes it a different URL to the cache.
    """
    body = _section("aiuiAppearance")
    assert "location.reload" not in body
    assert "frame.src = String(frame.src).split('?')[0]" in body


def test_a_frame_that_is_not_ready_says_so_instead_of_looking_armed():
    body = _section("aiuiAppearance")
    assert "if (!aiuiThemeSet(frame, tok.name, value)) {" in body


# --- the app that cannot be themed yet -----------------------------------

def test_an_app_with_no_tokens_is_offered_the_upgrade_not_sliders():
    body = _section("aiuiAppearance")
    assert "if (state && state.themeable) drawControls(state);" in body
    assert "else drawOffer();" in body


def test_the_upgrade_is_a_normal_build_and_is_watched_by_the_watcher():
    """A second poller on one task is a second answer. The build watcher
    already reports a change and reloads the frame."""
    body = _section("aiuiAppearance")
    assert "'/theme/upgrade'" in body
    assert "aiuiWatchChange(chatId, made.task_id, frame);" in body


# --- it is in the panel, where everything else is -------------------------

def test_the_control_sits_in_the_bar_with_the_others():
    src = _js()
    assert "bar.appendChild(paint);" in src
    assert "box.appendChild(look.el);" in src


def test_it_is_built_once_per_app_panel():
    src = _js()
    assert src.count("var look = aiuiAppearance(chatId, slug, frame);") == 1


def test_opening_it_twice_closes_it():
    src = _js()
    assert "if (look.isOpen()) {" in src
    assert "look.close();" in src
