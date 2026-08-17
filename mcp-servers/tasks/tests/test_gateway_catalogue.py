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
                     "matrix", "whatsapp", "signal", "teams", "buzz"]


def test_email_is_not_a_channel():
    # Removed at Ralph's request. Email is a connector you attach to your
    # account, not a place you talk to IO from, and listing it here promised a
    # way in that was never going to be built on this page.
    assert "email" not in [c["platform"] for c in rg.CHANNEL_CATALOGUE]


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


def test_buzz_never_offers_ios_own_bot(monkeypatch):
    # Buzz carries a personal connection, like Telegram. What it does NOT have
    # is a shared identity: an identity there lives inside somebody's
    # workspace, and IO is a member of nobody's until it is invited. Offering
    # "IO's bot" on this row would be a way in that does not exist, which is
    # the mistake the row shipped with.
    monkeypatch.setenv("BUZZ_ENABLED", "1")
    row = rg._channel_status(_buzz(), {})
    assert row["can_bring_bot"] is True
    assert "aiuiteam" not in rg._route_for(row, "@aiuiteam_bot")["via_label"]
    assert "Buzz" in rg._route_for(row, "@aiuiteam_bot")["via_label"]


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


def test_only_the_channels_that_can_honour_a_credential_ask_for_one():
    # A form on a channel that cannot use what it stores is a button that
    # lies. These are the ones with a working transport.
    #
    # Discord and Slack joined the list because IO's own app on each lives in
    # exactly one server and one workspace, so nobody outside them could be
    # reached at all. Bringing your own credentials is what removes that
    # ceiling without publishing an app anywhere.
    takers = {c["platform"] for c in rg.CHANNEL_CATALOGUE
              if rg._channel_status(c, {})["can_bring_bot"]}
    assert takers == {"telegram", "buzz", "discord", "slack"}


def test_only_telegram_has_a_bot_io_runs_for_everyone():
    assert rg.SHARED_BOT_PLATFORMS == {"telegram"}


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


def test_a_relayed_channel_names_who_relays_it():
    # The page's lede promises nobody else can see what you connect. That is
    # true of the IO account and not of the platform carrying the message, so
    # a channel that relays has to say so on the row.
    row = rg._channel_status(_buzz(), {})
    assert "Buzz" in row["caveat"]
    assert "pass through" in row["caveat"]


def test_every_row_carries_the_caveat_field():
    # Present on every row, empty where nothing relays, so the page draws one
    # shape and a new channel cannot silently omit it.
    for entry in rg.CHANNEL_CATALOGUE:
        assert "caveat" in rg._channel_status(entry, {})


def test_every_channel_names_its_own_connect_headline():
    # The page used to infer this from can_bring_bot, a binary that put
    # "from your shell" on the Buzz row, where no shell is involved.
    for entry in rg.CHANNEL_CATALOGUE:
        row = rg._channel_status(entry, {})
        assert row["connect_headline"].strip()


def test_buzz_does_not_claim_a_shell():
    # The headline no longer names Buzz, because it now sits under the Buzz
    # workspace form and describes what comes after it. What still matters is
    # that it does not borrow the terminal's words.
    assert "shell" not in rg._channel_status(_buzz(), {})["connect_headline"].lower()


def test_the_terminal_is_the_only_channel_that_mentions_a_shell():
    shells = [c["platform"] for c in rg.CHANNEL_CATALOGUE
              if "shell" in rg._channel_status(c, {})["connect_headline"].lower()]
    assert shells == ["cli"]
