"""A workflow that cannot do anything is not created.

Ralph asked IO to build a workflow with a manual trigger and a Set node
that sets message = "hello from IO". It built this, on 2026-11-18:

    node Manual Trigger | n8n-nodes-base.manualTrigger  params: {}
    node Set message    | n8n-nodes-base.set            params:
                                            {"assignments": []}
    connections: {}

Two nodes with nothing between them, and a Set node that sets nothing.
It looks like a workflow in the canvas and does nothing at all. n8n
accepted it happily, because n8n has no opinion about whether your
workflow is finished.

The model was not being careless. It had no way to know the shapes: n8n
exposes no node schema to an API key at all. /api/v1/node-types is 404
on 2.10.3, /rest/node-types is 404, and /types/nodes.json wants a
browser session. So the only things that can teach it are the tool's own
argument descriptions and a refusal that says what is wrong.

WHAT IS REFUSED, and what deliberately is not:

  * more than one node and NO connections. One node is a legitimate
    stub, and n8n's own canvas lets you build that way, but two
    unconnected nodes is never what anybody meant.
  * a Set node whose assignments are empty. That is the one node whose
    entire purpose is the thing that was left out, and it is the node a
    model reaches for most.

Everything else goes through. This is a guard against the two silent
shapes we actually saw, not a validator trying to have opinions about
n8n's hundreds of nodes.
"""
import os

import pytest

os.environ.setdefault("AIUI_FERNET_KEY",
                      "SFNQQkFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=")

import mytools

TRIGGER = {"id": "t", "name": "Manual Trigger", "parameters": {},
           "type": "n8n-nodes-base.manualTrigger", "typeVersion": 1,
           "position": [0, 0]}
SET_EMPTY = {"id": "s", "name": "Set message", "parameters": {
    "assignments": []}, "type": "n8n-nodes-base.set",
    "typeVersion": 3.4, "position": [220, 0]}
SET_FULL = {"id": "s", "name": "Set message", "parameters": {
    "mode": "manual", "assignments": {"assignments": [
        {"id": "a1", "name": "message", "value": "hello from IO",
         "type": "string"}]}},
    "type": "n8n-nodes-base.set", "typeVersion": 3.4,
    "position": [220, 0]}
JOINED = {"Manual Trigger": {"main": [[{"node": "Set message",
                                        "type": "main", "index": 0}]]}}


def problem(nodes, connections=None):
    """The refusal, or None. `_n8n_workflow_body` raises ValueError the
    same way it does for unreadable JSON."""
    try:
        mytools._n8n_workflow_body({"name": "x", "nodes": nodes,
                                    "connections": connections})
        return None
    except ValueError as e:
        return str(e)


# --- the two shapes we actually saw ---------------------------------------

def test_two_nodes_with_nothing_between_them_is_refused():
    said = problem([TRIGGER, SET_FULL], {})
    assert said, "the exact workflow from 2026-11-18 was accepted again"
    assert "connect" in said.lower(), said


def test_the_refusal_says_how_connections_are_keyed():
    """By the SOURCE NODE'S NAME. That is the part a model gets wrong,
    and it cannot look it up anywhere."""
    said = problem([TRIGGER, SET_FULL], {})
    assert "name" in said.lower(), said
    assert "Manual Trigger" in said, (
        "the refusal should use their own node's name, not a generic "
        "example: " + said)


def test_a_set_node_that_sets_nothing_is_refused():
    said = problem([TRIGGER, SET_EMPTY], JOINED)
    assert said, "a Set node with empty assignments was accepted"
    low = said.lower()
    assert "set message" in low or "assignments" in low, said


def test_the_refusal_shows_the_shape_that_works():
    said = problem([TRIGGER, SET_EMPTY], JOINED)
    assert "assignments" in said, said
    # The nested shape is the thing nobody guesses right.
    assert said.count("assignments") >= 2 or "value" in said, said


# --- what must still go through -------------------------------------------

def test_a_proper_workflow_is_built():
    body = mytools._n8n_workflow_body({
        "name": "IO test workflow", "nodes": [TRIGGER, SET_FULL],
        "connections": JOINED})
    assert body["name"] == "IO test workflow"
    assert len(body["nodes"]) == 2
    assert body["connections"] == JOINED


def test_one_node_on_its_own_is_allowed():
    """A legitimate stub, and n8n's own canvas lets you build that way."""
    assert problem([TRIGGER], {}) is None


