"""Rebuilding the tools service makes mcp-proxy pick its tools up again.

Measured on production 2026-11-09, and it made a shipped fix inert.

PR #159 changed what ClickUp's `assignees` field declares, from a string
to an array. It merged, the Deploy workflow succeeded, `.deploy-state`
recorded the SHA, and inside the tasks container the new definition was
there:

    in this container, create_task.assignees = ('array', 'A list of
                                                whole numbers.', False)
    published schema for assignees: {"anyOf": [{"items": {}, "type":
                                     "array"}, {"type": "null"}]}

and what mcp-proxy told a model was still:

    assignees  {"anyOf": [{"type": "string"}, {"type": "null"}]}

mcp-proxy builds TOOLS_CACHE from each backing server's OpenAPI when IT
boots, and nothing re-reads a server that was rebuilt underneath it. The
whole `my-*` family, 210 tools, is served by the tasks container, so
every change to one of their shapes needs mcp-proxy restarted or the
model keeps being told last week's schema. Nothing in the deploy did
that, and nothing said so.

This is the quiet kind of failure: a green deploy, a correct container,
and a model still working from the old shape. It would have been found
by someone wondering why a fix did not take, which is exactly what
happened.

A RESTART, not a rebuild. mcp-proxy's own image has not changed, and
rebuilding it on every tasks deploy would add minutes to every deploy
for nothing.

These read the script, because it is bash and there is no harness. They
assert the statement that has to be there, not the word mcp-proxy, which
appears in it several times for other reasons.
"""
import pathlib
import re

import pytest

SCRIPT = (pathlib.Path(__file__).resolve().parents[3]
          / "scripts" / "deploy_orchestrator.sh")


@pytest.fixture(scope="module")
def text():
    assert SCRIPT.is_file(), SCRIPT
    return SCRIPT.read_text(encoding="utf-8", errors="replace")


@pytest.fixture(scope="module")
def rebuild_step(text):
    """Only the rebuild step, so a match somewhere else cannot stand in
    for the one that has to be here."""
    start = text.index("[5/6] rebuild + restart services")
    end = text.index("[6/6] post-deploy smoke")
    return text[start:end]


def test_the_proxy_is_restarted_when_the_tools_service_is_rebuilt(rebuild_step):
    """The whole point. Without this a tool's new shape never reaches a
    model, however green the deploy was."""
    assert "restart mcp-proxy" in rebuild_step, rebuild_step


def test_it_restarts_rather_than_rebuilds_the_proxy(rebuild_step):
    """Its image has not changed. Rebuilding it on every tasks deploy
    costs minutes on every deploy and reads as a loop to anyone watching."""
    assert "--build mcp-proxy" not in rebuild_step, rebuild_step


def test_it_happens_only_for_the_service_that_serves_those_tools(rebuild_step):
    """Restarting the proxy after an api-gateway or Caddy deploy would be
    a blip nobody asked for. The my-* tools are served by `tasks`."""
    guard = re.search(r'"\$\{svc\}"\s*==\s*"tasks"', rebuild_step)
    assert guard, rebuild_step


def test_the_reason_is_written_down_where_it_happens(text):
    """The next person to read this will wonder why a deploy touches a
    service whose files did not change."""
    low = text.lower()
    assert "tools_cache" in low or "caches" in low or "cache" in low, (
        "nothing says why the proxy is restarted")


def test_the_rebuild_of_the_service_itself_still_happens(rebuild_step):
    """A restart of the proxy is in addition to, never instead of,
    rebuilding the service whose code changed."""
    assert "up -d --build ${svc}" in rebuild_step, rebuild_step


def test_caddy_is_still_restarted_not_rebuilt(rebuild_step):
    """Unchanged behaviour that sits in the same branch, so a careless
    edit here would be caught."""
    assert "restart caddy" in rebuild_step, rebuild_step
