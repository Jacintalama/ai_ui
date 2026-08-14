"""Connections holds tools. Channels holds places you talk to IO from.

They are different things and were mixed: the Connections dialog listed Slack,
Discord and Telegram as "coming soon" while those same three were live channels
on the Channels page. A user reading that dialog would conclude the opposite of
the truth, and the dialog cannot connect them anyway: a channel is connected by
pairing a code, not by an OAuth card.

This pins the split, because both lists are edited by hand and nothing else
would notice them drifting back together.
"""
import os
import pathlib

os.environ.setdefault("AIUI_FERNET_KEY",
                      "hUZ3RkVvY0JmS3FnWlp4TXcyN0RkNTZWc1RCQzNKS1E=")

import routes_gateway as rg

REPO = pathlib.Path(__file__).resolve().parents[3]
CONNECTIONS = (REPO / "mcp-servers" / "gdrive" / "integrations-ui.js")


def _connections_js():
    return CONNECTIONS.read_text(encoding="utf-8")


def test_the_connections_file_is_where_we_think():
    assert CONNECTIONS.exists(), CONNECTIONS


def test_no_channel_appears_in_the_connections_dialog():
    js = _connections_js().lower()
    for entry in rg.CHANNEL_CATALOGUE:
        # Matched on the card's id, which is how APPS entries are keyed.
        assert f"id: '{entry['platform']}'" not in js, (
            f"{entry['platform']} is a channel and must not be a Connections card")


def test_the_dialog_says_where_channels_live():
    # A user who came looking for Slack needs somewhere to go, or removing the
    # card just makes it look unsupported.
    assert "Channels page" in _connections_js()


def test_the_empty_chat_category_is_gone():
    # It existed only for the three channel cards.
    js = _connections_js()
    cats = js.split("var CATS = [", 1)[1].split("]", 1)[0]
    assert "'Chat'" not in cats


def test_the_tools_that_remain_are_not_channels():
    # The reverse direction: nothing in Channels should quietly become a
    # Connections card either.
    channels = {c["platform"] for c in rg.CHANNEL_CATALOGUE}
    js = _connections_js()
    ids = {chunk.split("'", 1)[0]
           for chunk in js.split("var APPS = [", 1)[1].split("{ id: '")[1:]}
    assert not (ids & channels), ids & channels
    assert "google" in ids, "the tools list must not have been emptied"
