"""Bringing your own bot on Discord and Slack.

Why these two matter more than they look. IO's Slack and Discord bots are ONE
app each, living in one workspace and one server. Anybody outside them cannot
be reached at all, and fixing that the obvious way means publishing an app and
running an OAuth install flow. Bringing your own credentials skips all of it:
the user makes their own app in their own workspace and pastes the tokens, and
IO never needs to be installed anywhere by us.

Identity is unchanged and deliberately so: `gateway_resolve` keys on (platform,
platform user id), so which bot delivers a message and who the message is from
stay separate questions. Bringing a bot does not bring an account.
"""
import os

os.environ.setdefault("AIUI_FERNET_KEY",
                      "hUZ3RkVvY0JmS3FnWlp4TXcyN0RkNTZWc1RCQzNKS1E=")

import pytest

import routes_gateway as rg


# --- what the page offers -----------------------------------------------

@pytest.mark.parametrize("platform", ["discord", "slack"])
def test_the_channel_can_take_your_own_bot(platform):
    assert platform in rg.BOT_CAPABLE_PLATFORMS


@pytest.mark.parametrize("platform", ["discord", "slack"])
def test_the_channel_has_a_form_to_fill_in(platform):
    spec = rg.CONNECT_FORMS[platform]
    assert spec["title"] and spec["pitch"] and spec["submit"]
    assert spec["fields"], "a bot-capable channel with no fields cannot be set up"


def test_slack_asks_for_both_tokens():
    """Socket Mode needs two, issued separately and failing separately. Asking
    for only the bot token is what makes "saved fine, never receives anything"
    possible."""
    names = [f["name"] for f in rg.CONNECT_FORMS["slack"]["fields"]]
    assert names[:2] == ["token", "app_token"]


def test_both_slack_tokens_are_treated_as_secrets():
    # `secret` decides that a field renders as a password AND that its value is
    # encrypted at rest. An app-level token opens a websocket that can read
    # every DM the app sees, so it is every bit as sensitive as the bot token.
    fields = {f["name"]: f for f in rg.CONNECT_FORMS["slack"]["fields"]}
    assert fields["token"]["secret"] is True
    assert fields["app_token"]["secret"] is True


def test_slack_help_names_the_setup_step_people_forget():
    """Socket Mode being off, or message.im not subscribed, is the single most
    common way a Slack app connects and then hears nothing at all."""
    blob = " ".join(f["help"] for f in rg.CONNECT_FORMS["slack"]["fields"])
    assert "Socket Mode" in blob
    assert "message.im" in blob


def test_discord_help_explains_the_shared_server_rule():
    """Discord will not let anyone DM a bot they share no server with, so a
    perfectly valid token still results in "nothing happens" without this."""
    blob = " ".join(f["help"] for f in rg.CONNECT_FORMS["discord"]["fields"])
    assert "server" in blob.lower()


# --- enabling is not the same act on every channel ----------------------

def test_only_telegram_connects_by_registering_a_webhook():
    """Telegram calls US, so enabling means registering a webhook. Discord,
    Slack and Buzz are connections IO holds open, reconciled by webhook-handler
    polling, so there is nothing to register and calling Telegram with their
    credentials is nonsense.

    This was already wrong for Buzz before Discord and Slack existed: toggling
    a Buzz connection sent its Nostr key to api.telegram.org, took Telegram's
    rejection as the truth, and left the row disabled with a Telegram error on
    it. The user could not switch their own connection back on.
    """
    assert rg.WEBHOOK_PLATFORMS == {"telegram"}
    for platform in rg.BOT_CAPABLE_PLATFORMS - rg.WEBHOOK_PLATFORMS:
        assert platform not in rg.WEBHOOK_PLATFORMS


def test_every_bot_capable_platform_has_a_form():
    """Otherwise the page offers "Use my own bot" and then renders an empty
    panel with a save button."""
    assert rg.BOT_CAPABLE_PLATFORMS <= set(rg.CONNECT_FORMS)


# --- required vs optional credentials -----------------------------------

def test_a_required_secret_is_not_marked_optional():
    """Both Slack tokens and the Discord token are mandatory: a row saved
    without one can never run, and would report success anyway."""
    for platform in ("discord", "slack", "telegram"):
        for field in rg.CONNECT_FORMS[platform]["fields"]:
            if field["secret"]:
                assert not field.get("optional"), f"{platform}.{field['name']}"


def test_the_buzz_key_is_optional_because_io_mints_one():
    """Nobody issues a Nostr identity, so leaving this blank is the NORMAL
    path, not an edge case. The page requires every secret field unless told
    otherwise, which made this path impossible to use from the browser: the
    label said "(optional)" and the button answered "Fill in agent key
    (optional) first."
    """
    fields = {f["name"]: f for f in rg.CONNECT_FORMS["buzz"]["fields"]}
    assert fields["token"]["secret"] is True
    assert fields["token"]["optional"] is True


def test_the_page_honours_the_optional_flag():
    from pathlib import Path
    page = (Path(__file__).resolve().parents[1] / "static"
            / "gateway-link.html").read_text(encoding="utf-8")
    assert "f.secret && !f.optional && !payload[f.name]" in page


# --- error copy ---------------------------------------------------------

class _Row:
    def __init__(self, platform, last_error="", endpoint="", bot_username=""):
        self.platform = platform
        self.last_error = last_error
        self.endpoint = endpoint
        self.bot_username = bot_username
        self.connected_at = None


@pytest.mark.parametrize("platform,expected", [
    ("telegram", "Telegram"),
    ("discord", "Discord"),
    ("slack", "Slack"),
])
def test_an_error_is_attributed_to_the_platform_that_said_it(platform, expected):
    """It read "Telegram said:" for every channel, so a Slack scope problem
    was reported as a Telegram complaint."""
    label = rg._error_label(_Row(platform, last_error="nope"))
    assert expected in label


def test_no_error_means_no_label():
    assert rg._error_label(_Row("slack")) == ""
