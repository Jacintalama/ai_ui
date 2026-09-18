"""Building an app that does not exist yet.

Ralph, with a screenshot, 2026-09-18: he asked for a camera landing page called
Thunder and got "I do not see an App Builder app named thunder. I can only
build inside an existing app, so choose one of your existing app slugs". Rex
was right about its own tools and useless to the person: every code tool needed
a slug, so the one thing it could not do was make the thing being asked for.

code_tool.py installs into an Open WebUI tool row, so nothing in the service
imports it. Loaded from its path, like the pipe tests.
"""
import importlib.util
import os

import pytest
from unittest.mock import AsyncMock

TOOL_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..",
    "open-webui-functions", "code_tool.py")

WHO = {"email": "owner@example.com"}
BUILT = {"task_id": "t-1", "slug": "thunder-camera-3f2a",
         "url": "https://ai-ui.coolestdomain.win/app-builder"}


def _load():
    spec = importlib.util.spec_from_file_location("code_tool", TOOL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def tools():
    mod = _load()
    return mod.Tools()


async def test_it_builds_from_what_they_asked_for(tools):
    tools._call = AsyncMock(return_value=BUILT)
    said = await tools.create_app("a landing page for my camera brand",
                                  "Thunder", __user__=WHO)
    _, kwargs = tools._call.call_args
    assert kwargs["description"] == "a landing page for my camera brand"
    assert kwargs["name"] == "Thunder"
    assert kwargs["user_email"] == "owner@example.com"
    assert "thunder-camera-3f2a" in said


async def test_the_route_it_calls_is_the_create_one(tools):
    tools._call = AsyncMock(return_value=BUILT)
    await tools.create_app("anything", __user__=WHO)
    args, _ = tools._call.call_args
    assert args[0] == "POST" and args[1] == "/code/create"


async def test_no_name_is_not_an_empty_name(tools):
    """The service seeds the slug from the description when no name is given.
    An empty string would be a name, and a nameless app."""
    tools._call = AsyncMock(return_value=BUILT)
    await tools.create_app("a page about bikes", "", __user__=WHO)
    _, kwargs = tools._call.call_args
    assert kwargs["name"] is None


async def test_the_link_rides_on_its_own_line(tools):
    """Same as apply_app_change: the panel draws a card for a link like this,
    and a link buried in a sentence is a link nobody clicks."""
    tools._call = AsyncMock(return_value=BUILT)
    said = await tools.create_app("a page", __user__=WHO)
    assert any(line.strip().endswith(BUILT["url"])
               for line in said.splitlines())


async def test_it_says_the_build_takes_time(tools):
    """A build is minutes, not seconds. An agent that says "done" hands the
    person a page that is not there yet."""
    tools._call = AsyncMock(return_value=BUILT)
    said = await tools.create_app("a page", __user__=WHO)
    assert "few minutes" in said


async def test_one_build_at_a_time_is_explained_not_swallowed(tools):
    """The platform runs one build at a time and says so. That is a fact the
    person can act on, so it has to survive as a sentence rather than becoming
    a generic failure."""
    tools._call = AsyncMock(
        side_effect=RuntimeError("A build is already running. Try shortly."))
    said = await tools.create_app("a page", __user__=WHO)
    assert "already running" in said


async def test_the_model_is_told_not_to_ask_for_an_existing_app(tools):
    """The description is what the model reads before choosing a tool. The
    failure being fixed here was a model that reached for the wrong tool and
    asked the person to pick a slug, so this instruction is the fix."""
    doc = (tools.create_app.__doc__ or "").lower()
    assert "does not exist yet" in doc
    assert "pick an existing app" in doc
