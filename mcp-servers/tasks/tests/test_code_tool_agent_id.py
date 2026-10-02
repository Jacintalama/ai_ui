"""create_app and apply_app_change say which agent is calling.

The design skill a build runs with is the calling agent's setting
(design_skill.py), and the agent's id comes from the tool runner's
__model__, never from the model's own arguments. Driven through the real
runner here, against the shipped tool source, so the whole hop from "Dev
called create_app" to the request body the tasks service receives is the
thing under test.
"""
import json
import os
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from agent_tools import execute_tool_call

TOOL = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                    "open-webui-functions", "code_tool.py")
OWNER = "owner@example.com"


def _source():
    with open(TOOL, encoding="utf-8") as fh:
        return fh.read()


def _call(name, arguments):
    return {"id": "call-1", "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments)}}


@pytest.fixture
def bodies(monkeypatch):
    """Every request body the tool sends, answered like the tasks service."""
    seen = []
    real_client = httpx.AsyncClient

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={
            "task_id": "t-1", "slug": "crumb-and-co",
            "description": "bigger hours",
            "url": "https://ai-ui.example/app-builder"})

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    return seen


async def _run(call, agent_id):
    with patch("agent_tools._load_native_tool_source",
               new=AsyncMock(return_value=_source())):
        return await execute_tool_call(call, OWNER, None, agent_id)


async def test_create_app_sends_the_running_agent(bodies):
    await _run(_call("create_app", {"description": "a bakery page"}),
               "agent-dev-c82b")
    assert bodies[0]["agent_id"] == "agent-dev-c82b"
    assert bodies[0]["user_email"] == OWNER


async def test_apply_app_change_sends_the_running_agent(bodies):
    await _run(_call("apply_app_change", {"token": "abc"}), "agent-dev-c82b")
    assert bodies[0] == {"user_email": OWNER, "token": "abc",
                         "agent_id": "agent-dev-c82b"}


async def test_no_agent_running_sends_none(bodies):
    await _run(_call("create_app", {"description": "a bakery page"}), None)
    assert bodies[0]["agent_id"] is None


async def test_the_model_cannot_name_the_agent(bodies):
    await _run(_call("create_app", {
        "description": "a bakery page",
        "__model__": {"id": "agent-somebody-else"},
        "agent_id": "agent-somebody-else"}), "agent-dev-c82b")
    assert bodies[0]["agent_id"] == "agent-dev-c82b"
