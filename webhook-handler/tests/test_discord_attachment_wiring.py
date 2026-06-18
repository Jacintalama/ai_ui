"""Discord App Builder reads PDF/Word/text attachments end to end (2026-06-18).

Covers the three new wiring points: the slash command advertises a file
attachment option, the interaction parser surfaces the resolved attachment, and
the tasks client forwards the extracted text to the build/enhance routes.
"""
import os
import sys

import pytest

# register_discord_commands lives at repo-root scripts/.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts"))

from handlers.discord_commands import DiscordCommandHandler  # noqa: E402


def test_aiuibuilder_slash_advertises_attachment_option():
    import register_discord_commands as reg
    payload = reg.build_command_payload()
    sub = next(o for o in payload["options"] if o["name"] == "aiuibuilder")
    opts = sub["options"]
    # args stays first (required, STRING) so the existing parser is unaffected
    assert opts[0]["name"] == "args" and opts[0]["type"] == reg.STRING
    assert opts[0]["required"] is True
    # the file option is the Discord ATTACHMENT type and optional
    file_opt = next(o for o in opts if o["name"] == "file")
    assert file_opt["type"] == reg.ATTACHMENT == 11
    assert file_opt["required"] is False


def test_first_attachment_reads_resolved_payload():
    data = {"resolved": {"attachments": {"991": {
        "url": "https://cdn.discordapp.com/x.pdf", "filename": "spec.pdf",
        "content_type": "application/pdf", "size": 4321, "proxy_url": "..."}}}}
    att = DiscordCommandHandler._first_attachment(data)
    assert att == {
        "url": "https://cdn.discordapp.com/x.pdf", "filename": "spec.pdf",
        "content_type": "application/pdf", "size": 4321,
    }


def test_first_attachment_none_when_absent():
    assert DiscordCommandHandler._first_attachment({}) is None
    assert DiscordCommandHandler._first_attachment({"resolved": {}}) is None


def test_parse_options_picks_string_arg_ignoring_attachment_order():
    """The args STRING must be read by TYPE, not position — a type-11 file
    option can arrive first and its value is a snowflake id, not the text."""
    opts = [{"type": 1, "name": "aiuibuilder", "options": [
        {"name": "file", "type": 11, "value": "991234567890"},
        {"name": "args", "type": 3, "value": "build a cafe site"},
    ]}]
    assert DiscordCommandHandler._parse_options(opts) == ("aiuibuilder", "build a cafe site")


async def test_start_build_forwards_attachment_fields():
    from clients.tasks import TasksClient
    captured = {}

    client = TasksClient(base_url="http://tasks-test:8210")

    async def fake_request(method, path, email, json=None, **kw):
        captured.update(method=method, path=path, json=json)

        class _R:
            def json(self):
                return {"slug": "s", "task_id": "t"}
        return _R()

    client._request = fake_request
    await client.start_build("e@x", "a cafe", attachment_text="MENU BODY",
                             attachment_name="menu.pdf")
    assert captured["path"] == "/api/aiuibuilder/build"
    assert captured["json"]["attachment_text"] == "MENU BODY"
    assert captured["json"]["attachment_name"] == "menu.pdf"


async def test_enhance_app_forwards_attachment_fields():
    from clients.tasks import TasksClient
    captured = {}

    client = TasksClient(base_url="http://tasks-test:8210")

    async def fake_request(method, path, email, json=None, **kw):
        captured.update(path=path, json=json)

        class _R:
            def json(self):
                return {"task_id": "t"}
        return _R()

    client._request = fake_request
    await client.enhance_app("e@x", "my-slug", "tweak it",
                             attachment_text="SPEC", attachment_name="s.docx")
    assert captured["path"] == "/api/aiuibuilder/my-slug/enhance"
    assert captured["json"]["attachment_text"] == "SPEC"
    assert captured["json"]["attachment_name"] == "s.docx"
