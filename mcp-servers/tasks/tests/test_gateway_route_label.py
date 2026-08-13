"""Which bot is carrying this account's messages.

"Connected" alone does not answer the question a user has once they can bring
their own bot: is IO reading my messages through its own bot, or through mine?
That distinction is the entire point of the feature, so the row has to name it.
"""
import os

os.environ.setdefault("AIUI_FERNET_KEY",
                      "hUZ3RkVvY0JmS3FnWlp4TXcyN0RkNTZWc1RCQzNKS1E=")

import routes_gateway as rg

SHARED = "@aiuiteam_bot"


def row(status="connected", bot=None, can_bring_bot=True):
    return {"platform": "telegram", "status": status, "bot": bot,
            "can_bring_bot": can_bring_bot}


def enabled_bot(username="ralphs_io_bot"):
    return {"bot_username": username, "enabled": True}


def test_a_personal_bot_is_named_as_yours():
    out = rg._route_for(row(bot=enabled_bot()), SHARED)
    assert out["via"] == "own"
    assert "@ralphs_io_bot" in out["via_label"]
    assert "your bot" in out["via_label"].lower()


def test_without_a_personal_bot_it_says_the_shared_one():
    out = rg._route_for(row(), SHARED)
    assert out["via"] == "shared"
    assert SHARED in out["via_label"]


def test_a_switched_off_personal_bot_does_not_claim_to_carry_anything():
    # Turning your bot off means IO reaches you on the shared one again. Saying
    # "your bot" here would tell the user their messages avoid IO's bot when
    # they do not.
    out = rg._route_for(row(bot={"bot_username": "x", "enabled": False}), SHARED)
    assert out["via"] == "shared"


def test_a_saved_bot_counts_before_the_pairing_that_follows():
    # An enabled personal bot is where IO reaches you, so it wins the moment it
    # exists. Matching the routing rule matters more than matching link state.
    out = rg._route_for(row(status="available", bot=enabled_bot()), SHARED)
    assert out["via"] == "own"


def test_an_unconnected_channel_claims_no_route():
    assert rg._route_for(row(status="planned"), SHARED)["via"] == ""
    assert rg._route_for(row(status="off"), SHARED)["via_label"] == ""


def test_a_missing_shared_handle_still_reads_as_a_sentence():
    out = rg._route_for(row(), "")
    assert out["via"] == "shared"
    assert out["via_label"].strip()
    assert "@" not in out["via_label"], "must not print a bare @ with no handle"


def test_a_personal_bot_with_no_username_still_reads_as_a_sentence():
    out = rg._route_for(row(bot={"bot_username": "", "enabled": True}), SHARED)
    assert out["via"] == "own"
    assert "@" not in out["via_label"]


def test_every_row_carries_the_fields_even_before_bots_are_known():
    # list_connections fills these in later, but the page draws one shape for
    # every row, so they must never be absent.
    for entry in rg.CHANNEL_CATALOGUE:
        base = rg._channel_status(entry, {})
        assert "via" in base and "via_label" in base


def test_the_page_renders_the_route_rather_than_a_bare_connected():
    page = (os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "static", "gateway-link.html"))
    with open(page, encoding="utf-8") as fh:
        html = fh.read()
    assert "badgeText" in html, "the badge must go through the route-aware helper"
    assert "your bot" in html
    assert "IO's bot" in html
    assert "via_label" in html


def test_a_channel_that_cannot_carry_a_personal_bot_claims_no_bot_at_all():
    # The terminal is the case that makes this obvious: you connect a DEVICE,
    # not a bot. Naming IO's Telegram bot on that row would be simply false,
    # and it read that way on screen before this existed.
    out = rg._route_for(row(bot=None, can_bring_bot=False), SHARED)
    assert out["via"] == ""
    assert out["via_label"] == ""


def test_the_terminal_row_never_claims_a_telegram_bot():
    cli = next(e for e in rg.CHANNEL_CATALOGUE if e["platform"] == "cli")
    base = rg._channel_status(cli, {"cli": {"name": "ralph-laptop",
                                            "linked_at": None}})
    out = rg._route_for(base, SHARED)
    assert SHARED not in out["via_label"]


def test_an_unconnected_bot_channel_offers_both_ways_in():
    # Before this, the row said only "ready to connect", so nothing on the page
    # revealed that bringing your own bot was even possible.
    out = rg._route_for(row(status="available", bot=None), SHARED)
    assert out["via"] == "offer"
    assert SHARED in out["via_label"]
    assert "your own" in out["via_label"].lower()


def test_the_offer_drops_the_handle_when_no_shared_bot_exists():
    out = rg._route_for(row(status="available", bot=None), "")
    assert out["via"] == "offer"
    assert "@" not in out["via_label"], "must not print a bare @ with no handle"
    assert out["via_label"].strip()


def test_a_channel_that_cannot_carry_a_bot_offers_nothing():
    # The terminal connects a DEVICE. An offer line naming a Telegram bot here
    # would be false, which is exactly what shipped once already.
    out = rg._route_for(row(status="available", bot=None, can_bring_bot=False),
                        SHARED)
    assert out["via"] == ""
    assert out["via_label"] == ""


def test_a_saved_bot_still_wins_over_the_offer():
    out = rg._route_for(row(status="available", bot=enabled_bot()), SHARED)
    assert out["via"] == "own"


def test_a_saved_but_unpaired_bot_says_there_is_work_left():
    # Ralph hit this live: he had saved his own bot, the panel below the row
    # named it, and the row itself said only "ready to connect" with no line
    # at all. Saved-and-unpaired and never-touched are different states and
    # must not read identically.
    out = rg._route_for(row(status="available", bot=enabled_bot()), SHARED)
    assert out["via"] == "own"
    assert "@ralphs_io_bot" in out["via_label"]
    assert "finish" in out["via_label"].lower(), (
        "the label must tell the user what is still left to do")


def test_a_connected_own_bot_does_not_nag_about_finishing():
    out = rg._route_for(row(status="connected", bot=enabled_bot()), SHARED)
    assert out["via"] == "own"
    assert "finish" not in out["via_label"].lower()
