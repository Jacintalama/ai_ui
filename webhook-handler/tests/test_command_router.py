"""parse_command must recognise cronjob and aiuibuilder as subcommands."""
from handlers.commands import CommandRouter


def test_cronjob_list():
    assert CommandRouter.parse_command("cronjob list") == ("cronjob", "list")


def test_cronjob_create_with_quoted_args():
    sub, args = CommandRouter.parse_command('cronjob create "0 8 * * *" "summarize emails"')
    assert sub == "cronjob"
    assert args == '''create "0 8 * * *" "summarize emails"'''


def test_aiuibuilder_list():
    assert CommandRouter.parse_command("aiuibuilder list") == ("aiuibuilder", "list")


def test_aiuibuilder_status_with_slug():
    assert CommandRouter.parse_command("aiuibuilder status my-app") == (
        "aiuibuilder", "status my-app"
    )


def test_unknown_still_falls_to_ask():
    """Existing behavior must not regress."""
    assert CommandRouter.parse_command("what is MCP")[0] == "ask"


def test_existing_status_subcommand_still_works():
    assert CommandRouter.parse_command("status")[0] == "status"


import pytest
from unittest.mock import AsyncMock, MagicMock
from handlers.commands import CommandRouter, CommandContext


def _bare_router():
    return CommandRouter(
        openwebui_client=MagicMock(),
        n8n_client=MagicMock(api_key=""),
        discord_user_email_map={},
        tasks_client=MagicMock(),
    )


@pytest.mark.asyncio
async def test_execute_routes_cronjob():
    """CommandRouter.execute must call _handle_cronjob, not fall to ask."""
    r = _bare_router()
    r._handle_cronjob = AsyncMock()
    async def respond(_): pass
    ctx = CommandContext(
        user_id="100", user_name="t", channel_id="c", raw_text="cronjob list",
        subcommand="cronjob", arguments="list", platform="discord",
        respond=respond, metadata={},
    )
    await r.execute(ctx)
    r._handle_cronjob.assert_called_once_with(ctx)


@pytest.mark.asyncio
async def test_execute_routes_aiuibuilder():
    r = _bare_router()
    r._handle_aiuibuilder = AsyncMock()
    async def respond(_): pass
    ctx = CommandContext(
        user_id="100", user_name="t", channel_id="c", raw_text="aiuibuilder list",
        subcommand="aiuibuilder", arguments="list", platform="discord",
        respond=respond, metadata={},
    )
    await r.execute(ctx)
    r._handle_aiuibuilder.assert_called_once_with(ctx)


@pytest.mark.asyncio
async def test_help_leads_with_user_actions():
    """New help copy leads with the plain-language user actions (Build / Schedule
    / Ask) and demotes dev commands to the Advanced line: `cronjob` is gone and
    `aiuibuilder` survives only as an Advanced entry.

    NOTE: must be `async def` + pytest.mark.asyncio. `asyncio.get_event_loop()`
    raises a hard RuntimeError on Python 3.12 and is deprecated on 3.11.
    """
    r = _bare_router()
    captured = []
    async def respond(m): captured.append(m)
    ctx = CommandContext(
        user_id="100", user_name="t", channel_id="c", raw_text="help",
        subcommand="help", arguments="", platform="discord",
        respond=respond, metadata={},
    )
    # No respond_components on this ctx → _handle_help sends the help text.
    await r._handle_help(ctx)
    text = captured[0]
    # Leads with the user-facing actions.
    assert "Build an app" in text
    assert "Schedule a task" in text
    assert "Ask" in text
    # cronjob is no longer advertised; aiuibuilder is demoted to Advanced.
    assert "cronjob" not in text
    assert "Advanced" in text
    advanced = text.split("Advanced", 1)[1]
    assert "aiuibuilder" in advanced
    # The static builder is the single source of truth for the copy.
    assert text == CommandRouter._help_text()
