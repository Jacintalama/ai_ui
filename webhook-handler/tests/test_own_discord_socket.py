"""The wire rules for a user's own Discord bot.

Deliberately needs nothing from the real discord library. Several test modules
here stub sys.modules["discord"] so that `main` can be imported without the
audio dependencies, and a stub has no ChannelType — which is exactly how the
first version of this file passed on its own and failed in the full suite.
`flatten` reads `message.guild` instead of comparing an enum, so these tests
hold whichever version of the module is loaded.
"""
from gateway.platforms import discord_socket


class _Author:
    bot = False
    id = 7
    display_name = "Ralph"


class _DM:
    """A direct message: discord.py leaves `guild` unset on these."""
    author = _Author()
    guild = None
    content = "hello"
    id = 99


class _GuildMessage:
    author = _Author()
    guild = object()
    content = "hello"
    id = 99


def test_the_discord_bot_never_asks_for_a_privileged_intent():
    """message_content is privileged: requesting it when the owner has not
    ticked it in the Developer Portal makes login fail outright, so every bot
    whose owner missed that checkbox would never connect. Discord always sends
    content for DMs with the bot regardless, so asking buys nothing and costs
    everything."""
    with open(discord_socket.__file__, encoding="utf-8") as f:
        code = "\n".join(l for l in f if not l.strip().startswith("#"))
    assert "intents.dm_messages = True" in code
    assert "intents.message_content" not in code
    assert "Intents.none()" in code, "start from nothing, not from defaults"


def test_a_dead_token_stops_rather_than_hammering_discord():
    """Retrying a rejected token cannot fix it, and hammering Discord with one
    is how an application gets rate limited."""
    with open(discord_socket.__file__, encoding="utf-8") as f:
        code = f.read()
    assert "discord.LoginFailure" in code
    body = code.split("except discord.LoginFailure", 1)[1].split("            except", 1)[0]
    assert "return" in body, "a rejected token must end the loop"


def test_flatten_reads_exactly_what_the_adapter_needs():
    assert discord_socket.flatten(_DM()) == {
        "is_bot": False, "is_dm": True, "text": "hello",
        "user_id": 7, "user_name": "Ralph", "message_id": 99}


def test_a_guild_message_is_never_seen_as_a_dm():
    """Checked here as well as in on_message, because the Brain is injected
    into every model call: answering in a guild channel would print one
    person's private memory to the whole room."""
    assert discord_socket.flatten(_GuildMessage())["is_dm"] is False


def test_dm_detection_needs_no_enum_from_the_library():
    """The first version compared channel.type against
    discord.ChannelType.private, which a stubbed discord module does not have.
    That made this file pass alone and fail in the full suite.

    Asserted on the STATEMENT, not the whole function: the docstring explains
    the enum it avoids, so a whole-body ban fails on the explanation rather
    than on the code, which is the same trap test_gateway_page_bot_copy.py hit.
    """
    with open(discord_socket.__file__, encoding="utf-8") as f:
        code = f.read()
    body = code.split("def _is_dm", 1)[1].split("\ndef ", 1)[0]
    statement = body.rsplit('"""', 1)[1]
    assert "ChannelType" not in statement
    assert "guild" in statement
