"""What the code tool is allowed to do without being asked twice.

The classifier decides what an unattended agent may run, so its answer for
these five names is a security decision, not a naming detail.
"""
import os
import re

from agent_tools import READ_METHODS, is_write_tool

TOOL = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                    "open-webui-functions", "code_tool.py")


def _source():
    with open(TOOL, encoding="utf-8") as fh:
        return fh.read()


def test_reading_is_never_a_write():
    for name in ("list_my_apps", "read_app_file", "search_my_app"):
        assert is_write_tool(name) is False, name


def test_proposing_is_not_a_write():
    """It writes a token row and changes nothing an app owner would
    notice. A Read only agent must be able to say what it would change."""
    assert is_write_tool("propose_app_change") is False
    assert "propose_app_change" in READ_METHODS


def test_applying_is_a_write():
    """The one call that can start a build. If this ever reads as a read,
    an unattended Read only agent could change a live app."""
    assert is_write_tool("apply_app_change") is True
    assert "apply_app_change" not in READ_METHODS


def test_the_tool_exposes_exactly_the_five_functions():
    source = _source()
    # Excludes a leading underscore so a private helper such as _call,
    # which is also "async def _call(self", is not counted as a sixth
    # public function.
    found = {name for name in re.findall(r"async def (\w+)\(self", source)
             if not name.startswith("_")}
    assert found == {"list_my_apps", "read_app_file", "search_my_app",
                     "propose_app_change", "apply_app_change"}


def test_the_tool_holds_no_filesystem_or_routing_logic():
    """Every decision belongs to the service, so Discord, Telegram and
    the web chat all answer the same way. A path check here would be a
    second, divergent copy of the one in app_code_access, which is the
    exact shape that produced this feature's worst defects."""
    source = _source()
    assert "os.path" not in source
    assert "pathlib" not in source
    assert "open(" not in source
    assert "resolve" not in source


def test_the_tool_never_deletes():
    source = _source().lower()
    for word in ("delete", "unlink", "rmtree", "remove"):
        assert word not in source, word


def test_apply_takes_only_a_token():
    """A slug argument here would invite the model to pick the app at
    confirm time, which is exactly what the stored proposal prevents."""
    source = _source()
    match = re.search(r"async def apply_app_change\(([^)]*)\)", source)
    assert match
    assert "slug" not in match.group(1)
