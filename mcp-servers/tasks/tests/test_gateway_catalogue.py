"""Every channel row carries the same controls, and says why an inert one is
inert.

Matching Hermes' shape is the point: the same toggle, Test and Configure on
every row. Honesty is the constraint: a control that cannot work must be
visibly inert with a reason, never a button that silently does nothing.
"""
import os

os.environ.setdefault("AIUI_FERNET_KEY",
                      "hUZ3RkVvY0JmS3FnWlp4TXcyN0RkNTZWc1RCQzNKS1E=")

import routes_gateway as rg


def test_the_catalogue_matches_the_hermes_list():
    # Hermes' own list, in its order, plus Buzz on the end. Buzz is not a
    # Hermes channel: it is here because Ralph asked for it, and it sits last
    # because it is the only one blocked by the other side rather than by us.
    names = [c["platform"] for c in rg.CHANNEL_CATALOGUE]
    assert names == ["telegram", "cli", "slack", "discord", "mattermost",
                     "matrix", "whatsapp", "signal", "email", "teams", "buzz"]


def test_buzz_does_not_pretend_to_be_connectable():
    # Every other row's blocker is work we have not done. Buzz's is that there
    # is no API on the other end yet, and the reason has to say so rather than
    # implying someone here is simply behind.
    buzz = next(c for c in rg.CHANNEL_CATALOGUE if c["platform"] == "buzz")
    row = rg._channel_status(buzz, {})
    assert row["status"] == "planned"
    assert row["can_bring_bot"] is False
    assert "api" in row["note"].lower()


def test_every_channel_says_what_it_is():
    for entry in rg.CHANNEL_CATALOGUE:
        assert entry["blurb"].strip()
        assert entry["label"].strip()
        assert entry["icon"].strip()


def test_every_channel_that_is_not_ready_says_why():
    for entry in rg.CHANNEL_CATALOGUE:
        row = rg._channel_status(entry, {})
        if row["status"] in ("planned", "off"):
            assert row["note"].strip(), f"{row['platform']} is silent about why"


def test_only_telegram_can_take_your_own_bot_today():
    for entry in rg.CHANNEL_CATALOGUE:
        row = rg._channel_status(entry, {})
        assert row["can_bring_bot"] is (entry["platform"] == "telegram")


def test_a_row_carries_a_bot_slot_even_when_empty():
    # The page renders the same shape for every row, so the field must always
    # be present rather than appearing only when a bot exists.
    for entry in rg.CHANNEL_CATALOGUE:
        assert "bot" in rg._channel_status(entry, {})


def test_mattermost_and_matrix_are_honest_about_being_unbuilt():
    rows = {c["platform"]: rg._channel_status(c, {})
            for c in rg.CHANNEL_CATALOGUE}
    assert rows["mattermost"]["status"] == "planned"
    assert rows["matrix"]["status"] == "planned"
