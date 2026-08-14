"""The page has to be honest about what a token does before anyone pastes one.

Following the pattern in ca07f1524: assert on the copy, because this is the
only place a user is told that IO can now send as their bot.
"""
from pathlib import Path

PAGE = Path(__file__).resolve().parents[1] / "static" / "gateway-link.html"
HTML = PAGE.read_text(encoding="utf-8")


def test_the_page_offers_a_way_to_bring_your_own_bot():
    assert "Use my own bot" in HTML


def test_the_page_renders_whatever_help_the_server_gives_a_field():
    # The wording moved to the server so every channel gets a setup form
    # without new UI. What the page must still guarantee is that it SHOWS
    # each field's help; the wording itself is asserted in
    # test_gateway_connect_forms.py, at its source.
    assert "f.help" in HTML
    assert "f.label" in HTML
    assert "f.secret" in HTML


def test_the_page_says_the_bot_is_private_to_the_user():
    assert "Nobody else can" in HTML


def test_the_page_offers_all_three_hermes_controls():
    # "Remove " is now completed by the channel's own word for a connection:
    # "Remove bot" on a Nostr keypair is the wrong noun.
    for control in ("Test", "Edit", '"Remove " + (c.identity_noun'):
        assert control in HTML


def test_the_page_never_ships_a_hardcoded_token():
    # A pasted example token would be a live credential in a public file.
    assert "AAH" not in HTML


def test_the_quick_connect_path_is_still_offered():
    assert "Quick connect" in HTML


def test_a_channel_that_cannot_take_a_bot_says_so_in_its_own_words():
    # Not the channel's general status note, which is shown elsewhere on the
    # card. Reusing that printed the same sentence twice, and printed
    # Terminal's pairing instructions under "Use my own bot", where they are
    # wrong.
    assert "cannot take your own bot yet" in HTML
    assert "c.note ||" not in HTML