def test_a_node_we_have_no_opinion_about_is_allowed():
    """This is a guard against two shapes we saw, not a validator with
    views on n8n's hundreds of nodes."""
    other = {"id": "h", "name": "HTTP Request", "parameters": {},
             "type": "n8n-nodes-base.httpRequest", "typeVersion": 4,
             "position": [220, 0]}
    joined = {"Manual Trigger": {"main": [[{"node": "HTTP Request",
                                            "type": "main", "index": 0}]]}}
    assert problem([TRIGGER, other], joined) is None


def test_a_set_node_with_assignments_the_old_way_is_allowed():
    """Older Set nodes used `values`, and refusing those would block
    anybody copying a real template."""
    old = {"id": "s", "name": "Set old", "type": "n8n-nodes-base.set",
           "typeVersion": 2, "position": [220, 0],
           "parameters": {"values": {"string": [
               {"name": "message", "value": "hi"}]}}}
    joined = {"Manual Trigger": {"main": [[{"node": "Set old",
                                            "type": "main", "index": 0}]]}}
    assert problem([TRIGGER, old], joined) is None


# --- the descriptions a model actually reads ------------------------------

def _tool(name):
    for t in mytools.PROVIDER_TOOLS["n8n"]:
        if t.name == name:
            return t
    raise AssertionError(name)


def test_the_arguments_carry_a_worked_example():
    """Measured: n8n exposes no node schema to an API key, so these
    descriptions are the only place a model can learn the shapes."""
    args = _tool("create_workflow").args
    nodes_help = args["nodes"][1]
    conns_help = args["connections"][1]
    assert "typeVersion" in nodes_help, nodes_help
    assert "n8n-nodes-base." in nodes_help, nodes_help
    # The two things that were got wrong.
    assert "assignments" in nodes_help, (
        "the Set node's shape is the one that silently produced nothing: "
        + nodes_help)
    assert "name" in conns_help.lower(), conns_help
    assert "main" in conns_help, conns_help


# --- the refusal has to REACH the model -----------------------------------

def _connected(monkeypatch):
    """Stand in for a stored n8n credential, and nothing else.

    The real `_call` checks the credential FIRST and answers "you have
    not connected n8n yet" before any shaping, which is right and is
    what the first version of this test actually proved. To reach the
    shaper, the person has to be connected.

    Nothing here stubs the shaping or the refusal: those are the thing
    under test, and the call never gets as far as the network because
    the refusal comes first.
    """
    async def creds(email, provider):
        return {"base_url": "https://n8n.example.test", "api_key": "k"}
    monkeypatch.setattr(mytools, "_secrets_for", creds)

    # And past the SSRF guard, which refuses a host that does not resolve
    # publicly. Also right, also a precondition, and also not the thing
    # under test: a made-up hostname in a unit test is exactly what it
    # exists to stop.
    async def resolves(url):
        return ""
    monkeypatch.setattr(mytools.host_guard, "problem", resolves)


async def test_a_refusal_comes_back_as_an_answer_not_an_exception(
        monkeypatch):
    _connected(monkeypatch)
    """Found by running it live, 2026-11-18, after the unit tests above
    were green.

    They call `_n8n_workflow_body` directly and assert the ValueError,
    which is right at that level. But `_call` builds the payload OUTSIDE
    its try, so the exception escaped the whole call: a chat turn got a
    500 and the model never saw the sentence telling it what to fix.

    A refusal that cannot be read is a crash with good intentions.
    """
    tool = _tool("create_workflow")
    out = await mytools._call("n8n", tool, "someone@example.com",
                              {"name": "x", "nodes": [TRIGGER, SET_FULL],
                               "connections": {}})
    assert isinstance(out, dict), "it raised instead of answering"
    assert out.get("ok") is False, out
    said = str(out.get("error") or "")
    assert "connect" in said.lower(), said
    # The shape to use has to survive into the answer, or the model
    # learns only that something was wrong.
    assert "Manual Trigger" in said, said


async def test_unreadable_json_also_comes_back_as_an_answer(
        monkeypatch):
    _connected(monkeypatch)
    tool = _tool("create_workflow")
    out = await mytools._call("n8n", tool, "someone@example.com",
                              {"name": "x", "nodes": "not json at all"})
    assert isinstance(out, dict), "it raised instead of answering"
    assert out.get("ok") is False
    assert "nodes" in str(out.get("error") or "")
