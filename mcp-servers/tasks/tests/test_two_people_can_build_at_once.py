"""A simple site does not take the lock, so two people can build at once.

The bug Ralph hit, 2026-11-05: he started a build, and a second person
could not start one at all. The guard was global, with no user in it, so
one build anywhere on the platform refused every other.

The guard is not wrong. Measured the same day: the agent peaks at ~873MB
inside a 1GB container, host swap was 2039 of 2047MB used with nothing
building, and the host has been OOM killed 51 times. Two agents at once
would take out the service that runs the whole platform.

What was wrong is that nearly nothing needed an agent. 50 of 51 apps in
the repo are static sites with no database. So this asserts the split:
the lock belongs to the agent, and a simple site never meets it.

Structural, on the real route source. The spawn path needs the DB tier,
so the ORDER of the guard against the lane decision is what is checked
here, and it is the thing that decides whether a second person is
refused.
"""
import os
import re

import pytest

import light_build

SRC = os.path.join(os.path.dirname(__file__), "..", "routes_aiuibuilder.py")


def _src():
    with open(SRC, encoding="utf-8") as fh:
        return fh.read()


def _spawn():
    src = _src()
    start = src.index("async def _create_and_spawn_build(")
    end = src.index("\nasync def ", start + 10)
    return src[start:end]


# --- the lock belongs to the agent ---------------------------------------

def test_the_lane_is_decided_before_the_guard_is_consulted():
    """Deciding after would mean a light build was already refused by the
    time anyone asked whether it needed an agent."""
    body = _spawn()
    decided = body.index("needs_agent = light_build.needs_the_agent(description)")
    guard = body.index("A build is already running")
    assert decided < guard


def test_a_simple_site_is_never_refused_because_somebody_else_is_building():
    """The whole bug. The 429 and the lock must both sit under the same
    `if not light`, or a light build still queues behind an agent."""
    body = _spawn()
    gate = body.index("if not light:")
    lock = body.index("pg_advisory_xact_lock(hashtext('aiuibuilder:build'))")
    refuse = body.index("status_code=429")
    assert gate < lock < refuse
    # Both are indented under that branch, not merely after it.
    between = body[gate:refuse]
    # Twelve spaces: inside `if not light:`, inside `async with session()`.
    # Eight would mean merely after the branch rather than under it, which
    # is the difference between a light build skipping the guard and
    # meeting it.
    assert "\n            if in_flight:" in between, (
        "the refusal is not inside the agent-only branch")


def test_the_agent_still_runs_one_at_a_time():
    """Nothing here loosens the agent's limit. Two agents at once is the
    thing that OOM kills the platform."""
    body = _spawn()
    assert body.count("pg_advisory_xact_lock(hashtext('aiuibuilder:build'))") == 1
    assert body.count("status_code=429") == 1


def test_a_light_build_never_reaches_the_agent():
    """It returns before the prompt is built and the subprocess spawned,
    which is where the ~900MB goes."""
    body = _spawn()
    light = body.index("if light:")
    spawn = body.index("_run_prebuild_questions_then_build")
    assert light < spawn
    assert "return str(task_id), slug" in body[light:spawn]


def test_a_light_build_gets_no_empty_folders():
    """_ensure_app_skeleton makes src/, styles/ and public/. This lane
    writes one file, so they would be folders nothing ever fills."""
    body = _spawn()
    light = body.index("if light:")
    # The CALL, not the import at the top of the function, which names
    # it too and sits above everything.
    skeleton = body.index("_ensure_app_skeleton(slug, None)")
    assert light < skeleton


def test_a_template_build_keeps_the_agent():
    """A template is multi-file by definition, so it is not a job for a
    lane that writes one file."""
    body = _spawn()
    assert "light = template_key is None and needs_agent is None" in body


# --- the decision itself, end to end -------------------------------------

@pytest.mark.parametrize("asked,lane", [
    ("a landing page for a coffee shop", "light"),
    ("a portfolio site", "light"),
    ("a site where customers log in", "agent"),
    ("a shop with a cart and checkout", "agent"),
    ("a todo app that remembers my tasks", "agent"),
])
def test_what_each_request_gets(asked, lane):
    got = "agent" if light_build.needs_the_agent(asked) else "light"
    assert got == lane, asked
