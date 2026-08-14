"""Slack and Discord as gateway channels.

Both integrations were live and carrying real traffic before this existed, so
the governing constraint is not "does the new path work" but "can the new path
disturb the old one". Most of what follows tests the second question.

The difference between them matters. A Slack DM already produced an answer, from
one shared model with one shared prompt, so the gateway REPLACES something. A
Discord DM produced nothing at all, so the gateway fills silence. That is why
the Slack seam has a fallback and the Discord one does not need one.
"""
import pytest

from gateway.platforms.discord import DiscordAdapter
from gateway.platforms.slack import SlackAdapter


class FakeSlack:
    def __init__(self):
        self.posted = []

    async def post_message(self, channel, text, **kw):
        self.posted.append((channel, text))


class FakeDiscord:
    def __init__(self):
        self.sent = []

    async def send_dm(self, user_id, content="", components=None):
        self.sent.append((user_id, content))
        return True


# --- Slack: what counts as a message ----------------------------------------

def test_a_slack_direct_message_becomes_an_event():
    event = SlackAdapter(None).parse_inbound(
        {"type": "message", "channel_type": "im", "text": "what is on today",
         "user": "U123", "channel": "D999", "ts": "1.2"}, {})
    assert event.text == "what is on today"
    assert event.source.platform == "slack"
    # Pairing keys on the PERSON, and in Slack the person and the conversation
    # are different values, unlike Telegram where they coincide.
    assert event.source.user_id == "U123"
    assert event.source.chat_id == "D999"
    assert event.source.chat_type == "dm"


@pytest.mark.parametrize("event,why", [
    ({"channel_type": "channel", "text": "hi", "user": "U1", "channel": "C1"},
     "a channel message would answer in front of everyone"),
    ({"channel_type": "im", "text": "hi", "user": "U1", "channel": "D1",
      "bot_id": "B1"}, "our own message echoed back"),
    ({"channel_type": "im", "text": "hi", "user": "U1", "channel": "D1",
      "subtype": "message_changed"}, "an edit, whose text is nested elsewhere"),
    ({"channel_type": "im", "text": "   ", "user": "U1", "channel": "D1"},
     "nothing was said"),
    ({"channel_type": "im", "text": "hi", "channel": "D1"}, "no sender"),
    ({"channel_type": "im", "text": "hi", "user": "U1"}, "nowhere to reply"),
    ("not a dict", "not an event at all"),
])
def test_slack_ignores_what_is_not_a_fresh_direct_message(event, why):
    assert SlackAdapter(None).parse_inbound(event, {}) is None, why


def test_a_slack_reply_goes_back_to_the_same_conversation():
    import asyncio
    slack = FakeSlack()
    asyncio.run(SlackAdapter(slack).send("D999", "three things"))
    assert slack.posted == [("D999", "three things")]


# --- Discord ----------------------------------------------------------------

def test_a_discord_direct_message_becomes_an_event():
    event = DiscordAdapter(None).parse_inbound(
        {"is_bot": False, "is_dm": True, "text": "hello",
         "user_id": 4242, "user_name": "ralph", "message_id": 7}, {})
    assert event.text == "hello"
    assert event.source.platform == "discord"
    # Ids arrive as integers from discord.py and everything downstream keys on
    # strings, so a mismatch here would pair the same person twice.
    assert event.source.user_id == "4242"
    assert event.source.chat_id == "4242"


@pytest.mark.parametrize("event,why", [
    ({"is_bot": True, "is_dm": True, "text": "hi", "user_id": 1},
     "another bot, or ourselves"),
    ({"is_bot": False, "is_dm": False, "text": "hi", "user_id": 1},
     "a guild channel would print private memory to the room"),
    ({"is_bot": False, "is_dm": True, "text": "  ", "user_id": 1},
     "nothing was said"),
    ({"is_bot": False, "is_dm": True, "text": "hi"}, "no sender"),
    (None, "not an event at all"),
])
def test_discord_ignores_what_is_not_a_direct_message(event, why):
    assert DiscordAdapter(None).parse_inbound(event, {}) is None, why


def test_a_discord_reply_is_a_direct_message_to_the_asker():
    import asyncio
    discord = FakeDiscord()
    asyncio.run(DiscordAdapter(discord).send("4242", "here you go"))
    assert discord.sent == [("4242", "here you go")]


