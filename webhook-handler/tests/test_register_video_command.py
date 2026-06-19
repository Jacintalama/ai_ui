import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts"))
import register_discord_commands as reg


def test_video_command_has_add_with_attachments():
    p = reg.build_video_command_payload()
    assert p["name"] == "video"
    add = next(o for o in p["options"] if o["name"] == "add")
    atts = [o for o in add["options"] if o["type"] == reg.ATTACHMENT]
    assert len(atts) == 10
    assert all(o["required"] is False for o in atts)
    assert any(o["name"] == "list" for o in p["options"])


def test_add_subcommand_no_required_after_optional():
    """Within the `add` subcommand, all options are optional ATTACHMENTs.
    Verify no required option appears after any optional one (Discord rule)."""
    p = reg.build_video_command_payload()
    add = next(o for o in p["options"] if o["name"] == "add")
    opts = add["options"]
    seen_optional = False
    for o in opts:
        if not o["required"]:
            seen_optional = True
        else:
            # A required option after an optional one would violate Discord's rule
            assert not seen_optional, (
                f"Required option '{o['name']}' appears after an optional option"
            )
