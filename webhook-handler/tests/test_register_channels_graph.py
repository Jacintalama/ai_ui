"""`/aiui channels` and `/aiui graph` must be registered with Discord.

Discord only offers a subcommand the application has PUT to it, so a handler
that exists in code but not in the registration table is unreachable from the
slash menu. Slack has no such table (one `/aiui` command, free text), which is
why only Discord needs this file.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts"))
import register_discord_commands as reg  # noqa: E402

from handlers.commands import CommandRouter  # noqa: E402


def _sub(name: str) -> dict:
    return next(o for o in reg.build_command_payload()["options"] if o["name"] == name)


def test_channels_is_registered_with_no_options():
    s = _sub("channels")
    assert s["type"] == reg.SUB_COMMAND
    assert s.get("options", []) == []
    assert s["description"]


def test_graph_is_registered_with_one_optional_topic():
    s = _sub("graph")
    assert s["type"] == reg.SUB_COMMAND
    opts = s["options"]
    assert [o["name"] for o in opts] == ["topic"]
    assert opts[0]["type"] == reg.STRING
    assert opts[0]["required"] is False


def test_every_registered_name_is_one_the_parser_knows():
    """A registered word the parser does not know falls through to 'ask',
    so the slash menu would offer a command that answers as a chatbot."""
    for o in reg.build_command_payload()["options"]:
        assert CommandRouter.parse_command(o["name"])[0] == o["name"], o["name"]


def test_no_required_option_follows_an_optional_one():
    """Discord rejects the whole PUT for this, and PUT replaces every command."""
    for sub in reg.build_command_payload()["options"]:
        seen_optional = False
        for o in sub.get("options", []):
            if not o["required"]:
                seen_optional = True
            else:
                assert not seen_optional, f"{sub['name']}: required '{o['name']}' after optional"