# --- the safety property: neither can disturb what already works ------------

def test_neither_channel_wakes_up_without_its_own_flag(monkeypatch):
    # Both integrations already carry real traffic, so having the credentials
    # must NOT be enough to reroute a DM. Deploying this changes nothing until
    # the flag is set, and blanking it restores the old behaviour with no code
    # change.
    import main
    from gateway.registry import registry

    for var in ("SLACK_BOT_TOKEN", "SLACK_SIGNING_SECRET", "DISCORD_BOT_TOKEN"):
        monkeypatch.setenv(var, "present")
    monkeypatch.delenv("GATEWAY_SLACK_ENABLED", raising=False)
    monkeypatch.delenv("GATEWAY_DISCORD_ENABLED", raising=False)

    assert registry.is_enabled("slack") is False
    assert registry.is_enabled("discord") is False
    assert registry.adapter("slack") is None
    assert registry.adapter("discord") is None


def test_the_flag_alone_is_not_enough_either(monkeypatch):
    # The reverse mistake: a flag set on a server with no Slack credentials
    # must not produce an adapter that cannot send.
    from gateway.registry import registry
    monkeypatch.setenv("GATEWAY_SLACK_ENABLED", "1")
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    assert registry.is_enabled("slack") is False


async def test_a_slack_dm_falls_back_when_the_channel_is_dormant(monkeypatch):
    """The seam returns False so the caller's generic reply still happens.

    This is the property that makes the change safe to deploy: with the flag
    unset, a Slack DM must behave exactly as it did before.
    """
    from handlers.slack import SlackWebhookHandler
    from gateway.registry import registry
    monkeypatch.delenv("GATEWAY_SLACK_ENABLED", raising=False)

    handler = SlackWebhookHandler.__new__(SlackWebhookHandler)
    handled = await handler._try_gateway(
        {"channel_type": "im", "text": "hi", "user": "U1", "channel": "D1"})
    assert handled is False, "a dormant channel must not swallow the message"


async def test_a_slack_dm_falls_back_when_the_gateway_raises(monkeypatch):
    # handle_event turns everything it can into a sentence, so reaching the
    # except means something outside it broke. The message must still get the
    # old answer rather than silence.
    from handlers import slack as slack_handler_mod
    from gateway import pipeline as gateway_pipeline
    from gateway.registry import registry

    monkeypatch.setenv("SLACK_BOT_TOKEN", "x")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "x")
    monkeypatch.setenv("GATEWAY_SLACK_ENABLED", "1")
    registry._adapters.pop("slack", None)

    async def _boom(event, adapter):
        raise RuntimeError("model exploded")
    monkeypatch.setattr(gateway_pipeline, "handle_event", _boom)

    handler = slack_handler_mod.SlackWebhookHandler.__new__(slack_handler_mod.SlackWebhookHandler)
    handled = await handler._try_gateway(
        {"channel_type": "im", "text": "hi", "user": "U1", "channel": "D1"})
    assert handled is False


async def test_a_channel_message_never_reaches_the_gateway(monkeypatch):
    # Belt and braces with the pipeline's own chat_type refusal. The Brain is
    # injected into every model call, so one leak here prints somebody's
    # private memory to a room.
    from handlers import slack as slack_handler_mod
    from gateway.registry import registry

    monkeypatch.setenv("SLACK_BOT_TOKEN", "x")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "x")
    monkeypatch.setenv("GATEWAY_SLACK_ENABLED", "1")
    registry._adapters.pop("slack", None)

    handler = slack_handler_mod.SlackWebhookHandler.__new__(slack_handler_mod.SlackWebhookHandler)
    handled = await handler._try_gateway(
        {"channel_type": "channel", "text": "hi", "user": "U1", "channel": "C1"})
    assert handled is False


def test_the_gateway_runs_after_the_command_router_not_before():
    # Order is the whole compatibility story: build-answer resume, the
    # onboarding card and the intent router all keep first refusal, and only
    # the generic fallback is replaced.
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "handlers" / "slack.py").read_text(encoding="utf-8")
    body = src.split("async def _handle_direct_message", 1)[1]
    assert body.index("try_resume_paused_build") < body.index("_try_gateway")
    assert body.index("_try_intent") < body.index("_try_gateway")
    assert body.index("_try_gateway") < body.index("chat_completion")
