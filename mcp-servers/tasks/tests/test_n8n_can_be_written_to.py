"""IO can build and change n8n workflows, and cannot quietly destroy one.

Ralph, 2026-11-17: "I want to test like the system can create a workflow
in the n8n update delete and etc", after being told plainly that write
access means a model can change automations that run unattended. He asked
for it knowing that, so it is built.

Every verb below was measured against his real n8n (2.10.3) before any of
this was written, because building against the docs and finding out in
production which calls the instance refuses is how a connector ships
broken:

    POST   /workflows              200, and n8n creates it active=False
    PUT    /workflows/{id}         200
    POST   /workflows/{id}/deactivate   200
    POST   /workflows/{id}/activate     400, "Workflow cannot be
           activated because it has no trigger node. At least one
           trigger, webhook, or polling node is required."
    POST   /workflows/{id}/archive      405, no such verb
    DELETE /workflows/{id}         200, and a GET afterwards is 404

TWO OF THOSE SHAPE THE TOOLS.

THERE IS NO TRASH. `isArchived` exists on the record and the API has no
verb to set it, so delete is a hard delete with nothing to undo it. A
model deleting the wrong workflow is unrecoverable, and twelve of
Ralph's thirty-two run unattended. So delete REFUSES a workflow that is
currently active: deactivating first makes destroying a running
automation two deliberate steps instead of one mistaken one.

A MANUAL TRIGGER IS NOT A TRIGGER, for activation. n8n refuses to
activate a workflow whose only entry point is "When clicking Test
workflow", which is exactly what a model builds when asked for a simple
test workflow. The tool says so rather than passing back a 400 that
reads like a broken connector.
"""
import os

import pytest

os.environ.setdefault("AIUI_FERNET_KEY",
                      "SFNQQkFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=")

import mytools


def _tool(name):
    for t in mytools.PROVIDER_TOOLS["n8n"]:
        if t.name == name:
            return t
    raise AssertionError("no n8n tool called %r; there are: %s"
                         % (name, [t.name for t in
                                   mytools.PROVIDER_TOOLS["n8n"]]))


WRITES = ("create_workflow", "update_workflow", "delete_workflow",
          "activate_workflow", "deactivate_workflow")


# --- the verbs exist, against the paths that answered ---------------------

@pytest.mark.parametrize("name", WRITES)
def test_the_write_tools_exist(name):
    assert _tool(name) is not None


@pytest.mark.parametrize("name", WRITES)
def test_every_write_is_marked_as_one(name):
    assert _tool(name).writes is True, (
        "%s is not marked a write, so nothing that asks before acting "
        "will ask before this" % name)


def test_the_reads_are_still_reads():
    for name in ("list_my_workflows", "get_workflow", "list_executions"):
        assert _tool(name).writes is False


def test_they_point_at_the_paths_that_answered():
    assert _tool("create_workflow").path == "/api/v1/workflows"
    assert _tool("create_workflow").method == "POST"
    assert _tool("update_workflow").path == "/api/v1/workflows/{workflow_id}"
    assert _tool("update_workflow").method == "PUT"
    assert _tool("delete_workflow").path == "/api/v1/workflows/{workflow_id}"
    assert _tool("delete_workflow").method == "DELETE"
    assert _tool("activate_workflow").path.endswith("/activate")
    assert _tool("deactivate_workflow").path.endswith("/deactivate")


# --- what a model has to supply -------------------------------------------

def test_creating_asks_for_the_parts_n8n_requires():
    args = _tool("create_workflow").args
    for need in ("name", "nodes", "connections"):
        assert need in args, "create_workflow cannot work without %r" % need
    assert args["name"][2] is True, "a workflow with no name"
    assert args["nodes"][2] is True, "a workflow with no nodes does nothing"


