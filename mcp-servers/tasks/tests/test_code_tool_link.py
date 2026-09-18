"""The app an agent changed comes back as somewhere to go.

code_tool.py is installed into an Open WebUI `tool` row and runs from there,
so nothing in the service imports it and nothing else tests it. That is the
same gap the pipe tests cover, and it is worth covering for the same reason:
the file in git is the copy somebody installs, and a change here reaches
production only when that row is updated.

Ralph, 2026-09-18: when an agent creates or changes an app, the reply should
carry the app. Rex's actual words were "The approved change is ready in App
Builder", which is true and gets nobody to the page.
"""
import importlib.util
import os

import pytest
from unittest.mock import AsyncMock

TOOL_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..",
    "open-webui-functions", "code_tool.py")

URL = "https://ai-ui.coolestdomain.win/apps/shoe-site/"


def _load():
    spec = importlib.util.spec_from_file_location("code_tool", TOOL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def tools():
    mod = _load()
    cls = getattr(mod, "Tools", None)
    assert cls is not None, "an Open WebUI tool file defines a Tools class"
    return cls()


def _answers(tools, payload):
    tools._call = AsyncMock(return_value=payload)


async def test_the_reply_carries_the_link_the_server_gave(tools):
    _answers(tools, {"slug": "shoe-site", "description": "new hero",
                     "url": URL})
    said = await tools.apply_app_change("tok", __user__={"email": "o@e.com"})
    assert URL in said
    assert "shoe-site" in said and "new hero" in said


async def test_the_link_is_on_its_own_line(tools):
    """So it survives being quoted back, and so the panel can find it: the
    card is drawn from the answer's text, not from a field."""
    _answers(tools, {"slug": "shoe-site", "description": "x", "url": URL})
    said = await tools.apply_app_change("tok", __user__={"email": "o@e.com"})
    assert any(line.strip().endswith(URL) for line in said.splitlines())


@pytest.mark.parametrize("payload", [
    {"slug": "shoe-site", "description": "x"},
    {"slug": "shoe-site", "description": "x", "url": ""},
    {"slug": "shoe-site", "description": "x", "url": None},
])
async def test_no_link_means_no_sentence_about_one(tools, payload):
    """An older service, or one that could not work out where the app lives,
    returns no url. Inventing a destination is worse than not offering one."""
    _answers(tools, payload)
    said = await tools.apply_app_change("tok", __user__={"email": "o@e.com"})
    assert "Open it here" not in said
    assert "None" not in said


async def test_it_still_says_what_is_happening(tools):
    """The link is added to the answer, not instead of it: a change is
    started, smoke tested, and rolled back if it breaks, and the person needs
    to know that as much as they need the address."""
    _answers(tools, {"slug": "shoe-site", "description": "new hero",
                     "url": URL})
    said = await tools.apply_app_change("tok", __user__={"email": "o@e.com"})
    assert "Started." in said
    assert "rolled back" in said


async def test_the_model_is_told_to_pass_the_link_on(tools):
    """The description is what the model reads before it calls this. Without
    it the link arrives in the tool result and is paraphrased away."""
    assert "link" in (tools.apply_app_change.__doc__ or "").lower()
