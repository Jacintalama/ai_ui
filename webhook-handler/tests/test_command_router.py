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
