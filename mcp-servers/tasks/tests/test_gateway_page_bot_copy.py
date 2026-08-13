"""The page has to be honest about what a token does before anyone pastes one.

Following the pattern in ca07f1524: assert on the copy, because this is the
only place a user is told that IO can now send as their bot.
"""
from pathlib import Path

PAGE = Path(__file__).resolve().parents[1] / "static" / "gateway-link.html"
HTML = PAGE.read_text(encoding="utf-8")


def test_the_page_offers_a_way_to_bring_your_own_bot():
    assert "Use my own bot" in HTML


def test_the_page_names_botfather_so_a_user_knows_where_to_get_a_token():
    assert "BotFather" in HTML


def test_the_page_says_the_bot_is_private_to_the_user():
    assert "Nobody else can" in HTML


def test_the_page_offers_all_three_hermes_controls():
    for control in ("Test", "Edit", "Remove bot"):
        assert control in HTML


def test_the_page_never_ships_a_hardcoded_token():
    # A pasted example token would be a live credential in a public file.
    assert "AAH" not in HTML


def test_the_quick_connect_path_is_still_offered():
    assert "Quick connect" in HTML