def test_the_body_is_the_shape_n8n_accepted():
    body = mytools._n8n_workflow_body({
        "name": "IO test workflow",
        "nodes": [{"id": "t", "name": "T", "type": "n8n-nodes-base.manualTrigger",
                   "typeVersion": 1, "position": [0, 0], "parameters": {}}],
        "connections": {}})
    assert body["name"] == "IO test workflow"
    assert isinstance(body["nodes"], list) and body["nodes"]
    assert isinstance(body["connections"], dict)
    # n8n rejected a create with no settings on some versions, and the
    # real instance accepted executionOrder v1, which is what its own UI
    # writes.
    assert body["settings"]["executionOrder"] == "v1"


def test_nodes_may_arrive_as_a_json_string():
    """A model writes JSON into a string argument more often than it
    builds a list, and the vendor answers 400 either way without saying
    which it minded."""
    body = mytools._n8n_workflow_body({
        "name": "x",
        "nodes": '[{"id":"t","name":"T","type":"n8n-nodes-base.manualTrigger",'
                 '"typeVersion":1,"position":[0,0],"parameters":{}}]',
        "connections": '{"T": {"main": []}}'})
    assert isinstance(body["nodes"], list)
    assert body["nodes"][0]["name"] == "T"
    assert isinstance(body["connections"], dict)
    assert "T" in body["connections"]


def test_rubbish_in_a_json_string_is_refused_by_name():
    with pytest.raises(ValueError) as e:
        mytools._n8n_workflow_body({"name": "x", "nodes": "not json at all"})
    assert "nodes" in str(e.value)


def test_a_workflow_is_never_created_already_running():
    """n8n creates inactive on its own, and nothing here should ask it to
    do otherwise: a workflow that starts running the moment a model wrote
    it is the thing nobody asked for."""
    body = mytools._n8n_workflow_body({"name": "x", "nodes": [{"a": 1}]})
    assert body.get("active") in (None, False)
    assert "active" not in _tool("create_workflow").args


# --- the guard that matters -----------------------------------------------

async def test_deleting_a_running_workflow_is_refused():
    """There is no trash. Delete is a hard delete and twelve of his
    thirty-two workflows run unattended."""
    async def get(path, extra=None):
        return {"id": "abc", "name": "Nightly invoice run", "active": True}

    args, problem = await mytools._n8n_prepare(
        "delete_workflow", {"workflow_id": "abc"}, get)
    assert problem, "a running workflow was deleted with no question asked"
    assert "active" in problem.lower() or "running" in problem.lower()
    assert "deactivate" in problem.lower(), (
        "the refusal should say what to do about it: " + problem)


async def test_deleting_a_stopped_workflow_goes_ahead():
    async def get(path, extra=None):
        return {"id": "abc", "name": "Old thing", "active": False}

    args, problem = await mytools._n8n_prepare(
        "delete_workflow", {"workflow_id": "abc"}, get)
    assert problem is None, problem


async def test_a_read_that_fails_does_not_block_the_delete():
    """`get` returns None when the lookup could not be made. Refusing
    then would make an unreachable instance look like a protected
    workflow, and the vendor is the one that decides anyway."""
    async def get(path, extra=None):
        return None

    args, problem = await mytools._n8n_prepare(
        "delete_workflow", {"workflow_id": "abc"}, get)
    assert problem is None


async def test_the_guard_leaves_the_other_verbs_alone():
    async def get(path, extra=None):
        return {"active": True}

    for name in ("update_workflow", "deactivate_workflow",
                 "create_workflow", "list_my_workflows"):
        args, problem = await mytools._n8n_prepare(
            name, {"workflow_id": "abc"}, get)
        assert problem is None, "%s was blocked: %s" % (name, problem)


# --- saying what n8n will refuse, before it refuses it --------------------

def test_activating_says_a_manual_trigger_is_not_enough():
    """Measured: n8n answers 400 "no trigger node. At least one trigger,
    webhook, or polling node is required". A model asked for a simple
    test workflow builds exactly that and then cannot activate it."""
    summary = _tool("activate_workflow").summary.lower()
    assert "trigger" in summary
    assert "manual" in summary, (
        "the one case that fails is the one a model builds by default, "
        "and the tool should say so: " + summary)
