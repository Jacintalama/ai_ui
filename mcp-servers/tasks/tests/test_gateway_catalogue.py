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


def _buzz():
    return next(c for c in rg.CHANNEL_CATALOGUE if c["platform"] == "buzz")


def test_buzz_is_dormant_until_this_server_is_connected_to_it(monkeypatch):
    # Deploying the adapter must change nothing visible. The endpoint it
    # serves is public, so a channel that switched itself on would be one that
    # started accepting traffic nobody asked it to accept.
    monkeypatch.delenv("BUZZ_ENABLED", raising=False)
    row = rg._channel_status(_buzz(), {})
    assert row["status"] == "off"
    assert row["note"].strip()


def test_buzz_is_offerable_once_it_is_switched_on(monkeypatch):
    monkeypatch.setenv("BUZZ_ENABLED", "1")
    row = rg._channel_status(_buzz(), {})
    assert row["status"] == "available"
    assert "code" in row["note"].lower(), (
        "the note has to tell a Buzz user how to get a pairing code")


def test_buzz_carries_no_personal_bot(monkeypatch):
    # Buzz users reach IO through the one integration, not through a bot each,
    # so the row must never offer to take a token.
    monkeypatch.setenv("BUZZ_ENABLED", "1")
    row = rg._channel_status(_buzz(), {})
    assert row["can_bring_bot"] is False
    assert rg._route_for(row, "@aiuiteam_bot")["via_label"] == ''


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
