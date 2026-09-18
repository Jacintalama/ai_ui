"""Telling somebody their build failed, rather than letting them find out.

Ralph, 2026-09-18: Rex said "Building thunder-2b68 now", and the next thing he
saw was a red Failed badge on a card he had to go and find on App Builder. The
build had been refused by the model provider for lack of credit, which is
something he can act on and nothing an agent can retry around.

A build runs for minutes after the agent answers, so an agent that never
checks can only ever be optimistic.

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
TASK = "8a2851d8-3aa9-4963-a987-a71df3bc40db"


def _load():
    spec = importlib.util.spec_from_file_location("code_tool", TOOL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def tools():
    return _load().Tools()


async def test_a_finished_build_hands_over_the_link(tools):
    tools._call = AsyncMock(return_value={
        "status": "completed", "slug": "thunder-2b68",
        "preview_url": "https://ai-ui.example/tasks/preview-app/thunder-2b68/"})
    said = await tools.build_status(TASK, __user__=WHO)
    assert "thunder-2b68 is built" in said
    assert "https://ai-ui.example/tasks/preview-app/thunder-2b68/" in said


async def test_a_failure_carries_the_reason_word_for_word(tools):
    """The provider's own sentence. Paraphrasing "402, add credits" into
    "something went wrong" is the difference between a person topping up and a
    person thinking their agent is broken."""
    tools._call = AsyncMock(return_value={
        "status": "failed", "slug": "thunder-2b68",
        "error": "API Error: 402 This request requires more credits"})
    said = await tools.build_status(TASK, __user__=WHO)
    assert "failed to build" in said
    assert "402" in said and "more credits" in said


async def test_a_failure_with_no_reason_still_says_it_failed(tools):
    tools._call = AsyncMock(return_value={"status": "failed",
                                          "slug": "thunder-2b68"})
    said = await tools.build_status(TASK, __user__=WHO)
    assert "failed to build" in said
    assert "None" not in said


async def test_a_build_waiting_on_an_answer_asks_it(tools):
    tools._call = AsyncMock(return_value={
        "status": "needs_input", "slug": "thunder-2b68",
        "question": "Should the form email you, or post to a webhook?"})
    said = await tools.build_status(TASK, __user__=WHO)
    assert "waiting on an answer" in said
    assert "webhook" in said


@pytest.mark.parametrize("status", ["running", "", "something-new"])
async def test_anything_else_is_still_building(tools, status):
    """Four names come back today. A fifth must read as "not finished" rather
    than as an error, because the honest default while a build runs is
    patience."""
    tools._call = AsyncMock(return_value={"status": status,
                                          "slug": "thunder-2b68"})
    said = await tools.build_status(TASK, __user__=WHO)
    assert "still building" in said


async def test_it_asks_about_the_build_it_was_given(tools):
    tools._call = AsyncMock(return_value={"status": "running", "slug": "x"})
    await tools.build_status(TASK, __user__=WHO)
    args, kwargs = tools._call.call_args
    assert args[0] == "GET" and args[1] == "/code/build"
    assert kwargs["task_id"] == TASK
    assert kwargs["user_email"] == "owner@example.com"


async def test_a_service_that_refuses_is_explained_not_crashed(tools):
    tools._call = AsyncMock(side_effect=RuntimeError("No such build."))
    said = await tools.build_status(TASK, __user__=WHO)
    assert "No such build." in said


async def test_the_model_is_told_to_check_before_saying_it_is_ready(tools):
    """The description is what a model reads before choosing a tool, and the
    failure being fixed is an agent that answered optimistically and stopped
    paying attention."""
    doc = (tools.build_status.__doc__ or "").lower()
    assert "before you tell" in doc and "ready" in doc
